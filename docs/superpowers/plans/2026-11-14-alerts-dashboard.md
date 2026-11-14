# Notifiche essenziali e stato immediato — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ridurre le notifiche Telegram ai soli eventi reali e mostrare in dashboard, senza testi lunghi, se la casa è su rete o batteria e se il FV ha eccedenza.

**Architecture:** un motore di notifiche testabile in `solarmon.py` (helper puri + classe `Notifier`) decide gli eventi; il loop principale gli delega ogni lettura. In `index.html` la frase `paintFinding` viene sostituita da due blocchi calcolati da `/api/now`: fonte attuale e stato FV. Nessuna nuova rotta, nessuna migrazione.

**Tech Stack:** Python 3 stdlib, pytest, HTML/CSS/JS senza build, taste-skill `lint.mjs` / `inspect.mjs`.

**Spec:** `docs/superpowers/specs/2026-11-14-alerts-dashboard-design.md`

## Global Constraints

- Solo libreria standard Python; nessuna dipendenza nuova.
- Nessuna migrazione del database e nessuna nuova rotta HTTP.
- UI in italiano, tema chiaro/scuro, nessuna build.
- `GRID_CONFIRM = 3` letture consecutive; `GRID_MIN_V = 90` V.
- Soglia eccedenza FV: ±50 W.
- Numeri con virgola decimale (`46,2 V`, `18%`); percentuale intera, tensione a un decimale.
- `BATT_LOW_V` e `ALERT_REPEAT_MIN` spariscono da codice ed example; valori residui nei `.env` vengono ignorati.
- Il refresh periodico di `QPIRI` resta: serve alla dashboard.
- Niente `aria-live` sui blocchi di stato: cambiano ogni 10 s.

## Review Focus

- **Ping-pong rete/batteria**: una o due letture non devono generare messaggi; solo 3 letture consecutive confermano. Test in Task 1 (`test_notifier_ignores_flapping`, `test_notifier_confirms_grid_transition_after_three_readings`).
- **Campi batteria/FV mancanti o non numerici**: niente `None`, `NaN` o `undefined` visibili. Test in Task 1 (`test_grid_switch_text_omits_missing_battery_state`) e Task 3 (caso dati mancanti).
- **Più allarmi insieme e `mode='F'`**: un solo messaggio, nessun duplicato. Test in Task 1 (`test_alarm_groups_adds_mode_fault_without_bit_one`, `test_notifier_sends_grouped_alarms_without_repeats`).
- **Bypass con ricarica da AC**: non dichiarare eccedenza FV quando `ac_chg=1`. Test in Task 3 (caso rete con ricarica AC).
- **Notte con FV a 0**: `mancano X W` è la condizione normale, non un guasto; testo neutro. Test in Task 3 (caso batteria in deficit).

## File map

| File | Responsabilità |
|---|---|
| `solarmon.py` | costanti `GRID_CONFIRM`/`GRID_MIN_V`, helper notifiche, `Notifier`, `alert` senza ripetizione, wiring nel loop principale |
| `tests/test_parsers.py` | test unitari del motore notifiche e regressione sulla rimozione dei vecchi alert |
| `index.html` | markup/CSS dei due blocchi, `sourceStatus`/`fvStatus`/`paintStatusBlocks`, rimozione `paintFinding` |
| `solarmon.env.example` | rimozione `BATT_LOW_V`/`ALERT_REPEAT_MIN`, nota sulla nuova politica |
| `docs/DECISIONS.md` | decisioni su eventi, soglia tensione rimossa, raggruppamento, stato dashboard |

---

### Task 1: motore notifiche (helper + `Notifier`)

**Files:**
- Modify: `solarmon.py` (costanti vicino a `BATT_LOW`/`REPEAT`, riga ~31; helper e `Notifier` dopo `alert`, riga ~311)
- Test: `tests/test_parsers.py` (nuova sezione in fondo)

