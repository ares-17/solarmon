"""Costruzione ed esecuzione degli scenari, valutazione affidabilità e azioni suggerite.

Configura gli scenari di espansione (AGM riparata, LFP da varie taglie, potenziamento FV),
stima la classe di affidabilità in base alla durata del campionamento e genera
le raccomandazioni operative ('Cosa fare') rispettando i vincoli di cautela.
"""

from __future__ import annotations

from typing import Any

from .battery import BatteryReport
from .db import Sample
from .metrics import Totals
from .model import BatterySpec, ScenarioResult, simulate
from .pv import PvReport
from .timeutil import TZ

# Parametri inverter consigliati per il banco LiFePO4 16 kWh 51.2 V
LFP_16_SETTINGS = {
    "battery_type": "USER",
    "bulk_v": 56.0,
    "float_v": 54.4,
    "cutoff_v": 46.0,
    "return_grid_v": 47.0,
    "return_batt_v": 51.0,
    "max_charge_a": 60.0,
}


def reliability(days: float) -> str:
    """Classifica l'affidabilità delle stime in base ai giorni effettivi osservati."""
    if days < 7.0:
        return "bassa"
    if days <= 30.0:
        return "media"
    return "buona"


def default_specs(capacities: tuple[float, ...] = (10, 16, 20)) -> list[BatterySpec]:
    """Genera l'elenco degli scenari di base definiti nella specifica."""
    specs = [
        BatterySpec(
            name="AGM riparata",
            capacity_kwh=4.8,
            dod=0.50,
            eff=0.80,
            max_charge_a=20.0,
            max_discharge_a=30.0,
            nominal_v=48.0,
            note="4,8 kWh nominali, 2,4 kWh utili (50% DoD), rendimento 0,80",
        ),
        BatterySpec(
            name="LFP 16 kWh, carica 20 A",
            capacity_kwh=16.0,
            dod=0.90,
            eff=0.90,
            max_charge_a=20.0,
            max_discharge_a=100.0,
            nominal_v=51.2,
            note="Batteria nuova ma con il Programma 02 attuale a 20 A",
        ),
        BatterySpec(
            name="LFP 16 kWh, carica 60 A",
            capacity_kwh=16.0,
            dod=0.90,
            eff=0.90,
            max_charge_a=60.0,
            max_discharge_a=100.0,
            nominal_v=51.2,
            note="Scenario di riferimento: richiede Programma 02 a 60 A (≈3 kW)",
        ),
    ]

    for cap in capacities:
        cap = float(cap)
        if cap == 16:
            continue
        specs.append(
            BatterySpec(
                name=f"LFP {int(cap) if cap.is_integer() else cap} kWh, carica 60 A",
                capacity_kwh=float(cap),
                dod=0.90,
                eff=0.90,
                max_charge_a=60.0,
                max_discharge_a=100.0,
                nominal_v=51.2,
                note=f"Alternativa LFP {cap} kWh, richiede Programma 02 a 60 A",
            )
        )

    return specs


