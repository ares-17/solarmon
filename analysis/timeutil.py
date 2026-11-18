"""Conversioni di fuso orario indipendenti dal tzdata della macchina.

`Europe/Rome` non usa `zoneinfo`: l'ora legale è calcolata con la regola europea
(ultima domenica di marzo e di ottobre alle 01:00 UTC), così un container senza
tzdata produce comunque gli stessi orari. Gli altri nomi passano da `zoneinfo`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from . import DEFAULT_TZ, ReportError

# Istante di riferimento: naive UTC, così le sottrazioni non dipendono dal fuso di sistema.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class TZ:
    """Fuso orario ridotto all'essenziale: un nome e l'offset per istante."""

    def __init__(self, name: str, offset_fn: Callable[[float], int]) -> None:
        self.name = name
        self._offset_fn = offset_fn

    def offset(self, ts: float) -> int:
        """Secondi a est di UTC validi nell'istante `ts` (epoch)."""
        return int(self._offset_fn(ts))

    def __repr__(self) -> str:
        return f"TZ({self.name!r})"


def _last_sunday_0100(year: int, month: int) -> float:
    """Epoch UTC delle 01:00 dell'ultima domenica del mese indicato."""
    first_of_next = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=timezone.utc)
    last = first_of_next - timedelta(days=1)
    sunday = last - timedelta(days=(last.weekday() + 1) % 7)
    return (sunday + timedelta(hours=1) - _EPOCH).total_seconds()


def _rome_offset(ts: float) -> int:
    """Offset CET (+1h) o CEST (+2h) secondo la regola europea."""
    year = datetime.fromtimestamp(ts, timezone.utc).year
    if _last_sunday_0100(year, 3) <= ts < _last_sunday_0100(year, 10):
        return 7200
    return 3600


def _zoneinfo_offset(name: str) -> Callable[[float], int]:
    """Offset delegato a `zoneinfo`, con errore leggibile se manca il fuso."""
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError as exc:  # pragma: no cover - Python 3.9+ ha sempre zoneinfo
        raise ReportError(f"Fuso '{name}' non disponibile: usa --tz {DEFAULT_TZ}") from exc

    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ReportError(f"Fuso orario sconosciuto: '{name}'. Usa --tz {DEFAULT_TZ}") from exc

    def offset(ts: float) -> int:
        delta = datetime.fromtimestamp(ts, zone).utcoffset() or timedelta(0)
        return int(delta.total_seconds())

    return offset


def get_tz(name: str = DEFAULT_TZ) -> TZ:
    """Restituisce il fuso richiesto (`Europe/Rome` calcolato, gli altri da zoneinfo)."""
    if name == DEFAULT_TZ:
        return TZ(DEFAULT_TZ, _rome_offset)
    return TZ(name, _zoneinfo_offset(name))


def to_local(ts: float, tz: TZ) -> datetime:
    """Datetime naive nell'ora locale del fuso (UTC + offset)."""
    return (datetime.fromtimestamp(ts, timezone.utc) + timedelta(seconds=tz.offset(ts))).replace(tzinfo=None)


def _epoch(naive_utc: datetime) -> float:
    return (naive_utc.replace(tzinfo=timezone.utc) - _EPOCH).total_seconds()


def _midnight_epoch(local_midnight: datetime, tz: TZ, ref_ts: float) -> float:
    """Epoch della mezzanotte locale, correggendo l'offset nei giorni di cambio ora."""
    guess = _epoch(local_midnight - timedelta(seconds=tz.offset(ref_ts)))
    return _epoch(local_midnight - timedelta(seconds=tz.offset(guess)))


def day_start(ts: float, tz: TZ) -> float:
    """Epoch della mezzanotte locale del giorno che contiene `ts`."""
    midnight = to_local(ts, tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return _midnight_epoch(midnight, tz, ts)


def next_day(ts: float, tz: TZ) -> float:
    """Epoch della mezzanotte locale del giorno successivo."""
    start = day_start(ts, tz)
    midnight = to_local(start, tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return _midnight_epoch(midnight + timedelta(days=1), tz, start)


def hour_of(ts: float, tz: TZ) -> int:
    """Ora locale (0-23) dell'istante indicato."""
    return to_local(ts, tz).hour


def month_key(ts: float, tz: TZ) -> tuple[int, int]:
    """Chiave (anno, mese) del mese locale che contiene `ts`."""
    local = to_local(ts, tz)
    return (local.year, local.month)


def is_night(ts: float, tz: TZ) -> bool:
    """Vero dalle 22:00 alle 06:00 locali: le 06:00:00 sono notte, le 06:01 no."""
    local = to_local(ts, tz)
    minutes = local.hour * 60 + local.minute
    return minutes >= 22 * 60 or minutes <= 6 * 60
