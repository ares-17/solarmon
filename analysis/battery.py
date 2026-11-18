"""Diagnostica del pacco batterie.

Misura throughput, salti di tensione rapidi, tenuta notturna e stima
dell'energia del ciclo più profondo senza inventare una curva di SOC.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .db import Sample
from .metrics import observed_seconds
from .timeutil import TZ, day_start, is_night

SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class BatteryReport:
    """Esito dell'analisi della batteria e indicatori di salute."""

    e_chg_kwh: float
    e_dis_kwh: float
    e_dis_max_kwh: float
    ref_kwh: float
    ratio: float | None
    jumps_per_day: float
    night_below_pct: float | None
    verdict: str  # "sana" | "da_controllare" | "da_sostituire" | "indeterminato"
    reasons: list[str]


def _integrate_power(samples: list[Sample], gap: int, power_fn) -> float:
    """Integra la potenza (Wh) tra campioni consecutivi con la regola del trapezio."""
    wh = 0.0
    for a, b in zip(samples, samples[1:]):
        dt = float(b.ts) - float(a.ts)
        if 0 < dt <= gap:
            p0 = power_fn(a)
            p1 = power_fn(b)
            wh += (p0 + p1) / 2.0 * (dt / 3600.0)
    return wh


def _find_daily_deepest_discharge(samples: list[Sample], tz: TZ, gap: int) -> float:
    """Massima energia scaricata (Wh) tra un massimo e un minimo di tensione nello stesso giorno locale.

    Considera solo campioni con mode == 'B' (o l'intero giorno se rilevante).
    La spec: 'la massima energia scaricata tra un massimo e un minimo di tensione
    nello stesso giorno'.
    """
    if not samples:
        return 0.0

    # Raggruppa i campioni per giorno locale
    days_samples: dict[float, list[Sample]] = {}
    for s in samples:
        d = day_start(float(s.ts), tz)
        days_samples.setdefault(d, []).append(s)

    max_daily_wh = 0.0

    for day_s in days_samples.values():
        if len(day_s) < 2:
            continue
        # Trova il massimo e il minimo di batt_v in mode B (se presenti),
        # altrimenti su tutti i campioni del giorno se mode B non c'è.
        b_samples = [s for s in day_s if s.mode == "B"]
        target_samples = b_samples if b_samples else day_s

        v_max = max(float(s.batt_v) for s in target_samples)
        v_min = min(float(s.batt_v) for s in target_samples)

        if v_max <= v_min:
            continue

        # Trova gli indici dei campioni corrispondenti a v_max e poi al successivo v_min
        # Oppure il massimo tra tutte le coppie (ts_max, ts_min) con ts_max < ts_min.
        # Più robusto: trova il timestamp del primo picco massimo e del successivo minimo nel giorno.
        first_max_ts = min(float(s.ts) for s in target_samples if float(s.batt_v) == v_max)
        after_max = [s for s in target_samples if float(s.ts) >= first_max_ts]
        if not after_max:
            continue
        min_after_max_v = min(float(s.batt_v) for s in after_max)
        last_min_ts = max(float(s.ts) for s in after_max if float(s.batt_v) == min_after_max_v)

        if last_min_ts <= first_max_ts:
            continue

        # Integra la potenza di scarica (dis_a * batt_v) tra first_max_ts e last_min_ts
        sub = [s for s in day_s if first_max_ts <= float(s.ts) <= last_min_ts]
        wh = _integrate_power(sub, gap, lambda s: max(0.0, float(s.dis_a or 0.0) * float(s.batt_v or 0.0)))
        if wh > max_daily_wh:
            max_daily_wh = wh

    return max_daily_wh


