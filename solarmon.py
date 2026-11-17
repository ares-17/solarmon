#!/usr/bin/env python3
"""solarmon: inverter PI30 (hidraw) -> SQLite + dashboard + dati grezzi JSON + bot Telegram (letture e scritture protette).
Solo libreria standard (paho-mqtt solo se MQTT_HOST e' impostato)."""
import calendar, collections, datetime, hmac, json, logging, math, os, secrets, select, signal, sqlite3, sys, threading, time, urllib.parse, urllib.request
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def load_env():  # legge solarmon.env (o il file in SOLARMON_ENV); l'ambiente reale ha la precedenza
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.environ.get("SOLARMON_ENV"), os.path.join(here, "solarmon.env"), "/etc/solarmon.env"):
        if p and os.path.isfile(p):
            with open(p) as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
            return p


load_env()
E = os.environ.get
log = logging.getLogger("solarmon")


def parse_price(raw):
    """Prezzo EUR/kWh da env: accetta virgola o punto; None se vuoto o non valido."""
    text = raw.strip()
    v = None
    if text:
        try:
            v = float(text.replace(",", "."))
        except ValueError:
            pass
        if v is None or not math.isfinite(v) or v <= 0:
            log.warning("GRID_PRICE_EUR_KWH non valido: %r", raw)
            v = None
    return v


DEV, DB = E("INVERTER_DEV", "/dev/inverter"), E("DB_PATH", "/var/lib/solarmon/solar.db")
HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
DEFAULT_BIND = "0.0.0.0" if (os.path.exists("/.dockerenv") or os.environ.get("CONTAINER") or os.environ.get("IN_DOCKER")) else "127.0.0.1"
PORT, BIND, RAW_TOKEN = int(E("PORT", "8000")), E("BIND_ADDR", DEFAULT_BIND), E("RAW_TOKEN", "")
INTERVAL, STORE_INTERVAL, RAW_KEEP = max(3, int(E("INTERVAL", "10"))), int(E("STORE_INTERVAL", "60")), int(E("RAW_KEEP", "3600"))
TG_TOKEN, TG_CHAT, MQTT_HOST = E("TG_TOKEN", ""), E("TG_CHAT", ""), E("MQTT_HOST", "")
TG_ADMIN = int(E("TG_ADMIN_ID") or TG_CHAT or 0)
ALLOW_WRITE = E("ALLOW_WRITE", "0") == "1"
GRID_CONFIRM, GRID_MIN_V = 3, 90.0
SOLAR_PLACE, SOLAR_LAT, SOLAR_LON = E("SOLAR_PLACE", ""), E("SOLAR_LAT", ""), E("SOLAR_LON", "")
GRID_PRICE = parse_price(E("GRID_PRICE_EUR_KWH", ""))
LOOPBACK = {"127.0.0.1", "::1", "localhost"}

MODES = {"P": "Accensione", "S": "Standby", "L": "Rete", "B": "Batteria", "F": "FAULT", "H": "Risparmio"}

# Capoluoghi di provincia: coordinate approssimate al km. La posizione serve solo ad
# alba/tramonto, quindi l'errore e' irrilevante; il comune scritto dall'utente e' solo
# un'etichetta, le coordinate sono quelle del capoluogo.
CAPITALS = {
    "AG": ("Agrigento", 37.311, 13.576), "AL": ("Alessandria", 44.913, 8.615),
    "AN": ("Ancona", 43.615, 13.518), "AO": ("Aosta", 45.737, 7.320),
    "AP": ("Ascoli Piceno", 42.854, 13.575), "AQ": ("L'Aquila", 42.351, 13.398),
    "AR": ("Arezzo", 43.463, 11.880), "AT": ("Asti", 44.900, 8.206),
    "AV": ("Avellino", 40.914, 14.791), "BA": ("Bari", 41.117, 16.872),
    "BG": ("Bergamo", 45.698, 9.677), "BI": ("Biella", 45.566, 8.053),
    "BL": ("Belluno", 46.142, 12.216), "BN": ("Benevento", 41.130, 14.778),
    "BO": ("Bologna", 44.494, 11.343), "BR": ("Brindisi", 40.632, 17.941),
    "BS": ("Brescia", 45.541, 10.211), "BT": ("Barletta", 41.320, 16.282),
    "BZ": ("Bolzano", 46.498, 11.355), "CA": ("Cagliari", 39.223, 9.121),
    "CB": ("Campobasso", 41.560, 14.662), "CE": ("Caserta", 41.073, 14.332),
    "CH": ("Chieti", 42.351, 14.167), "CL": ("Caltanissetta", 37.490, 14.062),
    "CN": ("Cuneo", 44.384, 7.542), "CO": ("Como", 45.808, 9.085),
    "CR": ("Cremona", 45.133, 10.022), "CS": ("Cosenza", 39.298, 16.254),
    "CT": ("Catania", 37.502, 15.087), "CZ": ("Catanzaro", 38.909, 16.587),
    "EN": ("Enna", 37.567, 14.279), "FC": ("Forlì", 44.222, 12.041),
    "FE": ("Ferrara", 44.838, 11.619), "FG": ("Foggia", 41.462, 15.544),
    "FI": ("Firenze", 43.769, 11.256), "FM": ("Fermo", 43.160, 13.718),
    "FR": ("Frosinone", 41.640, 13.342), "GE": ("Genova", 44.405, 8.946),
    "GO": ("Gorizia", 45.941, 13.622), "GR": ("Grosseto", 42.759, 11.112),
    "IM": ("Imperia", 43.889, 8.028), "IS": ("Isernia", 41.596, 14.233),
    "KR": ("Crotone", 39.080, 17.127), "LC": ("Lecco", 45.856, 9.397),
    "LE": ("Lecce", 40.351, 18.175), "LI": ("Livorno", 43.548, 10.310),
    "LO": ("Lodi", 45.314, 9.503), "LT": ("Latina", 41.467, 12.904),
    "LU": ("Lucca", 43.843, 10.505), "MB": ("Monza", 45.584, 9.274),
    "MC": ("Macerata", 43.300, 13.453), "ME": ("Messina", 38.193, 15.554),
    "MI": ("Milano", 45.464, 9.190), "MN": ("Mantova", 45.156, 10.791),
    "MO": ("Modena", 44.647, 10.925), "MS": ("Massa", 44.035, 10.139),
    "MT": ("Matera", 40.666, 16.604), "NA": ("Napoli", 40.852, 14.268),
    "NO": ("Novara", 45.446, 8.622), "NU": ("Nuoro", 40.321, 9.330),
    "OR": ("Oristano", 39.906, 8.588), "PA": ("Palermo", 38.116, 13.361),
    "PC": ("Piacenza", 45.052, 9.693), "PD": ("Padova", 45.407, 11.876),
    "PE": ("Pescara", 42.461, 14.216), "PG": ("Perugia", 43.110, 12.390),
    "PI": ("Pisa", 43.716, 10.396), "PN": ("Pordenone", 45.956, 12.661),
    "PO": ("Prato", 43.881, 11.102), "PR": ("Parma", 44.801, 10.328),
    "PT": ("Pistoia", 43.933, 10.917), "PU": ("Pesaro", 43.910, 12.913),
    "PV": ("Pavia", 45.185, 9.155), "PZ": ("Potenza", 40.640, 15.806),
    "RA": ("Ravenna", 44.418, 12.203), "RC": ("Reggio Calabria", 38.111, 15.647),
    "RE": ("Reggio Emilia", 44.698, 10.631), "RG": ("Ragusa", 36.926, 14.725),
    "RI": ("Rieti", 42.404, 12.856), "RM": ("Roma", 41.893, 12.483),
    "RN": ("Rimini", 44.067, 12.569), "RO": ("Rovigo", 45.070, 11.790),
    "SA": ("Salerno", 40.682, 14.768), "SI": ("Siena", 43.318, 11.331),
    "SO": ("Sondrio", 46.169, 9.874), "SP": ("La Spezia", 44.103, 9.824),
    "SR": ("Siracusa", 37.075, 15.286), "SS": ("Sassari", 40.726, 8.559),
    "SU": ("Sud Sardegna", 39.167, 8.522), "SV": ("Savona", 44.307, 8.481),
    "TA": ("Taranto", 40.464, 17.247), "TE": ("Teramo", 42.659, 13.704),
    "TN": ("Trento", 46.070, 11.121), "TO": ("Torino", 45.071, 7.686),
    "TP": ("Trapani", 38.017, 12.537), "TR": ("Terni", 42.563, 12.642),
    "TS": ("Trieste", 45.650, 13.770), "TV": ("Treviso", 45.666, 12.243),
    "UD": ("Udine", 46.071, 13.235), "VA": ("Varese", 45.820, 8.825),
    "VB": ("Verbania", 45.921, 8.552), "VC": ("Vercelli", 45.320, 8.418),
    "VE": ("Venezia", 45.440, 12.316), "VI": ("Vicenza", 45.545, 11.535),
    "VR": ("Verona", 45.438, 10.992), "VS": ("Medio Campidano", 39.562, 8.900),
    "VT": ("Viterbo", 42.420, 12.107), "VV": ("Vibo Valentia", 38.676, 16.100),
}


