# Analisi del periodo 7/30 giorni — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Con 7 e 30 giorni la dashboard mostra analisi del periodo (fasce, solo FV, cambi batteria→rete, energia giornaliera per fonte) e una stima di costo mensile, al posto delle card istantanee.

**Architecture:** Un nuovo endpoint GET `/api/analytics` calcola tutto lato server dai campioni SQLite già salvati e restituisce un JSON unico. Il frontend nasconde le card istantanee con 7/30 giorni, mostra una sezione analisi con KPI e grafici SVG e riusa la card "Energia al giorno" in versione impilata. Il prezzo è una variabile env opzionale usata solo nella vista a 30 giorni.

**Tech Stack:** Python 3 standard library, SQLite, HTTP server già esistente, HTML/CSS/JavaScript senza build, pytest, ruff, Chromium headless per il collaudo visivo.

**Spec:** `docs/superpowers/specs/2026-11-16-analisi-periodo-design.md`

## Global Constraints

- Solo libreria standard Python; nessuna dipendenza nuova.
- HTTP resta di sola lettura; il nuovo endpoint è GET e non scrive nulla.
- Nessuna migrazione del database: usare `ts`, `pv_w`, `out_w`, `grid_v`, `mode` e le colonne `e_*_wh` esistenti.
- Il 24 ore resta identico: layout, card e grafici non cambiano.
- Prezzo unico `GRID_PRICE_EUR_KWH` in €/kWh; costo mostrato **solo** con `H === 720`.
- Medie giornaliere su `days = observed_seconds / 86400`: mai `h/24`, mai il numero di date di calendario.
- Dati mancanti: nessun consumo inventato; i buchi oltre `max_stored_gap()` non producono energia.
- UI in italiano, tema chiaro/scuro, token CSS esistenti, leggibile a 390 px.
- Definizioni fisse: fasce `[0,4) [4,8) [8,12) [12,16) [16,20) [20,24)`; "solo FV" = fuori rete con `pv_w > 0`, `out_w > 0`, `pv_w >= out_w - 50` su entrambi i campioni; cambio batteria→rete confermato da 3 campioni consecutivi.
- La stima di costo copre solo i prelievi di rete in bypass; le ricariche da rete non sono nello storico e vanno dichiarate come limite.

## Review Focus

1. **Database vuoto o solo un campione:** l'utente deve vedere "nessun dato", non un consumo zero; `days: 0`, rapporti `null`, grafici vuoti. Test nella Task 5.
2. **Cambio 7→30 con `/api/analytics` in errore:** non devono restare i grafici della settimana sotto l'etichetta del mese. Test nella Task 7.
3. **Giorni parziali ai bordi e buchi di comunicazione:** le medie usano il tempo osservato, non 7/8 date, e i buchi non entrano nei kWh. Test nelle Task 4 e 5.
4. **Confini di ora/fascia/mezzanotte in ora locale:** un intervallo a cavallo del confine deve essere diviso, non attribuito tutto a un bucket. Test nella Task 2 e Task 4.
5. **Prezzo assente, vuoto o non valido:** nessun costo, nessun "€ –", e nessun errore all'avvio. Test nelle Task 1 e 5.

---

### Task 1: Prezzo dell'energia in env

**Files:**
- Modify: `solarmon.py:23-33` (configurazione)
- Modify: `solarmon.env.example:1-49`
- Test: `tests/test_parsers.py`

**Interfaces:**
- Consumes: `E = os.environ.get` già esistente.
- Produces: `parse_price(raw: str) -> float | None`; costante di modulo `GRID_PRICE: float | None`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.parametrize("raw, expected", [
    ("0.25", 0.25), ("0,25", 0.25), (" 0.30 ", 0.30),
    ("", None), ("abc", None), ("-1", None), ("0", None), ("nan", None),
])
def test_parse_price(solarmon, raw, expected):
    assert solarmon.parse_price(raw) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parsers.py::test_parse_price -v`
Expected: FAIL with "module 'solarmon' has no attribute 'parse_price'".

- [ ] **Step 3: Implement `parse_price(raw: str) -> float | None`**

In `solarmon.py`, near the other config helpers:

- strip the value, convert `,` to `.`, parse with `float`;
- return `None` on `ValueError`;
- return `None` if not `math.isfinite(v)` or `v <= 0`;
- return `v` otherwise.
- After `SOLAR_PLACE...`, add `GRID_PRICE = parse_price(E("GRID_PRICE_EUR_KWH", ""))`.
- For a non-empty invalid value, `log.warning("GRID_PRICE_EUR_KWH non valido: %r", raw)`; do not raise.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_parsers.py::test_parse_price -v`
Expected: PASS.

- [ ] **Step 5: Add the env example**

Append to `solarmon.env.example`:

```text
# --- costi (facoltativo) ---
# Prezzo dell'energia prelevata dalla rete, in euro/kWh.
# Vuoto = nessuna stima di costo. Accetta sia "0.25" sia "0,25".
GRID_PRICE_EUR_KWH=
```

- [ ] **Step 6: Commit**

```bash
git add solarmon.py solarmon.env.example tests/test_parsers.py
git commit -m "feat: prezzo energia da env"
```

---

### Task 2: Bucket di ora e fascia

