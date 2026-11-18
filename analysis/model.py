"""Motore di simulazione a passi della batteria e validazione del modello.

Simula il flusso energetico sui campioni reali:
1. FV copre il carico.
2. Eccedenza carica la batteria fino al limite di carica / capacità.
3. Deficit scarica la batteria fino al limite di scarica / DoD minimo.
4. Il residuo è prelevato dalla rete.
5. L'eccedenza FV che non entra nella batteria è contata come sprecata (curtailed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .battery import BatteryReport
from .db import Sample
from .metrics import observed_seconds, totals
from .timeutil import TZ

SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class BatterySpec:
    """Specifiche tecniche e limiti operativi della batteria simulata."""

    name: str
    capacity_kwh: float
    dod: float = 0.90
    eff: float = 0.90
    max_charge_a: float = 60.0
    max_discharge_a: float = 100.0
    nominal_v: float = 51.2
    note: str = ""


@dataclass(frozen=True)
class ScenarioResult:
    """Risultato aggregato della simulazione per uno scenario."""

    name: str
    grid_kwh_day: float
    self_sufficiency: float
    curtailed_kwh_day: float
    cycles_day: float
    empty_hours_day: float
    cost_day_eur: float | None
    note: str


def simulate(
    samples: list[Sample],
    available_pv_w: list[float],
    spec: BatterySpec,
    tz: TZ,
    *,
    allow_grid_charge: bool = False,
    initial_soc: float = 0.5,
    price: float | None = None,
    gap: int = 300,
) -> ScenarioResult:
    """Esegue la simulazione cronologica a passi per la configurazione data."""
    if not samples or len(samples) < 2:
        return ScenarioResult(
            name=spec.name,
            grid_kwh_day=0.0,
            self_sufficiency=0.0,
            curtailed_kwh_day=0.0,
            cycles_day=0.0,
            empty_hours_day=0.0,
            cost_day_eur=None if price is None else 0.0,
            note=spec.note,
        )

    obs_sec = observed_seconds(samples, gap)
    days = obs_sec / SECONDS_PER_DAY if obs_sec > 0 else 1.0

    usable_kwh = spec.capacity_kwh * spec.dod
    max_soc_wh = usable_kwh * 1000.0
    # Rendimento diviso in parti uguali: sqrt(eff) in carica e sqrt(eff) in scarica
    eta_half = math.sqrt(spec.eff) if spec.eff > 0 else 1.0

    # Limiti di potenza
    max_chg_w = spec.max_charge_a * spec.nominal_v
    # Max inverter 5000 W o limite C-rate della batteria
    max_dis_w = min(5000.0, spec.max_discharge_a * spec.nominal_v)

    # Stato iniziale in Wh
    soc_wh = max_soc_wh * max(0.0, min(1.0, initial_soc))

    total_load_wh = 0.0
    total_grid_wh = 0.0
    total_solar_direct_wh = 0.0
    total_discharged_wh = 0.0
    total_curtailed_wh = 0.0
    empty_seconds = 0.0

    for i, (a, b) in enumerate(zip(samples, samples[1:])):
        dt = float(b.ts) - float(a.ts)
        if not 0 < dt <= gap:
            continue

        # Carico medio nell'intervallo
        load_w = (max(0.0, float(a.out_w or 0.0)) + max(0.0, float(b.out_w or 0.0))) / 2.0
        # FV medio disponibile nell'intervallo
        pv_a = max(0.0, float(available_pv_w[i] if i < len(available_pv_w) else a.pv_w or 0.0))
        pv_b = max(0.0, float(available_pv_w[i + 1] if i + 1 < len(available_pv_w) else b.pv_w or 0.0))
        pv_w = (pv_a + pv_b) / 2.0

        hrs = dt / 3600.0
        step_load_wh = load_w * hrs
        total_load_wh += step_load_wh

        # 1. FV copre il carico
        solar_to_load_w = min(pv_w, load_w)
        total_solar_direct_wh += solar_to_load_w * hrs
        rem_load_w = load_w - solar_to_load_w
        surplus_pv_w = pv_w - solar_to_load_w

        # 2. Surplus carica la batteria
        if surplus_pv_w > 0:
            chg_w = min(surplus_pv_w, max_chg_w)
            energy_in_wh = chg_w * hrs * eta_half
            space_wh = max_soc_wh - soc_wh
            actual_in_wh = min(energy_in_wh, space_wh)
            soc_wh += actual_in_wh

            # PV eccedente non caricato
            used_surplus_w = (actual_in_wh / (hrs * eta_half)) if (hrs > 0 and eta_half > 0) else 0.0
            curtailed_w = max(0.0, surplus_pv_w - used_surplus_w)
            total_curtailed_wh += curtailed_w * hrs

        # 3. Deficit scarica la batteria
        if rem_load_w > 0:
            dis_req_w = min(rem_load_w, max_dis_w)
            # Per erogare dis_req_w, la batteria interna perde dis_req_w / eta_half
            energy_out_needed_wh = (dis_req_w * hrs) / eta_half if eta_half > 0 else dis_req_w * hrs
            actual_internal_wh = min(energy_out_needed_wh, soc_wh)
            soc_wh -= actual_internal_wh
            delivered_wh = actual_internal_wh * eta_half
            total_discharged_wh += delivered_wh

            # Rimanente carico va su rete
            delivered_w = delivered_wh / hrs if hrs > 0 else 0.0
            grid_w = rem_load_w - delivered_w
            total_grid_wh += grid_w * hrs

        # Tempo a batteria vuota
        if soc_wh <= 1e-4:
            empty_seconds += dt

    grid_kwh_day = (total_grid_wh / 1000.0) / days
    curtailed_kwh_day = (total_curtailed_wh / 1000.0) / days
    discharged_kwh_day = (total_discharged_wh / 1000.0) / days

    cycles_day = (discharged_kwh_day / usable_kwh) if usable_kwh > 0 else 0.0
    empty_hours_day = (empty_seconds / 3600.0) / days

    self_suff = (
        ((total_solar_direct_wh + total_discharged_wh) / total_load_wh * 100.0)
        if total_load_wh > 0
        else 0.0
    )

    cost_day_eur = (grid_kwh_day * price) if price is not None else None

    return ScenarioResult(
        name=spec.name,
        grid_kwh_day=grid_kwh_day,
        self_sufficiency=min(100.0, max(0.0, self_suff)),
        curtailed_kwh_day=curtailed_kwh_day,
        cycles_day=cycles_day,
        empty_hours_day=empty_hours_day,
        cost_day_eur=cost_day_eur,
        note=spec.note,
    )


def validate_baseline(
    samples: list[Sample],
    battery: BatteryReport | Any,
    cfg: dict[str, Any] | None,
    tz: TZ,
    *,
    gap: int = 300,
) -> tuple[bool, str]:
    """Valida il modello confrontando una simulazione con i dati misurati reali."""
    if not samples or len(samples) < 2:
        return False, "validazione saltata: campioni insufficienti"

    e_dis_max = getattr(battery, "e_dis_max_kwh", 0.0)
    if e_dis_max < 0.05:
        return False, "validazione saltata: nessun ciclo significativo osservato"

    # Ricava parametri reali
    max_charge_a = 20.0
    if cfg:
        for k in ("Max carica A", "max_charge_a"):
            if k in cfg:
                try:
                    max_charge_a = float(cfg[k])
                    break
                except (ValueError, TypeError):
                    pass

    # Spec di baseline con i valori misurati reali
    baseline_spec = BatterySpec(
        name="Baseline misurata",
        capacity_kwh=e_dis_max,
        dod=1.0,
        eff=1.0,
        max_charge_a=max_charge_a,
        max_discharge_a=100.0,
        nominal_v=48.0,
    )

    pv_w_series = [max(0.0, float(s.pv_w or 0.0)) for s in samples]
    res = simulate(samples, pv_w_series, baseline_spec, tz, gap=gap)

    # Confronta con i totali misurati reali
    meas_totals = totals(samples, gap)
    obs_days = meas_totals.days if meas_totals.days > 0 else 1.0
    meas_grid_kwh_day = meas_totals.grid_kwh / obs_days

    # Verifica deviazione prelievo rete entro +-20%
    if meas_grid_kwh_day > 0.1:
        dev = abs(res.grid_kwh_day - meas_grid_kwh_day) / meas_grid_kwh_day
        if dev > 0.20:
            return (
                False,
                f"modello non validato: prelievo rete simulato ({res.grid_kwh_day:.2f} kWh/giorno) devia del {dev*100:.1f}% rispetto al misurato ({meas_grid_kwh_day:.2f} kWh/giorno).",
            )

    return True, "modello validato"