def solar_site():
    """Coordinate per alba/tramonto: prima LAT/LON esplicite, poi il capoluogo di PLACE."""
    if SOLAR_LAT and SOLAR_LON:
        try:
            lat, lon = float(SOLAR_LAT.replace(",", ".")), float(SOLAR_LON.replace(",", "."))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return {"place": SOLAR_PLACE or "coordinate", "lat": lat, "lon": lon}
            log.warning("SOLAR_LAT/SOLAR_LON fuori range: ignorate")
        except ValueError:
            log.warning("SOLAR_LAT/SOLAR_LON non numeriche: ignorate")
    place = SOLAR_PLACE.strip()
    if not place:
        return None
    code = place.split(",")[-1].strip().upper()
    if code not in CAPITALS:
        code = next((k for k, v in CAPITALS.items() if v[0].casefold() == place.casefold()), "")
    hit = CAPITALS.get(code)
    if not hit:
        log.warning("SOLAR_PLACE non riconosciuto: %s", place)
        return None
    return {"place": place, "lat": hit[1], "lon": hit[2]}
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
# QPIRI: posizione -> etichetta (None = campo non mostrato)
L_OUT, L_CHG, L_MAXC, L_MAXAC, L_BACK, L_RECH, L_CUT = ("Priorita' uscita", "Priorita' carica", "Max carica A", "Max carica AC A",
                                                       "Ritorno a rete sotto V", "Ritorno a batteria sopra V", "Cutoff batteria V")
CFG_LABELS = ["AC in V", "AC in A", "Uscita V", "Frequenza Hz", "Uscita A", "VA nominali", "W nominali", "Batteria nominale V",
              L_BACK, L_CUT, "Bulk V", "Float V", "Tipo batteria", L_MAXAC, L_MAXC, "Range ingresso", L_OUT, L_CHG,
              None, None, None, None, L_RECH]
MAPS = {12: ["AGM", "Flooded", "User"], 15: ["Appliance", "UPS"], 16: ["Utility first", "Solar first", "SBU"],
        17: ["Utility first", "Solar first", "Solar+Utility", "Solo solare"]}
# Impostazioni scrivibili da Telegram: nome -> (comando PI30, valori ammessi, etichetta QPIRI). Per aggiungerne, basta una riga.
# Volutamente esclusi: tipo batteria e tensioni bulk/float (da fare dal pannello dell'inverter).
SETTINGS = {
    "uscita": ("POP", {"utility": "00", "solare": "01", "sbu": "02"}, L_OUT),
    "carica": ("PCP", {"utility": "00", "solare_prima": "01", "solare_utility": "02", "solo_solare": "03"}, L_CHG),
    "corrente_carica": ("MCHGC", [10, 20, 30, 40, 50, 60], L_MAXC),
    "corrente_carica_ac": ("MUCHGC", [2, 10, 20, 30, 40, 50, 60], L_MAXAC),
    "ritorno_rete_v": ("PBCV", list(range(44, 52)), L_BACK),
    "ritorno_batteria_v": ("PBDV", list(range(48, 59)), L_RECH),
    "cutoff_v": ("PSDV", list(range(40, 49)), L_CUT)}
