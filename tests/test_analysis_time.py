from datetime import datetime, timezone

from analysis.timeutil import day_start, get_tz, is_night, month_key, to_local


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
