# Report dell'impianto e simulazioni — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** un pacchetto Python che legge uno snapshot SQLite di `solarmon` e produce un report HTML/Markdown con flussi, diagnosi della batteria, potenziale FV e simulazioni di batterie LFP compatibili con l'inverter, senza modificare nulla del monitoraggio.

**Architecture:** `analysis/` è un pacchetto autonomo, solo libreria standard, che non importa `solarmon.py`. Ogni esecuzione legge il DB in sola lettura, calcola i numeri, costruisce un `ReportContext` e scrive `report.html`, `report.md` e `data.json`. La forma del report è fissa; cambiano i dati.

**Tech Stack:** Python 3.9+, SQLite, `argparse`, `dataclasses`, SVG generato in Python. Test con pytest. Nessuna dipendenza nuova, nessuna rete.

**Spec:** `docs/superpowers/specs/2026-11-18-report-simulazione-design.md`

## Global Constraints

- Solo libreria standard Python 3.9+; niente pip install, niente import di terze parti.
- **Nessuna modifica** a `solarmon.py`, `index.html`, `Dockerfile`, `docker-compose.yml`.
- Il database si apre in **sola lettura**; nessuna scrittura fuori da `--out` (default `reports/`).
- Nessuna chiamata di rete.
- Testo del report e messaggi CLI in italiano; commenti in italiano come il resto del repo.
- Determinismo: stesso input e stesso `--tz` producono lo stesso output, tranne `generated_at`.
- Fuso predefinito `Europe/Rome`; coordinate predefinite Cellole (CE): `41.20187970064`, `13.849261783999081`.
- Larghezza riga 120, lint `ruff check` con regole E,F,W,I.
- `pytest -q` verde alla fine di ogni task.

## Contesto rapido per chi non ha visto il repo

- `solarmon.py` è un processo unico: legge l'inverter via PI30, scrive SQLite, serve la dashboard. Non va modificato né importato (all'import legge env e configura il logging).
- La tabella `samples` ha 16 colonne: `ts, pv_w, pv_v, batt_v, out_w, load_pct, chg_a, dis_a, temp_c, grid_v, mode, ws, e_pv_wh, e_solar_wh, e_batt_wh, e_grid_wh`.
- `mode` vale `L` (bypass rete), `B` (batteria), `F` (guasto). In `L` tutto il carico è attribuito alla rete; altrimenti FV diretto = `min(pv_w, out_w)`, batteria = `out_w - FV`.
- `max_stored_gap()` in `solarmon` vale `max(300 s, 3 × STORE_INTERVAL)`; qui si usa lo stesso limite per non inventare energia nei buchi.
- Lo snapshot reale del 18/11 contiene 2.801 campioni dal 16/11 11:27 al 18/11 10:07, `days ≈ 1,94`, batteria con throughput di 0,22 kWh scaricati e 50 cambi di modo.
- `now.json` contiene `cfg` con le chiavi italiane: `Ritorno a rete sotto V`, `Cutoff batteria V`, `Max carica A`, ecc.

## Review Focus

1. **Snapshot di poche ore o di un solo giorno** → il report deve uscire con affidabilità "bassa" e batteria "indeterminato", senza crash e senza proiezioni annuali. Test in Task 4 e Task 10.
2. **Righe legacy senza colonne `e_*`** → l'energia va ricavata dai timestamp, non da zeri. Test in Task 3.
3. **Confini di giornata, ora e mese** → un intervallo a cavallo di mezzanotte o del cambio ora legale deve essere spezzato correttamente. Test in Task 1 e Task 3.
4. **Input opzionali assenti** (`--config`, `--bill`, coordinate) → le sezioni degradano con un messaggio, mai `NaN`, `None` o un crash. Test in Task 9 e Task 10.
5. **Batteria mai scaricata** → verdetto "indeterminato", non "da sostituire". Test in Task 4.

---

### Task 1: Scheletro del pacchetto e fuso orario

**Files:**
- Create: `analysis/__init__.py`
- Create: `analysis/timeutil.py`
- Create: `tests/test_analysis_time.py`
- Modify: `pyproject.toml` (aggiungere `.` a `pythonpath`)

**Interfaces:**
- Consumes: niente.
- Produces: `analysis.ReportError`, `analysis.DEFAULT_TZ`, `analysis.SITE_LAT`, `analysis.SITE_LON`;
  `analysis.timeutil.get_tz(name: str = DEFAULT_TZ) -> TZ` dove `TZ` espone `.name: str` e
  `.offset(ts: float) -> int` (secondi a est di UTC); `to_local(ts, tz) -> datetime` naive;
  `day_start(ts, tz) -> float`; `next_day(ts, tz) -> float`; `hour_of(ts, tz) -> int`;
  `month_key(ts, tz) -> tuple[int, int]`; `is_night(ts, tz) -> bool` (22:00–06:00,
  06:00:00 incluso, 06:01 escluso).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_time.py
from datetime import datetime, timezone

from analysis.timeutil import day_start, get_tz, is_night, month_key, to_local


def utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


def test_rome_dst_boundaries():
    tz = get_tz("Europe/Rome")
    assert tz.offset(utc(2026, 3, 29, 0, 59)) == 3600
    assert tz.offset(utc(2026, 3, 29, 1, 0)) == 7200
    assert tz.offset(utc(2026, 10, 25, 0, 59)) == 7200
    assert tz.offset(utc(2026, 10, 25, 1, 0)) == 3600