LEGEND = {"unita": "pv_w/out_w/out_va W, *_v V, chg_a/dis_a A, temp_c C, *_pct %", "mode": MODES,
          "ws": "32 caratteri QPIWS: tutti 0 = nessun allarme", "pv_w": "potenza FV (limitata dal carico se la batteria e' piena)",
          "chg_a/dis_a": "corrente in carica/scarica della batteria", "scc_on": "1 = MPPT sta caricando"}


SUN_CACHE = {}


def sun_day(day, lat, lon):
    """Alba e tramonto (epoch UTC) per una data, algoritmo NOAA semplificato."""
    key = (day.isoformat(), round(lat, 3), round(lon, 3))
    if key in SUN_CACHE:
        return SUN_CACHE[key]
    n = day.timetuple().tm_yday
    g = 2 * math.pi / 365.0 * (n - 1 + 0.5)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                   - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    dec = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
           - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
           - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(math.radians(lat)) * math.cos(dec))
              - math.tan(math.radians(lat)) * math.tan(dec))
    out = None
    if -1 <= cos_ha <= 1:
        ha = math.degrees(math.acos(cos_ha))
        base = calendar.timegm(day.timetuple())
        rise = base + round((720 - 4 * (lon + ha) - eq) * 60)
        sunset = base + round((720 - 4 * (lon - ha) - eq) * 60)
        if sunset > rise:
            out = (rise, sunset)
    if len(SUN_CACHE) > 800:
        SUN_CACHE.clear()
    SUN_CACHE[key] = out
    return out


def sun_payload(h):
    site = solar_site()
    if not site:
        return {"configured": False, "days": []}
    first = datetime.date(*time.gmtime(time.time() - h * 3600)[:3])
    last = datetime.date(*time.gmtime(time.time())[:3])
    days, day = [], first
    while day <= last:
        t = sun_day(day, site["lat"], site["lon"])
        if t:
            days.append({"date": day.isoformat(), "rise": t[0], "set": t[1]})
        day += datetime.timedelta(days=1)
    return {"configured": True, "place": site["place"], "lat": site["lat"],
            "lon": site["lon"], "days": days}


def max_gap():
    """Buco massimo (s) tra due letture contigue: oltre, il dato manca."""
    return max(300, 3 * INTERVAL)


def max_stored_gap():
    """Come max_gap, ma tollera le righe storiche scritte ogni STORE_INTERVAL."""
    return max(max_gap(), 3 * STORE_INTERVAL)


def power_split(pv_w, out_w, mode):
    """Ripartisce la potenza del carico tra FV diretto, batteria e rete (W)."""
    pv, out = max(0.0, float(pv_w or 0.0)), max(0.0, float(out_w or 0.0))
    if mode == "L":  # bypass: tutto il carico viene dalla rete
        return 0.0, 0.0, out
    return min(pv, out), max(0.0, out - pv), 0.0


def energy_step(prev, cur, gap=None):
    """Energia (Wh) tra due letture: PV prodotto e ripartizione del carico.

    prev/cur: (ts, pv_w, out_w, mode). Integra con la regola del trapezio sui
    secondi realmente trascorsi, non su un intervallo configurato. Oltre gap
    il buco e' un dato mancante e non produce energia.
    """
    limit = max_gap() if gap is None else gap
    dt = float(cur[0]) - float(prev[0])
    if not 0 < dt <= limit:
        return 0.0, 0.0, 0.0, 0.0
    pv0, pv1 = max(0.0, float(prev[1] or 0.0)), max(0.0, float(cur[1] or 0.0))
    s0, b0, g0 = power_split(prev[1], prev[2], prev[3])
    s1, b1, g1 = power_split(cur[1], cur[2], cur[3])
    k = dt / 3600.0
    return (pv0 + pv1) / 2 * k, (s0 + s1) / 2 * k, (b0 + b1) / 2 * k, (g0 + g1) / 2 * k


def energy_rows(rows):
    """(inizio, fine, (e_pv, e_solar, e_batt, e_grid)) per ogni riga.

    Usa i Wh salvati col campione; per le righe storiche (colonne NULL) li
    ricava dai timestamp dei campioni. rows: (ts, pv_w, out_w, mode, e_*).
    """
    prev, limit = None, max_stored_gap()
    for ts, pv, out, mode, e_pv, e_solar, e_batt, e_grid in rows:
        if None in (e_pv, e_solar, e_batt, e_grid):
            step = energy_step(prev, (ts, pv, out, mode), limit) if prev else (0.0,) * 4
        else:
            step = (float(e_pv), float(e_solar), float(e_batt), float(e_grid))
        yield (prev[0] if prev else None), ts, step
        prev = (ts, pv, out, mode)


def window_energy(rows, lo, hi):
    """Somma l'energia degli intervalli ritagliandoli sulla finestra [lo, hi]."""
    total = [0.0, 0.0, 0.0, 0.0]
    for start, end, step in energy_rows(rows):
        if start is None or end <= lo or start >= hi:
            continue
        span = float(end) - float(start)
        if span <= 0:
            continue
        fraction = (min(float(end), hi) - max(float(start), lo)) / span
        if fraction > 0:
            total = [a + b * fraction for a, b in zip(total, step)]
    return total


def mix_payload(h):
    """Energia consumata nel periodo, divisa per fonte. Le ricariche non entrano."""
    since, now = time.time() - h * 3600, time.time()
    with closing(connect()) as con:
        rows = con.execute("SELECT ts, pv_w, out_w, mode, %s FROM samples WHERE ts>? ORDER BY ts"
                           % ",".join(ENERGY_COLS), (since - max_stored_gap(),)).fetchall()
    _pv, solar, batt, grid = window_energy(rows, since, now)
    parts = [round(x / 1000.0, 3) for x in (solar, batt, grid)]
    visible = [r for r in rows if r[0] >= since]
    return {"h": h, "solar_kwh": parts[0], "batt_kwh": parts[1],
            "grid_kwh": parts[2], "load_kwh": round(sum(parts), 3),
            "samples": len(visible), "from": visible[0][0] if visible else None,
            "to": visible[-1][0] if visible else None}


def day_of(ts):
    return datetime.date.fromtimestamp(ts)


def midnight_of(day):
    return datetime.datetime.combine(day, datetime.time()).timestamp()


def next_midnight(ts):
    return midnight_of(day_of(ts) + datetime.timedelta(days=1))