**Files:**
- Modify: `solarmon.py` (vicino a `day_of`, `midnight_of`, `next_midnight`)
- Test: `tests/test_parsers.py`

**Interfaces:**
- Produces:
  - `band_index(ts: float) -> int` — 0…5, fascia locale da 4 ore;
  - `next_hour(ts: float) -> float` — timestamp del prossimo inizio ora locale;
  - `next_band(ts: float) -> float` — timestamp del prossimo inizio fascia locale;
  - `split_interval(start: float, end: float, next_boundary: Callable[[float], float]) -> list[tuple[float, float]]` — segmenti contigui che coprono `[start, end]`.

- [ ] **Step 1: Write the failing tests**

Aggiungi `import datetime` agli import di `tests/test_parsers.py` se non è già presente.

```python
def _local_ts(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute)).timestamp()

def test_band_index_uses_local_four_hour_bands(solarmon):
    d = datetime.date(2026, 11, 16)
    assert solarmon.band_index(_local_ts(d, 0)) == 0
    assert solarmon.band_index(_local_ts(d, 3, 59)) == 0
    assert solarmon.band_index(_local_ts(d, 4)) == 1
    assert solarmon.band_index(_local_ts(d, 23, 59)) == 5

def test_split_interval_splits_at_hour_boundaries(solarmon):
    d = datetime.date(2026, 11, 16)
    start, end = _local_ts(d, 3, 30), _local_ts(d, 5, 10)
    parts = solarmon.split_interval(start, end, solarmon.next_hour)
    assert len(parts) == 3
    assert parts[0] == pytest.approx((_local_ts(d, 3, 30), _local_ts(d, 4)))
    assert parts[1] == pytest.approx((_local_ts(d, 4), _local_ts(d, 5)))
    assert parts[2] == pytest.approx((_local_ts(d, 5), _local_ts(d, 5, 10)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_parsers.py::test_band_index_uses_local_four_hour_bands tests/test_parsers.py::test_split_interval_splits_at_hour_boundaries -v`
Expected: FAIL because the functions do not exist.

- [ ] **Step 3: Implement the helpers**

- Use `datetime.datetime.fromtimestamp(ts)` per la data/ora locale.
- `band_index` = `dt.hour // 4`.
- `next_hour` / `next_band` costruiscono il prossimo confine locale con `datetime.combine` e restituiscono `.timestamp()`. Se il confine non è > `ts` (DST o orologio anomalo), restituire `ts + 1` per evitare loop infiniti.
- `split_interval` cicla `a = start`; `b = min(end, next_boundary(a))`; se `b <= a` usa `end`; accumula `(a, b)` e prosegue. Non restituisce segmenti vuoti.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_parsers.py::test_band_index_uses_local_four_hour_bands tests/test_parsers.py::test_split_interval_splits_at_hour_boundaries -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add solarmon.py tests/test_parsers.py
git commit -m "feat: bucket locali per ore e fasce"
```

---

### Task 3: Rilevamento "solo FV" e cambi batteria→rete

**Files:**
- Modify: `solarmon.py` (vicino a `grid_on` e `Notifier`)
- Test: `tests/test_parsers.py`

**Interfaces:**
- Consumes: `GRID_MIN_V`, `GRID_CONFIRM`, `max_stored_gap()`.
- Produces:
  - `is_on_grid(grid_v: float | None, mode: str | None) -> bool`;
  - `solar_only(prev: tuple, cur: tuple) -> bool` — tuple `(ts, pv_w, out_w, grid_v, mode)`;
  - `count_switches(rows: list[tuple[float, float | None, str | None]], gap: float | None = None) -> tuple[int, dict[datetime.date, int]]`.
- `grid_on(gs, mode)` diventa un wrapper di `is_on_grid(gs.get("grid_v"), mode)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_solar_only_requires_no_grid_and_pv_covering_load(solarmon):
    ok = (0, 500.0, 500.0, 0.0, "B")
    assert solarmon.solar_only(ok, ok) is True
    assert solarmon.solar_only((0, 500.0, 600.0, 0.0, "B"),
                               (0, 500.0, 600.0, 0.0, "B")) is True
    assert solarmon.solar_only((0, 500.0, 560.0, 0.0, "B"),
                               (0, 500.0, 560.0, 0.0, "B")) is False
    assert solarmon.solar_only((0, 500.0, 500.0, 230.0, "L"),
                               (0, 500.0, 500.0, 230.0, "L")) is False
    assert solarmon.solar_only((0, 0.0, 0.0, 0.0, "B"),
                               (0, 0.0, 0.0, 0.0, "B")) is False

def test_count_switches_requires_three_consecutive_samples(solarmon):
    t = 1_700_000_000
    rows = [(t, 0.0, "B"), (t + 60, 230.0, "L"), (t + 120, 230.0, "L"),
            (t + 180, 230.0, "L"), (t + 240, 0.0, "B")]
    total, by_day = solarmon.count_switches(rows)
    assert total == 1
    assert sum(by_day.values()) == 1

