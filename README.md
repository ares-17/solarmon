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

- `solarmon.py` + `index.html`: versione **v1** funzionante (letta e collaudata sul campo).
  Non include ancora file env, `/api/raw` e comandi Telegram.
- La **v2** (env, ring buffer, `/api/raw`, bot Telegram con whitelist e audit) è descritta
  in `docs/chat-solarmon-2026-11-13.md` e va importata/sovrascritta prima della Milestone 1.

## Struttura prevista

```
solarmon/
├── solarmon.py            # processo unico: lettura, storage, HTTP, alert
├── index.html             # dashboard statica (nessuna build)
├── solarmon.env.example   # modello di configurazione, senza segreti
├── setup.sh               # installazione idempotente su Raspberry Pi OS
├── deploy/
│   ├── solarmon.service   # unit systemd con hardening
│   ├── 99-inverter.rules  # udev: nome stabile /dev/inverter
│   └── backup.sh          # backup SQLite + config
├── tests/                 # pytest con fixture reali redatte
└── docs/
    ├── DECISIONS.md       # scelte tecniche e motivazioni
    ├── RUNBOOK.md         # installazione, restore, rotazione token
    └── chat-solarmon-2026-11-13.md  # archivio della chat di progetto
```

## Sicurezza

Principi applicati (dettaglio in `docs/DECISIONS.md`):

- **Nessuna scrittura via HTTP**: il server espone solo rotte GET di lettura.
- **Bind su loopback** per default (`BIND_ADDR=127.0.0.1`); l'accesso da telefono passa da Tailscale.
- **Token** su `/api/raw`, endpoint pensato per incollare i dati a un'AI.
- **Telegram**: risponde solo all'utente `TG_ADMIN_ID` in chat privata; scritture disattivate
  salvo `ALLOW_WRITE=1`; whitelist di parametri, doppia conferma con codice monouso, audit su SQLite.
- **Segreti fuori dal repo**: `.env`, database, backup e dump sono in `.gitignore`.
- **systemd sandbox**: utente dedicato, `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome`, `PrivateTmp`, `CapabilityBoundingSet=` vuoto, `RestrictAddressFamilies`.
- **udev**: `/dev/inverter` con gruppo dedicato e permessi `0660` (non `0666`).

## Manutenzione

- **Auto-restart**: unit systemd con `Restart=always` e `RestartSec=5`.
- **Dati su disco**: SQLite in WAL, un campione ogni 60 s; le letture fini restano in RAM.
- **SD card**: log su RAM (`log2ram`), database su supporto esterno consigliato, backup giornaliero.
- **Ripristino**: immagine "golden" della SD + `setup.sh` idempotente + backup del database.

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
