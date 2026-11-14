# Decisioni tecniche

Registro delle scelte e del perché. Le decisioni vengono dalla chat di progetto
(archiviata in `chat-solarmon-2026-11-13.md`) più l'hardening deciso in fase di repo.

## D1 — Un solo processo Python, senza Docker né Podman

**Scelta.** `solarmon.py` fa tutto: legge l'inverter, scrive SQLite, serve la dashboard,
manda gli alert, opzionalmente pubblica su MQTT. systemd + venv.

**Motivo.** Sulla Pi 3B (1 GB RAM) Docker costa 50-80 MB e aggiunge un layer di rete e
storage da gestire, per tre processi banali. Soprattutto: **un solo processo alla volta può
aprire l'hidraw dell'inverter**, quindi un'app unica elimina per costruzione le collisioni
tra il daemon e i comandi manuali.

**Conseguenze.** Niente `docker compose`, niente `mpp-solar` come servizio. Le dipendenze
extra sono opzionali (`paho-mqtt` solo con `MQTT_HOST` impostato).

## D2 — SQLite con WAL, scrittura ogni 60 s

**Scelta.** Un campione ogni `STORE_INTERVAL` (60 s) anche se la lettura è ogni 10 s.
Le letture fini restano in un ring buffer in RAM (`RAW_KEEP`, 3600 s).

**Motivo.** La SD si consuma con le scritture continue. Per un inverter 60 s sono
abbondanti per lo storico; le letture fini servono solo per diagnosi e per `/api/raw`.

**Conseguenze.** `/api/raw` oltre la finestra RAM legge dal database a 60 s.

## D3 — HTTP in sola lettura, bind su loopback

**Scelta.** Il server espone solo rotte GET. `BIND_ADDR` default `127.0.0.1`.
Da remoto si passa da Tailscale. `/api/raw` protetto da `RAW_TOKEN` quando impostato; se il
bind non è loopback e il token è vuoto, la rotta risponde 403.

**Motivo.** La dashboard non deve essere raggiungibile in LAN da chiunque. Nessuna rotta
HTTP scrive sull'inverter: le modifiche passano solo dal bot Telegram (connessione in
uscita, nessuna porta aperta).

**Conseguenze.** Per usarla dal telefono senza Tailscale bisogna cambiare `BIND_ADDR`
esplicitamente, accettando il rischio.

## D4 — Scritture solo da Telegram, con tripla protezione

**Scelta.** `ALLOW_WRITE=0` di default. Il bot accetta comandi solo se:
1. l'utente è `TG_ADMIN_ID`;
2. la chat è privata (non gruppo);
3. il messaggio ha meno di 2 minuti.

Le modifiche richiedono `/set` + conferma `/ok CODICE` (codice monouso, 60 s), usano una
whitelist di 7 parametri con valori ammessi e controlli di coerenza. Ogni modifica salva
`QPIRI` prima/dopo e finisce nella tabella `audit`.

**Motivo.** Una tensione di carica sbagliata danneggia le batterie. Il punto debole residuo
è l'account Telegram: va attivata la verifica in due passaggi.

**Conseguenze.** Tipo batteria e tensioni bulk/float sono esclusi di proposito: si cambiano
dal pannello dell'inverter.

## D5 — MQTT opzionale e spento

**Scelta.** Mosquitto non viene installato dal setup di base. L'app pubblica
`solar/inverter/state` solo se `MQTT_HOST` è impostato.

**Motivo.** Serve solo come "presa" per un futuro Home Assistant. Un broker in più è
superficie d'attacco e RAM in più, senza beneficio finché HA non c'è.

**Conseguenze.** Quando arriverà HA: installare Mosquitto in locale, bind `127.0.0.1`,
autenticazione attiva, e puntare HA al broker via Tailscale.

## D6 — udev: `/dev/inverter` con gruppo dedicato, `0660`

**Scelta.** Regola udev con `SYMLINK+="inverter"`, `GROUP="inverter"`, `MODE="0660"`.
L'utente del servizio sta nel gruppo `inverter`.

**Motivo.** Il nome `hidraw0/1` cambia tra i riavvii. `0666` (suggerito nella chat) rende il
device scrivibile da chiunque: `0660` con gruppo dedicato dà lo stesso risultato senza
esporre l'inverter a utenti non previsti.

## D7 — Segreti solo fuori dal repo

**Scelta.** `.gitignore` esclude `.env`/`solarmon.env`, database, backup, dump dell'inverter.
Il modello `solarmon.env.example` contiene solo placeholder. Permessi `0600` sul file env e sul
database, `0640` sui backup (leggibili dal gruppo `solarmon`).

**Motivo.** Il token del bot e il numero di serie dell'inverter non devono finire in git
né in una condivisione.

**Conseguenze.** Il dump reale (`inverter_dump.txt`) resta fuori; per i test si usa una
copia redatta in `tests/fixtures/`.

## D8 — Auto-restart e osservatore esterno

**Scelta.** `Restart=always`, `RestartSec=5`, `StartLimitBurst` sulla unit. L'agente Beszel
sulla Pi segnala se l'host sparisce.

**Motivo.** L'app non può avvisare della propria morte né di una SD corrotta o di un
blackout. Serve un osservatore esterno.

## D9 — Token nei log (corretto)

