"""Test dei parser e del CRC sul protocollo PI30.

Questi test bloccano il comportamento su risposte reali dell'inverter: se un refactoring
cambia gli indici dei campi, il test fallisce prima che il dato sbagliato finisca nel DB.
"""

import datetime
import importlib.util
import json
import logging
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path

import fixtures
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def solarmon():
    spec = importlib.util.spec_from_file_location("solarmon", ROOT / "solarmon.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- CRC -------------------------------------------------------------------


def test_crc_known_vector(solarmon):
    """CRC-XMODEM del comando QPIGS con la correzione PI30."""
    assert solarmon.crc16(b"QPIGS") == bytes.fromhex("b7a9")


def test_crc_is_two_bytes_and_deterministic(solarmon):
    first = solarmon.crc16(b"QPIRI")
    second = solarmon.crc16(b"QPIRI")
    assert len(first) == 2
    assert first == second


# --- QPIGS -----------------------------------------------------------------


def test_parse_gs_maps_all_fields(solarmon):
    gs = solarmon.parse_gs(fixtures.QPIGS)
    assert gs == {
        "grid_v": 233.2,
        "out_v": 229.7,
        "out_va": 551.0,
        "out_w": 339.0,
        "load_pct": 11.0,
        "batt_v": 53.9,
        "chg_a": 0.0,
        "batt_pct": 100.0,
        "temp_c": 39.0,
        "pv_v": 103.4,
        "dis_a": 0.0,
        "pv_w": 383.0,
        "scc_on": 1,
        "ac_chg": 0,
    }


def test_parse_gs_types(solarmon):
    gs = solarmon.parse_gs(fixtures.QPIGS)
    assert isinstance(gs["pv_w"], float)
    assert isinstance(gs["scc_on"], int)
    assert isinstance(gs["ac_chg"], int)


# --- QPIRI -----------------------------------------------------------------


def test_parse_cfg_maps_values(solarmon):
    cfg = solarmon.parse_cfg(fixtures.QPIRI)
    assert cfg["AC in V"] == "230.0"
    assert cfg["VA nominali"] == "5000"
    assert cfg["Batteria nominale V"] == "48.0"
    assert cfg["Bulk V"] == "56.4"
    assert cfg["Float V"] == "54.0"
    assert cfg["Tipo batteria"] == "AGM"
    assert cfg["Range ingresso"] == "UPS"
    assert cfg["Priorita' uscita"] == "SBU"
    assert cfg["Priorita' carica"] == "Solo solare"


def test_parse_cfg_numeric_fields_have_no_leading_zeros(solarmon):
    cfg = solarmon.parse_cfg(fixtures.QPIRI)
    assert cfg["Max carica A"] == "20"
    assert cfg["AC in V"] == "230.0"


# --- QPIWS -----------------------------------------------------------------


def test_faults_clean(solarmon):
    assert solarmon.faults(fixtures.QPIWS_CLEAN) == []


def test_faults_reports_bit_seven(solarmon):
    faults = solarmon.faults(fixtures.QPIWS_LOW_OUTPUT)
    assert faults == ["Tensione di uscita troppo bassa (display F58?)"]


def test_faults_ignore_non_fault_bits(solarmon):
    # bit 5 = mancanza rete (avviso), non deve essere un guasto grave ma va segnalato
    ws = "0" * 5 + "1" + "0" * 26
    assert solarmon.faults(ws) == ["Mancanza rete"]


# --- mappe -----------------------------------------------------------------


def test_modes_contains_fault_and_battery(solarmon):
    assert solarmon.MODES["F"] == "FAULT"
    assert solarmon.MODES["B"] == "Batteria"


def test_notify_does_not_log_the_bot_token(solarmon, monkeypatch, caplog):
    monkeypatch.setattr(solarmon, "TG_TOKEN", "123456:SECRET")
    monkeypatch.setattr(solarmon, "TG_CHAT", "42")

    def failing_urlopen(*args, **kwargs):
        raise RuntimeError("HTTP Error 403: https://api.telegram.org/bot123456:SECRET/sendMessage")

    monkeypatch.setattr(solarmon.urllib.request, "urlopen", failing_urlopen)
    with caplog.at_level(logging.WARNING):
        solarmon.notify("prova")
    assert "SECRET" not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.fixture
def db(solarmon, tmp_path):
    solarmon.DB = str(tmp_path / "solar.db")
    con = solarmon.connect()
    solarmon.ensure_schema(con)
    con.close()
    with solarmon.RING_LOCK:
        solarmon.RING.clear()
    return solarmon


@pytest.fixture
def server(solarmon):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), solarmon.Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % httpd.server_port
    httpd.shutdown()
    httpd.server_close()


