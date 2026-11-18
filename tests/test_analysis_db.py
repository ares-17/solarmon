"""Test della lettura in sola lettura dello snapshot SQLite."""

import sqlite3

import pytest
from analysis_helpers import make_db, row

from analysis import ReportError
from analysis.db import load_samples, max_gap


def test_load_samples_and_nulls(tmp_path):
    db = tmp_path / "solar.db"
    make_db(db, [row(ts=100, pv_w=120.0, out_w=300.0, batt_v=51.2, mode="B")])
    samples = load_samples(db)
    assert len(samples) == 1
    assert samples[0].pv_w == 120.0
    assert samples[0].mode == "B"
    assert samples[0].e_pv_wh is None


def test_numeric_nulls_become_zero(tmp_path):
    db = tmp_path / "solar.db"
    make_db(db, [row(ts=100, pv_w=None, out_w=None, batt_v=None, grid_v=None, temp_c=None)])
    s = load_samples(db)[0]
    for valore in (s.pv_w, s.out_w, s.batt_v, s.grid_v, s.temp_c):
        assert valore == 0.0
        assert isinstance(valore, float)


def test_energy_columns_keep_their_position(tmp_path):
    db = tmp_path / "solar.db"
    make_db(db, [row(ts=100, e_pv_wh=1.0, e_solar_wh=2.0, e_batt_wh=3.0, e_grid_wh=4.0)])
    s = load_samples(db)[0]
    assert (s.e_pv_wh, s.e_solar_wh, s.e_batt_wh, s.e_grid_wh) == (1.0, 2.0, 3.0, 4.0)


def test_since_filters_with_inclusive_boundary(tmp_path):
    db = tmp_path / "solar.db"
    make_db(db, [row(ts=100), row(ts=200), row(ts=300)])
    assert [s.ts for s in load_samples(db)] == [100, 200, 300]
    assert [s.ts for s in load_samples(db, since=50)] == [100, 200, 300]
    # il confine è incluso: ts == since entra nel risultato
    assert [s.ts for s in load_samples(db, since=200)] == [200, 300]
    assert [s.ts for s in load_samples(db, since=200.0)] == [200, 300]
    assert load_samples(db, since=301) == []


def test_max_gap_matches_solarmon_rule():
    assert max_gap(60) == 300
    assert max_gap(1) == 300


def test_missing_database_is_a_report_error(tmp_path):
    with pytest.raises(ReportError):
        load_samples(tmp_path / "nope.db")


def test_database_without_samples_table_is_a_report_error(tmp_path):
    db = tmp_path / "other.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE other(x INTEGER)")
    con.commit()
    con.close()
    with pytest.raises(ReportError):
        load_samples(db)