def test_count_switches_ignores_flapping_and_gaps(solarmon):
    t = 1_700_000_000
    flapping = [(t, 0.0, "B"), (t + 60, 230.0, "L"), (t + 120, 0.0, "B"),
                (t + 180, 230.0, "L"), (t + 240, 0.0, "B")]
    assert solarmon.count_switches(flapping)[0] == 0
    gap = [(t, 0.0, "B"), (t + 60, 230.0, "L"), (t + 120, 230.0, "L"),
           (t + 4000, 230.0, "L"), (t + 4060, 230.0, "L")]
    assert solarmon.count_switches(gap, gap=300)[0] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_parsers.py::test_solar_only_requires_no_grid_and_pv_covering_load tests/test_parsers.py::test_count_switches_requires_three_consecutive_samples tests/test_parsers.py::test_count_switches_ignores_flapping_and_gaps -v`
Expected: FAIL because the helpers do not exist.

- [ ] **Step 3: Implement the helpers**

- `is_on_grid`: `mode == "L" and _finite(grid_v) and float(grid_v) > GRID_MIN_V`.
- `solar_only`: entrambi i campioni devono avere `is_on_grid(...) is False`, `pv_w > 0`, `out_w > 0`, `pv_w >= out_w - 50`.
- `count_switches`:
  - stato confermato = `is_on_grid` del primo campione; candidato e contatore azzerati;
  - per ogni campione successivo: se il buco `dt` supera `gap or max_stored_gap()`, riallinea lo stato confermato al campione e azzera il candidato **senza contare**;
  - se lo stato è diverso dal confermato, incrementa il candidato se uguale al precedente, altrimenti riparte da 1;
  - al raggiungimento di `GRID_CONFIRM` conferma; se il nuovo stato è "in rete", incrementa `total` e `by_day[day_of(ts)]`; poi riallinea e azzera;
  - un ritorno allo stato confermato azzera il candidato.
- `grid_on` delega a `is_on_grid`, mantenendo il comportamento del notifier.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_parsers.py::test_solar_only_requires_no_grid_and_pv_covering_load tests/test_parsers.py::test_count_switches_requires_three_consecutive_samples tests/test_parsers.py::test_count_switches_ignores_flapping_and_gaps tests/test_parsers.py::test_grid_on_requires_line_mode_and_ac -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add solarmon.py tests/test_parsers.py
git commit -m "feat: rileva solo FV e cambi batteria-rete"
```

---

### Task 4: Aggregazioni energia, fasce, giorni e profilo orario

**Files:**
- Modify: `solarmon.py` (dopo `window_energy`/`mix_payload`)
- Test: `tests/test_parsers.py`

**Interfaces:**
- Consumes: `energy_rows`, `next_midnight`, `next_band`, `next_hour`, `split_interval`, `solar_only`, `day_of`.
- Produces:
  - `observed_seconds(raw: list[tuple], since: float, now: float, gap: float | None = None) -> float` — raw tuple `(ts, pv_w, out_w, grid_v, mode)`;
  - `energy_totals(energy_input: list[tuple], since: float, now: float) -> tuple[float, float, float, float]` — Wh `(pv, solar, batt, grid)`, energy tuple `(ts, pv_w, out_w, mode, e_pv, e_solar, e_batt, e_grid)`;
  - `band_totals(energy_input, since, now) -> list[list[float]]` — 6 righe `[solar_wh, batt_wh, grid_wh]`;
  - `daily_by_source(energy_input, since, now) -> dict` — `{"ts": [...], "solar": [...], "batt": [...], "grid": [...]}`, kWh;
  - `solar_only_profile(raw, since, now, days) -> tuple[list[float], float, float | None]` — `minutes_per_day[24]`, ore totali, percentuale.

- [ ] **Step 1: Write the failing tests**

```python
def test_observed_seconds_clips_to_window_and_ignores_gaps(solarmon):
    raw = [(95, 0, 0, 0, "B"), (105, 0, 0, 0, "B"),
           (115, 0, 0, 0, "B"), (1000, 0, 0, 0, "B")]
    assert solarmon.observed_seconds(raw, 100, 200, gap=60) == pytest.approx(15)
    assert solarmon.observed_seconds(raw, 100, 200, gap=5) == 0

def test_band_totals_split_energy_at_four_hour_boundary(solarmon):
    d = datetime.date(2026, 11, 16)
    start, end = _local_ts(d, 3, 30), _local_ts(d, 4, 30)
    rows = [(start, 0, 1000, "B", None, None, None, None),
            (end, 0, 1000, "B", None, None, None, None)]
    bands = solarmon.band_totals(rows, start, end)
    assert bands[0][1] == pytest.approx(500)
    assert bands[1][1] == pytest.approx(500)
    assert sum(b[1] for b in bands) == pytest.approx(1000)

def test_daily_by_source_splits_at_local_midnight(solarmon):
    d = datetime.date(2026, 11, 16)
    start = _local_ts(d, 23, 30)
    end = _local_ts(d + datetime.timedelta(days=1), 0, 30)
    rows = [(start, 0, 1000, "B", None, None, None, None),
            (end, 0, 1000, "B", None, None, None, None)]
    daily = solarmon.daily_by_source(rows, start, end)
    assert daily["batt"] == pytest.approx([0.5, 0.5], abs=0.01)

def test_solar_only_profile_attributes_minutes_to_local_hours(solarmon):
    d = datetime.date(2026, 11, 16)
    start = _local_ts(d, 10, 0)
    end = _local_ts(d, 10, 30)
    raw = [(start, 800, 500, 0, "B"), (end, 800, 500, 0, "B")]
    minutes, hours, pct = solarmon.solar_only_profile(raw, start, end, days=0.5)
    assert minutes[10] == pytest.approx(60)
    assert hours == pytest.approx(0.5)
    assert pct == pytest.approx(100)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_parsers.py::test_observed_seconds_clips_to_window_and_ignores_gaps tests/test_parsers.py::test_band_totals_split_energy_at_four_hour_boundary tests/test_parsers.py::test_daily_by_source_splits_at_local_midnight tests/test_parsers.py::test_solar_only_profile_attributes_minutes_to_local_hours -v`