def test_api_now_is_json_and_has_security_headers(server):
    with closing(urllib.request.urlopen(server + "/api/now", timeout=5)) as response:
        assert response.status == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        data = json.load(response)
    assert "mode_name" in data
    assert "faults" in data


def test_dashboard_html_has_content_security_policy(server):
    with closing(urllib.request.urlopen(server + "/", timeout=5)) as response:
        assert response.status == 200
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_series_with_invalid_h_does_not_fail(db, server):
    with closing(urllib.request.urlopen(server + "/api/series?h=abc", timeout=5)) as response:
        assert response.status == 200
        assert set(json.load(response)) == {"ts", "pv_w", "out_w", "batt_v", "pv_v"}


def test_raw_denied_without_token_when_token_is_set(db, server, monkeypatch):
    monkeypatch.setattr(db, "RAW_TOKEN", "s3cret")
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(server + "/api/raw", timeout=5)
    assert error.value.code == 403


def test_raw_returns_data_with_token(db, server, monkeypatch):
    monkeypatch.setattr(db, "RAW_TOKEN", "s3cret")
    with closing(urllib.request.urlopen(server + "/api/raw?token=s3cret", timeout=5)) as response:
        body = json.load(response)
    assert body["count"] == 0
    assert body["source"] == "db"


def test_raw_denied_when_exposed_without_token(db, server, monkeypatch):
    monkeypatch.setattr(db, "RAW_TOKEN", "")
    monkeypatch.setattr(db, "BIND", "0.0.0.0")
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(server + "/api/raw", timeout=5)
    assert error.value.code == 403


CFG = {"Ritorno a rete sotto V": "45.0", "Cutoff batteria V": "42.0", "Ritorno a batteria sopra V": "48.0"}


def test_prepare_accepts_consistent_cutoff(solarmon):
    assert solarmon.prepare("cutoff_v", "44", CFG) == ("PSDV44.0", "Cutoff batteria V")


def test_prepare_rejects_cutoff_above_back_to_grid(solarmon):
    with pytest.raises(ValueError):
        solarmon.prepare("cutoff_v", "46", CFG)


def test_prepare_maps_output_priority(solarmon):
    assert solarmon.prepare("uscita", "sbu", CFG) == ("POP02", "Priorita' uscita")


# --- prezzo energia ---------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [
    ("0.25", 0.25), ("0,25", 0.25), (" 0.30 ", 0.30),
    ("", None), ("abc", None), ("-1", None), ("0", None), ("nan", None),
])
def test_parse_price(solarmon, raw, expected):
    assert solarmon.parse_price(raw) == expected


# --- bucket locali e suddivisione intervalli --------------------------------


def _local_ts(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute)).timestamp()


def test_band_index_uses_local_four_hour_bands(solarmon):
    d = datetime.date(2026, 11, 16)
    assert solarmon.band_index(_local_ts(d, 0)) == 0
    assert solarmon.band_index(_local_ts(d, 3, 59)) == 0
    assert solarmon.band_index(_local_ts(d, 4)) == 1
    assert solarmon.band_index(_local_ts(d, 23, 59)) == 5


def test_split_interval_splits_at_hour_boundaries(solarmon):
    d = datetime.date(2026, 11, 16)
    start, end = _local_ts(d, 3, 30), _local_ts(d, 5, 10)
    parts = solarmon.split_interval(start, end, solarmon.next_hour)
    assert len(parts) == 3
    assert parts[0] == pytest.approx((_local_ts(d, 3, 30), _local_ts(d, 4)))
    assert parts[1] == pytest.approx((_local_ts(d, 4), _local_ts(d, 5)))
    assert parts[2] == pytest.approx((_local_ts(d, 5), _local_ts(d, 5, 10)))