def test_night_month_and_local_midnight():
    tz = get_tz("Europe/Rome")
    assert is_night(utc(2026, 11, 18, 22, 0), tz)
    assert is_night(utc(2026, 11, 18, 5, 0), tz)
    assert not is_night(utc(2026, 11, 18, 12, 0), tz)
    assert month_key(utc(2026, 11, 18, 12, 0), tz) == (2026, 11)
    assert to_local(day_start(utc(2026, 11, 18, 12, 0), tz), tz).strftime("%H:%M") == "00:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_time.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'analysis'`.

- [ ] **Step 3: Implement**

`analysis/__init__.py`:

```python
"""Report offline dell'impianto: legge uno snapshot, non importa solarmon."""
VERSION = "1.0"
DEFAULT_TZ = "Europe/Rome"
SITE_LAT = 41.20187970064
SITE_LON = 13.849261783999081


class ReportError(Exception):
    """Errore leggibile: il CLI lo stampa ed esce con codice 2."""
```

`analysis/timeutil.py`: implementare `TZ` come wrapper con `.name` e `.offset(ts)`.
Per `Europe/Rome` usare **sempre** la regola CET/CEST calcolata (ultima domenica di marzo
e di ottobre, alle 01:00 UTC), così il risultato non dipende dal tzdata della macchina.
Per altri nomi usare `zoneinfo.ZoneInfo`; se manca, sollevare `ReportError` con un
messaggio che suggerisce `--tz Europe/Rome`. `to_local` restituisce datetime **naive**
(UTC + offset). `day_start` e `next_day` usano la mezzanotte locale.

In `pyproject.toml` cambiare `pythonpath = ["tests"]` in `pythonpath = ["tests", "."]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_time.py -q && ruff check analysis tests/test_analysis_time.py`
Expected: PASS e `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add analysis/__init__.py analysis/timeutil.py tests/test_analysis_time.py pyproject.toml
git commit -m "feat(analysis): scheletro del pacchetto e fuso Europe/Rome"
```

---

### Task 2: Lettura del database

**Files:**
- Create: `analysis/db.py`
- Create: `tests/analysis_helpers.py`
- Create: `tests/test_analysis_db.py`

**Interfaces:**
- Consumes: `analysis.ReportError`.
- Produces:
  - `analysis.db.Sample` con campi `ts: int`, `pv_w`, `pv_v`, `batt_v`, `out_w`, `load_pct`,
    `chg_a`, `dis_a`, `temp_c`, `grid_v` (`float`), `mode: str`, `ws: str`,
    `e_pv_wh`, `e_solar_wh`, `e_batt_wh`, `e_grid_wh` (`float | None`).
  - `analysis.db.load_samples(path: str | Path, since: float | None = None) -> list[Sample]`
  - `analysis.db.max_gap(store_interval: int = 60) -> int`
  - `tests/analysis_helpers.py: make_db(path, rows)`, `row(**kwargs)`, `sample(**kwargs)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_db.py
import pytest

from analysis.db import load_samples, max_gap
from analysis import ReportError
from analysis_helpers import make_db, row


def test_load_samples_and_nulls(tmp_path):
    db = tmp_path / "solar.db"
    make_db(db, [row(ts=100, pv_w=120.0, out_w=300.0, batt_v=51.2, mode="B")])
    samples = load_samples(db)
    assert len(samples) == 1
    assert samples[0].pv_w == 120.0
    assert samples[0].mode == "B"
    assert samples[0].e_pv_wh is None


def test_max_gap_matches_solarmon_rule():
    assert max_gap(60) == 300
    assert max_gap(1) == 300


def test_missing_database_is_a_report_error(tmp_path):
    with pytest.raises(ReportError):
        load_samples(tmp_path / "nope.db")
```

`tests/analysis_helpers.py` crea la tabella con lo schema esatto di `solarmon.py`:

```python
import sqlite3

SCHEMA = """CREATE TABLE samples(ts INTEGER PRIMARY KEY, pv_w REAL, pv_v REAL, batt_v REAL,
out_w REAL, load_pct REAL, chg_a REAL, dis_a REAL, temp_c REAL, grid_v REAL, mode TEXT,
ws TEXT, e_pv_wh REAL, e_solar_wh REAL, e_batt_wh REAL, e_grid_wh REAL)"""


def row(ts, pv_w=0.0, pv_v=0.0, batt_v=51.0, out_w=0.0, load_pct=0.0, chg_a=0.0,
        dis_a=0.0, temp_c=25.0, grid_v=230.0, mode="L", ws="0" * 32,
        e_pv_wh=None, e_solar_wh=None, e_batt_wh=None, e_grid_wh=None):
    return (ts, pv_w, pv_v, batt_v, out_w, load_pct, chg_a, dis_a, temp_c, grid_v,
            mode, ws, e_pv_wh, e_solar_wh, e_batt_wh, e_grid_wh)


def make_db(path, rows):
    con = sqlite3.connect(path)
    con.execute(SCHEMA)
    con.executemany("INSERT INTO samples VALUES (" + ",".join("?" * 16) + ")", rows)
    con.commit()
    con.close()
    return path


def sample(**kwargs):
    from analysis.db import Sample
    base = dict(ts=0, pv_w=0.0, pv_v=0.0, batt_v=51.0, out_w=0.0, load_pct=0.0,
                chg_a=0.0, dis_a=0.0, temp_c=25.0, grid_v=230.0, mode="L",
                ws="0" * 32, e_pv_wh=None, e_solar_wh=None, e_batt_wh=None,
                e_grid_wh=None)
    base.update(kwargs)
    return Sample(**base)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_db.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'analysis.db'`.