Expected: FAIL because the helpers do not exist.

- [ ] **Step 3: Implement the helpers**

- `observed_seconds`: per ogni coppia consecutiva, `dt = ts2 - ts1`; se `0 < dt <= gap`, somma `min(now, ts2) - max(since, ts1)` se positivo.
- `energy_totals`: per ogni intervallo di `energy_rows`, ritaglia su `[since, now]` e somma `e_pv`, `e_solar`, `e_batt`, `e_grid` moltiplicati per la frazione visibile; ignora `start is None`.
- `band_totals`: per ogni intervallo, ritaglia, poi `split_interval(start, end, next_band)`; per ogni segmento somma la frazione di energia nella fascia `band_index(segment_start)`. Restituisce sempre 6 righe.
- `daily_by_source`: per ogni intervallo, ritaglia, poi `split_interval(start, end, next_midnight)`; bucket `day_of(segment_start)`, somma in kWh. Restituisce giorni ordinati con solo giorni attraversati da energia; l'allineamento ai giorni con campioni lo fa `analytics_payload`.
- `solar_only_profile`: per ogni coppia valida con `solar_only(prev, cur)`, ritaglia e `split_interval(..., next_hour)`; somma i secondi nell'ora locale di `segment_start`. `minutes = secondi/60/days` se `days > 0`, altrimenti 0; `hours = secondi/3600`; `pct = secondi/observed_seconds*100` o `None` se observed è 0.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_parsers.py::test_observed_seconds_clips_to_window_and_ignores_gaps tests/test_parsers.py::test_band_totals_split_energy_at_four_hour_boundary tests/test_parsers.py::test_daily_by_source_splits_at_local_midnight tests/test_parsers.py::test_solar_only_profile_attributes_minutes_to_local_hours -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add solarmon.py tests/test_parsers.py
git commit -m "feat: aggregazioni energia per fasce e giorni"
```

---

### Task 5: Payload `/api/analytics` e rotta

**Files:**
- Modify: `solarmon.py` (`analytics_payload` dopo `mix_payload`; ramo in `Handler.do_GET`)
- Test: `tests/test_parsers.py`

**Interfaces:**
- Consumes: Task 1–4 helpers, `connect`, `ENERGY_COLS`, `max_stored_gap`, `midnight_of`, `day_of`, `GRID_PRICE`.
- Produces: `analytics_payload(h: int, now: float | None = None) -> dict` con la forma esatta dello spec; rotta `GET /api/analytics?h=...`.

- [ ] **Step 1: Write the failing endpoint tests**

```python
def _insert_analytics(con, rows):
    for ts, pv, out, grid, mode, e in rows:
        con.execute("INSERT INTO samples(ts,pv_w,out_w,grid_v,mode,"
                    "e_pv_wh,e_solar_wh,e_batt_wh,e_grid_wh) VALUES(?,?,?,?,?,?,?,?,?)",
                    (ts, pv, out, grid, mode, *e))

def test_analytics_empty_database_contract(db, server):
    with closing(urllib.request.urlopen(server + "/api/analytics?h=168", timeout=5)) as r:
        body = json.load(r)
    assert body["days"] == 0
    assert body["totals"]["load_kwh"] == 0
    assert body["totals"]["self_sufficiency"] is None
    assert body["totals"]["grid_cost_eur"] is None
    assert body["switches"]["per_day"] is None
    assert len(body["bands"]) == 6
    assert len(body["solar_only"]["minutes_per_day"]) == 24
    assert body["switches"]["days"] == [] and body["daily"]["ts"] == []

def test_analytics_totals_bands_and_days(db, server, monkeypatch):
    import datetime
    monkeypatch.setattr(db, "STORE_INTERVAL", 3600)  # righe orarie nel test
    now = int(time.time())
    since = now - 7 * 86400
    con = db.connect()
    rows = []
    for i in range(-1, 7 * 24 + 1):
        ts = since + i * 3600
        rows.append((ts, 1000, 1000, 0, "B", (1000, 1000, 500, 500)))
    _insert_analytics(con, rows)
    con.commit(); con.close()
    monkeypatch.setattr(db, "GRID_PRICE", 0.25)
    with closing(urllib.request.urlopen(server + "/api/analytics?h=168", timeout=5)) as r:
        body = json.load(r)
    assert body["days"] == pytest.approx(7, abs=0.1)
    assert body["totals"]["solar_kwh"] == pytest.approx(168, abs=1)
    assert body["totals"]["batt_kwh"] == pytest.approx(84, abs=1)
    assert body["totals"]["grid_kwh"] == pytest.approx(84, abs=1)
    assert body["totals"]["load_kwh"] == pytest.approx(336, abs=2)
    assert body["totals"]["self_sufficiency"] == pytest.approx(75, abs=0.2)
    assert body["totals"]["grid_cost_eur"] == pytest.approx(21, abs=0.2)
    assert body["totals"]["covered_value_eur"] == pytest.approx(63, abs=0.2)
    assert len(body["bands"]) == 6
    assert sum(b["solar_kwh"] + b["batt_kwh"] + b["grid_kwh"] for b in body["bands"]) \
        == pytest.approx(body["totals"]["load_kwh"] / body["days"], abs=0.01)
    assert len(body["daily"]["ts"]) == 8
    assert sum(body["daily"]["solar"]) + sum(body["daily"]["batt"]) \
        + sum(body["daily"]["grid"]) == pytest.approx(body["totals"]["load_kwh"], abs=0.1)