**Interfaces:**
- Consumes: `WS` (mappa bit → (nome, grave)), `notify(text)`, `math`.
- Produces:
  - `GRID_CONFIRM: int = 3`, `GRID_MIN_V: float = 90`
  - `grid_on(gs: dict, mode: str) -> bool`
  - `grid_switch_text(new_on_grid: bool, gs: dict, mode: str) -> str | None`
  - `alarm_groups(ws: str, mode: str) -> tuple[list[str], list[str]]`
  - `alarm_text(prev: frozenset[str] | None, groups: tuple[list[str], list[str]]) -> str | None`
  - `class Notifier: __init__(self, send=None); update(self, gs: dict, mode: str, ws: str) -> None`
  - `alert(key, on, text_on, text_off="")` senza ripetizione periodica.

- [ ] **Step 1: scrivi i test che falliscono**

Aggiungi in fondo a `tests/test_parsers.py`:

```python
# --- notifiche --------------------------------------------------------------


def _gs(**kw):
    base = {"pv_w": 0, "out_w": 0, "batt_v": 52.0, "batt_pct": 80, "grid_v": 0,
            "chg_a": 0, "dis_a": 0, "ac_chg": 0}
    base.update(kw)
    return base


def test_grid_on_requires_line_mode_and_ac(solarmon):
    assert solarmon.grid_on(_gs(grid_v=230), "L") is True
    assert solarmon.grid_on(_gs(grid_v=0), "L") is False
    assert solarmon.grid_on(_gs(grid_v=230), "B") is False


def test_grid_switch_text_to_grid(solarmon):
    assert solarmon.grid_switch_text(True, _gs(batt_v=46.2, batt_pct=18), "L") == \
        "Passato alla rete: batteria al 18% (46,2 V)."
    assert solarmon.grid_switch_text(True, _gs(batt_v=None, batt_pct=18), "L") == \
        "Passato alla rete: batteria al 18%."
    assert solarmon.grid_switch_text(True, _gs(batt_v=None, batt_pct=None), "L") == \
        "Passato alla rete."


def test_grid_switch_text_return_only_for_battery_mode(solarmon):
    assert solarmon.grid_switch_text(False, _gs(batt_v=52.1, batt_pct=63), "B") == \
        "Tornato alla batteria: 52,1 V (63%)."
    assert solarmon.grid_switch_text(False, _gs(), "S") is None


def test_alarm_groups_splits_severe_and_warnings(solarmon):
    ws = "0" * 32
    ws = ws[:16] + "1" + ws[17:]  # bit 16: sovraccarico (grave)
    ws = ws[:5] + "1" + ws[6:]    # bit 5: mancanza rete (avviso)
    severe, warnings = solarmon.alarm_groups(ws, "B")
    assert severe == ["Sovraccarico"]
    assert warnings == ["Mancanza rete"]


def test_alarm_groups_adds_mode_fault_without_bit_one(solarmon):
    severe, warnings = solarmon.alarm_groups("0" * 32, "F")
    assert severe == ["Modalità FAULT"]
    assert warnings == []
    severe, _ = solarmon.alarm_groups("0" + "1" + "0" * 30, "F")
    assert severe == ["Inverter fault"]


def test_alarm_text_groups_and_reports_cleared(solarmon):
    assert solarmon.alarm_text(
        frozenset({"Mancanza rete"}), (["Sovraccarico"], ["Mancanza rete"])) == \
        "Allarmi inverter\nGuasti: Sovraccarico\nAvvisi: Mancanza rete"
    assert solarmon.alarm_text(
        frozenset({"Mancanza rete", "Sovraccarico"}), (["Sovraccarico"], [])) == \
        "Allarmi inverter\nGuasti: Sovraccarico\nRientrati: Mancanza rete."
    assert solarmon.alarm_text(frozenset({"Sovraccarico"}), ([], [])) == \
        "Allarmi rientrati: Sovraccarico."
    assert solarmon.alarm_text(frozenset({"Sovraccarico"}), (["Sovraccarico"], [])) is None
    assert solarmon.alarm_text(None, ([], [])) is None


def test_alert_does_not_repeat_while_active(solarmon, monkeypatch):
    sent = []
    monkeypatch.setattr(solarmon, "notify", sent.append)
    solarmon.active.clear()
    solarmon.alert("x", True, "on", "off")
    solarmon.alert("x", True, "on", "off")
    solarmon.alert("x", False, "", "off")
    solarmon.alert("x", False, "", "off")
    assert sent == ["on", "off"]


def _notifier(solarmon):
    sent = []
    return solarmon.Notifier(sent.append), sent


def test_notifier_confirms_grid_transition_after_three_readings(solarmon):
    n, sent = _notifier(solarmon)
    batt = _gs(pv_w=900, out_w=500)
    grid = _gs(grid_v=230, batt_v=46.2, batt_pct=18)
    n.update(batt, "B", "0" * 32)
    assert sent == []
    n.update(grid, "L", "0" * 32)
    n.update(grid, "L", "0" * 32)
    assert sent == []
    n.update(grid, "L", "0" * 32)
    assert sent == ["Passato alla rete: batteria al 18% (46,2 V)."]
    n.update(grid, "L", "0" * 32)
    assert sent == ["Passato alla rete: batteria al 18% (46,2 V)."]


def test_notifier_ignores_flapping(solarmon):
    n, sent = _notifier(solarmon)
    batt, grid = _gs(), _gs(grid_v=230)
    n.update(batt, "B", "0" * 32)
    for _ in range(3):
        n.update(grid, "L", "0" * 32)
        n.update(batt, "B", "0" * 32)
    assert sent == []


def test_notifier_sends_grouped_alarms_without_repeats(solarmon):
    n, sent = _notifier(solarmon)
    clean = "0" * 32
    overload = clean[:16] + "1" + clean[17:]
    n.update(_gs(), "B", clean)
    n.update(_gs(), "B", overload)
    n.update(_gs(), "B", overload)
    assert sent == ["Allarmi inverter\nGuasti: Sovraccarico"]
    n.update(_gs(), "B", clean)
    assert sent == ["Allarmi inverter\nGuasti: Sovraccarico",
                    "Allarmi rientrati: Sovraccarico."]


def test_notifier_sends_alarms_active_at_startup(solarmon):
    n, sent = _notifier(solarmon)
    overload = "0" * 16 + "1" + "0" * 15
    n.update(_gs(), "B", overload)
    assert sent == ["Allarmi inverter\nGuasti: Sovraccarico"]
```

