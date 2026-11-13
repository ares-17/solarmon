#!/usr/bin/env python3
"""solarmon: inverter PI30 (hidraw) -> SQLite + dashboard web + alert Telegram + MQTT opzionale.
Solo libreria standard (paho-mqtt solo se MQTT_HOST e' impostato). Solo letture: nessun comando di scrittura."""
import json, logging, os, select, sqlite3, sys, threading, time, urllib.parse, urllib.request
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

E = os.environ.get
DEV, DB = E("INVERTER_DEV", "/dev/inverter"), E("DB_PATH", "/var/lib/solarmon/solar.db")
HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
PORT, INTERVAL = int(E("PORT", "8000")), int(E("INTERVAL", "60"))
BIND_ADDR = E("BIND_ADDR", "127.0.0.1")
TG_TOKEN, TG_CHAT, MQTT_HOST = E("TG_TOKEN", ""), E("TG_CHAT", ""), E("MQTT_HOST", "")
BATT_LOW, REPEAT = float(E("BATT_LOW_V", "47")), int(E("ALERT_REPEAT_MIN", "60")) * 60
log = logging.getLogger("solarmon")

MODES = {"P": "Accensione", "S": "Standby", "L": "Rete", "B": "Batteria", "F": "FAULT", "H": "Risparmio"}
# QPIWS, indice del bit -> (descrizione, grave?). Mappa da specifica Voltronic: verificare con un allarme reale.
WS = {1: ("Inverter fault", 1), 2: ("Bus over", 1), 3: ("Bus under", 1), 4: ("Bus soft fail", 1),
      5: ("Mancanza rete", 0), 6: ("Corto circuito PV", 0), 7: ("Tensione di uscita troppo bassa (display F58?)", 1),
      8: ("Tensione di uscita troppo alta", 1), 9: ("Sovratemperatura", 1), 10: ("Ventola bloccata", 1),
      11: ("Tensione batteria troppo alta", 1), 12: ("Batteria scarica (allarme)", 0), 14: ("Batteria sotto soglia, spegnimento", 0),
      16: ("Sovraccarico", 1), 17: ("Errore EEPROM", 1), 18: ("Sovracorrente inverter", 1), 19: ("Inverter soft fail", 1),
      20: ("Self test fallito", 1), 21: ("Tensione DC in uscita eccessiva", 1), 22: ("Batteria scollegata", 1),
      23: ("Sensore di corrente guasto", 1), 24: ("Corto circuito batteria", 1), 25: ("Limitazione potenza", 0),
      26: ("Tensione PV alta", 0), 27: ("Sovraccarico MPPT (fault)", 1), 28: ("Sovraccarico MPPT", 0),
      29: ("Batteria troppo scarica per caricare", 0)}
CFG_LABELS = ["AC in V", "AC in A", "Uscita V", "Frequenza Hz", "Uscita A", "VA nominali", "W nominali", "Batteria nominale V",
              "Ritorno a rete sotto V", "Cutoff batteria V", "Bulk V", "Float V", "Tipo batteria", "Max carica AC A",
              "Max carica A", "Range ingresso", "Priorita' uscita", "Priorita' carica"]
MAPS = {12: ["AGM", "Flooded", "User"], 15: ["Appliance", "UPS"], 16: ["Utility first", "Solar first", "SBU"],
        17: ["Utility first", "Solar first", "Solar+Utility", "Solo solare"]}


def crc16(data):  # CRC-XMODEM con la correzione PI30 (0x28, 0x0D, 0x0A -> +1)
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    fix = lambda x: x + 1 if x in (0x28, 0x0D, 0x0A) else x
    return bytes([fix(crc >> 8), fix(crc & 0xFF)])