- [ ] **Step 3: Implement**

`analysis/db.py`: `Sample` con `@dataclass(frozen=True)`; `load_samples` apre con
`sqlite3.connect(f"file:{path}?mode=ro", uri=True)`, verifica che `samples` esista
(altrimenti `ReportError`), fa `SELECT` delle 16 colonne ordinate per `ts` e converte
`NULL` numerici in `0.0`, lasciando `None` nelle quattro colonne energia. `since`
filtra `ts >= since` con parametro SQL. `max_gap` è `max(300, 3 * store_interval)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_db.py -q && ruff check analysis tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add analysis/db.py tests/analysis_helpers.py tests/test_analysis_db.py
git commit -m "feat(analysis): lettura in sola lettura dello snapshot SQLite"
```

---

### Task 3: Flussi, profili e cambi di modo

**Files:**
- Create: `analysis/metrics.py`
- Create: `tests/test_analysis_metrics.py`

**Interfaces:**
- Consumes: `Sample`.
- Produces:
  - `Totals(days, pv_kwh, solar_kwh, batt_kwh, grid_kwh, load_kwh, self_sufficiency)`
  - `power_split(s: Sample) -> tuple[float, float, float]` → `(solar_w, batt_w, grid_w)`
  - `energy_step(a: Sample, b: Sample, gap: int) -> tuple[float, float, float, float]`
    → Wh `(pv, solar, batt, grid)`
  - `observed_seconds(samples, gap) -> float`
  - `totals(samples, gap) -> Totals`
  - `daily_by_source(samples, tz, gap) -> dict` con liste `ts, solar, batt, grid`
  - `hourly_profile(samples, tz, gap) -> list[dict]` con `hour, solar_kwh, batt_kwh, grid_kwh, load_kwh`
  - `voltage_series(samples, tz, max_points=720) -> list[tuple[float, float]]` con
    `(ts, batt_v)` ridotti a un punto ogni `ceil(n / max_points)` campioni, più l'ultimo
  - `switch_stats(samples, gap) -> dict` con `total, per_day`
  - `split_interval(start, end, boundary) -> list[tuple[float, float]]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_metrics.py
import pytest

from analysis.db import Sample
from analysis.metrics import (
    energy_step, observed_seconds, power_split, switch_stats, totals,
)
from analysis_helpers import sample


def test_power_split_bypass_all_grid():
    assert power_split(sample(pv_w=500, out_w=300, mode="L")) == (0.0, 0.0, 300.0)


def test_energy_step_trapezoid():
    a = sample(ts=0, pv_w=100, out_w=200, mode="B")
    b = sample(ts=60, pv_w=300, out_w=200, mode="B")
    pv, solar, batt, grid = energy_step(a, b, 300)
    assert pv == pytest.approx(3.333, abs=0.01)
    assert solar == pytest.approx(2.5, abs=0.01)
    assert batt == pytest.approx(0.833, abs=0.01)
    assert grid == 0


def test_gap_does_not_produce_energy():
    a = sample(ts=0, pv_w=1000, out_w=1000, mode="B")
    b = sample(ts=400, pv_w=1000, out_w=1000, mode="B")
    assert energy_step(a, b, 300) == (0.0, 0.0, 0.0, 0.0)


def test_totals_and_days():
    rows = [sample(ts=i * 60, pv_w=100, out_w=100, mode="B") for i in range(1441)]
    assert observed_seconds(rows, 300) == 86400
    t = totals(rows, 300)
    assert t.days == pytest.approx(1.0)
    assert t.pv_kwh == pytest.approx(2.4, abs=0.05)
    assert t.self_sufficiency == pytest.approx(100.0)


def test_switch_confirmation_needs_three_samples():
    rows = [sample(ts=i * 60, mode=m) for i, m in enumerate(["B", "L", "B", "L", "L", "L"])]
    assert switch_stats(rows, 300)["total"] == 1


def test_split_interval_at_boundary():
    from analysis.metrics import split_interval
    assert split_interval(0, 10, lambda t: 4) == [(0, 4), (4, 10)]
```

Aggiungere un test per `hourly_profile` con un intervallo `10:59:30 → 11:00:30` che
verifica che l'energia finisca in due ore diverse, un test per `daily_by_source` con
un intervallo a cavallo di mezzanotte, e un test per `voltage_series` che verifica
`len(serie) <= max_points + 1` e che l'ultimo punto sia l'ultimo campione.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_metrics.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'analysis.metrics'`.

- [ ] **Step 3: Implement**

Replicare `power_split`, la regola del trapezio e la conferma a 3 campioni di
`solarmon.py`. Per i profili: `split_interval` spezza ogni intervallo ai confini dati da
`next_day`/`next_hour`; i kWh per bucket sono `Wh / 1000`, e il profilo orario si divide
per `days` (kWh/giorno). `voltage_series` è un campionamento uniforme per il grafico.
Usare le colonne `e_*` quando tutte e quattro non sono `None`, altrimenti `energy_step`.
I cambi si contano solo verso la rete, con conferma al terzo campione consecutivo; un
buco oltre `gap` azzera la conferma.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_metrics.py -q && ruff check analysis tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add analysis/metrics.py tests/test_analysis_metrics.py
git commit -m "feat(analysis): flussi, profili orari e cambi di modo"
```

