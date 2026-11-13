"""Test dei parser e del CRC sul protocollo PI30.

Questi test bloccano il comportamento su risposte reali dell'inverter: se un refactoring
cambia gli indici dei campi, il test fallisce prima che il dato sbagliato finisca nel DB.
"""

import importlib.util
import json
import logging
import threading
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
