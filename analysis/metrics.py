"""Flussi di energia, profili locali e cambi di modo.

Le regole replicano quelle di `solarmon.py` senza importarlo: ripartizione del
carico, trapezio sui secondi reali, buchi che non producono energia e cambi verso
la rete confermati da tre campioni consecutivi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from .db import Sample
from .timeutil import TZ, day_start, hour_of, next_day, to_local

# Soglia di tensione oltre la quale con modo "L" il carico è sulla rete (solarmon).
MIN_GRID_V = 90.0
# Campioni consecutivi che confermano un cambio di modo.
CONFIRM_SAMPLES = 3
SECONDS_PER_DAY = 86400
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ZEROS = (0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Totals:
    """Totali del periodo osservato: kWh per fonte e autosufficienza percentuale."""

    days: float
    pv_kwh: float
    solar_kwh: float
    batt_kwh: float
    grid_kwh: float
    load_kwh: float
    self_sufficiency: float | None


def power_split(s: Sample) -> tuple[float, float, float]:
    """Ripartisce il carico in (FV diretto, batteria, rete) in W."""
    pv, out = max(0.0, float(s.pv_w or 0.0)), max(0.0, float(s.out_w or 0.0))
    if s.mode == "L":  # bypass: tutto il carico viene dalla rete
        return 0.0, 0.0, out
    return min(pv, out), max(0.0, out - pv), 0.0


def energy_step(a: Sample, b: Sample, gap: int) -> tuple[float, float, float, float]:
    """Energia (Wh) tra due campioni: FV prodotto e ripartizione del carico.

    Integra con la regola del trapezio sui secondi realmente trascorsi. Oltre
    `gap` il buco è un dato mancante e non produce energia.
    """
    dt = float(b.ts) - float(a.ts)
    if not 0 < dt <= gap:
        return _ZEROS
    pv0, pv1 = max(0.0, float(a.pv_w or 0.0)), max(0.0, float(b.pv_w or 0.0))
    s0, b0, g0 = power_split(a)
    s1, b1, g1 = power_split(b)
    k = dt / 3600.0
    return (pv0 + pv1) / 2 * k, (s0 + s1) / 2 * k, (b0 + b1) / 2 * k, (g0 + g1) / 2 * k


def _interval_energy(a: Sample, b: Sample, gap: int) -> tuple[float, float, float, float]:
    """Wh dell'intervallo a→b: colonne `e_*` complete, altrimenti trapezio.

    Le quattro colonne salvate sono per intervallo: valgono solo se presenti
    tutte e quattro (0.0 è energia valida, None no). La regola del buco vale in
    ogni caso, così giorni osservati ed energia restano coerenti.
    """
    dt = float(b.ts) - float(a.ts)
    if not 0 < dt <= gap:
        return _ZEROS
    if None not in (b.e_pv_wh, b.e_solar_wh, b.e_batt_wh, b.e_grid_wh):
        return (
            float(b.e_pv_wh),
            float(b.e_solar_wh),
            float(b.e_batt_wh),
            float(b.e_grid_wh),
        )
    return energy_step(a, b, gap)


def _seconds(a: Sample, b: Sample, gap: int) -> float:
    """Secondi validi tra due campioni: zero se il buco supera `gap`."""
    dt = float(b.ts) - float(a.ts)
    return dt if 0 < dt <= gap else 0.0


def observed_seconds(samples: list[Sample], gap: int) -> float:
    """Secondi realmente coperti dai campioni, esclusi i buchi oltre `gap`."""
    return sum(_seconds(a, b, gap) for a, b in zip(samples, samples[1:]))


def totals(samples: list[Sample], gap: int) -> Totals:
    """Totali del periodo: giorni osservati, kWh per fonte e autosufficienza."""
    sums = [0.0, 0.0, 0.0, 0.0]
    for a, b in zip(samples, samples[1:]):
        for i, value in enumerate(_interval_energy(a, b, gap)):
            sums[i] += value
    pv, solar, batt, grid = (value / 1000.0 for value in sums)
    load = solar + batt + grid
    self_sufficiency = (solar + batt) / load * 100.0 if load > 0 else None
    return Totals(
        days=observed_seconds(samples, gap) / SECONDS_PER_DAY,
        pv_kwh=pv,
        solar_kwh=solar,
        batt_kwh=batt,
        grid_kwh=grid,
        load_kwh=load,
        self_sufficiency=self_sufficiency,
    )


def split_interval(start: float, end: float, boundary: Callable[[float], float]) -> list[tuple[float, float]]:
    """Spezza `[start, end]` nei confini dati da `boundary`, senza segmenti vuoti.

    Se `boundary` non avanza (valore minore o uguale all'inizio del segmento)
    l'intervallo è trattato come non spezzabile: si chiude con `end` e si esce,
    così un confine mal definito non manda in loop infinito.
    """
    if end <= start:
        return []
    segments: list[tuple[float, float]] = []
    a = float(start)
    end = float(end)
    while a < end:
        b = float(boundary(a))
        if b <= a:
            segments.append((a, end))
            break
        b = min(b, end)
        segments.append((a, b))
        a = b
    return segments


def _naive_epoch(naive_utc: datetime) -> float:
    return (naive_utc.replace(tzinfo=timezone.utc) - _EPOCH).total_seconds()


def _local_epoch(target: datetime, tz: TZ, ref_ts: float) -> float:
    """Epoch dell'ora locale `target`, con l'offset corretto intorno a `ref_ts`."""
    guess = _naive_epoch(target - timedelta(seconds=tz.offset(ref_ts)))
    return _naive_epoch(target - timedelta(seconds=tz.offset(guess)))


def _next_hour(ts: float, tz: TZ) -> float:
    """Epoch dell'inizio dell'ora locale successiva, sempre maggiore di `ts`."""
    local = to_local(ts, tz)
    target = local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    candidate = _local_epoch(target, tz, ts)
    if candidate <= ts:  # ora locale inesistente o ambigua (cambio d'ora)
        remainder = (ts + tz.offset(ts)) % 3600
        candidate = ts + (3600 - remainder if remainder else 3600)
    return candidate


def _bucket_energy(
    samples: list[Sample],
    gap: int,
    boundary: Callable[[float], float],
) -> dict[float, list[float]]:
    """Wh per bucket (chiave = inizio segmento) di (solar, batt, grid)."""
    buckets: dict[float, list[float]] = {}
    for a, b in zip(samples, samples[1:]):
        energy = _interval_energy(a, b, gap)
        if not any(energy):
            continue
        dt = float(b.ts) - float(a.ts)
        for seg_start, seg_end in split_interval(float(a.ts), float(b.ts), boundary):
            share = (seg_end - seg_start) / dt
            bucket = buckets.setdefault(seg_start, [0.0, 0.0, 0.0])
            bucket[0] += energy[1] * share
            bucket[1] += energy[2] * share
            bucket[2] += energy[3] * share
    return buckets


def daily_by_source(samples: list[Sample], tz: TZ, gap: int) -> dict:
    """kWh per giorno locale e per fonte: liste allineate `ts, solar, batt, grid`."""
    buckets: dict[float, list[float]] = {}
    for seg_start, energy in _bucket_energy(samples, gap, lambda t: next_day(t, tz)).items():
        bucket = buckets.setdefault(day_start(seg_start, tz), [0.0, 0.0, 0.0])
        for i in range(3):
            bucket[i] += energy[i]
    days = sorted(buckets)
    return {
        "ts": [int(day) for day in days],
        "solar": [buckets[day][0] / 1000.0 for day in days],
        "batt": [buckets[day][1] / 1000.0 for day in days],
        "grid": [buckets[day][2] / 1000.0 for day in days],
    }


def hourly_profile(samples: list[Sample], tz: TZ, gap: int) -> list[dict]:
    """Profilo orario medio (kWh/giorno) su 24 ore locali, sempre 24 righe."""
    buckets = _bucket_energy(samples, gap, lambda t: _next_hour(t, tz))
    per_hour = [[0.0, 0.0, 0.0] for _ in range(24)]
    for seg_start, energy in buckets.items():
        bucket = per_hour[hour_of(seg_start, tz)]
        for i in range(3):
            bucket[i] += energy[i]
    days = observed_seconds(samples, gap) / SECONDS_PER_DAY
    divisor = days * 1000.0 if days > 0 else 0.0

    profile = []
    for hour, (solar, batt, grid) in enumerate(per_hour):
        values = [v / divisor if divisor else 0.0 for v in (solar, batt, grid)]
        profile.append({
            "hour": hour,
            "solar_kwh": values[0],
            "batt_kwh": values[1],
            "grid_kwh": values[2],
            "load_kwh": sum(values),
        })
    return profile


def voltage_series(samples: list[Sample], tz: TZ, max_points: int = 720) -> list[tuple[float, float]]:
    """Serie (ts, batt_v) ridotta a un punto ogni `ceil(n / max_points)` campioni.

    `tz` resta in firma per uniformità con le altre metriche: i timestamp sono
    epoch, la conversione in ora locale la fa il renderer.
    """
    if not samples or max_points <= 0:
        return []
    step = max(1, -(-len(samples) // max_points))
    points = [(float(s.ts), float(s.batt_v)) for s in samples[::step]]
    last = (float(samples[-1].ts), float(samples[-1].batt_v))
    if points[-1] != last:
        points.append(last)
    return points


def _is_on_grid(s: Sample) -> bool:
    """Vero se il carico è sulla rete: modo "L" e tensione di rete sopra soglia."""
    return s.mode == "L" and float(s.grid_v or 0.0) > MIN_GRID_V


def switch_stats(samples: list[Sample], gap: int) -> dict:
    """Cambi verso la rete confermati da `CONFIRM_SAMPLES` campioni consecutivi.

    Un buco oltre `gap` azzera la conferma e riparte dallo stato del campione
    corrente. `per_day` usa i giorni UTC (la firma non ha il fuso orario).
    """
    total = 0
    per_day: dict[int, int] = {}
    if not samples:
        return {"total": total, "per_day": per_day}
    prev_ts = samples[0].ts
    confirmed = _is_on_grid(samples[0])
    candidate: bool | None = None
    count = 0
    for s in samples[1:]:
        state = _is_on_grid(s)
        dt, prev_ts = s.ts - prev_ts, s.ts
        if dt > gap:
            confirmed, candidate, count = state, None, 0
            continue
        if state == confirmed:
            candidate, count = None, 0
            continue
        count = count + 1 if state == candidate else 1
        candidate = state
        if count >= CONFIRM_SAMPLES:
            if state:  # solo i cambi verso la rete
                total += 1
                day = int(s.ts) - int(s.ts) % SECONDS_PER_DAY
                per_day[day] = per_day.get(day, 0) + 1
            confirmed, candidate, count = state, None, 0
    return {"total": total, "per_day": per_day}