---

### Task 4: Diagnostica della batteria

**Files:**
- Create: `analysis/battery.py`
- Create: `tests/test_analysis_battery.py`

**Interfaces:**
- Consumes: `Sample`, `energy_step`, `observed_seconds`.
- Produces: `BatteryReport(e_chg_kwh, e_dis_kwh, e_dis_max_kwh, ref_kwh, ratio,
  jumps_per_day, night_below_pct, verdict, reasons)` e
  `analyze_battery(samples, cfg, tz, *, nominal_kwh=4.8, dod=0.5, gap=300) -> BatteryReport`.
  `cfg` è il dizionario `cfg` di `now.json` oppure `None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_battery.py
import pytest

from analysis.battery import analyze_battery
from analysis.timeutil import get_tz
from analysis_helpers import sample

TZ = get_tz("Europe/Rome")


def test_voltage_jump_detected():
    rows = [sample(ts=0, batt_v=48.1, mode="B", dis_a=10, out_w=500),
            sample(ts=60, batt_v=56.4, mode="L", dis_a=0, out_w=500)]
    report = analyze_battery(rows, None, TZ, nominal_kwh=4.8)
    assert report.jumps_per_day >= 1


def test_dead_pack_is_to_replace():
    rows = []
    for i in range(3 * 1440):
        hour = (i % 1440) / 60
        if 6 <= hour < 9:
            batt, mode, dis = 56.2 - (hour - 6) * 2.7, "B", 1.0
        else:
            batt, mode, dis = 51.0, "L", 0.0
        rows.append(sample(ts=i * 60, batt_v=batt, mode=mode, dis_a=dis, out_w=300))
    report = analyze_battery(rows, None, TZ, nominal_kwh=4.8)
    assert report.verdict == "da_sostituire"


def test_never_discharged_is_indeterminate():
    rows = [sample(ts=i * 60, batt_v=51.0, mode="L", dis_a=0, out_w=200)
            for i in range(2880)]
    assert analyze_battery(rows, None, TZ).verdict == "indeterminato"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_battery.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'analysis.battery'`.

- [ ] **Step 3: Implement**

`E_chg`/`E_dis`: integrare `chg_a × batt_v` e `dis_a × batt_v` con la regola dei buchi.
`E_dis_max`: per ogni giorno locale, trovare il massimo e il minimo di `batt_v` con
`mode="B"` e integrare la scarica tra i due; riportare il massimo tra i giorni.
`ref_kwh = nominal_kwh * dod`; `ratio = E_dis_max / ref_kwh` se `ref_kwh > 0`.
Salti: coppie consecutive con `0 < dt ≤ 120` e `abs(ΔV) ≥ 4`.
`night_below_pct`: campioni notturni con `batt_v < ritorno + 1`; `None` se `cfg` manca.
Verdetto nell'ordine: indeterminato (meno di 24 h; oppure nessun giorno con escursione
≥ 5 V e tentativo di scarica **e** zero salti) → da_sostituire (≥ 5 salti/giorno,
`ratio < 0.20`, oppure ≥ 50% notti sotto soglia per 3 notti) → da_controllare (1–4 salti
o `0.20 ≤ ratio < 0.50`) → sana. Con `cfg` assente si salta solo il criterio notturno:
un `ratio` misurato resta decisivo. Le `reasons` sono frasi con i numeri.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_battery.py -q && ruff check analysis tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add analysis/battery.py tests/test_analysis_battery.py
git commit -m "feat(analysis): diagnostica del pacco batterie"
```

---

### Task 5: Fotovoltaico osservato e potenziale

**Files:**
- Create: `analysis/pv.py`
- Create: `tests/test_analysis_pv.py`

**Interfaces:**
- Consumes: `Sample`, `energy_step`.
- Produces: `PvReport(observed_kwh, peak_w, peak_ts, kwp_eff, available_kwh,
  curtailed_kwh, note)` e
  `analyze_pv(samples, tz, *, lat=None, lon=None, kwp=None, eta=0.85,
  inverter_max_w=4000, gap=300) -> PvReport`; `clear_sky_wm2(lat, lon, ts) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_pv.py
from datetime import datetime, timezone

import pytest

from analysis.pv import analyze_pv, clear_sky_wm2
from analysis.timeutil import get_tz
from analysis_helpers import sample

TZ = get_tz("Europe/Rome")
LAT, LON = 41.20187970064, 13.849261783999081


def utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


def test_clear_sky_night_and_noon():
    assert clear_sky_wm2(LAT, LON, utc(2026, 11, 18, 0, 30)) == 0
    assert clear_sky_wm2(LAT, LON, utc(2026, 11, 18, 11, 0)) > 300


