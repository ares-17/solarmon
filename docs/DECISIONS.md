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

## Questioni aperte

- **Numero e modello dei pannelli**: servono le etichette (Wp, Vmp, Voc, Isc) e quante
  stringhe. Ipotesi compatibile con 104 V: 6 pannelli in serie da ~17 V.
- **Errore 58**: la corrispondenza con `inverter_voltage_too_low_fault` di `QPIWS` va
  verificata su un allarme reale.
- **Comandi di scrittura**: formati (`MCHGC020`, `PBCV46.0`, …) presi dalla specifica PI30,
  non ancora provati sul modello. Primo test consigliato: `/set corrente_carica 20` (valore
  già impostato).
- **Soglie batteria**: `cutoff 42 V` e ritorno rete `45 V` sono bassi per AGM da standby;
  decidere dopo qualche giorno di storico e con il datasheet della 12FIT100/19.