- [ ] **Step 2: esegui i test e verifica che falliscano**

Run: `python3 -m pytest tests/test_parsers.py -k "grid_on or grid_switch or alarm or notifier or alert_does" -v`
Expected: FAIL con `AttributeError: module 'solarmon' has no attribute 'grid_on'` (e simili).

- [ ] **Step 3: implementa helper e `Notifier` in `solarmon.py`**

Aggiungi `GRID_CONFIRM = 3` e `GRID_MIN_V = 90.0` vicino alle altre costanti. Dopo `alert`, implementa:

- `it_num(v, d=0)` → stringa con virgola (`f"{v:.{d}f}".replace(".", ",")`); non esportata.
- `_finite(v)` → `True` solo se `float(v)` è finito; `None`/stringhe non numeriche → `False`.
- `grid_on(gs, mode)` → `mode == "L" and _finite(gs.get("grid_v")) and float(gs["grid_v"]) > GRID_MIN_V`.
- `grid_switch_text(new_on_grid, gs, mode)` → testi esatti dei test. Per il passaggio
  alla rete: con carica e tensione `Passato alla rete: batteria al 18% (46,2 V).`;
  solo carica `Passato alla rete: batteria al 18%.`; solo tensione
  `Passato alla rete: batteria a 46,2 V.`; nessuna delle due `Passato alla rete.`.
  Per il ritorno (solo con `mode == "B"`): con entrambe
  `Tornato alla batteria: 52,1 V (63%).`; solo tensione
  `Tornato alla batteria: 52,1 V.`; solo carica `Tornato alla batteria: 63%.`;
  nessuna `Tornato alla batteria.`. Con `new_on_grid=False` e `mode != "B"` → `None`.