def test_analytics_switches_end_to_end(db, server, monkeypatch):
    now = int(time.time()); base = now - 10 * 60
    con = db.connect()
    _insert_analytics(con, [
        (base, 0, 0, 0, "B", (0, 0, 0, 0)),
        (base + 60, 0, 0, 230, "L", (0, 0, 0, 100)),
        (base + 120, 0, 0, 230, "L", (0, 0, 0, 100)),
        (base + 180, 0, 0, 230, "L", (0, 0, 0, 100)),
    ])
    con.commit(); con.close()
    with closing(urllib.request.urlopen(server + "/api/analytics?h=1", timeout=5)) as r:
        body = json.load(r)
    assert body["switches"]["total"] == 1
    assert body["switches"]["per_day"] == pytest.approx(1 / body["days"], abs=0.01)

def test_analytics_invalid_h_uses_default(db, server):
    with closing(urllib.request.urlopen(server + "/api/analytics?h=abc", timeout=5)) as r:
        assert json.load(r)["h"] == 24
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_parsers.py::test_analytics_empty_database_contract tests/test_parsers.py::test_analytics_totals_bands_and_days tests/test_parsers.py::test_analytics_switches_end_to_end tests/test_parsers.py::test_analytics_invalid_h_uses_default -v`
Expected: FAIL with HTTP 404 or "analytics_payload not defined".

- [ ] **Step 3: Implement `analytics_payload(h: int, now: float | None = None) -> dict`**

- `now = time.time()` se `now is None`; `since = now - h*3600`.
- Una query:

```sql
SELECT ts, pv_w, out_w, grid_v, mode, e_pv_wh, e_solar_wh, e_batt_wh, e_grid_wh
FROM samples WHERE ts > ? ORDER BY ts
```

con parametro `since - max_stored_gap()`.
- Costruisci `raw = [(ts, pv_w, out_w, grid_v, mode)]` e `energy_input = [(ts, pv_w, out_w, mode, e_pv, e_solar, e_batt, e_grid)]`.
- `observed = observed_seconds(raw, since, now)`; `days = round(observed/86400, 2)`.
- Totali da `energy_totals`; `load = solar+batt+grid`; `self_sufficiency = round((solar+batt)/load*100, 1) if load > 0 else None`.
- Fasce da `band_totals`: dividi ogni valore per `days` se `days > 0`, arrotonda a 3; etichette fisse `00–04`, `04–08`, `08–12`, `12–16`, `16–20`, `20–24`.
- `visible_days = sorted({day_of(ts) for ts,... in raw if ts >= since})`.
- `daily = daily_by_source(...)`; allinea a `visible_days` con zeri per i giorni mancanti; `ts` = `int(midnight_of(d))`; valori arrotondati a 3.
- `switch_rows = [(ts, grid_v, mode) for ...]` da tutti i campioni restituiti (anche quelli prima di `since`, solo per lo stato iniziale); `total, by_day = count_switches(switch_rows)`; `per_day = round(total/days, 1) if days > 0 else None`; `days` della risposta: una voce per `visible_days`, con `count` 0 se assente.
- `solar_only_profile(...)`: minuti arrotondati a 1, ore a 2, percentuale a 1.
- Costi: se `GRID_PRICE is None` o `days == 0` → `None`; altrimenti `round(grid_kwh*GRID_PRICE, 2)` e `round((solar_kwh+batt_kwh)*GRID_PRICE, 2)`.
- `from = int(since)`, `to = int(now)`, `price_eur_kwh = GRID_PRICE`.
- Se `days == 0`: totali 0, `self_sufficiency=None`, `solar_only_pct=None`, `per_day=None`, costi `None`, `bands` 6 righe di zeri, minuti 24 zeri, liste giornaliere vuote.
- Aggiungi il ramo in `Handler.do_GET`: `elif u.path == "/api/analytics": self.out(analytics_payload(qint(q, "h", 24, 1, 24 * 365)))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_parsers.py::test_analytics_empty_database_contract tests/test_parsers.py::test_analytics_totals_bands_and_days tests/test_parsers.py::test_analytics_switches_end_to_end tests/test_parsers.py::test_analytics_invalid_h_uses_default -v`
Expected: PASS.

- [ ] **Step 5: Run the full Python suite**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add solarmon.py tests/test_parsers.py
git commit -m "feat: endpoint analisi del periodo"
```