def test_effective_kwp_is_recovered():
    rows = []
    for i in range(0, 24 * 60, 10):
        ts = utc(2026, 11, 17) + i * 60
        ghi = clear_sky_wm2(LAT, LON, ts / 1.0)
        rows.append(sample(ts=ts, pv_w=3000 * (ghi / 1000) * 0.85, pv_v=100, mode="B"))
    report = analyze_pv(rows, TZ, lat=LAT, lon=LON)
    assert report.kwp_eff == pytest.approx(3.0, abs=0.2)


def test_without_coordinates_potential_is_disabled():
    report = analyze_pv([sample(ts=0, pv_w=100)], TZ)
    assert report.kwp_eff is None
    assert report.available_kwh is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_pv.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'analysis.pv'`.

- [ ] **Step 3: Implement**

Geometria solare semplificata (declinazione, angolo orario, elevazione) e cielo chiaro
Haurwitz: `GHI = 1098 * cos(z) * exp(-0.057 / cos(z))`, zero sotto l'orizzonte.
`kwp_eff`: per i campioni con `GHI > 100` e `pv_w > 0`, calcolare
`pv_w / (GHI / 1000 * eta)`, prendere il 95° percentile; se `kwp` è fornito, usarlo.
`available_w = min(kwp_eff * (GHI / 1000) * eta * 1000, inverter_max_w)`.
`available_kwh` e `curtailed_kwh` si integrano sugli stessi intervalli validi;
`observed_kwh` come somma di `e_pv_wh` o di `energy_step`. Senza coordinate, `kwp_eff`,
`available_kwh` e `curtailed_kwh` sono `None` e `note` lo dice.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_pv.py -q && ruff check analysis tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add analysis/pv.py tests/test_analysis_pv.py
git commit -m "feat(analysis): potenziale fotovoltaico a cielo chiaro"
```

---

### Task 6: Bolletta

**Files:**
- Create: `analysis/bill.py`
- Create: `tests/test_analysis_bill.py`

**Interfaces:**
- Consumes: niente.
- Produces: `BillRow(year, month, f1, f2, f3)` con proprietà `total` e
  `load_bill(path) -> list[BillRow]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_bill.py
import pytest

from analysis import ReportError
from analysis.bill import load_bill

CSV = """;Gen - 26 ;Feb - 26
Fascia unica ;0;0
F1 ;115,98;108,76
F2 ;125,09;107,84
F3 ;179,01;157,08
"""


def test_parse_italian_amounts_and_months(tmp_path):
    path = tmp_path / "bolletta.csv"
    path.write_text(CSV, encoding="utf-8")
    rows = load_bill(path)
    assert [(r.year, r.month) for r in rows] == [(2026, 1), (2026, 2)]
    assert rows[0].f1 == 115.98
    assert rows[0].total == pytest.approx(420.08)


def test_missing_file_is_report_error(tmp_path):
    with pytest.raises(ReportError):
        load_bill(tmp_path / "nope.csv")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_bill.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'analysis.bill'`.

- [ ] **Step 3: Implement**

Leggere con `csv.reader(delimiter=";")`; mappare le abbreviazioni italiane
(`gen, feb, mar, apr, mag, giu, lug, ago, set, ott, nov, dic`) e l'anno a due cifre.
Riconoscere le righe `F1`, `F2`, `F3`; ignorare `Fascia unica`, `F4`, `F5`, `F6`.
Convertire `"115,98"` in `115.98`; valori vuoti o non numerici → `ReportError`.
Restituire i mesi in ordine cronologico.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_bill.py -q && ruff check analysis tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add analysis/bill.py tests/test_analysis_bill.py
git commit -m "feat(analysis): lettura della bolletta mensile"
```

---

### Task 7: Motore di simulazione

**Files:**
- Create: `analysis/model.py`
- Create: `tests/test_analysis_model.py`

**Interfaces:**
- Consumes: `Sample`, `energy_step`, `BatteryReport`.
- Produces:
  - `BatterySpec(name, capacity_kwh, dod=0.9, eff=0.90, max_charge_a=60.0,
    max_discharge_a=100.0, nominal_v=51.2, note="")`
  - `ScenarioResult(name, grid_kwh_day, self_sufficiency, curtailed_kwh_day,
    cycles_day, empty_hours_day, cost_day_eur, note)`
  - `simulate(samples, available_pv_w, spec, tz, *, allow_grid_charge=False,
    initial_soc=0.5, price=None, gap=300) -> ScenarioResult`
  - `validate_baseline(samples, battery, cfg, tz, gap=300) -> tuple[bool, str]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_model.py
import pytest

from analysis.model import BatterySpec, simulate, validate_baseline
from analysis.timeutil import get_tz
from analysis_helpers import sample

TZ = get_tz("Europe/Rome")


def day_rows(load_w=1000, pv_w=0):
    return [sample(ts=i * 60, pv_w=pv_w, out_w=load_w, mode="B") for i in range(1440)]


def test_ten_kwh_covers_the_night():
    # 4 h di FV a 2 kW, carico 1 kW per 24 h, batteria 10 kWh / 9 utili.
    rows = []
    for i in range(1440):
        pv = 2000 if 600 <= i < 840 else 0
        rows.append(sample(ts=i * 60, pv_w=pv, out_w=1000, mode="B"))
    spec = BatterySpec("test", 10.0, 0.9, 1.0, 60, 100)
    result = simulate(rows, [r.pv_w for r in rows], spec, TZ, initial_soc=0.0)
    assert result.grid_kwh_day == pytest.approx(16.0, abs=0.2)
    assert result.curtailed_kwh_day == 0