- `alarm_groups(ws, mode)` → scorre `WS.items()` su `ws[i:i+1] == "1"`, separa gravi/avvisi; se `mode == "F"` e `"Inverter fault"` non è già in `severe`, inserisce `"Modalità FAULT"` in testa. `ws` mancante vale `""`.
- `alarm_text(prev, groups)` → calcola `current = frozenset(severe + warnings)`; se `prev is not None and current == prev` → `None`; se `current` e `cleared` sono vuoti → `None`; se `current` è vuoto → `"Allarmi rientrati: " + "; ".join(sorted(cleared)) + "."`; altrimenti righe `Allarmi inverter`, `Guasti: ...`, `Avvisi: ...`, `Rientrati: ...` (solo quelle non vuote).
- `class Notifier`:
  - `__init__(self, send=None)` → `self.send = send or notify`; `self.prev_grid = None`; `self.grid_candidate = None`; `self.grid_count = 0`; `self.prev_alarms = None`.
  - `update(gs, mode, ws)`:
    - prima lettura: `prev_grid = grid_on(...)` senza messaggio;
    - se `on_grid != prev_grid`, accumula `grid_candidate`/`grid_count`; al raggiungimento di `GRID_CONFIRM` aggiorna `prev_grid`, azzera il conteggio e invia `grid_switch_text(...)` solo se non è `None`;
    - se `on_grid == prev_grid`, azzera candidato e conteggio;
    - allarmi: `groups = alarm_groups(ws, mode)`; prima lettura salva `prev_alarms` e, se non vuoto, invia `alarm_text(None, groups)`; alle letture successive, se l'insieme cambia, invia `alarm_text(prev_alarms, groups)` e aggiorna.
- `alert(key, on, text_on, text_off="")`: se `on` e la chiave non è in `active`, salva e invia `text_on`; se `not on` e la chiave è in `active`, rimuove e invia `text_off` solo se non vuoto. Nessun uso di `REPEAT` o del tempo.

- [ ] **Step 4: esegui i test e verifica che passino**

Run: `python3 -m pytest tests/test_parsers.py -k "grid_on or grid_switch or alarm or notifier or alert_does" -v`
Expected: PASS (11 test).

Run: `python3 -m pytest -q`
Expected: tutti i test esistenti più i nuovi, PASS.

- [ ] **Step 5: commit**

```bash
git add solarmon.py tests/test_parsers.py
git commit -m "feat: motore di notifiche basato su eventi"
```

---

### Task 2: wiring nel loop, rimozione vecchi alert e documentazione

**Files:**
- Modify: `solarmon.py` (costanti riga ~31; `main()` riga ~553-584)
- Modify: `solarmon.env.example` (blocco `# --- allarmi ---`)
- Modify: `docs/DECISIONS.md` (in fondo)
- Test: `tests/test_parsers.py`

**Interfaces:**
- Consumes: `Notifier`, `alert`, `GRID_CONFIRM` da Task 1.
- Produces: nessuna nuova funzione pubblica; il loop chiama `notifier.update(gs, mode, ws)`.

- [ ] **Step 1: scrivi il test di regressione che fallisce**

Aggiungi in fondo a `tests/test_parsers.py`:

```python
def test_legacy_alerts_are_removed(solarmon):
    import inspect
    src = inspect.getsource(solarmon)
    for needle in ("Batteria bassa", "BATT_LOW", "ALERT_REPEAT_MIN",
                   "solarmon avviato", "Configurazione inverter cambiata",
                   "Modalita':"):
        assert needle not in src
```

- [ ] **Step 2: esegui il test e verifica che fallisca**

Run: `python3 -m pytest tests/test_parsers.py::test_legacy_alerts_are_removed -v`
Expected: FAIL su `Batteria bassa`.

- [ ] **Step 3: collega `Notifier` e rimuovi i vecchi alert da `main()`**

In `main()`:

- crea `notifier = Notifier()` prima del `while True`;
- elimina `notify("solarmon avviato ...")`;
- nel ramo di successo della lettura sostituisci l'alert con
  `alert("nodata", False, "", "Comunicazione con l'inverter ripristinata.")`;
