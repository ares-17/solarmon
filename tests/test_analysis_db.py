"""Test della lettura in sola lettura dello snapshot SQLite."""

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


def test_max_gap_matches_solarmon_rule():
    assert max_gap(60) == 300
    assert max_gap(1) == 300


def test_missing_database_is_a_report_error(tmp_path):
    with pytest.raises(ReportError):
        load_samples(tmp_path / "nope.db")