def analyze_battery(
    samples: list[Sample],
    cfg: dict[str, Any] | None,
    tz: TZ,
    *,
    nominal_kwh: float = 4.8,
    dod: float = 0.5,
    gap: int = 300,
) -> BatteryReport:
    """Esegue la diagnostica del pacco batterie e determina il verdetto tecnico."""
    obs_sec = observed_seconds(samples, gap)
    days = obs_sec / SECONDS_PER_DAY

    # 1. Throughput
    chg_wh = _integrate_power(samples, gap, lambda s: max(0.0, float(s.chg_a or 0.0) * float(s.batt_v or 0.0)))
    dis_wh = _integrate_power(samples, gap, lambda s: max(0.0, float(s.dis_a or 0.0) * float(s.batt_v or 0.0)))
    e_chg_kwh = chg_wh / 1000.0
    e_dis_kwh = dis_wh / 1000.0

    # 2. Ciclo più profondo e riferimento
    deepest_wh = _find_daily_deepest_discharge(samples, tz, gap)
    e_dis_max_kwh = deepest_wh / 1000.0
    ref_kwh = nominal_kwh * dod
    ratio = (e_dis_max_kwh / ref_kwh) if ref_kwh > 0 else None

    # 3. Salti di tensione (ΔV >= 4V in <= 120s)
    jumps = 0
    for a, b in zip(samples, samples[1:]):
        dt = float(b.ts) - float(a.ts)
        if 0 < dt <= 120:
            if abs(float(b.batt_v) - float(a.batt_v)) >= 4.0:
                jumps += 1
    jumps_per_day = (jumps / days) if days > 0 else float(jumps)

    # 4. Tempo notturno sotto soglia (22:00 - 06:00)
    # batt_v < ritorno a rete + 1 V
    grid_return_v = None
    if cfg:
        # Cerca la chiave di ritorno a rete
        for k in ("Ritorno a rete sotto V", "ritorno_rete_v", "grid_return_v"):
            if k in cfg:
                try:
                    grid_return_v = float(cfg[k])
                    break
                except (ValueError, TypeError):
                    pass

    night_samples = [s for s in samples if is_night(float(s.ts), tz)]
    night_below_pct: float | None = None
    nights_below_half = 0

    if grid_return_v is not None and night_samples:
        threshold = grid_return_v + 1.0
        below_count = sum(1 for s in night_samples if float(s.batt_v) < threshold)
        night_below_pct = (below_count / len(night_samples)) * 100.0

        # Conta per ciascuna notte se >= 50% dei campioni sono sotto soglia
        nights_dict: dict[float, list[Sample]] = {}
        for s in night_samples:
            # Associa la notte al giorno di inizio (se ora < 12, appartiene alla sera precedente)
            d = day_start(float(s.ts) - 12 * 3600, tz)
            nights_dict.setdefault(d, []).append(s)

        for n_s in nights_dict.values():
            if n_s:
                cnt = sum(1 for s in n_s if float(s.batt_v) < threshold)
                if (cnt / len(n_s)) >= 0.50:
                    nights_below_half += 1

    # 5. Verifica condizioni per verdetto
    # Criterio di escursione >= 5V e tentativo di scarica (mode=B, dis_a > 0.5A, out_w > 100W)
    has_discharge_attempt = False
    has_5v_excursion = False

    # Controlla per ogni giorno locale
    days_samples: dict[float, list[Sample]] = {}
    for s in samples:
        d = day_start(float(s.ts), tz)
        days_samples.setdefault(d, []).append(s)

    for day_s in days_samples.values():
        if not day_s:
            continue
        v_diff = max(float(s.batt_v) for s in day_s) - min(float(s.batt_v) for s in day_s)
        if v_diff >= 5.0:
            has_5v_excursion = True
        for s in day_s:
            if s.mode == "B" and float(s.dis_a or 0.0) > 0.5 and float(s.out_w or 0.0) > 100.0:
                has_discharge_attempt = True

    reasons: list[str] = []
    verdict: str

    # Determina verdetto nell'ordine:
    # 1. Indeterminato:
    #    - meno di 24 ore osservate
    #    - oppure nessun giorno con escursione >= 5V e tentativo di scarica E zero salti
    if days < 1.0:
        verdict = "indeterminato"
        reasons.append(f"Meno di 24 ore osservate ({days:.2f} giorni).")
    elif not (has_5v_excursion and has_discharge_attempt) and jumps == 0:
        verdict = "indeterminato"
        reasons.append("Nessun giorno con escursione tensione >= 5 V e scarica attiva (mode B, carico > 100 W).")
    # 2. Da sostituire:
    #    - >= 5 salti/giorno
    #    - oppure ratio < 0.20 (se calcolabile da tentativo di scarica)
    #    - oppure almeno il 50% dei campioni notturni sotto soglia per >= 3 notti
    elif jumps_per_day >= 5.0 or (ratio is not None and ratio < 0.20) or nights_below_half >= 3:
        verdict = "da_sostituire"
        if jumps_per_day >= 5.0:
            reasons.append(f"Rilevati {jumps_per_day:.1f} salti bruschi di tensione al giorno (>= 4 V in <= 120 s).")
        if ratio is not None and ratio < 0.20:
            reasons.append(
                f"Energia ciclo profondo ({e_dis_max_kwh:.2f} kWh) inferiore al 20% del riferimento ({ref_kwh:.2f} kWh): ratio {ratio*100:.1f}%."
            )
        if nights_below_half >= 3:
            reasons.append(f"{nights_below_half} notti con oltre il 50% dei campioni sotto la soglia di ritorno a rete.")
    # 3. Da controllare:
    #    - 1-4 salti/giorno
    #    - oppure 0.20 <= ratio < 0.50
    elif (1.0 <= jumps_per_day < 5.0) or (ratio is not None and 0.20 <= ratio < 0.50):
        verdict = "da_controllare"
        if 1.0 <= jumps_per_day < 5.0:
            reasons.append(f"Rilevati {jumps_per_day:.1f} salti di tensione al giorno.")
        if ratio is not None and 0.20 <= ratio < 0.50:
            reasons.append(
                f"Energia ciclo profondo ({e_dis_max_kwh:.2f} kWh) tra il 20% e il 50% del riferimento sano ({ref_kwh:.2f} kWh)."
            )
    # 4. Sana:
    #    - nessun salto, ratio >= 50%, notti sopra soglia
    else:
        verdict = "sana"
        reasons.append("Nessun salto anomalo di tensione rilevato.")
        if ratio is not None:
            reasons.append(f"Ciclo profondo ({e_dis_max_kwh:.2f} kWh) pari al {ratio*100:.1f}% del riferimento sano.")
        if night_below_pct is not None:
            reasons.append(f"Tensione notturna mantenuta sopra soglia (sotto soglia solo nel {night_below_pct:.1f}% dei campioni).")

    return BatteryReport(
        e_chg_kwh=e_chg_kwh,
        e_dis_kwh=e_dis_kwh,
        e_dis_max_kwh=e_dis_max_kwh,
        ref_kwh=ref_kwh,
        ratio=ratio,
        jumps_per_day=jumps_per_day,
        night_below_pct=night_below_pct,
        verdict=verdict,
        reasons=reasons,
    )