- nel ramo di errore usa
  `alert("nodata", fails * INTERVAL >= 60, "Inverter non risponde da %d s (%d letture)." % (fails * INTERVAL, fails), "Comunicazione con l'inverter ripristinata.")`;
- nel refresh `QPIRI` mantieni l'aggiornamento di `STATE["cfg"]` e `cfg_ts`, elimina il calcolo di `diff` e la `notify("Configurazione inverter cambiata...")`;
- dopo `STATE.update(...)` chiama `notifier.update(gs, mode, ws)`;
- elimina il ciclo `for i, (name, severe) in WS.items(): alert("ws%d" ...)`; gli allarmi ora passano solo da `Notifier`;
- elimina `alert("modef", ...)`, il blocco `low = ...` / `alert("batt", ...)` e `notify("Modalita': ...")`;
- sostituisci l'inizializzazione con `mq, fails, cfg_ts, store_ts = mqtt_client(), 0, 0, 0` e rimuovi `prev = mode` dal fondo del loop;
- elimina la riga `BATT_LOW, REPEAT = ...` dalle costanti e aggiorna il commento sopra `alert`, che non deve più parlare di ripetizione.

Il resto del loop (storage, MQTT, sleep) resta invariato.

- [ ] **Step 4: aggiorna `solarmon.env.example`**

Sostituisci il blocco:

```bash
# --- allarmi ---
BATT_LOW_V=47
ALERT_REPEAT_MIN=60
```

con:

```bash
# --- notifiche ---
# Le notifiche Telegram sono eventi (passaggio rete/batteria, guasti, inverter muto):
# non ci sono soglie da configurare.
```

- [ ] **Step 5: aggiungi la nota in `docs/DECISIONS.md`**

In fondo al file:

```markdown
## Notifiche essenziali (2026-11-14)

- Le notifiche Telegram sono eventi, non stati: passaggio rete/batteria, guasti
  raggruppati, inverter muto. Niente avvio, cambi di modalità generici, modifiche
  di configurazione o ripetizioni orarie.
- La soglia `BATT_LOW_V` è stata rimossa: sotto carico la tensione scende e
  produceva falsi "batteria bassa" con messaggi ripetuti. L'evento utile è il
  passaggio effettivo alla rete, confermato da 3 letture consecutive.
- Gli allarmi `QPIWS` sono raggruppati in un solo messaggio per cambio di insieme,
  con guasti e avvisi separati; nessuna ripetizione mentre persistono.
- Il refresh periodico di `QPIRI` resta perché alimenta la dashboard; sparisce solo
  la notifica delle modifiche di configurazione.
```

- [ ] **Step 6: esegui i test e verifica che passino**

Run: `python3 -m pytest -q`
Expected: PASS, incluso `test_legacy_alerts_are_removed`.

- [ ] **Step 7: commit**

```bash
git add solarmon.py solarmon.env.example docs/DECISIONS.md tests/test_parsers.py
git commit -m "feat: notifica solo passaggi rete/batteria, guasti e inverter muto"
```

---

### Task 3: due blocchi di stato in dashboard

**Files:**
- Modify: `index.html` (CSS vicino a `.finding`, markup riga ~199, JS vicino a `paintFinding`/`render`)
- Modify: `docs/DECISIONS.md` (in fondo)
- Verifica: `/tmp/opencode/solarmon-status-check.py` e `/tmp/opencode/solarmon-status-mock.py` (non committati)

**Interfaces:**
- Consumes: `/api/now` con `{gs, mode, mode_name, faults}`; `fmt` già esistente.
- Produces:
  - `sourceStatus(gs, mode, modeName) -> {text: string, tone: '' | 'good' | 'warn' | 'bad'}`
  - `fvStatus(gs, onGrid) -> {text: string, tone: '' | 'good' | 'warn' | 'bad'}`
  - `paintStatusBlocks(gs, mode, modeName) -> void`

- [ ] **Step 1: scrivi il controllo che fallisce**