---

### Task 6: Sezione analisi e visibilità per periodo

**Files:**
- Modify: `index.html:239`, `index.html:284-330`, `index.html:366-1005`
- Test: `tests/test_parsers.py`

**Interfaces:**
- Consumes: `/api/analytics?h=...` dalla Task 5.
- Produces: elementi `#flow`, `#row3`, `#panel-batt`, `#analytics`, `#a-load`, `#a-pv`, `#a-self`, `#a-grid`, `#a-switch`, `#a-solo`, `#a-cost-note`, `#c-bands`, `#c-solo`, `#c-switch`, relativi `-sub`, `-meta`, `cap-*`; funzioni JS `applyPeriodLayout()`, `paintAnalytics(narrow)`.

- [ ] **Step 1: Write the failing static tests**

```python
def test_dashboard_has_analytics_markup():
    html = (ROOT / "index.html").read_text()
    for needle in ('id="flow"', 'id="row3"', 'id="panel-batt"', 'id="analytics"',
                   'id="a-load"', 'id="a-pv"', 'id="a-self"', 'id="a-grid"',
                   'id="a-switch"', 'id="a-solo"', 'id="c-bands"', 'id="c-solo"',
                   'id="c-switch"', 'api/analytics'):
        assert needle in html

def test_dashboard_script_parses(tmp_path):
    import subprocess
    html = (ROOT / "index.html").read_text()
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    path = tmp_path / "dashboard.js"; path.write_text(script)
    subprocess.run(["node", "--check", str(path)], check=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_parsers.py::test_dashboard_has_analytics_markup tests/test_parsers.py::test_dashboard_script_parses -v`
Expected: the markup test fails on the first missing id; the script test passes or fails depending on the current file.

- [ ] **Step 3: Add markup and CSS**

- Aggiungi `id="flow"` alla card flusso, `id="row3"` al contenitore `.row3`, `id="panel-batt"` alla card batteria.
- Dopo la card mix e prima del `.grid` dei grafici, aggiungi:

```html
<div class="grid" id="analytics" hidden>
  <section class="panel" aria-labelledby="h-analytics">
    <div class="p-head"><h2 id="h-analytics">Analisi del periodo</h2><p class="meta" id="a-meta">–</p></div>
    <div class="kpis">
      <div class="kpi"><p class="kpi-k">Consumo</p><p class="kpi-v" id="a-load">–</p><p class="kpi-s" id="a-load-sub"></p></div>
      <div class="kpi"><p class="kpi-k">FV prodotto</p><p class="kpi-v" id="a-pv">–</p><p class="kpi-s" id="a-pv-sub"></p></div>
      <div class="kpi"><p class="kpi-k">Autosufficienza</p><p class="kpi-v" id="a-self">–</p><p class="kpi-s" id="a-self-sub"></p></div>
      <div class="kpi"><p class="kpi-k">Prelievo rete</p><p class="kpi-v" id="a-grid">–</p><p class="kpi-s" id="a-grid-sub"></p></div>
      <div class="kpi"><p class="kpi-k">Cambi/giorno</p><p class="kpi-v" id="a-switch">–</p><p class="kpi-s" id="a-switch-sub"></p></div>
      <div class="kpi"><p class="kpi-k">Solo FV</p><p class="kpi-v" id="a-solo">–</p><p class="kpi-s" id="a-solo-sub"></p></div>
    </div>
    <p class="cost-note" id="a-cost-note" hidden></p>
  </section>
  <section class="panel" aria-labelledby="h-bands">
    <div class="p-head"><h2 id="h-bands">Consumo per fasce orarie</h2><p class="meta" id="a-bands-meta">–</p></div>
    <figure><svg class="chart" id="c-bands" role="img" aria-labelledby="cap-bands"></svg>
      <figcaption id="cap-bands">Media giornaliera sui giorni osservati; i totali sono nei KPI.</figcaption></figure>
  </section>
  <section class="panel" aria-labelledby="h-solo">
    <div class="p-head"><h2 id="h-solo">Solo FV, senza rete</h2><p class="meta" id="a-solo-meta">–</p></div>
    <figure><svg class="chart" id="c-solo" role="img" aria-labelledby="cap-solo"></svg>
      <figcaption id="cap-solo">Minuti al giorno per ora locale in cui il carico era coperto dai pannelli, senza rete.</figcaption></figure>
  </section>
  <section class="panel" aria-labelledby="h-switch">
    <div class="p-head"><h2 id="h-switch">Cambi batteria → rete</h2><p class="meta" id="a-switch-meta">–</p></div>
    <figure><svg class="chart" id="c-switch" role="img" aria-labelledby="cap-switch"></svg>
      <figcaption id="cap-switch">Cambi confermati da 3 campioni consecutivi (≈3 min); linea tratteggiata = media.</figcaption></figure>
  </section>
</div>
```

- Aggiungi CSS per `.kpis` (6 colonne desktop, 3 a 640–899 px, 2 sotto 640 px), `.kpi`, `.kpi-k`, `.kpi-v`, `.kpi-s`, `.cost-note`, e `.row3.two{grid-template-columns:repeat(2,1fr)}` dentro `@media (min-width:900px)`.
- Non cambiare gli stili esistenti della card flusso o del 24 ore.

