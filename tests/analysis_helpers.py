"""Helper dei test di analisi: DB temporanei con lo schema esatto di solarmon."""

import sqlite3

SCHEMA = """CREATE TABLE samples(ts INTEGER PRIMARY KEY, pv_w REAL, pv_v REAL, batt_v REAL,
out_w REAL, load_pct REAL, chg_a REAL, dis_a REAL, temp_c REAL, grid_v REAL, mode TEXT,
ws TEXT, e_pv_wh REAL, e_solar_wh REAL, e_batt_wh REAL, e_grid_wh REAL)"""


def row(ts, pv_w=0.0, pv_v=0.0, batt_v=51.0, out_w=0.0, load_pct=0.0, chg_a=0.0,
        dis_a=0.0, temp_c=25.0, grid_v=230.0, mode="L", ws="0" * 32,
        e_pv_wh=None, e_solar_wh=None, e_batt_wh=None, e_grid_wh=None):
    """Riga nella forma delle 16 colonne di samples."""
    return (ts, pv_w, pv_v, batt_v, out_w, load_pct, chg_a, dis_a, temp_c, grid_v,
            mode, ws, e_pv_wh, e_solar_wh, e_batt_wh, e_grid_wh)


def make_db(path, rows):
    """Crea un file SQLite con la sola tabella samples e le righe date."""
    con = sqlite3.connect(path)
    con.execute(SCHEMA)
    con.executemany("INSERT INTO samples VALUES (" + ",".join("?" * 16) + ")", rows)
    con.commit()
    con.close()
    return path


def sample(**kwargs):
    """Costruisce un Sample lasciando i default ai campi non indicati."""
    from analysis.db import Sample
    base = dict(ts=0, pv_w=0.0, pv_v=0.0, batt_v=51.0, out_w=0.0, load_pct=0.0,
                chg_a=0.0, dis_a=0.0, temp_c=25.0, grid_v=230.0, mode="L",
                ws="0" * 32, e_pv_wh=None, e_solar_wh=None, e_batt_wh=None,
                e_grid_wh=None)
    base.update(kwargs)
    return Sample(**base)