class Inverter:
    def __init__(self):
        self.fd = None

    def close(self):
        if self.fd is not None:
            try: os.close(self.fd)
            except OSError: pass
            self.fd = None

    def query(self, cmd, tries=3):
        raw = cmd.encode(); pkt = raw + crc16(raw) + b"\r"; last = None
        for _ in range(tries):
            try:
                if self.fd is None: self.fd = os.open(DEV, os.O_RDWR | os.O_NONBLOCK)
                while select.select([self.fd], [], [], 0)[0]: os.read(self.fd, 256)  # svuota residui
                for i in range(0, len(pkt), 8): os.write(self.fd, pkt[i:i + 8])
                buf, end = b"", time.time() + 5
                while time.time() < end and b"\r" not in buf:
                    if select.select([self.fd], [], [], 0.5)[0]: buf += os.read(self.fd, 256)
                if b"\r" not in buf: raise TimeoutError("timeout")
                buf = buf.split(b"\r")[0].lstrip(b"\x00")
                if not buf.startswith(b"(") or crc16(buf[:-2]) != buf[-2:]: raise ValueError("risposta non valida")
                text = buf[1:-2].decode("ascii", "ignore")
                if text == "NAK": raise ValueError("NAK")
                return text
            except (OSError, ValueError, TimeoutError) as e:
                last = e; self.close(); time.sleep(1)
        raise RuntimeError("%s: %s" % (cmd, last))


def parse_gs(t):
    f = t.split(); n = lambda i: float(f[i]); s = f[16]
    return dict(grid_v=n(0), out_v=n(2), out_va=n(4), out_w=n(5), load_pct=n(6), batt_v=n(8), chg_a=n(9),
                batt_pct=n(10), temp_c=n(11), pv_v=n(13), dis_a=n(15), pv_w=n(19), scc_on=int(s[6]), ac_chg=int(s[7]))


def parse_cfg(t):
    f, out = t.split(), {}
    for i, label in enumerate(CFG_LABELS):
        v = f[i]
        if i in MAPS:
            try: v = MAPS[i][int(v)]
            except (ValueError, IndexError): pass
        elif v.isdigit(): v = str(int(v))  # il protocollo invia "020" per 20
        out[label] = v
    return out


# ---- notifiche con anti-spam: una al cambio di stato, ripetuta al massimo ogni REPEAT secondi finche' persiste
active = {}


def notify(text):
    log.warning("ALERT %s", text)
    if TG_TOKEN:
        try:
            urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % TG_TOKEN,
                                   urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text}).encode(), timeout=10)
        except Exception as e:  # l'eccezione di urlopen contiene l'URL con il token
            log.error("telegram: %s", type(e).__name__)


def alert(key, on, text_on, text_off):
    now = time.time()
    if on and (key not in active or now - active[key] >= REPEAT):
        active[key] = now; notify(text_on)
    elif not on and key in active:
        del active[key]; notify(text_off)


# ---- storage e stato
STATE = {"ts": 0, "gs": {}, "mode": "?", "ws": "", "cfg": {}}
SCHEMA = ("CREATE TABLE IF NOT EXISTS samples(ts INTEGER PRIMARY KEY, pv_w REAL, pv_v REAL, batt_v REAL, out_w REAL,"
          " load_pct REAL, chg_a REAL, dis_a REAL, temp_c REAL, grid_v REAL, mode TEXT, ws TEXT)")


def connect():
    c = sqlite3.connect(DB, timeout=5); c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA busy_timeout=5000"); return c


def faults(ws): return [WS[i][0] for i in WS if ws[i:i + 1] == "1"]