def test_full_battery_curtails_pv():
    rows = [sample(ts=i * 60, pv_w=4000, out_w=100, mode="B") for i in range(600)]
    spec = BatterySpec("small", 1.0, 0.9, 0.90, 60, 100)
    result = simulate(rows, [r.pv_w for r in rows], spec, TZ)
    assert result.curtailed_kwh_day > 1.0


def test_validation_is_skipped_without_cycle():
    rows = day_rows(load_w=1000, pv_w=0)
    battery = type("B", (), {"e_dis_max_kwh": 0.01})()
    ok, note = validate_baseline(rows, battery, None, TZ)
    assert ok is False
    assert "saltata" in note
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_model.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'analysis.model'`.

- [ ] **Step 3: Implement**

Per ogni coppia valida `(a, b)`: `dt`, potenza media di carico e FV. Ordine:
FV → carico; eccedenza → batteria; deficit → batteria; resto → rete. Limiti:
`max_chg_w = spec.max_charge_a * spec.nominal_v`,
`max_dis_w = min(5000.0, spec.max_discharge_a * spec.nominal_v)`.
SOC in Wh tra 0 e `capacity_kwh * 1000 * dod`; rendimento diviso in parti uguali
(`sqrt(eff)` in carica e in scarica). Energia sprecata = eccedenza non caricata.
`grid_kwh_day` e le altre grandezze si dividono per i giorni osservati.
`cost_day_eur = grid_kwh_day * price` solo se `price` è passato (aggiungere il parametro
`price=None` alla firma di `simulate`).
`validate_baseline`: costruisce uno `BatterySpec` con `capacity_kwh = e_dis_max_kwh`,
`dod=1.0`, `eff=1.0`, limiti da `cfg` (default 20 A), simula e confronta `grid_kwh_day`
con i prelievi misurati e `cycles_day * capacity` con `e_dis_kwh`; entro ±20% → `(True,
"modello validato")`, altrimenti `(False, "modello non validato: ...")`. Se
`e_dis_max_kwh < 0.05`, restituire `(False, "validazione saltata: nessun ciclo")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_model.py -q && ruff check analysis tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add analysis/model.py tests/test_analysis_model.py
git commit -m "feat(analysis): motore di simulazione della batteria"
```

---

### Task 8: Scenari, validazione e azioni

**Files:**
- Create: `analysis/scenarios.py`
- Create: `tests/test_analysis_scenarios.py`

**Interfaces:**
- Consumes: `BatterySpec`, `ScenarioResult`, `simulate`, `validate_baseline`,
  `PvReport`, `BatteryReport`, `Totals`, `Sample`.
- Produces:
  - `default_specs(capacities=(10, 16, 20)) -> list[BatterySpec]` con i nomi esatti della spec
  - `reliability(days: float) -> str` → `"bassa" | "media" | "buona"`
  - `run_scenarios(samples, pv, tz, *, battery, cfg, price=None,
    capacities=(10, 16, 20), pv_scales=(1.5, 2.0), gap=300) -> list[ScenarioResult]`
  - `suggested_actions(totals, battery, pv, scenarios, reliability, hourly) -> list[str]`
  - `LFP_16_SETTINGS: dict` con le impostazioni consigliate per la LiFePO4 16 kWh:
    `battery_type="USER"`, `bulk_v=56.0`, `float_v=54.4`, `cutoff_v=46.0`,
    `return_grid_v=47.0`, `return_batt_v=51.0`, `max_charge_a=60.0`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_scenarios.py
from analysis.scenarios import default_specs, reliability, suggested_actions


def test_specs_include_the_compatible_16kwh():
    specs = {s.name: s for s in default_specs()}
    assert "LFP 16 kWh, carica 60 A" in specs
    assert specs["LFP 16 kWh, carica 60 A"].capacity_kwh == 16.0
    assert specs["LFP 16 kWh, carica 60 A"].max_charge_a == 60.0
    assert "LFP 16 kWh, carica 20 A" in specs


def test_reliability_thresholds():
    assert reliability(1.9) == "bassa"
    assert reliability(7.0) == "media"
    assert reliability(31.0) == "buona"


def test_lfp_16_settings_are_declared():
    from analysis.scenarios import LFP_16_SETTINGS
    assert LFP_16_SETTINGS["bulk_v"] == 56.0
    assert LFP_16_SETTINGS["max_charge_a"] == 60.0


def test_low_reliability_prefixes_every_action():
    totals = type("T", (), {"grid_kwh": 10.0, "self_sufficiency": 19.0})()
    battery = type("B", (), {"verdict": "da_sostituire"})()
    pv = type("P", (), {"curtailed_kwh": 2.0})()
    scenario = type("S", (), {"name": "LFP 16 kWh, carica 60 A", "grid_kwh_day": 5.0})()
    actions = suggested_actions(totals, battery, pv, [scenario], "bassa", [])
    assert actions
    assert all(a.startswith("Esercizio, non decisione") for a in actions)


def test_20a_charges_less_than_60a():
    from analysis.model import BatterySpec, simulate
    from analysis.timeutil import get_tz
    from analysis_helpers import sample
    tz = get_tz("Europe/Rome")
    rows = [sample(ts=i * 60, pv_w=3000 if 600 <= i < 840 else 0, out_w=300, mode="B")
            for i in range(1440)]
    pv = [r.pv_w for r in rows]
    slow = simulate(rows, pv, BatterySpec("20A", 16, 0.9, 0.90, 20, 100), tz, initial_soc=0.0)
    fast = simulate(rows, pv, BatterySpec("60A", 16, 0.9, 0.90, 60, 100), tz, initial_soc=0.0)
    assert slow.curtailed_kwh_day > fast.curtailed_kwh_day
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_scenarios.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'analysis.scenarios'`.