- [ ] **Step 4: Add the minimal JS shell**

- Stato: `let ANA = null, ANA_H = null, ANA_ERR = false;`
- In `load()`: recupera `/api/analytics?h=` solo con `H > 24`; su successo `ANA = a; ANA_H = H; ANA_ERR = false`; su errore `ANA_ERR = true` e lascia `ANA` solo se `ANA_H === H`, altrimenti `ANA = null`.
- Nel click dei periodi: se `H` cambia, assegna il nuovo valore, `ANA = null; ANA_H = null; ANA_ERR = false;`, chiama `applyPeriodLayout()` prima di `load()`.
- `applyPeriodLayout()`: `$('flow').hidden = H > 24; $('panel-batt').hidden = H > 24; $('analytics').hidden = H <= 24; $('row3').classList.toggle('two', H > 24);`
- Chiama `applyPeriodLayout()` in `route()` e all'avvio.
- `paintAnalytics(narrow)`: per ora riempie solo i KPI e i meta; se `ANA_ERR` o `!ANA` mostra "dati non disponibili" e `–`; se `ANA.days === 0` mostra i totali a 0 e i rapporti a `–`; altrimenti riempie i sei KPI. A 720 con `price_eur_kwh != null` aggiunge i costi nei sottotitoli e mostra `#a-cost-note` con il testo del limite; altrimenti nasconde la nota.
- `paintCharts()` chiama `paintAnalytics(narrow)` quando `H > 24`.
- `render()` continua a chiamare `paintCharts`.

- [ ] **Step 5: Run tests and syntax check**

Run:
```bash
pytest tests/test_parsers.py::test_dashboard_has_analytics_markup tests/test_parsers.py::test_dashboard_script_parses -v
node --check /tmp/opencode/dashboard.js 2>/dev/null || true
```
Expected: markup test PASS; script test PASS.

- [ ] **Step 6: Commit**

```bash
git add index.html tests/test_parsers.py
git commit -m "feat: sezione analisi del periodo in dashboard"
```

---

### Task 7: Grafici della sezione analisi

**Files:**
- Modify: `index.html` (funzioni SVG e `paintDaily`)
- Test: script di smoke in `/tmp/opencode` + `tests/test_parsers.py`

**Interfaces:**
- Consumes: `ANA` dalla Task 6, `frame`, `scaleY`, `empty`, `el`, `txt`, `fmt`, `dayLbl`.
- Produces:
  - `stackedBars(svg, labels, series, opts = {})` — `series = [{values, color, label}]`, valori kWh;
  - `simpleBars(svg, labels, values, opts = {})` — opts `{height, color, fmtY, ref, emptyMsg}`;
  - `paintDaily(narrow)` che con `H > 24` disegna le barre impilate da `ANA.daily`.

- [ ] **Step 1: Create the failing smoke check**

Create `/tmp/opencode/mock_solar.py` (throwaway) that:

