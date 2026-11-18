# solarmon

Monitoraggio di un impianto solare off-grid con inverter Voltronic/Axpert (protocollo PI30) su Raspberry Pi 3B.

Un solo processo Python, senza dipendenze obbligatorie oltre la libreria standard:

```
inverter ──USB(hidraw)──> solarmon.py ──┬──> SQLite (storico)
                                        ├──> dashboard HTTP (telefono/PC)
                                        ├──> alert Telegram
                                        └──> MQTT (opzionale, spento di default)
```

L'app è l'unico processo che parla con l'inverter: nessun altro programma deve aprire
`/dev/inverter` mentre è attiva, altrimenti le letture si sovrappongono e vanno in timeout.

## Hardware di riferimento

| Componente | Dettaglio |
|---|---|
| Host | Raspberry Pi 3B, Raspberry Pi OS Lite 64-bit |
| Inverter | Voltronic/Axpert 5 kVA / 5 kW, 48 V, off-grid MPPT, firmware `00072.10` |
| Protocollo | PI30 su USB nativa (VID:PID `0665:5161`), device stabile `/dev/inverter` |
| Batterie | 4 × 12 V 100 Ah AGM in serie (48 V, ~4,8 kWh nominali) |
| Accesso remoto | Tailscale (nessuna porta aperta sul router) |
| Monitoraggio host | agente Beszel su hub esterno (rileva la Pi morta) |

## Stato del repository

- `solarmon.py`: **v2** (letta sul campo, integrata il 13/11) con file env, ring buffer,
  `/api/raw`, bot Telegram con whitelist e audit. L'hardening S1–S10 di `docs/SECURITY.md`
  è stato riapplicato sopra la v2 ed è coperto dai test.
- `setup.sh` e `deploy/`: unit systemd con hardening e auto-restart, regola udev `0660`,
  backup giornaliero con retention. Il servizio parte anche senza token Telegram.
- `index.html`: dashboard statica, compatibile con le risposte v2.

## Struttura

```
solarmon/
├── solarmon.py             # processo unico: lettura, storage, HTTP, alert
├── index.html              # dashboard statica (nessuna build)
├── solarmon.env.example    # modello di configurazione, senza segreti
├── setup.sh                # installazione idempotente nativa su Raspberry Pi OS
├── Dockerfile              # immagine container minimale (python:3.12-slim)
├── docker-compose.yml      # orchestrazione per deploy containerizzato
├── docker-entrypoint.sh    # gestione permessi hardware e user solarmon
├── deploy/
│   ├── solarmon.service    # unit systemd con hardening e Restart=always
│   ├── solarmon-backup.service / .timer
│   ├── 99-inverter.rules   # udev: /dev/inverter, gruppo inverter, 0660
│   └── backup.sh           # backup SQLite con retention
├── scripts/
│   └── build_manual_md.py  # rigenera docs/PIP-MS_1-5KVA_manual.md
├── tests/                  # pytest con fixture reali redatte
└── docs/
    ├── PIP-MS_1-5KVA_manual.md # manuale utente ufficiale convertito (PF1 1K-5K)
    ├── DECISIONS.md       # scelte tecniche e motivazioni
    ├── RUNBOOK.md         # installazione, restore, rotazione token
    └── chat-solarmon-2026-11-13.md  # archivio della chat di progetto
```

## Report e simulazioni

Modulo offline per analizzare uno snapshot del database e simulare scenari di accumulo LiFePO4 compatibili con l'inverter, senza toccare il monitoraggio attivo.

```bash
# Esecuzione report con coordinate impianto (default Cellole CE: 41.201880, 13.849262)
python3 -m analysis.report --db solar-snapshot.db --config now.json --bill consumu_annuali.csv --out reports/
```

Il comando genera nella cartella `reports/YYYY-MM-DD_HHMM/`:
- `report.html`: report autonomo stampabile in PDF con grafici SVG vettoriali.
- `report.md`: riepilogo sintetico in formato Markdown.
- `data.json`: tutti i dati e le metriche calcolate in formato JSON.

## Deploy con Docker

In alternativa all'installazione nativa systemd con `setup.sh`, è possibile avviare l'applicazione in container:

