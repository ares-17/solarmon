"""Lettura in sola lettura dello snapshot SQLite scritto da solarmon.

Il database viene aperto con `mode=ro`: l'analisi non deve mai modificare il file
che il servizio di monitoraggio sta usando.
"""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from analysis import ReportError

# Colonne nell'ordine dello schema di solarmon.py.
COLUMNS = (
    "ts", "pv_w", "pv_v", "batt_v", "out_w", "load_pct", "chg_a", "dis_a",
    "temp_c", "grid_v", "mode", "ws", "e_pv_wh", "e_solar_wh", "e_batt_wh", "e_grid_wh",
)

# Intervallo minimo (s) oltre il quale una pausa di campionamento è un buco di dati.
MIN_GAP = 300


@dataclass(frozen=True)
class Sample:
    """Una riga di `samples`, con i NULL numerici già normalizzati a 0.0."""

    ts: int
    pv_w: float
    pv_v: float
    batt_v: float
    out_w: float
    load_pct: float
    chg_a: float
    dis_a: float
    temp_c: float
    grid_v: float
    mode: str
    ws: str
    e_pv_wh: float | None
    e_solar_wh: float | None
    e_batt_wh: float | None
    e_grid_wh: float | None


def _connect(path: str | Path) -> sqlite3.Connection:
    """Apre lo snapshot in sola lettura, traducendo ogni errore in ReportError."""
    p = Path(path)
    if not p.is_file():
        raise ReportError(f"database non trovato: {p}")
    uri = f"file:{quote(str(p.resolve()), safe='/')}?mode=ro"
    try:
        return sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:  # permessi, file non SQLite, path non valido
        raise ReportError(f"impossibile aprire il database {p}: {exc}") from exc


def _to_sample(raw: tuple) -> Sample:
    """Converte una riga SQL: 0.0 sui numerici NULL, None sulle quattro energie."""
    return Sample(
        ts=int(raw[0]),
        pv_w=raw[1] or 0.0,
        pv_v=raw[2] or 0.0,
        batt_v=raw[3] or 0.0,
        out_w=raw[4] or 0.0,
        load_pct=raw[5] or 0.0,
        chg_a=raw[6] or 0.0,
        dis_a=raw[7] or 0.0,
        temp_c=raw[8] or 0.0,
        grid_v=raw[9] or 0.0,
        mode=raw[10] or "",
        ws=raw[11] or "",
        e_pv_wh=raw[12],
        e_solar_wh=raw[13],
        e_batt_wh=raw[14],
        e_grid_wh=raw[15],
    )


def load_samples(path: str | Path, since: float | None = None) -> list[Sample]:
    """Legge i campioni ordinati per `ts`, opzionalmente solo da `since` in poi."""
    sql = f"SELECT {', '.join(COLUMNS)} FROM samples"
    params: tuple = ()
    if since is not None:
        sql += " WHERE ts >= ?"
        params = (since,)
    sql += " ORDER BY ts"

    try:
        with closing(_connect(path)) as con:
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'samples'"
            ).fetchone()
            if exists is None:
                raise ReportError(f"tabella 'samples' assente in {path}")
            rows = con.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        raise ReportError(f"lettura del database {path} fallita: {exc}") from exc
    return [_to_sample(r) for r in rows]


def max_gap(store_interval: int = 60) -> int:
    """Pausa oltre la quale i campioni sono considerati discontinui (regola di solarmon)."""
    return max(MIN_GAP, 3 * store_interval)