- serve `index.html` con `let H = 24` sostituito da `let H = 168` (o `720` via variabile d'ambiente);
- risponde a `/api/now`, `/api/series`, `/api/daily`, `/api/mix`, `/api/sun` con JSON minimi validi;
- risponde a `/api/analytics` con un payload fisso con 6 fasce, 24 minuti, 7 giorni di cambi e daily.

Run:
```bash
python3 /tmp/opencode/mock_solar.py 8765 &
chromium-browser --headless --no-sandbox --disable-gpu --virtual-time-budget=3000 \
  --dump-dom http://127.0.0.1:8765/ | grep -c '<rect'
```
Expected: FAIL because `#c-bands`, `#c-solo` e `#c-switch` sono vuoti (0 rect).

- [ ] **Step 2: Implement `stackedBars` and `simpleBars`**

- `stackedBars`: `frame(svg, opts.height || 220)`; margini come `barChart`; `max = max(somme delle serie per posizione)`; `scaleY(0, max, 4)`; per ogni posizione disegna i segmenti dal basso nell'ordine delle serie, con `fill` del colore; etichette x solo per 0, metà e ultima posizione; y con `fmt`.
- `simpleBars`: come `barChart` ma riceve etichette arbitrarie e `opts.color`; se `opts.ref` è presente, disegna una linea tratteggiata alla media con etichetta; se tutti i valori sono 0 e `emptyMsg` è impostato, usa `empty()`.
- Usa i token esistenti: `--mix-solar`, `--mix-batt`, `--mix-grid`, `--accent`, `--text`, `--muted`.

- [ ] **Step 3: Implement `paintAnalytics` charts and `paintDaily`**

- Fasce: `stackedBars($('c-bands'), ANA.bands.map(b => b.label), [{values: b.solar_kwh, color: 'var(--mix-solar)'}, {values: b.batt_kwh, color: 'var(--mix-batt)'}, {values: b.grid_kwh, color: 'var(--mix-grid)'}], {height: narrow ? 190 : 230})`. Se `ANA.days === 0` o `load_kwh === 0`, usa `empty()` con "Nessun dato/consumo nel periodo".
- Solo FV: `simpleBars($('c-solo'), Array.from({length: 24}, (_, i) => String(i)), ANA.solar_only.minutes_per_day, {height: narrow ? 170 : 200, color: 'var(--accent)', fmtY: (v) => fmt(v), emptyMsg: 'Nessun intervallo osservato.'})`; etichette visibili 00, 06, 12, 18, 23.
- Cambi: `simpleBars($('c-switch'), ANA.switches.days.map(d => dayLbl(d.ts)), ANA.switches.days.map(d => d.count), {height: narrow ? 160 : 190, color: 'var(--text)', ref: ANA.switches.per_day != null ? {value: ANA.switches.per_day, label: 'media ' + fmt(ANA.switches.per_day, 1)} : null})`.
- Caption e meta: fasce con kWh/giorno; solo FV con `X h nel periodo, Y% del tempo osservato`; cambi con `N cambi in M giorni, media X/giorno`.
- `paintDaily`: se `H > 24`, usa `stackedBars($('c-day'), ANA.daily.ts.map(dayLbl), [solar, batt, grid], {height: narrow ? 168 : 186})`, meta `consumo nel periodo` e caption "Energia consumata ogni giorno, divisa per fonte."; se `ANA` manca o `days === 0`, `empty()`.
- Con `H === 24`, lascia il percorso attuale basato su `DAY` e `barChart`.

- [ ] **Step 4: Run the smoke check**

Run:
```bash
python3 /tmp/opencode/mock_solar.py 8765 &
chromium-browser --headless --no-sandbox --disable-gpu --virtual-time-budget=3000 \
  --dump-dom http://127.0.0.1:8765/ > /tmp/opencode/dom-7d.html
grep -q 'id="analytics"' /tmp/opencode/dom-7d.html
grep -q 'class="kpi-v" id="a-load">' /tmp/opencode/dom-7d.html
test "$(grep -o '<rect' /tmp/opencode/dom-7d.html | wc -l)" -gt 20
```
Expected: PASS; le tre card contengono barre e i KPI sono valorizzati.

- [ ] **Step 5: Check the error path**

Riavvia il mock con `/api/analytics` che risponde 500 e H=720. Esegui di nuovo `--dump-dom`.
Expected: `#analytics` visibile, `#c-bands` senza `<rect>`, meta "dati non disponibili"; nessun grafico del periodo precedente.

- [ ] **Step 6: Run syntax and full tests**

Run:
```bash
pytest -q
node --check /tmp/opencode/dashboard.js 2>/dev/null || true
```
Expected: all tests pass.

- [ ] **Step 7: Visual check**

Take screenshots at 1440, 768 and 390 px, light and dark, for H=168 and H=720. Verify: KPI wrap on mobile, 6 band labels readable, no overlap, cost only at 720, no "€ –".

- [ ] **Step 8: Commit**

```bash
git add index.html tests/test_parsers.py
git commit -m "feat: grafici analisi per fasce, solo FV e cambi"
```

---

### Task 8: Documentazione e verifica finale

**Files:**
- Modify: `docs/DECISIONS.md`
- Modify: `README.md`
- Test: suite completa

**Interfaces:**
- Consumes: tutto il lavoro precedente.

- [ ] **Step 1: Update `DECISIONS.md`**

Add a section `## Analisi del periodo e stima dei costi (2026-11-16)`:

- le card istantanee sono nascoste con 7/30 giorni perché descrivono l'istante, non il periodo;
- le medie usano i giorni equivalenti osservati (`observed_seconds/86400`), non `h/24` né le date di calendario;
- fasce locali fisse da 4 ore e profilo orario in ora locale;
- "solo FV" = fuori rete, carico coperto dai pannelli con tolleranza 50 W;
- cambi batteria→rete confermati da 3 campioni consecutivi, medi sui giorni osservati;
- `GRID_PRICE_EUR_KWH` è un prezzo unico, applicato ai soli prelievi di rete e mostrato solo a 30 giorni;
- limite noto: le ricariche della batteria da rete non sono nello storico, quindi la stima è per difetto e il valore coperto per eccesso.

- [ ] **Step 2: Update `README.md`**

Add one line under "Manutenzione" or "Note" with `GRID_PRICE_EUR_KWH` and the fact that the estimate appears only in the 30-day view.

- [ ] **Step 3: Run the full verification**

```bash
pytest -q
ruff check .
python3 - <<'PY'
from pathlib import Path
html = Path("index.html").read_text()
script = html.split("<script>", 1)[1].split("</script>", 1)[0]
Path("/tmp/opencode/dashboard.js").write_text(script)
PY
node --check /tmp/opencode/dashboard.js
```

Expected: pytest green, ruff green, node check silent.

- [ ] **Step 4: Re-run the dashboard smoke for 24h, 7d, 30d**

- 24h: `#analytics` hidden, `#flow` and `#panel-batt` visible, `#c-day` shows the old 30-day PV bars.
- 7d: `#analytics` visible, `#flow` and `#panel-batt` hidden, three charts with bars, no cost.
- 30d: same plus costs if the mock price is set.
- Empty analytics: KPI totals 0, ratios `–`, charts "Nessun dato".
- Analytics 500: no stale bars, message "dati non disponibili".

- [ ] **Step 5: Commit**

```bash
git add docs/DECISIONS.md README.md
git commit -m "docs: analisi del periodo e stima costi"
```
