"""Test della diagnostica della batteria."""

from analysis_helpers import sample

from analysis.battery import analyze_battery
from analysis.timeutil import get_tz

TZ = get_tz("Europe/Rome")


def test_voltage_jump_detected():
    rows = [
        sample(ts=0, batt_v=48.1, mode="B", dis_a=10, out_w=500),
        sample(ts=60, batt_v=56.4, mode="L", dis_a=0, out_w=500),
    ]
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
    rows = [sample(ts=i * 60, batt_v=51.0, mode="L", dis_a=0, out_w=200) for i in range(2880)]
    assert analyze_battery(rows, None, TZ).verdict == "indeterminato"


def test_healthy_pack_verdict():
    # 3 giorni: scarica con escursione ampia, ratio >= 50%, nessun salto, notte sopra soglia
    rows = []
    cfg = {"Ritorno a rete sotto V": "47.0"}
    for day in range(3):
        day_offset = day * 86400
        for i in range(1440):
            ts = day_offset + i * 60
            hour = (i % 1440) / 60
            if 0 <= hour < 10:
                # Notte / prima mattina sopra soglia (49.0V > 47+1V)
                batt = 49.0
                rows.append(sample(ts=ts, batt_v=batt, mode="L", chg_a=0.0, dis_a=0.0, out_w=100))
            elif 10 <= hour < 14:
                # Carica graduale da 49.0 a 55.0 V in 4 ore (nessun salto brusco)
                batt = 49.0 + (hour - 10) * 1.5
                rows.append(sample(ts=ts, batt_v=batt, mode="B", chg_a=10.0, dis_a=0.0, out_w=200))
            elif 14 <= hour < 18:
                # Mantenimento a 55.0 V
                batt = 55.0
                rows.append(sample(ts=ts, batt_v=batt, mode="B", chg_a=2.0, dis_a=0.0, out_w=200))
            elif 18 <= hour < 22:
                # Scarica graduale da 55.0 V a 49.0 V (escursione 6V >= 5V, dis_a=10A * ~52V * 4h ~= 2.08 kWh)
                batt = 55.0 - (hour - 18) * 1.5
                rows.append(sample(ts=ts, batt_v=batt, mode="B", chg_a=0.0, dis_a=10.0, out_w=500))
            else:
                # 22-24 sera / notte sopra soglia a 49.0 V
                batt = 49.0
                rows.append(sample(ts=ts, batt_v=batt, mode="L", chg_a=0.0, dis_a=0.0, out_w=100))

    report = analyze_battery(rows, cfg, TZ, nominal_kwh=4.8, dod=0.5)
    assert report.verdict == "sana"
    assert report.ratio is not None and report.ratio >= 0.50
    assert report.jumps_per_day == 0


def test_less_than_24h_is_indeterminate():
    rows = [sample(ts=i * 60, batt_v=51.0, mode="B", dis_a=5.0, out_w=250) for i in range(100)]
    report = analyze_battery(rows, None, TZ)
    assert report.verdict == "indeterminato"
