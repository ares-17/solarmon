import sys
from datetime import datetime, timezone

from analysis.timeutil import day_start, get_tz, hour_of, is_night, month_key, next_day, to_local


def utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


def test_rome_dst_boundaries():
    tz = get_tz("Europe/Rome")
    assert tz.offset(utc(2026, 3, 29, 0, 59)) == 3600
    assert tz.offset(utc(2026, 3, 29, 1, 0)) == 7200
    assert tz.offset(utc(2026, 10, 25, 0, 59)) == 7200
    assert tz.offset(utc(2026, 10, 25, 1, 0)) == 3600


def test_night_month_and_local_midnight():
    tz = get_tz("Europe/Rome")
    assert is_night(utc(2026, 11, 18, 22, 0), tz)
    assert is_night(utc(2026, 11, 18, 5, 0), tz)
    assert not is_night(utc(2026, 11, 18, 5, 1), tz)
    assert not is_night(utc(2026, 11, 18, 12, 0), tz)
    assert month_key(utc(2026, 11, 18, 12, 0), tz) == (2026, 11)
    assert to_local(day_start(utc(2026, 11, 18, 12, 0), tz), tz).strftime("%H:%M") == "00:00"


def test_next_day_covers_whole_calendar_day():
    """I giorni di cambio ora durano 23 o 25 ore: il confine è la mezzanotte locale."""
    tz = get_tz("Europe/Rome")
    spring = utc(2026, 3, 29, 12, 0)
    autumn = utc(2026, 10, 25, 12, 0)
    assert next_day(spring, tz) - day_start(spring, tz) == 23 * 3600
    assert next_day(autumn, tz) - day_start(autumn, tz) == 25 * 3600
    # In CET la mezzanotte del 19 novembre è le 23:00 UTC del 18.
    assert next_day(utc(2026, 11, 18, 12, 0), tz) == utc(2026, 11, 18, 23, 0)


def test_hour_of_is_local():
    tz = get_tz("Europe/Rome")
    assert hour_of(utc(2026, 11, 18, 11, 30), tz) == 12
    assert hour_of(utc(2026, 7, 1, 22, 30), tz) == 0


def test_rome_does_not_need_zoneinfo(monkeypatch):
    """Europe/Rome usa la regola CET/CEST: deve funzionare anche senza tzdata."""

    def boom(name):
        raise AssertionError(f"Europe/Rome non deve passare da zoneinfo ({name})")

    monkeypatch.setattr("analysis.timeutil._zoneinfo_offset", boom)
    # Qualsiasi import di zoneinfo fallirebbe: il percorso di Europe/Rome non lo tocca.
    monkeypatch.setitem(sys.modules, "zoneinfo", None)
    tz = get_tz("Europe/Rome")
    assert tz.offset(0) == 3600
    assert tz.offset(utc(2026, 7, 1)) == 7200
