# Security review — solarmon

Revisione del codice v1 (`solarmon.py`, `index.html`) e del setup descritto nella chat.
Il **13/11/2026** è stata integrata la v2: i fix S1–S10 sono stati riapplicati e coperti dai
test. Ogni voce ha stato: **DA FARE** (non ancora corretto), **PARZIALE**, **FATTO** (corretto
nel repo) o **ACCETTATO** (rischio residuo motivato).

## Riepilogo

| ID | Gravità | Problema | Stato |
|---|---|---|---|
| S1 | Alta | Il token del bot Telegram finisce nei journal quando `urlopen` fallisce | FATTO |
| S2 | Alta | HTTP in ascolto su `0.0.0.0` senza autenticazione | FATTO |
| S3 | Alta | Servizio systemd come root (setup della chat) | FATTO |
| S4 | Media | `/dev/inverter` con `MODE=0666` (scrivibile da chiunque) | FATTO |
| S5 | Media | Nessun token su `/api/raw`: dati operativi esposti | FATTO |
| S6 | Media | Mosquitto senza auth e in ascolto su tutte le interfacce | FATTO (non installato) |
| S7 | Bassa | Connessione SQLite aperta a ogni richiesta HTTP e mai chiusa | FATTO |
| S8 | Bassa | `os.makedirs(os.path.dirname(DB))` esplode se `DB_PATH` è relativo senza directory | FATTO |
| S9 | Bassa | Nessun header di sicurezza (CSP, nosniff) sulle risposte | FATTO |
| S10 | Bassa | Parametri HTTP non tutti limitati (finestra `/api/raw` in v2) | FATTO |
| S11 | Bassa | Nessun rate limit sulle rotte HTTP | ACCETTATO (loopback/Tailscale) |
| S12 | Informativa | Il token Telegram viaggia nell'URL (limite dell'API Bot) | ACCETTATO + mitigazioni |

## Dettaglio

### S1 — Token Telegram nei log

```python
except Exception as e:
    log.error("telegram: %s", e)
```

`urllib.error.HTTPError.__str__` include l'URL completo, che contiene
`https://api.telegram.org/bot<TOKEN>/sendMessage`. Con un 4xx/5xx il token finisce in
`journalctl`, nei backup dei log e in qualsiasi output condiviso.

**Fix applicato:** loggare solo il tipo di eccezione, mai il messaggio:

```python
except Exception as e:
    log.error("telegram: %s", type(e).__name__)
```

Se il token è già finito nei log: rigenerarlo da @BotFather.

### S2 — Dashboard esposta sulla LAN

`ThreadingHTTPServer(("0.0.0.0", PORT), Handler)` accetta connessioni da qualsiasi
interfaccia e non c'è autenticazione. Chi è in rete legge produzione, batteria, configurazione
e (in v2) i dati grezzi.

**Fix:** `BIND_ADDR` con default `127.0.0.1`; accesso da telefono solo via Tailscale.
Se serve la LAN, valutare un reverse proxy con auth, non aprire la porta.

### S3 — Servizio come root

Il setup della chat usa `sudo` e non crea un utente dedicato. Un bug nel parser o nel server
HTTP avrebbe privilegi totali sulla Pi.

**Fix:** utente di sistema `solarmon`, gruppo `inverter` per l'hidraw, unit con sandbox
(`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`,
`CapabilityBoundingSet=`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`,
`SystemCallFilter=@system-service`).

### S4 — Device scrivibile da tutti

`MODE="0666"` sulla regola udev rende l'inverter accessibile in scrittura a qualsiasi
processo locale. I comandi di scrittura possono cambiare tensioni di carica.

**Fix:** `GROUP="inverter"`, `MODE="0660"`, utente del servizio nel gruppo.

### S5 — `/api/raw` senza token

La rotta serve a incollare i dati a un'AI: contiene storico, configurazione e stato.
In v2 è previsto `RAW_TOKEN`, ma se non impostato resta aperta.

**Fix applicato:** token obbligatorio con `hmac.compare_digest`; se il bind non è loopback e
il token è vuoto la rotta risponde 403 (non espone nulla). Il token non viene mai loggato.

### S6 — MQTT aperto

Il compose della chat espone `1883:1883` con Mosquitto senza autenticazione. Chiunque in rete
può leggere lo stato e pubblicare comandi (se la whitelist è lato app, almeno le scritture
restano protette, ma il canale è spoofabile).

**Fix:** Mosquitto solo su `127.0.0.1`, `allow_anonymous false`, password file, e opzionale
TLS se il broker è raggiunto da fuori. Meglio: non installarlo finché non serve HA.

### S7 — Connessioni SQLite non chiuse

`connect()` viene chiamata a ogni richiesta HTTP e la connessione non viene chiusa: su un
telefono che ricarica la dashboard ogni 30 s sono decine di file descriptor al giorno.

**Fix:** una connessione condivisa con lock, oppure `contextlib.closing` per richiesta.
Aggiungere `busy_timeout`.

### S8 — `makedirs` su path vuoto

Con `DB_PATH=solar.db` (percorso relativo) `os.path.dirname` restituisce `""` e
`os.makedirs("")` solleva `FileNotFoundError`.

**Fix:** `os.makedirs(os.path.dirname(os.path.abspath(DB)), exist_ok=True)`.

### S9 — Header di sicurezza

Le risposte HTML non hanno CSP né `X-Content-Type-Options`. La dashboard è statica e i valori
sono numerici o presi da mappe fisse, quindi il rischio XSS è basso, ma l'header costa nulla.

**Fix:** `Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'`
(la dashboard ha script inline) e `X-Content-Type-Options: nosniff`.

### S10 — Parametri non limitati

`/api/series` limita `h` a 365 giorni. La nuova `/api/raw` deve limitare `seconds`, `step`
e il numero di campioni restituiti, altrimenti una richiesta può allocare molta memoria.

**Fix applicato:** `seconds` limitato a 30 giorni, `step` a 86400, `h` a 365 giorni; il
risultato è comunque tagliato a 5000 righe e un valore non numerico ricade sul default
(200, non 500).

### S12 — Token nell'URL Telegram

È il funzionamento previsto dall'API Bot. Mitigazioni: non loggare mai l'URL (S1), non
condividere screenshot del terminale, rigenerare il token se sospetto, 2FA sull'account
Telegram perché il bot è controllabile da chi possiede l'account.

## Checklist prima della produzione

- [x] S1 token sanificato nei log
- [x] S2 bind su `127.0.0.1` e accesso via Tailscale
- [x] S3 utente dedicato + unit hardened
- [x] S4 udev `0660` con gruppo `inverter`
- [x] S5 `/api/raw` protetto: token oppure 403 se esposto senza token
- [x] S6 Mosquitto non installato o con auth e bind locale
- [x] S7/S8 fix a SQLite
- [x] S9 header di sicurezza
- [x] `ALLOW_WRITE=0` finché i comandi di scrittura non sono verificati sul modello
- [x] File env `0600`, proprietario root, gruppo `solarmon`
- [x] `.env`, DB e dump assenti dal repo (`git ls-files | grep -E '\.env$|\.db$'` vuoto)