1. **Configurazione ambiente**:
   ```bash
   cp solarmon.env.example solarmon.env
   chmod 600 solarmon.env
   # Compila solarmon.env con TG_TOKEN, TG_CHAT, TG_ADMIN_ID ed eventuale RAW_TOKEN
   ```

2. **Prerequisito hardware (regola udev sull'host)**:
   Per garantire che il device `/dev/inverter` esista e sia accessibile:
   ```bash
   sudo cp deploy/99-inverter.rules /etc/udev/rules.d/
   sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw
   ```

3. **Avvio con Docker Compose**:
   ```bash
   docker compose up -d
   ```
   * Il container viene eseguito come utente di sistema dedicato `solarmon`.
   * Il database SQLite persistente risiede nella cartella `./data/` sull'host.
   * La dashboard risponde su `http://<IP_HOST>:8000`.
   * Il compose imposta DNS espliciti (`1.1.1.1`, `8.8.8.8`): la Pi usa `systemd-resolved`
     (stub su `127.0.0.53`), che Docker non può usare come upstream e senza il quale il
     container resta senza DNS (Telegram va in `URLError`, `gaierror -3`). Se la rete blocca
     i DNS pubblici, sostituiscili con l'IP del router o di Pi-hole.

4. **Verifica stato e log**:
   ```bash
   docker compose logs -f
   curl -s localhost:8000/api/now | jq
   ```

## Sicurezza

Principi applicati (dettaglio in `docs/DECISIONS.md`):

- **Nessuna scrittura via HTTP**: il server espone solo rotte GET di lettura.
- **Bind su loopback** per default (`BIND_ADDR=127.0.0.1`); l'accesso da telefono passa da Tailscale.
- **Token** su `/api/raw`: con `BIND_ADDR` non loopback e `RAW_TOKEN` vuoto la rotta risponde 403.
- **Telegram**: risponde solo all'utente `TG_ADMIN_ID` in chat privata; scritture disattivate
  salvo `ALLOW_WRITE=1`; whitelist di parametri, doppia conferma con codice monouso, audit su SQLite.
- **Segreti fuori dal repo**: `.env`, database, backup e dump sono in `.gitignore`.
- **systemd sandbox**: utente dedicato, `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome`, `PrivateTmp`, `CapabilityBoundingSet=` vuoto, `RestrictAddressFamilies`.
- **udev**: `/dev/inverter` con gruppo dedicato e permessi `0660` (non `0666`).

## Manutenzione

- **Auto-restart**: unit systemd con `Restart=always` e `RestartSec=5`.
- **Dati su disco**: SQLite in WAL, un campione ogni 60 s; le letture fini restano in RAM
  e alimentano i kWh, integrati sul tempo reale a ogni lettura (non su `STORE_INTERVAL`).
- **SD card**: log su RAM (`log2ram`), database su supporto esterno consigliato, backup giornaliero.
- **Ripristino**: immagine "golden" della SD + `setup.sh` idempotente + backup del database.
- **Stima dei costi**: imposta `GRID_PRICE_EUR_KWH` in €/kWh (accetta "0,25" o "0.25"); la stima compare solo nella vista a 30 giorni e copre i soli prelievi di rete.

## Sviluppo e collaudo

Sul PC collegato all'inverter (con l'app ferma):

```bash
# verifica canale e parsing: stampa le risposte grezze
INVERTER_DEV=/dev/hidraw1 python3 solarmon.py probe
```

Sulla Pi, dopo il setup:

```bash
systemctl status solarmon
journalctl -u solarmon -f
curl -s localhost:8000/api/now | jq
```

## Note

- L'errore `58` del display corrisponde a "tensione di uscita troppo bassa"; la mappatura
  dei bit di `QPIWS` va confermata con un allarme reale.
- I pannelli non sono deducibili dai dati attuali: servono le etichette (Wp, Voc, Isc) e il
  numero di pannelli per stringa.
- Le soglie batteria attuali (`cutoff 42 V`, ritorno rete `45 V`) sono basse per batterie AGM
  da standby: da rivalutare dopo qualche giorno di storico.