# --- posizione solare -------------------------------------------------------


def test_solar_site_reads_explicit_coordinates(solarmon, monkeypatch):
    monkeypatch.setattr(solarmon, "SOLAR_LAT", "41,90")
    monkeypatch.setattr(solarmon, "SOLAR_LON", "12,49")
    monkeypatch.setattr(solarmon, "SOLAR_PLACE", "")
    site = solarmon.solar_site()
    assert site == {"place": "coordinate", "lat": 41.9, "lon": 12.49}


def test_solar_site_resolves_province_capital(solarmon, monkeypatch):
    monkeypatch.setattr(solarmon, "SOLAR_LAT", "")
    monkeypatch.setattr(solarmon, "SOLAR_LON", "")
    monkeypatch.setattr(solarmon, "SOLAR_PLACE", "roma, rm")
    site = solarmon.solar_site()
    assert site["place"] == "roma, rm"
    assert 41.5 < site["lat"] < 42.3
    assert 12.0 < site["lon"] < 12.9


def test_solar_site_returns_none_when_unset(solarmon, monkeypatch):
    monkeypatch.setattr(solarmon, "SOLAR_LAT", "")
    monkeypatch.setattr(solarmon, "SOLAR_LON", "")
    monkeypatch.setattr(solarmon, "SOLAR_PLACE", "posto-inventato, ZZ")
    assert solarmon.solar_site() is None


def test_sun_endpoint_returns_local_daylight(db, server, monkeypatch):
    monkeypatch.setattr(db, "SOLAR_LAT", "41.9")
    monkeypatch.setattr(db, "SOLAR_LON", "12.5")
    monkeypatch.setattr(db, "SOLAR_PLACE", "Roma, RM")
    with closing(urllib.request.urlopen(server + "/api/sun?h=24", timeout=5)) as response:
        body = json.load(response)
    assert body["configured"] is True
    assert body["days"]
    for day in body["days"]:
        assert day["rise"] < day["set"]
        assert 8 * 3600 <= day["set"] - day["rise"] <= 16 * 3600


def test_sun_endpoint_without_position(db, server, monkeypatch):
    monkeypatch.setattr(db, "SOLAR_LAT", "")
    monkeypatch.setattr(db, "SOLAR_LON", "")
    monkeypatch.setattr(db, "SOLAR_PLACE", "")
    with closing(urllib.request.urlopen(server + "/api/sun?h=24", timeout=5)) as response:
        body = json.load(response)
    assert body == {"configured": False, "days": []}