def run_scenarios(
    samples: list[Sample],
    pv: PvReport,
    tz: TZ,
    *,
    battery: BatteryReport | Any,
    cfg: dict[str, Any] | None = None,
    price: float | None = None,
    capacities: tuple[float, ...] = (10, 16, 20),
    pv_scales: tuple[float, ...] = (1.5, 2.0),
    gap: int = 300,
) -> list[ScenarioResult]:
    """Esegue tutti gli scenari standard e le varianti con FV maggiorato."""
    if not samples:
        return []

    # Serie PV di riferimento: se disponibile_kwh è calcolato, usiamo la stima di produzione disponibile,
    # altrimenti la serie osservata pv_w
    has_potential = pv.kwp_eff is not None and pv.available_kwh is not None
    base_pv_series = [max(0.0, float(s.pv_w or 0.0)) for s in samples]

    results: list[ScenarioResult] = []

    # Scenari batteria standard
    specs = default_specs(capacities)
    for spec in specs:
        res = simulate(
            samples,
            base_pv_series,
            spec,
            tz,
            price=price,
            gap=gap,
        )
        results.append(res)

    # Scenari espansione FV (solo se il potenziale FV è disponibile)
    if has_potential:
        ref_lfp_spec = next((s for s in specs if s.name == "LFP 16 kWh, carica 60 A"), None)
        if ref_lfp_spec is not None:
            for scale in pv_scales:
                # Scala la potenza istantanea fino al limite inverter di 4000 W
                scaled_pv = [min(4000.0, w * scale) for w in base_pv_series]
                name = f"16 kWh + FV ×{scale:g}"
                scaled_spec = BatterySpec(
                    name=name,
                    capacity_kwh=ref_lfp_spec.capacity_kwh,
                    dod=ref_lfp_spec.dod,
                    eff=ref_lfp_spec.eff,
                    max_charge_a=ref_lfp_spec.max_charge_a,
                    max_discharge_a=ref_lfp_spec.max_discharge_a,
                    nominal_v=ref_lfp_spec.nominal_v,
                    note=f"Batteria 16 kWh a 60 A con produzione FV moltiplicata per {scale:g} (cap 4000 W)",
                )
                res = simulate(
                    samples,
                    scaled_pv,
                    scaled_spec,
                    tz,
                    price=price,
                    gap=gap,
                )
                results.append(res)

    return results


def suggested_actions(
    totals: Totals | Any,
    battery: BatteryReport | Any,
    pv: PvReport | Any,
    scenarios: list[ScenarioResult],
    rel: str,
    hourly: list[dict[str, Any]],
) -> list[str]:
    """Genera al massimo 3 raccomandazioni concrete basate sui dati misurati.

    Se l'affidabilità è 'bassa', ogni azione è rigorosamente prefissata con
    'Esercizio, non decisione: '.
    """
    prefix = "Esercizio, non decisione: " if rel == "bassa" else ""
    actions: list[str] = []

    # 1. Se la batteria è 'da_sostituire' (o da controllare grave) -> sostituzione
    b_verdict = getattr(battery, "verdict", "")
    if b_verdict in ("da_sostituire", "da_controllare"):
        # Trova risparmio stimato con scenario LFP 16 kWh, carica 60 A
        lfp16 = next((s for s in scenarios if "16 kWh, carica 60 A" in s.name), None)
        obs_days = getattr(totals, "days", 1.0) or 1.0
        obs_grid_day = (getattr(totals, "grid_kwh", 0.0) or 0.0) / obs_days
        if lfp16:
            saved_kwh = max(0.0, obs_grid_day - lfp16.grid_kwh_day)
            actions.append(
                f"{prefix}Sostituzione banco batterie con LiFePO4 16 kWh (51,2 V, carica 60 A): "
                f"recupero stimato di circa {saved_kwh:.1f} kWh/giorno di prelievo da rete."
            )
        else:
            actions.append(
                f"{prefix}Sostituzione del banco batterie degradato con tecnologia moderna a litio (LiFePO4)."
            )

    # 2. Se il FV è strozzato (curtailed) e affidabilità >= media (o con prefisso esercizio se bassa)
    curtailed = getattr(pv, "curtailed_kwh", 0.0) or 0.0
    if curtailed > 0.5:
        obs_days = getattr(totals, "days", 1.0) or 1.0
        curt_day = curtailed / obs_days
        actions.append(
            f"{prefix}Espansione della capacità di accumulo o dei carichi diurni: "
            f"attualmente circa {curt_day:.1f} kWh/giorno di potenziale FV vengono strozzati dal mancato assorbimento."
        )

    # 3. Spostamento carichi: se ci sono picchi serali (ore 18-22) spostabili a mezzogiorno (ore 11-15)
    if hourly:
        mean_load = sum(h.get("load_kwh", 0.0) for h in hourly) / len(hourly)
        evening_hours = [h for h in hourly if 18 <= h.get("hour", 0) <= 22]
        if evening_hours and mean_load > 0:
            max_evening = max(h.get("load_kwh", 0.0) for h in evening_hours)
            if max_evening > 1.4 * mean_load:
                actions.append(
                    f"{prefix}Spostamento carichi flessibili nella fascia 11:00–15:00 per sfruttare il picco di produzione "
                    f"solare e alleggerire il carico serale."
                )

    return actions[:3]