In v1 `notify()` fa `log.error("telegram: %s", e)`: se `urlopen` fallisce, l'eccezione
contiene l'URL completo e quindi **il token del bot finisce nei journal**. Nella v2 integrata
il log riporta solo `type(e).__name__`, e un test verifica che il token non compaia.

## D10 — Integrazione della v2 e riapplicazione dell'hardening

**Scelta.** La v2 scaricata dalla chat è stata integrata mantenendo le correzioni S1–S10:
bind loopback di default, log senza token, SQLite chiuso e con timeout, header di sicurezza,
parametri HTTP limitati, `/api/raw` negato se esposto senza token, `umask 077`.

**Motivo.** La v2 aggiunge funzioni (file env, `/api/raw`, bot con scritture) ma riapriva i
punti già chiusi in v1. Integrare invece di sostituire evita regressioni silenziose.

**Conseguenze.** Le correzioni sono coperte da test (token, 403, parametri invalidi,
`prepare`). La copia di partenza `online-version/` è stata integrata e poi rimossa.

## D11 — Allineamento e validazione con il Manuale Ufficiale PIP-MS (PF1)

**Scelta.** Il manuale ufficiale `PIP-MS_1-5KVA_manual-20190109.pdf` è stato convertito
in Markdown (`docs/PIP-MS_1-5KVA_manual.md`) e usato come fonte di verità per
la validazione di comandi PI30, allarmi, codici di errore e specifiche elettriche.

**Risoluzioni.**
1. **Errore 58 confermato**: Definito ufficialmente nel manuale come `Output voltage is too low`
   (tensione AC di uscita < 190 Vac o > 260 Vac). Riservato ai modelli 4KVA/5KVA.
   Corrisponde al bit 7 del comando `QPIWS`.
2. **Validazione Comandi e Range di Scrittura (`SETTINGS`)**:
   Tutti i comandi supportati da `solarmon` e le relative opzioni ammesse corrispondono
   esattamente ai programmi del display LCD:
   - `uscita`: Programma 01 (`POP00` UTI, `POP01` SOL, `POP02` SBU).
   - `carica`: Programma 16 (`PCP00` UTI, `PCP01` CSO, `PCP02` SNU, `PCP03` OSO).
   - `corrente_carica`: Programma 02 (`MCHGC0xx`, 10A..140A).
   - `corrente_carica_ac`: Programma 11 (`MUCHGC0xx`, opzioni 2, 10, 20, 30, 40, 50, 60A su 4K/5K).
   - `ritorno_rete_v`: Programma 12 (`PBCVxx.x`, 44.0V..51.0V, default fabbrica 46.0V).
   - `ritorno_batteria_v`: Programma 13 (`PBDVxx.x`, 48.0V..58.0V o FUL, default fabbrica 54.0V).
   - `cutoff_v`: Programma 29 (`PSDVxx.x`, 40.0V..48.0V, default fabbrica 42.0V).
3. **Limiti Regolatore di Carica MPPT (4K/5K 48V)**:
   - Tensione massima a vuoto (Voc): 145 Vdc.
   - Range operativo MPPT: 60 ~ 115 Vdc.
   - Con la lettura tipica di ~103 Vdc rilevata sul campo, la stringa opera al centro
     della finestra MPPT con margine di sicurezza rispetto al limite distruttivo dei 145 V.

## Questioni aperte

- **Numero e modello dei pannelli**: servono le etichette fisiche (Wp, Vmp, Voc, Isc) e quante
  stringhe. La tensione operativa di ~103 Vdc è pienamente compatibile con la finestra MPPT (60-115 V)
  e ben sotto il limite assoluto di 145 Voc.
- **Soglie batteria in esercizio**: le impostazioni correnti (cutoff 42 V, ritorno rete 45 V)
  rispecchiano i default di fabbrica del manuale per AGM 48V. Valutare se alzare il ritorno rete
  a 46-47 V per allungare la vita ciclica delle batterie AGM.

## Mix del consumo e ore di luce (2026-11-13)

- Il mix attribuisce il **carico**, non il bilancio: FV diretto `min(pv_w, out_w)` fuori
  bypass, batteria `max(0, out_w - pv_w)` fuori bypass, rete tutto `out_w` quando
  `mode='L'`. Le ricariche restano fuori, così le tre voci chiudono sempre sul consumo.
- In bypass l'inverter passa l'ingresso AC al carico: attribuire tutto alla rete è la
  lettura prudente, anche se il FV sta caricando la batteria.
- `SOLAR_PLACE` risolve il **capoluogo** di provincia, non il comune: errore < ~10 km,
  irrilevante per alba/tramonto (1° di longitudine ≈ 4 minuti).

## Notifiche essenziali (2026-11-14)

- Le notifiche Telegram sono eventi, non stati: passaggio rete/batteria, guasti
  raggruppati, inverter muto. Niente avvio, cambi di modalità generici, modifiche
  di configurazione o ripetizioni orarie.
- La soglia `BATT_LOW_V` è stata rimossa: sotto carico la tensione scende e
  produceva falsi "batteria bassa" con messaggi ripetuti. L'evento utile è il
  passaggio effettivo alla rete, confermato da 3 letture consecutive.
- Gli allarmi `QPIWS` sono raggruppati in un solo messaggio per cambio di insieme,
  con guasti e avvisi separati; nessuna ripetizione mentre persistono.
- Il refresh periodico di `QPIRI` resta perché alimenta la dashboard; sparisce solo
  la notifica delle modifiche di configurazione.
