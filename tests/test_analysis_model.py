"""Test del motore di simulazione della batteria e degli scenari."""

import pytest
from analysis_helpers import sample

from analysis.model import BatterySpec, simulate, validate_baseline
from analysis.timeutil import get_tz

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