def band_index(ts):
    """Indice fascia locale da 4 ore (0=00-04, 1=04-08, ..., 5=20-24)."""
    return datetime.datetime.fromtimestamp(ts).hour // 4


def next_hour(ts):
    """Timestamp inizio prossima ora locale."""
    dt = datetime.datetime.fromtimestamp(ts)
    nxt = datetime.datetime.combine(dt.date(), datetime.time(dt.hour)) + datetime.timedelta(hours=1)
    res = nxt.timestamp()
    return res if res > ts else ts + 1


def next_band(ts):
    """Timestamp inizio prossima fascia locale da 4 ore."""
    dt = datetime.datetime.fromtimestamp(ts)
    next_band_hour = (dt.hour // 4 + 1) * 4
    if next_band_hour < 24:
        nxt = datetime.datetime.combine(dt.date(), datetime.time(next_band_hour))
    else:
        nxt = datetime.datetime.combine(dt.date() + datetime.timedelta(days=1), datetime.time(0))
    res = nxt.timestamp()
    return res if res > ts else ts + 1


def split_interval(start, end, next_boundary):
    """Divide [start, end] in segmenti contigui ai confini dati da next_boundary."""
    parts = []
    a = float(start)
    b_limit = float(end)
    while a < b_limit:
        b = min(b_limit, next_boundary(a))
        if b <= a:
            b = b_limit
        parts.append((a, b))
        a = b
    return parts


def observed_seconds(raw, since, now, gap=None):
    """Secondi realmente osservati nella finestra, ignorando i buchi di comunicazione."""
    limit = gap or max_stored_gap()
    total = 0.0
    for prev, cur in zip(raw, raw[1:]):
        dt = float(cur[0]) - float(prev[0])
        if not 0 < dt <= limit:
            continue
        visible = min(float(now), float(cur[0])) - max(float(since), float(prev[0]))
        if visible > 0:
            total += visible
    return total


def energy_totals(energy_input, since, now):
    """Wh (pv, solar, batt, grid) nella finestra, ritagliando ogni intervallo."""
    total = [0.0, 0.0, 0.0, 0.0]
    for start, end, step in energy_rows(energy_input):
        if start is None:
            continue
        span = float(end) - float(start)
        if span <= 0:
            continue
        fraction = (min(float(end), now) - max(float(start), since)) / span
        if fraction > 0:
            total = [a + b * fraction for a, b in zip(total, step)]
    return tuple(total)


def band_totals(energy_input, since, now):
    """Wh [solar, batt, grid] per ciascuna delle sei fasce locali da 4 ore."""
    totals = [[0.0, 0.0, 0.0] for _ in range(6)]
    for start, end, step in energy_rows(energy_input):
        if start is None:
            continue
        span = float(end) - float(start)
        a, b = max(float(start), float(since)), min(float(end), float(now))
        if span <= 0 or b <= a:
            continue
        for sa, sb in split_interval(a, b, next_band):
            fraction = (sb - sa) / span
            row = totals[band_index(sa)]
            row[0] += step[1] * fraction
            row[1] += step[2] * fraction
            row[2] += step[3] * fraction
    return totals


def daily_by_source(energy_input, since, now):
    """kWh al giorno locale per fonte: solar, batt, grid."""
    buckets = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
    for start, end, step in energy_rows(energy_input):
        if start is None:
            continue
        span = float(end) - float(start)
        a, b = max(float(start), float(since)), min(float(end), float(now))
        if span <= 0 or b <= a:
            continue
        for sa, sb in split_interval(a, b, next_midnight):
            fraction = (sb - sa) / span / 1000.0
            bucket = buckets[day_of(sa)]
            for i in range(3):
                bucket[i] += step[i + 1] * fraction
    ordered = sorted(buckets)
    return {"ts": [int(midnight_of(d)) for d in ordered],
            "solar": [round(buckets[d][0], 3) for d in ordered],
            "batt": [round(buckets[d][1], 3) for d in ordered],
            "grid": [round(buckets[d][2], 3) for d in ordered]}


def solar_only_profile(raw, since, now, days):
    """Minuti/giorno per ora locale con carico coperto solo dal FV, senza rete."""
    seconds = [0.0] * 24
    limit = max_stored_gap()
    for prev, cur in zip(raw, raw[1:]):
        if not solar_only(prev, cur):
            continue
        dt = float(cur[0]) - float(prev[0])
        if not 0 < dt <= limit:
            continue
        a, b = max(float(prev[0]), float(since)), min(float(cur[0]), float(now))
        if b <= a:
            continue
        for sa, sb in split_interval(a, b, next_hour):
            seconds[datetime.datetime.fromtimestamp(sa).hour] += sb - sa
    total = sum(seconds)
    minutes = [round(s / 60.0 / days, 1) if days > 0 else 0.0 for s in seconds]
    observed = observed_seconds(raw, since, now)
    pct = round(total / observed * 100.0, 1) if observed > 0 else None
    return minutes, round(total / 3600.0, 2), pct


def daily_payload(days=30):
    """Produzione FV per giorno locale, integrata sul tempo reale."""
    since = time.time() - days * 86400
    with closing(connect()) as con:
        rows = con.execute("SELECT ts, pv_w, out_w, mode, %s FROM samples WHERE ts>? ORDER BY ts"
                           % ",".join(ENERGY_COLS), (since,)).fetchall()
    buckets = collections.defaultdict(float)
    for start, end, (e_pv, _solar, _batt, _grid) in energy_rows(rows):
        if e_pv <= 0:
            continue
        if start is None:
            buckets[day_of(end)] += e_pv / 1000.0
            continue
        a, b = float(start), float(end)
        while a < b:  # ripartisce l'intervallo ai confini di mezzanotte locali
            cut = min(b, next_midnight(a))
            if cut <= a:  # difesa da fusi orari anomali
                cut = b
            buckets[day_of(a)] += e_pv * (cut - a) / (b - a) / 1000.0
            a = cut
    ordered = sorted(buckets)
    return {"ts": [int(midnight_of(d)) for d in ordered],
            "kwh": [round(buckets[d], 2) for d in ordered]}


def crc16(data):  # CRC-XMODEM con la correzione PI30 (0x28, 0x0D, 0x0A -> +1)
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    fix = lambda x: x + 1 if x in (0x28, 0x0D, 0x0A) else x
    return bytes([fix(crc >> 8), fix(crc & 0xFF)])


class Nak(ValueError):
    pass


class Inverter:
    def __init__(self):
        self.fd, self.lock = None, threading.Lock()  # il lock serializza poll e bot sulla stessa porta

    def close(self):
        if self.fd is not None:
            try: os.close(self.fd)
            except OSError: pass
            self.fd = None

    def query(self, cmd, tries=3, retry_nak=True):
        raw = cmd.encode(); pkt = raw + crc16(raw) + b"\r"; last = None
        with self.lock:
            for n in range(tries):
                try:
                    if self.fd is None: self.fd = os.open(DEV, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
                    while select.select([self.fd], [], [], 0)[0]: os.read(self.fd, 256)  # svuota residui
                    for i in range(0, len(pkt), 8): os.write(self.fd, pkt[i:i + 8])
                    buf, end = b"", time.time() + 5
                    while time.time() < end and b"\r" not in buf:
                        if select.select([self.fd], [], [], 0.5)[0]: buf += os.read(self.fd, 256)
                    if b"\r" not in buf: raise TimeoutError("timeout")
                    buf = buf.split(b"\r")[0].lstrip(b"\x00")
                    if not buf.startswith(b"(") or crc16(buf[:-2]) != buf[-2:]: raise ValueError("risposta non valida")
                    text = buf[1:-2].decode("ascii", "ignore")
                    if text == "NAK": raise Nak("NAK (comando rifiutato)")
                    return text
                except (OSError, ValueError, TimeoutError) as e:
                    last = e
                    if isinstance(e, Nak) and not retry_nak: break
                    if not isinstance(e, Nak): self.close()
                    if n < tries - 1: time.sleep(1)
        raise RuntimeError("%s: %s" % (cmd, last))


def parse_gs(t):
    f = t.split(); n = lambda i: float(f[i]); s = f[16]
    return dict(grid_v=n(0), out_v=n(2), out_va=n(4), out_w=n(5), load_pct=n(6), batt_v=n(8), chg_a=n(9),
                batt_pct=n(10), temp_c=n(11), pv_v=n(13), dis_a=n(15), pv_w=n(19), scc_on=int(s[6]), ac_chg=int(s[7]))


def parse_cfg(t):
    f, out = t.split(), {}
    for i, label in enumerate(CFG_LABELS):
        if label is None: continue
        v = f[i]
        if i in MAPS:
            try: v = MAPS[i][int(v)]
            except (ValueError, IndexError): pass
        elif v.isdigit():
            v = str(int(v))
        out[label] = v
    return out


# ---- notifiche: invia solo al cambio di stato (nessuna ripetizione mentre persiste)
active = {}


def tg_api(method, **p):
    url = "https://api.telegram.org/bot%s/%s" % (TG_TOKEN, method)
    return json.load(urllib.request.urlopen(url, urllib.parse.urlencode(p).encode(), timeout=int(p.get("timeout", 0)) + 15))


def tg_send(text):
    if TG_TOKEN and TG_CHAT:
        try: tg_api("sendMessage", chat_id=TG_CHAT, text=text[:4000])
        except Exception as e: log.error("telegram: %s", type(e).__name__)


def notify(text):
    log.warning("ALERT %s", text); tg_send(text)


def alert(key, on, text_on, text_off=""):
    if on and key not in active:
        active[key] = True
        if text_on:
            notify(text_on)
    elif not on and key in active:
        del active[key]
        if text_off:
            notify(text_off)


def it_num(v, d=0):
    return f"{v:.{d}f}".replace(".", ",")


def _finite(v):
    if v is None:
        return False
    try:
        f = float(v)
        return math.isfinite(f)
    except (TypeError, ValueError):
        return False


def is_on_grid(grid_v, mode):
    return mode == "L" and _finite(grid_v) and float(grid_v) > GRID_MIN_V


def grid_on(gs, mode):
    return is_on_grid(gs.get("grid_v"), mode)


def solar_only(prev, cur):
    """Carico coperto dai pannelli senza rete, con tolleranza di 50 W."""

    def ok(row):
        _, pv_w, out_w, grid_v, mode = row
        return (not is_on_grid(grid_v, mode) and _finite(pv_w) and float(pv_w) > 0
                and _finite(out_w) and float(out_w) > 0
                and float(pv_w) >= float(out_w) - 50)

    return ok(prev) and ok(cur)


def count_switches(rows, gap=None):
    """Cambi batteria->rete confermati da GRID_CONFIRM campioni consecutivi."""
    total, by_day = 0, collections.defaultdict(int)
    if not rows:
        return total, {}
    limit = gap or max_stored_gap()
    prev_ts, prev_grid, prev_mode = rows[0]
    confirmed = is_on_grid(prev_grid, prev_mode)
    candidate, count = None, 0
    for ts, grid_v, mode in rows[1:]:
        state = is_on_grid(grid_v, mode)
        dt, prev_ts = ts - prev_ts, ts
        if dt > limit:
            confirmed, candidate, count = state, None, 0
            continue
        if state == confirmed:
            candidate, count = None, 0
            continue
        count = count + 1 if state == candidate else 1
        candidate = state
        if count >= GRID_CONFIRM:
            if state:
                total += 1
                by_day[day_of(ts)] += 1
            confirmed, candidate, count = state, None, 0
    return total, dict(by_day)


def grid_switch_text(new_on_grid, gs, mode):
    has_v = _finite(gs.get("batt_v"))
    has_pct = _finite(gs.get("batt_pct"))
    if new_on_grid:
        if has_pct and has_v:
            return f"Passato alla rete: batteria al {int(round(float(gs['batt_pct'])))}% ({it_num(float(gs['batt_v']), 1)} V)."
        elif has_pct:
            return f"Passato alla rete: batteria al {int(round(float(gs['batt_pct'])))}%."
        elif has_v:
            return f"Passato alla rete: batteria a {it_num(float(gs['batt_v']), 1)} V."
        else:
            return "Passato alla rete."
    else:
        if mode != "B":
            return None
        if has_v and has_pct:
            return f"Tornato alla batteria: {it_num(float(gs['batt_v']), 1)} V ({int(round(float(gs['batt_pct'])))}%)."
        elif has_v:
            return f"Tornato alla batteria: {it_num(float(gs['batt_v']), 1)} V."
        elif has_pct:
            return f"Tornato alla batteria: {int(round(float(gs['batt_pct'])))}%."
        else:
            return "Tornato alla batteria."


def alarm_groups(ws, mode):
    ws = ws or ""
    severe, warnings = [], []
    has_inv_fault = False
    for i in sorted(WS):
        name, is_sev = WS[i]
        if ws[i:i + 1] == "1":
            if name == "Inverter fault":
                has_inv_fault = True
            if is_sev:
                severe.append(name)
            else:
                warnings.append(name)
    if mode == "F" and not has_inv_fault:
        severe.insert(0, "Modalità FAULT")
    return severe, warnings


def alarm_text(prev, groups):
    severe, warnings = groups
    current = frozenset(severe + warnings)
    if prev is not None and current == prev:
        return None
    cleared = sorted(prev - current) if prev is not None else []
    if not current and not cleared:
        return None
    if not current:
        return "Allarmi rientrati: " + "; ".join(cleared) + "."
    lines = ["Allarmi inverter"]
    if severe:
        lines.append("Guasti: " + "; ".join(severe))
    if warnings:
        lines.append("Avvisi: " + "; ".join(warnings))
    if cleared:
        lines.append("Rientrati: " + "; ".join(cleared) + ".")
    return "\n".join(lines)


class Notifier:
    def __init__(self, send=None):
        self.send = send or notify
        self.prev_grid = None
        self.grid_candidate = None
        self.grid_count = 0
        self.prev_alarms = None

    def update(self, gs, mode, ws):
        on_grid = grid_on(gs, mode)
        if self.prev_grid is None:
            self.prev_grid = on_grid
        else:
            if on_grid != self.prev_grid:
                if on_grid == self.grid_candidate:
                    self.grid_count += 1
                else:
                    self.grid_candidate = on_grid
                    self.grid_count = 1
                if self.grid_count >= GRID_CONFIRM:
                    msg = grid_switch_text(on_grid, gs, mode)
                    self.prev_grid = on_grid
                    self.grid_candidate = None
                    self.grid_count = 0
                    if msg:
                        self.send(msg)
            else:
                self.grid_candidate = None
                self.grid_count = 0

        groups = alarm_groups(ws, mode)
        msg = alarm_text(self.prev_alarms, groups)
        self.prev_alarms = frozenset(groups[0] + groups[1])
        if msg:
            self.send(msg)



# ---- stato, storage, buffer di letture fini
STATE = {"ts": 0, "gs": {}, "mode": "?", "ws": "", "cfg": {}, "cycle_s": 0}
RING = collections.deque(maxlen=max(10, RAW_KEEP // INTERVAL + 1))
RING_LOCK = threading.Lock()
COLS = ["ts", "pv_w", "pv_v", "batt_v", "out_w", "load_pct", "chg_a", "dis_a", "temp_c", "grid_v", "mode", "ws"]
ENERGY_COLS = ["e_pv_wh", "e_solar_wh", "e_batt_wh", "e_grid_wh"]
SCHEMA = ["CREATE TABLE IF NOT EXISTS samples(ts INTEGER PRIMARY KEY, pv_w REAL, pv_v REAL, batt_v REAL, out_w REAL,"
          " load_pct REAL, chg_a REAL, dis_a REAL, temp_c REAL, grid_v REAL, mode TEXT, ws TEXT,"
          " e_pv_wh REAL, e_solar_wh REAL, e_batt_wh REAL, e_grid_wh REAL)",
          "CREATE TABLE IF NOT EXISTS audit(ts INTEGER, who TEXT, cmd TEXT, result TEXT, before TEXT)"]


def connect():
    c = sqlite3.connect(DB, timeout=5); c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA busy_timeout=5000"); return c


def ensure_schema(con):
    """Crea le tabelle e aggiunge le colonne energia ai DB esistenti."""
    for statement in SCHEMA: con.execute(statement)
    have = {r[1] for r in con.execute("PRAGMA table_info(samples)")}
    for col in ENERGY_COLS:
        if col not in have:
            con.execute("ALTER TABLE samples ADD COLUMN %s REAL" % col)
    con.commit()


def faults(ws): return [WS[i][0] for i in WS if ws[i:i + 1] == "1"]


def merge(g, ts):
    m = {"ts": ts}
    for k, v in g[-1].items():
        if k == "ts": continue
        vals = [r[k] for r in g if isinstance(r.get(k), (int, float))]
        m[k] = round(sum(vals) / len(vals), 2) if vals and isinstance(v, (int, float)) else v
    m["ws"] = next((r["ws"] for r in g if "1" in r["ws"]), g[-1]["ws"])
    m["mode"] = "F" if any(r["mode"] == "F" for r in g) else g[-1]["mode"]
    return m


def bucket(rows, step):
    if step <= 1: return rows
    out, cur, key = [], [], None
    for r in rows:
        k = r["ts"] // step * step
        if k != key and cur: out.append(merge(cur, key)); cur = []
        key = k; cur.append(r)
    if cur: out.append(merge(cur, key))
    return out


def qint(q, key, default, lo, hi):
    try: v = int(q.get(key, [str(default)])[0])
    except (TypeError, ValueError): return default
    return max(lo, min(v, hi))


def raw_payload(q):
    """Dati grezzi per analisi (es. da dare a un'AI): ?seconds=300&step=0&compact=0"""
    sec, step = qint(q, "seconds", 300, 1, 30 * 86400), qint(q, "step", 0, 0, 86400)
    now = time.time()
    with RING_LOCK: ring = list(RING)
    if ring and now - ring[0]["ts"] + INTERVAL >= sec:
        src, rows = "ram", [r for r in ring if r["ts"] >= now - sec]
    else:
        src = "db"
        with closing(connect()) as con:
            rows = [dict(zip(COLS, r)) for r in con.execute(
                "SELECT %s FROM samples WHERE ts>=? ORDER BY ts" % ",".join(COLS), (now - sec,))]
    rows = bucket(rows, step)[-5000:]
    body = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"), "window_s": sec, "source": src,
            "interval_s": INTERVAL if src == "ram" else STORE_INTERVAL, "step_s": step, "legend": LEGEND,
            "inverter_config": STATE["cfg"], "count": len(rows)}
    if q.get("compact", ["0"])[0] == "1":
        cols = list(rows[0]) if rows else []
        body["columns"], body["rows"] = cols, [[r.get(c) for c in cols] for r in rows]
    else:
        body["samples"] = rows
    return body


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
                             "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
                             "frame-ancestors 'none'; base-uri 'none'")
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):  # nessuna scrittura possibile via HTTP: le modifiche passano solo da Telegram
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/":
                self.out(open(HTML, "rb").read(), "text/html; charset=utf-8")
            elif u.path == "/api/now":
                s = dict(STATE); s["mode_name"] = MODES.get(s["mode"], "?"); s["faults"] = faults(s["ws"]); self.out(s)
            elif u.path == "/api/raw":
                tok = q.get("token", [self.headers.get("X-Token", "")])[0]
                if RAW_TOKEN:
                    if not hmac.compare_digest(tok, RAW_TOKEN): self.send_error(403); return
                elif BIND not in LOOPBACK:
                    self.send_error(403, "RAW_TOKEN non impostato"); return
                self.out(raw_payload(q))
            elif u.path == "/api/series":
                h = qint(q, "h", 24, 1, 24 * 365); b = max(60, h * 3600 // 600)
                with closing(connect()) as con:
                    rows = con.execute("SELECT ts/%d*%d, avg(pv_w), avg(out_w), avg(batt_v), max(pv_v) FROM samples "
                                       "WHERE ts>? GROUP BY 1 ORDER BY 1" % (b, b), (time.time() - h * 3600,)).fetchall()
                cols = list(zip(*rows)) if rows else [[]] * 5
                self.out(dict(zip(["ts", "pv_w", "out_w", "batt_v", "pv_v"], cols)))
            elif u.path == "/api/sun":
                self.out(sun_payload(qint(q, "h", 24, 1, 24 * 365)))
            elif u.path == "/api/mix":
                self.out(mix_payload(qint(q, "h", 24, 1, 24 * 365)))
            elif u.path == "/api/daily":
                self.out(daily_payload())
            else:
                self.send_error(404)
        except Exception as e:
            log.error("http: %s", e); self.send_error(500)


# ---- bot Telegram: solo TG_ADMIN, solo chat privata, scritture con conferma a codice (60 s)
PENDING = {}


def describe(name):
    a = SETTINGS[name][1]
    return "%s: %s" % (name, "|".join(a) if isinstance(a, dict) else "%s..%s" % (a[0], a[-1]))


def prepare(name, raw, cfg):
    if name not in SETTINGS: raise ValueError("parametro sconosciuto")
    cmd, allowed, label = SETTINGS[name]
    if isinstance(allowed, dict):
        if raw not in allowed: raise ValueError("valori ammessi: " + ", ".join(allowed))
        return cmd + allowed[raw], label
    try: v = float(raw.replace(",", "."))
    except ValueError: raise ValueError("serve un numero")
    if v not in allowed: raise ValueError("valori ammessi: " + ", ".join(str(x) for x in allowed))
    num = lambda k: float(cfg[k])
    if name == "cutoff_v" and v >= num(L_BACK): raise ValueError("il cutoff deve restare sotto il ritorno a rete (%s V)" % cfg[L_BACK])
    if name == "ritorno_rete_v" and not num(L_CUT) < v < num(L_RECH): raise ValueError("deve stare tra cutoff (%s) e ritorno a batteria (%s)" % (cfg[L_CUT], cfg[L_RECH]))
    if name == "ritorno_batteria_v" and v <= num(L_BACK): raise ValueError("deve stare sopra il ritorno a rete (%s V)" % cfg[L_BACK])
    return ("%s%03d" % (cmd, v) if cmd in ("MCHGC", "MUCHGC") else "%s%.1f" % (cmd, v)), label


def status_text():
    s, g = STATE, STATE["gs"]
    if not s["ts"]: return "Nessun dato ancora."
    t = ("%s, dati di %d s fa\nFV %.0f W (%.1f V)\nCarico %.0f W (%.0f%%)\nBatteria %.1f V, %.0f%% (+%.0f / -%.0f A)\n"
         "Temperatura %.0f C, rete %.0f V") % (MODES.get(s["mode"], "?"), time.time() - s["ts"], g["pv_w"], g["pv_v"], g["out_w"],
                                              g["load_pct"], g["batt_v"], g["batt_pct"], g["chg_a"], g["dis_a"], g["temp_c"], g["grid_v"])
    f = faults(s["ws"]); return t + ("\nALLARMI: " + "; ".join(f) if f else "\nNessun allarme")


def handle(m, inv, con):
    if not m or "text" not in m: return
    f, ch = m.get("from", {}), m.get("chat", {})
    if not (f.get("id") == TG_ADMIN and ch.get("id") == int(TG_CHAT) and ch.get("type") == "private" and not f.get("is_bot")):
        log.warning("bot: messaggio ignorato (from=%s chat=%s)", f.get("id"), ch.get("id")); return  # nessuna risposta agli estranei
    if time.time() - m.get("date", 0) > 120: return  # scarta messaggi vecchi
    parts = m["text"].strip().split(); cmd = parts[0].split("@")[0].lower()
    try:
        if cmd in ("/start", "/help"):
            tg_send("/stato situazione\n/oggi energia FV di oggi\n/config impostazioni inverter\n"
                    "/set <parametro> <valore>, poi /ok <codice>\n\nParametri:\n" + "\n".join(describe(n) for n in SETTINGS)
                    + ("" if ALLOW_WRITE else "\n\nScrittura DISATTIVATA (ALLOW_WRITE=0)"))
        elif cmd == "/stato": tg_send(status_text())
        elif cmd == "/config": tg_send("\n".join("%s: %s" % kv for kv in STATE["cfg"].items()) or "Config non ancora letta.")
        elif cmd == "/oggi":
            start = midnight_of(datetime.date.today())
            rows = con.execute("SELECT ts, pv_w, out_w, mode, %s FROM samples WHERE ts>=? ORDER BY ts"
                               % ",".join(ENERGY_COLS),
                               (start - max_stored_gap(),)).fetchall()
            wh = window_energy(rows, start, time.time())[0]
            tg_send("Produzione FV oggi: %.2f kWh" % (wh / 1000.0))
        elif cmd == "/set":
            if not ALLOW_WRITE: return tg_send("Scrittura disattivata (ALLOW_WRITE=0 nel file env).")
            if len(parts) != 3: return tg_send("Uso: /set <parametro> <valore>\n" + "\n".join(describe(n) for n in SETTINGS))
            cfg = parse_cfg(inv.query("QPIRI")); pc, label = prepare(parts[1].lower(), parts[2].lower(), cfg)
            code = "%04d" % secrets.randbelow(10000)
            PENDING.clear(); PENDING.update(code=code, cmd=pc, exp=time.time() + 60)
            tg_send("%s: %s -> %s\nComando: %s\nPer confermare entro 60 s: /ok %s" % (label, cfg[label], parts[2], pc, code))
        elif cmd == "/ok":
            p = dict(PENDING); PENDING.clear()
            if not p or time.time() > p["exp"] or parts[1:] != [p["code"]]: return tg_send("Nessuna modifica in attesa, codice errato o scaduto.")
            before = parse_cfg(inv.query("QPIRI"))
            try: res = inv.query(p["cmd"], tries=1, retry_nak=False)
            except Exception as e: res = "ERRORE: %s" % e
            time.sleep(1); after = parse_cfg(inv.query("QPIRI")); STATE["cfg"] = after
            con.execute("INSERT INTO audit VALUES(?,?,?,?,?)", (int(time.time()), str(f.get("id")), p["cmd"], res, json.dumps(before))); con.commit()
            diff = "\n".join("%s: %s -> %s" % (k, before[k], v) for k, v in after.items() if before.get(k) != v)
            tg_send("%s -> %s\n%s" % (p["cmd"], res, diff or "Nessuna differenza in QPIRI."))
    except Exception as e:
        log.error("bot: %s", e); tg_send("Errore: %s" % e)


def bot_loop(inv):
    con, off = connect(), 0
    try:
        r = tg_api("getUpdates", offset=-1, timeout=0)["result"]; off = r[-1]["update_id"] + 1 if r else 0  # salta il backlog
    except Exception as e: log.error("bot init: %s", type(e).__name__)
    while True:
        try:
            for u in tg_api("getUpdates", offset=off, timeout=30, allowed_updates=json.dumps(["message"]))["result"]:
                off = u["update_id"] + 1; handle(u.get("message"), inv, con)
        except Exception as e:
            log.error("bot: %s", type(e).__name__); time.sleep(5)


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
    con = connect()
    ensure_schema(con)
    inv = Inverter()
    def shutdown(*_):
        log.info("arresto in corso...")
        try: inv.close()
        except Exception: pass
        sys.exit(0)
    signal.signal(signal.SIGTERM, shutdown); signal.signal(signal.SIGINT, shutdown)
    server = ThreadingHTTPServer((BIND, PORT), Handler); server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("dashboard su http://%s:%d", BIND, PORT)
    if not RAW_TOKEN and BIND not in LOOPBACK:
        log.warning("/api/raw risponde 403: BIND_ADDR=%s senza RAW_TOKEN", BIND)
    if TG_TOKEN and TG_CHAT and TG_ADMIN: threading.Thread(target=bot_loop, args=(inv,), daemon=True).start()
    mq, fails, cfg_ts, store_ts = mqtt_client(), 0, 0, 0
    store_cols = COLS + ENERGY_COLS
    notifier, prev_read, acc = Notifier(), None, [0.0, 0.0, 0.0, 0.0]
    while True:
        t0 = time.time()
        try:
            gs = parse_gs(inv.query("QPIGS")); t_gs = time.time()
            mode = inv.query("QMOD")[:1]; ws = inv.query("QPIWS")[:32]
            fails = 0; alert("nodata", False, "", "Comunicazione con l'inverter ripristinata.")
        except Exception as e:
            fails += 1; log.error("lettura: %s", e)
            prev_read = None  # non inventare energia nel buco di comunicazione
            alert("nodata", fails * INTERVAL >= 60, "Inverter non risponde da %d s (%d letture)." % (fails * INTERVAL, fails),
                  "Comunicazione con l'inverter ripristinata.")
            time.sleep(INTERVAL); continue
        if t0 - cfg_ts > 600:  # rilegge periodicamente la config per alimentare la dashboard
            try:
                STATE["cfg"] = parse_cfg(inv.query("QPIRI")); cfg_ts = t0
            except Exception as e: log.error("QPIRI: %s", e)
        row = dict(ts=int(t_gs), **gs, mode=mode, ws=ws)
        with RING_LOCK: RING.append(row)
        STATE.update(ts=int(t_gs), gs=gs, mode=mode, ws=ws, cycle_s=round(time.time() - t0, 2))
        notifier.update(gs, mode, ws)
        if prev_read is not None:  # energia sul tempo reale, a ogni lettura
            acc = [a + b for a, b in zip(acc, energy_step(prev_read, (t_gs, gs["pv_w"], gs["out_w"], mode)))]
        prev_read = (t_gs, gs["pv_w"], gs["out_w"], mode)
        if t0 - store_ts >= STORE_INTERVAL - 0.5:
            store_ts = t0
            stored = dict(row)
            stored.update(zip(ENERGY_COLS, acc))
            con.execute("INSERT OR REPLACE INTO samples(%s) VALUES(%s)"
                        % (",".join(store_cols), ",".join("?" * len(store_cols))),
                        [stored[c] for c in store_cols]); con.commit()
            acc = [0.0, 0.0, 0.0, 0.0]
        if mq: mq.publish("solar/inverter/state", json.dumps(dict(gs, mode=mode, ws=ws)), retain=True)
        time.sleep(max(0.5, INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    if sys.argv[1:] == ["probe"]:  # python3 solarmon.py probe  (ferma prima ogni altro processo che usa l'inverter)
        inv = Inverter(); raw = {c: inv.query(c) for c in ("QPIGS", "QMOD", "QPIWS", "QPIRI")}
        print(json.dumps(raw, indent=1)); print(parse_gs(raw["QPIGS"])); print(parse_cfg(raw["QPIRI"]))
    else:
        main()