def _add_samples(con, rows):
    """rows: (ts, pv_w, out_w, mode[, (e_pv, e_solar, e_batt, e_grid)])."""
    for row in rows:
        e = row[4] if len(row) > 4 else (None,) * 4
        con.execute("INSERT INTO samples(ts,pv_w,out_w,mode,grid_v,batt_v,chg_a,dis_a,"
                    "e_pv_wh,e_solar_wh,e_batt_wh,e_grid_wh) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(row[:4]) + (230, 52, 0, 0) + tuple(e))


def test_energy_step_uses_real_elapsed_seconds(solarmon):
    prev = (1000.0, 500.0, 1000.0, "?")  # ts, pv_w, out_w, mode
    cur = (1010.0, 500.0, 1000.0, "?")
    assert solarmon.energy_step(prev, cur, gap=60) == pytest.approx(
        (500 * 10 / 3600, 500 * 10 / 3600, 500 * 10 / 3600, 0))
    assert solarmon.energy_step(prev, (1100.0, 500, 1000, "?"), gap=60) == (0, 0, 0, 0)


def test_mix_uses_recorded_energy_not_store_interval(db, server, monkeypatch):
    """I kWh sono la somma dell'energia misurata: STORE_INTERVAL non li cambia."""
    now = int(time.time())
    con = db.connect()
    _add_samples(con, [
        (now - 120, 0, 0, "?", (0, 0, 0, 0)),
        (now - 60, 0, 0, "?", (300, 100, 150, 50)),
        (now - 10, 0, 0, "?", (300, 100, 150, 50)),
    ])
    con.commit()
    con.close()
    results = []
    for store in (60, 3600):
        monkeypatch.setattr(db, "STORE_INTERVAL", store)
        with closing(urllib.request.urlopen(server + "/api/mix?h=1", timeout=5)) as response:
            results.append(json.load(response))
    assert results[0] == results[1]
    assert results[0]["solar_kwh"] == 0.2
    assert results[0]["batt_kwh"] == 0.3
    assert results[0]["grid_kwh"] == 0.1
    assert results[0]["load_kwh"] == 0.6


@pytest.mark.parametrize("step", [10, 60])
def test_mix_legacy_rows_are_integrated_over_real_time(db, server, step):
    """Righe senza colonne energia: 1 kW per un'ora = 1 kWh, con qualunque cadenza."""
    now = int(time.time())
    con = db.connect()
    _add_samples(con, [(now - 3600 + i, 0, 1000, "?") for i in range(0, 3601, step)])
    con.commit()
    con.close()
    with closing(urllib.request.urlopen(server + "/api/mix?h=2", timeout=5)) as response:
        body = json.load(response)
    assert body["load_kwh"] == pytest.approx(1.0, abs=0.01)
    assert body["batt_kwh"] == pytest.approx(1.0, abs=0.01)
    assert body["solar_kwh"] == 0 and body["grid_kwh"] == 0


def test_mix_without_samples_returns_zeroes(db, server):
    with closing(urllib.request.urlopen(server + "/api/mix?h=24", timeout=5)) as response:
        body = json.load(response)
    assert body["load_kwh"] == 0 and body["samples"] == 0


def test_mix_ignores_data_gaps(db, server):
    now = int(time.time())
    con = db.connect()
    _add_samples(con, [(now - 3600, 0, 1000, "?"), (now - 600, 0, 1000, "?")])
    con.commit()
    con.close()
    with closing(urllib.request.urlopen(server + "/api/mix?h=2", timeout=5)) as response:
        body = json.load(response)
    assert body["load_kwh"] == 0


def test_mix_splits_load_over_real_elapsed_time(db, server, monkeypatch):
    monkeypatch.setattr(db, "STORE_INTERVAL", 1800)  # righe storiche ogni 30 min
    now = int(time.time())
    con = db.connect()
    _add_samples(con, [
        (now - 3600, 600, 400, "B"),  # FV diretto 400, batteria 0
        (now - 1800, 200, 500, "B"),  # FV diretto 200, batteria 300
        (now, 0, 500, "L"),           # bypass: tutto il carico e' rete
    ])
    con.commit()
    con.close()
    with closing(urllib.request.urlopen(server + "/api/mix?h=2", timeout=5)) as response:
        body = json.load(response)
    assert body["solar_kwh"] == 0.2
    assert body["batt_kwh"] == 0.15
    assert body["grid_kwh"] == 0.125
    assert body["load_kwh"] == 0.475
    assert body["samples"] == 3


def test_mix_parts_always_sum_to_load(db, server):
    now = int(time.time())
    con = db.connect()
    _add_samples(con, [
        (now - 30, 3335, 3335, "B"),  # FV diretto
        (now - 20, 0, 3335, "B"),     # batteria
        (now - 10, 0, 3335, "L"),     # rete
    ])
    con.commit()
    con.close()
    with closing(urllib.request.urlopen(server + "/api/mix?h=1", timeout=5)) as response:
        body = json.load(response)
    parts = body["solar_kwh"] + body["batt_kwh"] + body["grid_kwh"]
    assert parts == pytest.approx(body["load_kwh"], abs=1e-6)


def test_mix_unknown_mode_is_not_bypass(db, server, monkeypatch):
    monkeypatch.setattr(db, "STORE_INTERVAL", 3600)  # righe storiche ogni ora
    now = int(time.time())
    con = db.connect()
    _add_samples(con, [(now - 3700, 200, 500, "?"), (now - 100, 200, 500, "?")])
    con.commit()
    con.close()
    with closing(urllib.request.urlopen(server + "/api/mix?h=2", timeout=5)) as response:
        body = json.load(response)
    assert body["solar_kwh"] == 0.2
    assert body["batt_kwh"] == 0.3
    assert body["grid_kwh"] == 0


def test_daily_integrates_pv_over_real_time_and_splits_midnight(db, server):
    import datetime

    base = datetime.datetime.combine(datetime.date.today() - datetime.timedelta(days=3),
                                     datetime.time())
    midnight = base.timestamp()
    con = db.connect()
    # 1 kW costante da 30 min prima a 30 min dopo la mezzanotte, un campione al minuto
    _add_samples(con, [(int(midnight - 1800 + i), 1000, 0, "B") for i in range(0, 3601, 60)])
    con.commit()
    con.close()
    with closing(urllib.request.urlopen(server + "/api/daily", timeout=5)) as response:
        body = json.load(response)
    previous = (base - datetime.timedelta(days=1)).timestamp()
    assert body["kwh"][body["ts"].index(int(previous))] == pytest.approx(0.5, abs=0.01)
    assert body["kwh"][body["ts"].index(int(midnight))] == pytest.approx(0.5, abs=0.01)


def test_ensure_schema_migrates_legacy_database(solarmon, tmp_path):
    con = sqlite3.connect(tmp_path / "legacy.db")
    con.execute("CREATE TABLE samples(ts INTEGER PRIMARY KEY, pv_w REAL, pv_v REAL, batt_v REAL, out_w REAL,"
                " load_pct REAL, chg_a REAL, dis_a REAL, temp_c REAL, grid_v REAL, mode TEXT, ws TEXT)")
    con.commit()
    solarmon.ensure_schema(con)
    solarmon.ensure_schema(con)  # idempotente
    cols = {r[1] for r in con.execute("PRAGMA table_info(samples)")}
    assert set(solarmon.ENERGY_COLS) <= cols
    con.close()


# --- notifiche --------------------------------------------------------------


def _gs(**kw):
    base = {"pv_w": 0, "out_w": 0, "batt_v": 52.0, "batt_pct": 80, "grid_v": 0,
            "chg_a": 0, "dis_a": 0, "ac_chg": 0}
    base.update(kw)
    return base


def test_grid_on_requires_line_mode_and_ac(solarmon):
    assert solarmon.grid_on(_gs(grid_v=230), "L") is True
    assert solarmon.grid_on(_gs(grid_v=0), "L") is False
    assert solarmon.grid_on(_gs(grid_v=230), "B") is False


def test_solar_only_requires_no_grid_and_pv_covering_load(solarmon):
    ok = (0, 500.0, 500.0, 0.0, "B")
    assert solarmon.solar_only(ok, ok) is True
    assert solarmon.solar_only((0, 500.0, 540.0, 0.0, "B"),
                               (0, 500.0, 540.0, 0.0, "B")) is True
    assert solarmon.solar_only((0, 500.0, 600.0, 0.0, "B"),
                               (0, 500.0, 600.0, 0.0, "B")) is False
    assert solarmon.solar_only((0, 500.0, 560.0, 0.0, "B"),
                               (0, 500.0, 560.0, 0.0, "B")) is False
    assert solarmon.solar_only((0, 500.0, 500.0, 230.0, "L"),
                               (0, 500.0, 500.0, 230.0, "L")) is False
    assert solarmon.solar_only((0, 0.0, 0.0, 0.0, "B"),
                               (0, 0.0, 0.0, 0.0, "B")) is False


def test_count_switches_requires_three_consecutive_samples(solarmon):
    t = 1_700_000_000
    rows = [(t, 0.0, "B"), (t + 60, 230.0, "L"), (t + 120, 230.0, "L"),
            (t + 180, 230.0, "L"), (t + 240, 0.0, "B")]
    total, by_day = solarmon.count_switches(rows)
    assert total == 1
    assert sum(by_day.values()) == 1


def test_count_switches_ignores_flapping_and_gaps(solarmon):
    t = 1_700_000_000
    flapping = [(t, 0.0, "B"), (t + 60, 230.0, "L"), (t + 120, 0.0, "B"),
                (t + 180, 230.0, "L"), (t + 240, 0.0, "B")]
    assert solarmon.count_switches(flapping)[0] == 0
    gap = [(t, 0.0, "B"), (t + 60, 230.0, "L"), (t + 120, 230.0, "L"),
           (t + 4000, 230.0, "L"), (t + 4060, 230.0, "L")]
    assert solarmon.count_switches(gap, gap=300)[0] == 0


def test_observed_seconds_clips_to_window_and_ignores_gaps(solarmon):
    raw = [(95, 0, 0, 0, "B"), (105, 0, 0, 0, "B"),
           (115, 0, 0, 0, "B"), (1000, 0, 0, 0, "B")]
    assert solarmon.observed_seconds(raw, 100, 200, gap=60) == pytest.approx(15)
    assert solarmon.observed_seconds(raw, 100, 200, gap=5) == 0


def test_band_totals_split_energy_at_four_hour_boundary(solarmon, monkeypatch):
    monkeypatch.setattr(solarmon, "STORE_INTERVAL", 3600)
    d = datetime.date(2026, 11, 16)
    start, end = _local_ts(d, 3, 30), _local_ts(d, 4, 30)
    rows = [(start, 0, 1000, "B", None, None, None, None),
            (end, 0, 1000, "B", None, None, None, None)]
    bands = solarmon.band_totals(rows, start, end)
    assert bands[0][1] == pytest.approx(500)
    assert bands[1][1] == pytest.approx(500)
    assert sum(b[1] for b in bands) == pytest.approx(1000)


def test_daily_by_source_splits_at_local_midnight(solarmon, monkeypatch):
    monkeypatch.setattr(solarmon, "STORE_INTERVAL", 3600)
    d = datetime.date(2026, 11, 16)
    start = _local_ts(d, 23, 30)
    end = _local_ts(d + datetime.timedelta(days=1), 0, 30)
    rows = [(start, 0, 1000, "B", None, None, None, None),
            (end, 0, 1000, "B", None, None, None, None)]
    daily = solarmon.daily_by_source(rows, start, end)
    assert daily["batt"] == pytest.approx([0.5, 0.5], abs=0.01)


def test_solar_only_profile_attributes_minutes_to_local_hours(solarmon, monkeypatch):
    monkeypatch.setattr(solarmon, "STORE_INTERVAL", 3600)
    d = datetime.date(2026, 11, 16)
    start = _local_ts(d, 10, 0)
    end = _local_ts(d, 10, 30)
    raw = [(start, 800, 500, 0, "B"), (end, 800, 500, 0, "B")]
    minutes, hours, pct = solarmon.solar_only_profile(raw, start, end, days=0.5)
    assert minutes[10] == pytest.approx(60)
    assert hours == pytest.approx(0.5)
    assert pct == pytest.approx(100)


def test_grid_switch_text_to_grid(solarmon):
    assert solarmon.grid_switch_text(True, _gs(batt_v=46.2, batt_pct=18), "L") == \
        "Passato alla rete: batteria al 18% (46,2 V)."
    assert solarmon.grid_switch_text(True, _gs(batt_v=None, batt_pct=18), "L") == \
        "Passato alla rete: batteria al 18%."
    assert solarmon.grid_switch_text(True, _gs(batt_v=None, batt_pct=None), "L") == \
        "Passato alla rete."


def test_grid_switch_text_return_only_for_battery_mode(solarmon):
    assert solarmon.grid_switch_text(False, _gs(batt_v=52.1, batt_pct=63), "B") == \
        "Tornato alla batteria: 52,1 V (63%)."
    assert solarmon.grid_switch_text(False, _gs(), "S") is None


def test_alarm_groups_splits_severe_and_warnings(solarmon):
    ws = "0" * 32
    ws = ws[:16] + "1" + ws[17:]  # bit 16: sovraccarico (grave)
    ws = ws[:5] + "1" + ws[6:]    # bit 5: mancanza rete (avviso)
    severe, warnings = solarmon.alarm_groups(ws, "B")
    assert severe == ["Sovraccarico"]
    assert warnings == ["Mancanza rete"]


def test_alarm_groups_adds_mode_fault_without_bit_one(solarmon):
    severe, warnings = solarmon.alarm_groups("0" * 32, "F")
    assert severe == ["Modalità FAULT"]
    assert warnings == []
    severe, _ = solarmon.alarm_groups("0" + "1" + "0" * 30, "F")
    assert severe == ["Inverter fault"]


def test_alarm_text_groups_and_reports_cleared(solarmon):
    assert solarmon.alarm_text(
        frozenset({"Mancanza rete"}), (["Sovraccarico"], ["Mancanza rete"])) == \
        "Allarmi inverter\nGuasti: Sovraccarico\nAvvisi: Mancanza rete"
    assert solarmon.alarm_text(
        frozenset({"Mancanza rete", "Sovraccarico"}), (["Sovraccarico"], [])) == \
        "Allarmi inverter\nGuasti: Sovraccarico\nRientrati: Mancanza rete."
    assert solarmon.alarm_text(frozenset({"Sovraccarico"}), ([], [])) == \
        "Allarmi rientrati: Sovraccarico."
    assert solarmon.alarm_text(frozenset({"Sovraccarico"}), (["Sovraccarico"], [])) is None
    assert solarmon.alarm_text(None, ([], [])) is None


def test_alert_does_not_repeat_while_active(solarmon, monkeypatch):
    sent = []
    monkeypatch.setattr(solarmon, "notify", sent.append)
    solarmon.active.clear()
    solarmon.alert("x", True, "on", "off")
    solarmon.alert("x", True, "on", "off")
    solarmon.alert("x", False, "", "off")
    solarmon.alert("x", False, "", "off")
    assert sent == ["on", "off"]


def _notifier(solarmon):
    sent = []
    return solarmon.Notifier(sent.append), sent


def test_notifier_confirms_grid_transition_after_three_readings(solarmon):
    n, sent = _notifier(solarmon)
    batt = _gs(pv_w=900, out_w=500)
    grid = _gs(grid_v=230, batt_v=46.2, batt_pct=18)
    n.update(batt, "B", "0" * 32)
    assert sent == []
    n.update(grid, "L", "0" * 32)
    n.update(grid, "L", "0" * 32)
    assert sent == []
    n.update(grid, "L", "0" * 32)
    assert sent == ["Passato alla rete: batteria al 18% (46,2 V)."]
    n.update(grid, "L", "0" * 32)
    assert sent == ["Passato alla rete: batteria al 18% (46,2 V)."]


def test_notifier_ignores_flapping(solarmon):
    n, sent = _notifier(solarmon)
    batt, grid = _gs(), _gs(grid_v=230)
    n.update(batt, "B", "0" * 32)
    for _ in range(3):
        n.update(grid, "L", "0" * 32)
        n.update(batt, "B", "0" * 32)
    assert sent == []


def test_notifier_sends_grouped_alarms_without_repeats(solarmon):
    n, sent = _notifier(solarmon)
    clean = "0" * 32
    overload = clean[:16] + "1" + clean[17:]
    n.update(_gs(), "B", clean)
    n.update(_gs(), "B", overload)
    n.update(_gs(), "B", overload)
    assert sent == ["Allarmi inverter\nGuasti: Sovraccarico"]
    n.update(_gs(), "B", clean)
    assert sent == ["Allarmi inverter\nGuasti: Sovraccarico",
                    "Allarmi rientrati: Sovraccarico."]


def test_notifier_sends_alarms_active_at_startup(solarmon):
    n, sent = _notifier(solarmon)
    overload = "0" * 16 + "1" + "0" * 15
    n.update(_gs(), "B", overload)
    assert sent == ["Allarmi inverter\nGuasti: Sovraccarico"]


def test_legacy_alerts_are_removed(solarmon):
    import inspect
    src = inspect.getsource(solarmon)
    for needle in ("Batteria bassa", "BATT_LOW", "ALERT_REPEAT_MIN",
                   "solarmon avviato", "Configurazione inverter cambiata",
                   "Modalita':"):
        assert needle not in src


