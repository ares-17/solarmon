"""Modello fotovoltaico: produzione osservata, cielo chiaro e stima potenziale.

Implementa la geometria solare semplificata, il modello a cielo chiaro di Haurwitz,
la calibrazione della potenza nominale efficace (kWp_eff) sul 95° percentile
dell'insolazione diurna e il calcolo dell'energia strozzata (curtailment).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from .db import Sample
from .metrics import energy_step
from .timeutil import TZ


@dataclass(frozen=True)
class PvReport:
    """Riepilogo della produzione fotovoltaica osservata e stimata."""

    observed_kwh: float
    peak_w: float
    peak_ts: int | None
    kwp_eff: float | None
    available_kwh: float | None
    curtailed_kwh: float | None
    note: str


def clear_sky_wm2(lat: float, lon: float, ts: float) -> float:
    """Calcola la radiazione globale orizzontale a cielo chiaro (GHI, W/m²) con Haurwitz.

    lat, lon in gradi decimali (positivo nord / est). ts è epoch UTC.
    """
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    # Giorno dell'anno (1..366) e frazione del giorno in ore UTC
    day_of_year = dt.timetuple().tm_yday
    hour_utc = dt.hour + dt.minute / 60.0 + dt.second / 3600.0

    # Angolo frazionario dell'anno in radianti
    gamma = 2.0 * math.pi * (day_of_year - 1) / 365.0

    # Declinazione solare in radianti (formula di Spencer / NOAA)
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )

    # Equazione del tempo (in minuti)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )

    # Ora solare vera (True Solar Time) in minuti
    # lon positivo a est -> 4 minuti per grado
    time_offset = eqtime + 4.0 * lon
    tst = hour_utc * 60.0 + time_offset
    solar_noon_offset = (tst / 4.0) - 180.0  # gradi
    hour_angle = math.radians(solar_noon_offset)

    lat_rad = math.radians(lat)

    # Cosenzo dell'angolo zenitale solare (cos_z = sin(lat)*sin(decl) + cos(lat)*cos(decl)*cos(ha))
    cos_z = math.sin(lat_rad) * math.sin(decl) + math.cos(lat_rad) * math.cos(decl) * math.cos(hour_angle)

    if cos_z <= 0.0:
        return 0.0

    # Modello di Haurwitz (1945): GHI = 1098 * cos(z) * exp(-0.057 / cos(z))
    # Valido per cos_z > 0
    ghi = 1098.0 * cos_z * math.exp(-0.057 / cos_z)
    return max(0.0, ghi)


def _percentile(values: list[float], p: float) -> float:
    """Calcola il percentile p (0..100) da una lista non vuota di float."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    d0 = s[int(f)] * (c - k)
    d1 = s[int(c)] * (k - f)
    return d0 + d1


def analyze_pv(
    samples: list[Sample],
    tz: TZ,
    *,
    lat: float | None = None,
    lon: float | None = None,
    kwp: float | None = None,
    eta: float = 0.85,
    inverter_max_w: float = 4000.0,
    gap: int = 300,
) -> PvReport:
    """Analizza la produzione osservata e stima il potenziale fotovoltaico."""
    if not samples:
        return PvReport(
            observed_kwh=0.0,
            peak_w=0.0,
            peak_ts=None,
            kwp_eff=None,
            available_kwh=None,
            curtailed_kwh=None,
            note="Nessun dato disponibile.",
        )

    # 1. Produzione osservata e picco
    peak_w = 0.0
    peak_ts: int | None = None
    for s in samples:
        w = max(0.0, float(s.pv_w or 0.0))
        if w > peak_w:
            peak_w = w
            peak_ts = int(s.ts)

    # Integrazione osservato
    obs_wh = 0.0
    for a, b in zip(samples, samples[1:]):
        dt = float(b.ts) - float(a.ts)
        if 0 < dt <= gap:
            if b.e_pv_wh is not None:
                obs_wh += float(b.e_pv_wh)
            else:
                pv_step, _, _, _ = energy_step(a, b, gap)
                obs_wh += pv_step
    observed_kwh = obs_wh / 1000.0

    # 2. Se le coordinate mancano, disabilita il modello a cielo chiaro
    if lat is None or lon is None:
        return PvReport(
            observed_kwh=observed_kwh,
            peak_w=peak_w,
            peak_ts=peak_ts,
            kwp_eff=None,
            available_kwh=None,
            curtailed_kwh=None,
            note="Potenziale non calcolabile: mancano le coordinate geografiche.",
        )

    # 3. Calcolo kwp_eff
    if kwp is not None and kwp > 0:
        kwp_eff = float(kwp)
    else:
        # Calibra su campioni diurni con GHI > 100 e pv_w > 0
        ratios: list[float] = []
        for s in samples:
            w = max(0.0, float(s.pv_w or 0.0))
            if w > 0:
                ghi = clear_sky_wm2(lat, lon, float(s.ts))
                if ghi > 100.0:
                    # w = kWp * (ghi / 1000) * eta * 1000 = kWp * ghi * eta
                    # kWp = w / (ghi * eta)
                    ratios.append(w / (ghi * eta))

        if ratios:
            kwp_eff = _percentile(ratios, 95.0)
        else:
            kwp_eff = None

    if kwp_eff is None:
        return PvReport(
            observed_kwh=observed_kwh,
            peak_w=peak_w,
            peak_ts=peak_ts,
            kwp_eff=None,
            available_kwh=None,
            curtailed_kwh=None,
            note="Campioni diurni insufficienti per calibrare la taglia efficace.",
        )

    # 4. Integrazione produzione disponibile e strozzata
    avail_wh = 0.0
    for a, b in zip(samples, samples[1:]):
        dt = float(b.ts) - float(a.ts)
        if 0 < dt <= gap:
            ghi_a = clear_sky_wm2(lat, lon, float(a.ts))
            ghi_b = clear_sky_wm2(lat, lon, float(b.ts))
            pot_a = min(kwp_eff * (ghi_a / 1000.0) * eta * 1000.0, inverter_max_w)
            pot_b = min(kwp_eff * (ghi_b / 1000.0) * eta * 1000.0, inverter_max_w)
            step_avail_wh = (pot_a + pot_b) / 2.0 * (dt / 3600.0)
            avail_wh += step_avail_wh

    available_kwh = avail_wh / 1000.0
    curtailed_kwh = max(0.0, available_kwh - observed_kwh)

    note = (
        f"Taglia efficace stimata: {kwp_eff:.2f} kWp (95° percentile a cielo chiaro, rendimento {int(eta*100)}%)."
        if kwp is None
        else f"Taglia nominale fornita: {kwp_eff:.2f} kWp."
    )

    return PvReport(
        observed_kwh=observed_kwh,
        peak_w=peak_w,
        peak_ts=peak_ts,
        kwp_eff=kwp_eff,
        available_kwh=available_kwh,
        curtailed_kwh=curtailed_kwh,
        note=note,
    )