class Handler(BaseHTTPRequestHandler):
    server_version = "solarmon"
    sys_version = ""

    def log_message(self, *a): pass

    def out(self, body, ct="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Cache-Control", "no-store")
        if ct.startswith("text/html"):
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; img-src 'self' data:")
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/":
                self.out(open(HTML, "rb").read(), "text/html; charset=utf-8")
            elif u.path == "/api/now":
                s = dict(STATE); s["mode_name"] = MODES.get(s["mode"], "?"); s["faults"] = faults(s["ws"]); self.out(s)
            elif u.path == "/api/series":
                try: h = min(max(int(q.get("h", ["24"])[0]), 1), 24 * 365)
                except ValueError: h = 24
                b = max(60, h * 3600 // 600)
                with closing(connect()) as con:
                    rows = con.execute("SELECT ts/%d*%d, avg(pv_w), avg(out_w), avg(batt_v), max(pv_v) FROM samples "
                                       "WHERE ts>? GROUP BY 1 ORDER BY 1" % (b, b), (time.time() - h * 3600,)).fetchall()
                cols = list(zip(*rows)) if rows else [[]] * 5
                self.out(dict(zip(["ts", "pv_w", "out_w", "batt_v", "pv_v"], cols)))
            elif u.path == "/api/daily":
                with closing(connect()) as con:
                    rows = con.execute("SELECT min(ts), sum(pv_w)*%d/3600000.0 FROM samples WHERE ts>? "
                                       "GROUP BY date(ts,'unixepoch','localtime') ORDER BY 1" % INTERVAL,
                                       (time.time() - 30 * 86400,)).fetchall()
                self.out({"ts": [r[0] for r in rows], "kwh": [round(r[1], 2) for r in rows]})
            else:
                self.send_error(404)
        except Exception as e:
            log.error("http: %s", e); self.send_error(500)


def mqtt_client():
    if not MQTT_HOST: return None
    try:
        import paho.mqtt.client as m
        c = m.Client(m.CallbackAPIVersion.VERSION2) if hasattr(m, "CallbackAPIVersion") else m.Client()
        c.connect_async(MQTT_HOST); c.loop_start(); return c
    except Exception as e:
        log.error("mqtt: %s", e)


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(os.path.dirname(os.path.abspath(DB)), exist_ok=True)
    con = connect(); con.execute(SCHEMA); con.commit()
    server = ThreadingHTTPServer((BIND_ADDR, PORT), Handler); server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("dashboard su http://%s:%d", BIND_ADDR, PORT)
    mq, inv, fails, prev, cfg_ts = mqtt_client(), Inverter(), 0, None, 0
    notify("solarmon avviato")
    while True:
        t0 = time.time()
        try:
            gs = parse_gs(inv.query("QPIGS")); mode = inv.query("QMOD")[:1]; ws = inv.query("QPIWS")[:32]
            fails = 0; alert("nodata", False, "", "Comunicazione con l'inverter ripristinata")
        except Exception as e:
            fails += 1; log.error("lettura: %s", e)
            alert("nodata", fails >= 3, "Inverter non risponde da %d letture (%d min)" % (fails, fails * INTERVAL // 60),
                  "Comunicazione con l'inverter ripristinata")
            time.sleep(INTERVAL); continue
        if t0 - cfg_ts > 3600:
            try: STATE["cfg"] = parse_cfg(inv.query("QPIRI")); cfg_ts = t0
            except Exception as e: log.error("QPIRI: %s", e)
        STATE.update(ts=int(t0), gs=gs, mode=mode, ws=ws)
        con.execute("INSERT OR REPLACE INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (int(t0), gs["pv_w"], gs["pv_v"], gs["batt_v"], gs["out_w"], gs["load_pct"], gs["chg_a"],
                     gs["dis_a"], gs["temp_c"], gs["grid_v"], mode, ws)); con.commit()
        for i, (name, severe) in WS.items():
            alert("ws%d" % i, ws[i:i + 1] == "1", "%s %s (QPIWS=%s)" % ("GUASTO:" if severe else "Avviso:", name, ws),
                  "Rientrato: " + name)
        alert("modef", mode == "F", "Inverter in modalita' FAULT (QPIWS=%s)" % ws, "Inverter uscito da FAULT")
        low = gs["batt_v"] < BATT_LOW or ("batt" in active and gs["batt_v"] < BATT_LOW + 1)
        alert("batt", low, "Batteria bassa: %.1f V (%d%%)" % (gs["batt_v"], gs["batt_pct"]), "Batteria risalita: %.1f V" % gs["batt_v"])
        if prev and mode != prev: notify("Modalita': %s -> %s" % (MODES.get(prev, prev), MODES.get(mode, mode)))
        prev = mode
        if mq: mq.publish("solar/inverter/state", json.dumps(dict(gs, mode=mode, ws=ws)), retain=True)
        time.sleep(max(1, INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    if sys.argv[1:] == ["probe"]:  # python3 solarmon.py probe  (ferma prima ogni altro processo che usa l'inverter)
        inv = Inverter(); raw = {c: inv.query(c) for c in ("QPIGS", "QMOD", "QPIWS", "QPIRI")}
        print(json.dumps(raw, indent=1)); print(parse_gs(raw["QPIGS"])); print(parse_cfg(raw["QPIRI"]))
    else:
        main()