- [ ] **Step 3: Implement**

`default_specs` restituisce, nell'ordine: `AGM riparata` (4,8 kWh, dod 0.5, eff 0.80,
20 A), `LFP 16 kWh, carica 20 A`, `LFP 16 kWh, carica 60 A`, `LFP 10 kWh, carica 60 A`,
`LFP 20 kWh, carica 60 A`.
`run_scenarios`: per ogni spec simula con il FV disponibile (osservato o stimato);
per le due righe `16 kWh + FV ×1,5` e `×2` scala `available_pv_w` e limita a 4000 W;
aggiunge la nota sull'intervento al Programma 02 per gli scenari a 60 A.
`LFP_16_SETTINGS` raccoglie le impostazioni inverter della LiFePO4 16 kWh elencate nella
spec (USER, bulk 56,0 V, float 54,4 V, cutoff 46,0 V, ritorno rete 47,0 V, ritorno
batteria 51,0 V, carica 60 A); il report le stampa come riquadro "impostazioni richieste"
accanto allo scenario di riferimento. `solarmon` non le scrive.
`suggested_actions`: massimo tre azioni, con le regole della spec; con affidabilità
"bassa" ogni frase inizia con `"Esercizio, non decisione: "`. La terza regola usa
`hourly` per trovare la fascia 18–22 con carico sopra 1,5× la media giornaliera.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_scenarios.py -q && ruff check analysis tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add analysis/scenarios.py tests/test_analysis_scenarios.py
git commit -m "feat(analysis): scenari batteria e azioni suggerite"
```

---

### Task 9: Report HTML e Markdown

**Files:**
- Create: `analysis/render.py`
- Create: `tests/test_analysis_render.py`

**Interfaces:**
- Consumes: tutti i tipi precedenti.
- Produces: `ReportContext` (dataclass con i campi elencati sotto) e
  `render_html(ctx) -> str`, `render_markdown(ctx) -> str`.

`ReportContext` contiene: `generated_at, tz_name, first_ts, last_ts, days, reliability,
totals, battery, pv, switches, hourly, daily, bill_rows, scenarios, actions,
settings, warnings, voltage`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_render.py
from analysis.render import render_html
from test_analysis_render_context import make_context


def test_html_is_self_contained():
    html = render_html(make_context())
    assert html.startswith("<!DOCTYPE html>")
    assert "NaN" not in html and "None" not in html
    assert "http://" not in html and "https://" not in html
    assert "<script" not in html


def test_html_has_all_sections():
    html = render_html(make_context())
    for title in ("Flussi", "Batteria", "Fotovoltaico", "Consumi",
                  "Simulazioni", "Cosa fare", "Dati e limiti"):
        assert title in html


def test_markdown_keeps_the_verdict():
    from analysis.render import render_markdown
    assert "da sostituire" in render_markdown(make_context()).lower()
```

Creare `tests/test_analysis_render_context.py` con `make_context()` che restituisce un
`ReportContext` completo e minimo (2 giorni, batteria "da_sostituire", 4 scenari).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_render.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'analysis.render'`.

- [ ] **Step 3: Implement**

HTML con CSS inline, sette sezioni, tabelle e tre grafici SVG statici: barre impilate
giornaliere, linea della tensione batteria (da `voltage`), barre del profilo orario.
Il riquadro "impostazioni richieste" per la LiFePO4 16 kWh (`LFP_16_SETTINGS`) sta sotto
la tabella degli scenari. Palette coerente con il dashboard (`#e8a33d` FV, `#4f8fd8`
batteria, `#c0504d` rete) e `@media print` A4. Nessun JavaScript. Markdown con KPI,
verdetto, tabella scenari, impostazioni, azioni e limiti.
`generated_at` è l'unico valore non deterministico: arriva dal contesto.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_render.py -q && ruff check analysis tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add analysis/render.py tests/test_analysis_render.py tests/test_analysis_render_context.py
git commit -m "feat(analysis): report HTML autonomo e riepilogo Markdown"
```

---

### Task 10: CLI, orchestrazione e documentazione

**Files:**
- Create: `analysis/report.py`
- Create: `tests/test_analysis_report.py`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `docs/DECISIONS.md`

**Interfaces:**
- Consumes: tutto quanto sopra.
- Produces: `build_report(db_path, out_dir, *, config=None, bill=None, lat=SITE_LAT,
  lon=SITE_LON, kwp=None, nominal_kwh=4.8, price=None, capacities=None, tz=DEFAULT_TZ,
  generated_at=None) -> Path` e `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_report.py