Crea `/tmp/opencode/solarmon-status-check.py` con Playwright. Serve `index.html` da un server statico (`python3 -m http.server 8123` nella root del repo) e intercetta le API con `page.route`.

Casi e risultati attesi:

| Caso | `mode` | `gs` | Fonte attesa | FV atteso |
|---|---|---|---|---|
| Batteria con eccedenza | `B` | `pv_w=3000, out_w=1000` | `Batteria` (good) | `2.000 W in più` (good) |
| Batteria in deficit | `B` | `pv_w=200, out_w=800` | `Batteria` (good) | `mancano 600 W` (neutro) |
| Batteria bilanciata | `B` | `pv_w=500, out_w=520` | `Batteria` (good) | `copre la casa` (neutro) |
| Rete, FV in carica | `L` | `grid_v=230, pv_w=2000, out_w=300, chg_a=20, batt_v=52, ac_chg=0` | `Rete` (warn) | `1.040 W in carica` (good) |
| Rete, carica AC | `L` | come sopra ma `ac_chg=1` | `Rete` (warn) | `0 W in carica` (neutro) |
| Standby | `S` | `pv_w=0, out_w=500` | `Standby` (neutro) | `mancano 500 W` (neutro) |
| FAULT | `F` | `pv_w=0, out_w=500` | `FAULT` (bad) | `mancano 500 W` (neutro) |
| Dati mancanti | `null` | `{}` | `–` (neutro) | `–` (neutro) |

Il controllo legge `#status-source-v`, `#status-fv-v` e i `className` di `#status-source` / `#status-fv`, e fallisce se gli ID non esistono. Eseguilo ora:

Run: `python3 /tmp/opencode/solarmon-status-check.py`
Expected: FAIL, `#status-source-v` assente.

- [ ] **Step 2: aggiungi markup e CSS**

Sostituisci in `index.html`:

```html
<p class="finding" id="finding">Lettura in corso…</p>
```

con:

```html
<div class="status" id="status" role="group" aria-label="Stato attuale">
  <p class="status-item" id="status-source">
    <span class="status-k">Adesso</span>
    <span class="status-v" id="status-source-v">–</span>
  </p>
  <p class="status-item" id="status-fv">
    <span class="status-k">FV</span>
    <span class="status-v" id="status-fv-v">–</span>
  </p>
</div>
```

Aggiungi il CSS dopo `.finding`:

```css
.status{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.status-item{display:flex;align-items:baseline;gap:8px;padding:5px 11px;border:1px solid var(--border);border-radius:var(--r-ctl);background:var(--raised);min-width:0}
.status-k{font-size:12px;color:var(--muted)}
.status-v{display:inline-flex;align-items:center;gap:6px;font-size:20px;font-weight:600;letter-spacing:-.02em;white-space:nowrap}
.status-v::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--muted);flex:none}
.status-item.good .status-v::before{background:var(--positive)}
.status-item.warn .status-v::before{background:var(--warn-ink)}
.status-item.bad .status-v::before{background:var(--negative)}
```

Nel blocco `@media (max-width:639px)` aggiungi `.status-v{font-size:18px}`.

- [ ] **Step 3: implementa le tre funzioni JS e rimuovi `paintFinding`**

Al posto di `paintFinding` (riga ~487) inserisci:

- `sourceStatus(gs, mode, modeName)`:
  - `mode === 'L'` e `grid_v > 90` → `{text: 'Rete', tone: 'warn'}`;
  - `mode === 'L'` senza rete → `{text: 'Rete assente', tone: 'warn'}`;
  - `mode === 'B'` → `{text: 'Batteria', tone: 'good'}`;
  - `mode === 'F'` → `{text: 'FAULT', tone: 'bad'}`;
  - altrimenti `{text: modeName || '–', tone: ''}`.
