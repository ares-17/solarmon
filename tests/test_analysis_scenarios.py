"""Test della definizione degli scenari, affidabilità e azioni suggerite."""

from analysis_helpers import sample

from analysis.model import BatterySpec, simulate
from analysis.scenarios import LFP_16_SETTINGS, default_specs, reliability, suggested_actions
from analysis.timeutil import get_tz


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
    assert LFP_16_SETTINGS["bulk_v"] == 56.0
    assert LFP_16_SETTINGS["max_charge_a"] == 60.0


def test_low_reliability_prefixes_every_action():
    totals = type("T", (), {"grid_kwh": 10.0, "self_sufficiency": 19.0, "days": 1.0})()
    battery = type("B", (), {"verdict": "da_sostituire"})()
    pv = type("P", (), {"curtailed_kwh": 2.0})()
    scenario = type("S", (), {"name": "LFP 16 kWh, carica 60 A", "grid_kwh_day": 5.0})()
    actions = suggested_actions(totals, battery, pv, [scenario], "bassa", [])
    assert actions
    assert all(a.startswith("Esercizio, non decisione") for a in actions)


def test_20a_charges_less_than_60a():
    tz = get_tz("Europe/Rome")
    rows = [sample(ts=i * 60, pv_w=3000 if 600 <= i < 840 else 0, out_w=300, mode="B") for i in range(1440)]
    pv = [r.pv_w for r in rows]
    slow = simulate(rows, pv, BatterySpec("20A", 16, 0.9, 0.90, 20, 100), tz, initial_soc=0.0)
    fast = simulate(rows, pv, BatterySpec("60A", 16, 0.9, 0.90, 60, 100), tz, initial_soc=0.0)
    assert slow.curtailed_kwh_day > fast.curtailed_kwh_day
