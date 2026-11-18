"""Test dei flussi di energia, dei profili locali e dei cambi di modo."""

from datetime import datetime, timezone

import pytest
from analysis_helpers import sample

from analysis.metrics import (
    daily_by_source,
    energy_step,
    hourly_profile,
    observed_seconds,
    power_split,
    split_interval,
    switch_stats,
    totals,
    voltage_series,
)
from analysis.timeutil import day_start, get_tz, next_day

TZ = get_tz("Europe/Rome")


def utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


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
    assert split_interval(0, 10, lambda t: 4) == [(0, 4), (4, 10)]


def test_split_interval_stops_on_bad_boundary():
    """Un confine non avanzante non deve far girare all'infinito."""
    assert split_interval(0, 10, lambda t: 0) == [(0, 10)]
    assert split_interval(10, 10, lambda t: 0) == []


def test_hourly_profile_splits_at_hour():
    midnight = day_start(1_700_000_000, TZ)
    start = midnight + 10 * 3600 + 59 * 60 + 30
    rows = [
        sample(ts=int(start), pv_w=1000, out_w=1000, mode="B"),
        sample(ts=int(start) + 60, pv_w=1000, out_w=1000, mode="B"),
    ]
    profile = hourly_profile(rows, TZ, 300)

    assert [p["hour"] for p in profile] == list(range(24))
    days = 60 / 86400
    half_kwh = (1000 * 60 / 3600) / 2 / 1000 / days
    assert profile[10]["solar_kwh"] == pytest.approx(half_kwh, abs=0.01)
    assert profile[11]["solar_kwh"] == pytest.approx(half_kwh, abs=0.01)
    assert profile[10]["load_kwh"] == pytest.approx(half_kwh, abs=0.01)
    assert profile[10]["batt_kwh"] == 0
    assert profile[9]["solar_kwh"] == 0
    assert profile[12]["solar_kwh"] == 0


def test_daily_by_source_splits_at_midnight():
    midnight = day_start(1_700_000_000, TZ)
    rows = [
        sample(ts=int(midnight) - 30, pv_w=1000, out_w=1000, mode="B"),
        sample(ts=int(midnight) + 30, pv_w=1000, out_w=1000, mode="B"),
    ]
    daily = daily_by_source(rows, TZ, 300)

    assert daily["ts"] == [int(day_start(midnight - 30, TZ)), int(midnight)]
    half_kwh = (1000 * 60 / 3600) / 2 / 1000
    for value in daily["solar"]:
        assert value == pytest.approx(half_kwh, abs=1e-9)
    assert daily["batt"] == [0, 0]
    assert daily["grid"] == [0, 0]


@pytest.mark.parametrize(("noon", "hours"), [(utc(2026, 3, 29, 12), 23), (utc(2026, 10, 25, 12), 25)])
def test_daily_buckets_follow_local_dst_days(noon, hours):
    """Nei giorni di cambio ora il giorno locale dura 23 o 25 ore, non 24."""
    start = int(day_start(noon, TZ))
    end = int(next_day(start, TZ))
    assert end - start == hours * 3600
    rows = [
        sample(ts=start, pv_w=1000, out_w=1000, mode="B"),
        sample(ts=end, pv_w=1000, out_w=1000, mode="B"),
    ]
    daily = daily_by_source(rows, TZ, 100000)
    assert daily["ts"] == [start]
    assert daily["solar"][0] == pytest.approx(hours, abs=0.01)


def test_voltage_series_caps_and_keeps_last():
    rows = [sample(ts=i * 60, batt_v=50.0 + i / 1000) for i in range(2000)]
    series = voltage_series(rows, TZ, max_points=100)
    assert len(series) <= 101
    assert series[-1] == pytest.approx((1999 * 60, 51.999))
    assert series[0] == pytest.approx((0, 50.0))
    assert voltage_series([], TZ, max_points=100) == []


def test_stored_energy_columns_used_per_interval():
    rows = [
        sample(ts=0),
        sample(ts=60, e_pv_wh=10, e_solar_wh=8, e_batt_wh=1, e_grid_wh=2),
        sample(ts=120, e_pv_wh=20, e_solar_wh=16, e_batt_wh=2, e_grid_wh=4),
    ]
    t = totals(rows, 300)
    assert t.pv_kwh == pytest.approx(0.030)
    assert t.solar_kwh == pytest.approx(0.024)
    assert t.batt_kwh == pytest.approx(0.003)
    assert t.grid_kwh == pytest.approx(0.006)
    assert t.load_kwh == pytest.approx(0.033)
    assert t.self_sufficiency == pytest.approx(27 / 33 * 100)


def test_partial_or_missing_energy_columns_fallback():
    """Con una sola colonna valorizzata vale il trapezio, non l'energia parziale."""
    rows = [
        sample(ts=0, pv_w=1000, out_w=1000, mode="B"),
        sample(ts=60, pv_w=1000, out_w=1000, mode="B", e_pv_wh=0, e_solar_wh=0, e_batt_wh=0, e_grid_wh=0),
        sample(ts=120, pv_w=1000, out_w=1000, mode="B", e_pv_wh=999),
    ]
    t = totals(rows, 300)
    assert t.pv_kwh == pytest.approx(1000 * 60 / 3600 / 1000)
    assert t.solar_kwh == pytest.approx(1000 * 60 / 3600 / 1000)


def test_gap_skips_stored_energy():
    """Un buco oltre gap resta un buco anche se le colonne e_* sono valorizzate."""
    rows = [
        sample(ts=0),
        sample(ts=400, e_pv_wh=100, e_solar_wh=100, e_batt_wh=0, e_grid_wh=0),
    ]
    assert totals(rows, 300).pv_kwh == 0


def test_totals_without_load_has_no_self_sufficiency():
    t = totals([sample(ts=0), sample(ts=60)], 300)
    assert t.days == pytest.approx(60 / 86400)
    assert t.load_kwh == 0
    assert t.self_sufficiency is None