- `fvStatus(gs, onGrid)`:
  - `pv = +gs.pv_w`, `out = +gs.out_w`; se uno dei due non è finito → `{text: '–', tone: ''}`;
  - se `onGrid`: con `ac_chg !== 1`, `chg_a > 0.2`, `pv > 0` e `batt_v` finito → `fmt(chg_a * batt_v) + ' W in carica'` con tono `good`; altrimenti `{text: '0 W in carica', tone: ''}`;
  - se non in rete: `d = pv - out`; `d > 50` → `fmt(d) + ' W in più'` (good); `d < -50` → `'mancano ' + fmt(-d) + ' W'` (neutro); altrimenti `{text: 'copre la casa', tone: ''}`.
- `paintStatusBlocks(gs, mode, modeName)`:
  - `onGrid = mode === 'L' && +gs.grid_v > 90`;
  - aggiorna `#status-source-v` e `#status-fv-v`;
  - imposta `className` a `status-item` più il tono, se presente.

In `render()`, sostituisci `paintFinding(gs, faults, NOW.mode);` con:

```js
painStatusBlocks(gs, NOW.mode, NOW.mode_name);
```

Elimina la funzione `paintFinding` e ogni riferimento a `#finding`. La classe `.finding` resta perché usata dalla pagina impostazioni.

- [ ] **Step 4: esegui il controllo e verifica che passi**

Run: `python3 /tmp/opencode/solarmon-status-check.py`
Expected: PASS su tutti gli 8 casi.

- [ ] **Step 5: verifica sintassi, lint e resa**

Estrai lo script inline e controllalo:

```bash
python3 - <<'EOF'
import re
s = open('index.html').read()
open('/tmp/opencode/index-check.js', 'w').write(re.search(r'<script>(.*?)</script>', s, re.S).group(1))
EOF
node --check /tmp/opencode/index-check.js
```

Run: `node ~/.agents/skills/design-taste-frontend/scripts/lint.mjs --app index.html`
Expected: `0 FAIL, 0 WARN`.

Crea `/tmp/opencode/solarmon-status-mock.py` (stdlib) che serve `index.html` e i cinque endpoint con il caso "batteria con eccedenza". Poi:

```bash
python3 /tmp/opencode/solarmon-status-mock.py 8124 &
CHROME_PATH=${CHROME_PATH:-$HOME/.cache/ms-playwright/chromium-1254/chrome-linux64/chrome} \
  node ~/.agents/skills/design-taste-frontend/scripts/inspect.mjs \
  http://127.0.0.1:8124/ --app --out /tmp/opencode/status-inspect
```

Expected: `0 FAIL, 0 WARN`; apri gli screenshot desktop e mobile e verifica che i due blocchi siano sopra la piega e non sbordino. Controlla anche il tema scuro con una seconda esecuzione impostando `color_scheme="dark"` nello script Playwright.

- [ ] **Step 6: aggiungi la nota in `docs/DECISIONS.md`**

In fondo al file:

```markdown
## Stato immediato in dashboard (2026-11-14)

- Due blocchi sotto il titolo rispondono a colpo d'occhio: fonte attuale
  (Rete/Batteria) e stato FV (in più / copre / mancano / in carica). La frase
  lunga e `paintFinding` sono stati rimossi.
- In bypass il FV è dichiarato "in carica" solo con `ac_chg=0`: la ricarica da AC
  non è separabile dalla produzione FV, quindi non si dichiara un'eccedenza.
- L'eccedenza usa una soglia di 50 W; il deficit è neutro perché di notte è la
  condizione normale, non un guasto.
```

- [ ] **Step 7: commit**

```bash
git add index.html docs/DECISIONS.md
git commit -m "feat: mostra subito fonte e eccedenza FV in dashboard"
```

---

## Verifica finale

- `python3 -m pytest -q` → tutti i test PASS.
- `node --check /tmp/opencode/index-check.js` → nessun errore.
- `lint.mjs --app index.html` → `0 FAIL, 0 WARN`.
- `inspect.mjs` a 1440/768/390, chiaro e scuro → `0 FAIL, 0 WARN`.
- Prova manuale con il mock: passaggio rete/batteria dopo 3 letture, guasti raggruppati, nessuna ripetizione, dashboard leggibile senza frase lunga.
- `git status` pulito sul branch; nessun artefatto di `/tmp` committato.
