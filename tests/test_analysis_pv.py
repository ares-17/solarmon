"""Test del modello fotovoltaico osservato e a cielo chiaro."""

from datetime import datetime, timezone

import pytest
from analysis_helpers import sample

from analysis.pv import analyze_pv, clear_sky_wm2
from analysis.timeutil import get_tz

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
