"""Helper per i test di render: genera un ReportContext minimale ma completo."""

from datetime import datetime, timezone

from analysis.battery import BatteryReport
from analysis.bill import BillRow
from analysis.metrics import Totals
from analysis.model import ScenarioResult
from analysis.pv import PvReport
from analysis.render import ReportContext
from analysis.scenarios import LFP_16_SETTINGS


def make_context() -> ReportContext:
    now_utc = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc).timestamp()
    tot = Totals(
        days=2.0,
        pv_kwh=10.0,
        solar_kwh=6.0,
        batt_kwh=2.0,
        grid_kwh=12.0,
        load_kwh=20.0,
        self_sufficiency=40.0,
    )
    batt = BatteryReport(
        e_chg_kwh=2.5,
        e_dis_kwh=2.0,
        e_dis_max_kwh=0.3,
        ref_kwh=2.4,
        ratio=0.125,
        jumps_per_day=6.0,
        night_below_pct=85.0,
        verdict="da_sostituire",
        reasons=[
            "Rilevati 6.0 salti bruschi di tensione al giorno.",
            "Energia ciclo profondo (0.30 kWh) inferiore al 20% del riferimento (ratio 12.5%).",
        ],
    )
    pv = PvReport(
        observed_kwh=10.0,
        peak_w=2800.0,
        peak_ts=int(now_utc - 86400),
        kwp_eff=3.2,
        available_kwh=16.0,
        curtailed_kwh=6.0,
        note="Taglia efficace stimata: 3.20 kWp.",
    )
    switches = {"total": 12, "per_day": {int(now_utc): 6}}
    hourly = [
        {
            "hour": h,
            "solar_kwh": 0.25 if 10 <= h <= 15 else 0.0,
            "batt_kwh": 0.1 if 18 <= h <= 21 else 0.0,
            "grid_kwh": 0.5 if (h < 7 or h > 21) else 0.1,
            "load_kwh": 0.6,
        }
        for h in range(24)
    ]
    daily = {
        "ts": [int(now_utc - 86400), int(now_utc)],
        "solar": [3.0, 3.0],
        "batt": [1.0, 1.0],
        "grid": [6.0, 6.0],
    }
    bill = [BillRow(year=2026, month=10, f1=50.0, f2=60.0, f3=90.0)]
    scenarios = [
        ScenarioResult(
            name="Osservato",
            grid_kwh_day=6.0,
            self_sufficiency=40.0,
            curtailed_kwh_day=3.0,
            cycles_day=0.4,
            empty_hours_day=14.0,
            cost_day_eur=None,
            note="Misurazioni reali",
        ),
        ScenarioResult(
            name="LFP 16 kWh, carica 60 A",
            grid_kwh_day=1.5,
            self_sufficiency=85.0,
            curtailed_kwh_day=0.2,
            cycles_day=0.6,
            empty_hours_day=2.0,
            cost_day_eur=None,
            note="Richiede Programma 02 a 60 A",
        ),
    ]
    actions = [
        "Esercizio, non decisione: Sostituzione banco batterie con LiFePO4 16 kWh.",
        "Esercizio, non decisione: Spostamento carichi nelle ore centrali.",
    ]
    voltage = [(float(now_utc - 3600 * i), 51.0 - i * 0.1) for i in range(10)]
    settings = LFP_16_SETTINGS
    warnings = ["Meno di 7 giorni osservati: affidabilità bassa."]

    return ReportContext(
        generated_at="2026-11-18 12:00:00",
        tz_name="Europe/Rome",
        first_ts=int(now_utc - 2 * 86400),
        last_ts=int(now_utc),
        days=2.0,
        reliability="bassa",
        totals=tot,
        battery=batt,
        pv=pv,
        switches=switches,
        hourly=hourly,
        daily=daily,
        bill_rows=bill,
        scenarios=scenarios,
        actions=actions,
        settings=settings,
        warnings=warnings,
        voltage=voltage,
    )