import json

from analysis.report import build_report, main
from analysis_helpers import make_db, row


def two_days(path):
    rows = []
    for d in range(2):
        for i in range(1440):
            ts = d * 86400 + i * 60
            pv = 1500 if 600 <= i < 840 else 0
            rows.append(row(ts=ts, pv_w=pv, batt_v=51.0, out_w=400.0, mode="B",
                            e_pv_wh=pv / 60.0, e_solar_wh=pv / 60.0))
    return make_db(path, rows)


def test_build_report_writes_three_files(tmp_path):
    db = two_days(tmp_path / "solar.db")
    out = build_report(db, tmp_path / "reports", generated_at="2026-11-18 10:00")
    assert (out / "report.html").exists()
    assert (out / "report.md").exists()
    data = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert data["days"] > 0
    assert data["battery"]["verdict"] in {"sana", "da_controllare", "da_sostituire", "indeterminato"}


def test_empty_database_exits_with_two(tmp_path):
    db = make_db(tmp_path / "solar.db", [])
    code = main(["--db", str(db), "--out", str(tmp_path / "reports")])
    assert code == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_report.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'analysis.report'`.

- [ ] **Step 3: Implement**

Orchestrazione: `load_samples` → `totals`/profili/cambi/`voltage_series` →
`analyze_battery` con il `cfg` di `--config` → `analyze_pv` → `load_bill` se presente →
`run_scenarios` → `suggested_actions` → `ReportContext` → scrivere i tre file in
`out/YYYY-MM-DD_HHMM/` → stampare un riepilogo di ~10 righe con percorso e affidabilità.
`argparse` con le opzioni della spec; `--price` accetta virgola o punto; `--config`
legge `json.load(...)["cfg"]`; errori → messaggio su stderr e codice 2.
Aggiungere a `.gitignore`: `snapshots/`, `reports/`, `*.db`.
In `README.md` aggiungere "Report e simulazioni" con il comando di esempio e le
coordinate di Cellole. In `docs/DECISIONS.md` registrare: report offline, nessuna
modifica al bordo, ipotesi del modello, FV osservato come limite inferiore, batteria
16 kWh compatibile e vincoli di configurazione.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_report.py -q && pytest -q && ruff check .`
Expected: PASS. Se `ruff check .` segnala i file esistenti non toccati, eseguire
`ruff check analysis tests` e dichiararlo nel commit.

- [ ] **Step 5: Commit**

```bash
git add analysis/report.py tests/test_analysis_report.py .gitignore README.md docs/DECISIONS.md
git commit -m "feat(analysis): CLI del report e documentazione"
```

---

### Task 11: Script per lo snapshot

**Files:**
- Create: `scripts/pull-snapshot.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: `ssh`, `scp`, il DB montato sull'host (`<remoto>/data/solar.db`).
- Produces: `snapshots/YYYY-MM-DD.db` sull'host locale.

- [ ] **Step 1: Write the failing test**

```bash
bash -n scripts/pull-snapshot.sh
```
Expected: FAIL (`No such file or directory`).

- [ ] **Step 2: Implement**

`set -eu`; argomenti `HOST` (obbligatorio) e `REMOTE_DB` (default
`~/solarmon/data/solar.db`). Sul remoto eseguire via SSH un backup consistente:

```bash
ssh "$HOST" python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect('/tmp/solarmon-snapshot.db'); s.backup(d); d.close()" "$REMOTE_DB"
scp "$HOST:/tmp/solarmon-snapshot.db" "snapshots/$(date +%F).db"
ssh "$HOST" rm -f /tmp/solarmon-snapshot.db
```

Nessuna credenziale nel file, nessuna porta aperta. Messaggio d'uso se manca `HOST`.

- [ ] **Step 3: Run the check**

Run: `bash -n scripts/pull-snapshot.sh && scripts/pull-snapshot.sh`
Expected: il primo comando tace; il secondo stampa l'uso ed esce con codice 2.

- [ ] **Step 4: Document**

In `README.md` aggiungere i due comandi: `scripts/pull-snapshot.sh pi` e
`python3 -m analysis.report --db snapshots/2026-11-18.db --config now.json --bill consumu_annuali.csv`.

- [ ] **Step 5: Commit**

```bash
git add scripts/pull-snapshot.sh README.md
git commit -m "feat: script per lo snapshot dalla Raspberry"
```

---

## Self-review

- **Copertura spec:** obiettivo (Task 10), non obiettivi (nessuna modifica al bordo in
  tutti i task), vincoli (Task 1), DB (Task 2), flussi e profili (Task 3), batteria
  (Task 4), FV (Task 5), bolletta (Task 6), simulazione (Task 7), scenari 16 kWh e
  azioni (Task 8), HTML/MD (Task 9), CLI e docs (Task 10), pull (Task 11).
- **Tipi coerenti:** `Sample`, `Totals`, `BatteryReport`, `PvReport`, `BatterySpec`,
  `ScenarioResult`, `ReportContext` usati con gli stessi nomi in tutti i task.
- **Review Focus:** i cinque casi hanno un test nei task indicati.
- **Proporzione:** il piano contiene firme e test, non l'implementazione completa.
