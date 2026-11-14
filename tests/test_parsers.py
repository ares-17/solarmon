"""Test dei parser e del CRC sul protocollo PI30.

Questi test bloccano il comportamento su risposte reali dell'inverter: se un refactoring
cambia gli indici dei campi, il test fallisce prima che il dato sbagliato finisca nel DB.
"""

import importlib.util
import json
import logging
import threading
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
    for statement in solarmon.SCHEMA:
        con.execute(statement)
    con.commit()
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
