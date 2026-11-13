# Runbook operativo

Procedure per installare, verificare, aggiornare e ripristinare solarmon sulla Raspberry Pi.
I percorsi indicati (`/opt/solarmon`, `/var/lib/solarmon`, `/etc/solarmon.env`) sono quelli
di riferimento: `setup.sh` è la fonte di verità e li imposta in modo idempotente.

## 1. Installazione da zero

```bash
# sulla Pi, Raspberry Pi OS Lite 64-bit, utente con sudo
git clone <repo> solarmon && cd solarmon
sudo bash setup.sh
sudoedit /etc/solarmon.env        # TG_TOKEN, TG_CHAT, TG_ADMIN_ID, BIND_ADDR
sudo systemctl restart solarmon
```

Verifiche:

```bash
ls -l /dev/inverter                       # symlink presente
systemctl status solarmon                 # active (running)
journalctl -u solarmon -n 50 --no-pager
curl -s http://127.0.0.1:8000/api/now     # JSON con ts recente
```

Se `/dev/inverter` manca: cavo USB, `lsusb` (deve comparire `0665:5161`), poi
`sudo udevadm control --reload && sudo udevadm trigger`.

## 2. Operazioni quotidiane

| Cosa | Comando |
|---|---|
| Stato servizio | `systemctl status solarmon` |
| Log in tempo reale | `journalctl -u solarmon -f` |
| Ultimi errori | `journalctl -u solarmon -p err -n 100` |
| Riavvio | `sudo systemctl restart solarmon` |
| Stato API | `curl -s localhost:8000/api/now | jq` |
| Dati grezzi per AI | `curl -s "localhost:8000/api/raw?seconds=3600&step=30&compact=1"` |

Il servizio ha `Restart=always`: un crash viene recuperato in circa 5 secondi. Un riavvio
continuo (visibile in `systemctl status` come "start-limit-hit") indica un problema
persistente: leggere i log, non aumentare i tentativi.

## 3. Backup

Il timer giornaliero esegue `sqlite3 .backup` (copia consistente anche con WAL attivo) e
conserva gli ultimi 14 file. I segreti di `/etc/solarmon.env` non vengono copiati: restano
nel gestore di password.

```bash
systemctl list-timers solarmon-backup.timer
ls -lh /var/lib/solarmon/backups/
```

Ripristino del database:

```bash
sudo systemctl stop solarmon
sudo cp /var/lib/solarmon/backups/solar-YYYYMMDD.db /var/lib/solarmon/solar.db
sudo rm -f /var/lib/solarmon/solar.db-wal /var/lib/solarmon/solar.db-shm
sudo systemctl start solarmon
```

Copia fuori dalla Pi (consigliata, via Tailscale):

```bash
rsync -av pi:/var/lib/solarmon/backups/ ~/backup-solarmon/
```

## 4. Rotazione dei segreti

**Token Telegram** (sospetto leak o cambio bot):

1. @BotFather → `/revoke` → nuovo token.
2. `sudoedit /etc/solarmon.env` → aggiornare `TG_TOKEN`.
3. `sudo systemctl restart solarmon`.
4. Verificare che il messaggio di avvio arrivi su Telegram.

**RAW_TOKEN**:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Aggiornare `/etc/solarmon.env`, riavviare, aggiornare il segnalibro sul telefono.

**Verifica che i segreti non siano nel repo:**

```bash
git ls-files | grep -E '(^|/)\.env$|solarmon\.env$|\.db$|dump' && echo "PRESENTI: rimuovere" || echo "OK"
```

## 5. Aggiornamento

```bash
cd /opt/solarmon
sudo git pull --ff-only
sudo systemctl restart solarmon
curl -s localhost:8000/api/now | jq .ts
```

Se l'aggiornamento tocca lo schema SQLite, il servizio deve applicare la migrazione
all'avvio; in caso contrario fermarsi e ripristinare il backup precedente.

## 6. Ripristino della SD

1. Flash di Raspberry Pi OS Lite con Imager, hostname/utente/SSH/WiFi nelle impostazioni avanzate.
2. `git clone` del repo e `sudo bash setup.sh`.
3. Ripristino del database dal backup più recente (sezione 3).
4. `sudoedit /etc/solarmon.env` con i segreti (recuperati dal gestore password, non dal repo).
5. Verifica `/api/now` e una notifica Telegram di prova.

In alternativa, se esiste un'immagine "golden" della SD: flash dell'immagine, poi solo
aggiornamento del repo e ripristino del database. Tenere una SD di scorta già clonata.

## 7. Diagnostica

| Sintomo | Controlli |
|---|---|
| `Inverter non risponde` | `pgrep -af solarmon` (un solo processo), `ls -l /dev/inverter`, cavo, `dmesg | tail` |
| Timeout intermittenti | nessun altro processo sull'hidraw, `cycle_s` in `/api/now` sotto 2 s |
| `NAK` | comando non supportato dal modello: non insistere, annotare quale |
| Dashboard irraggiungibile | `ss -ltnp | grep 8000`, `BIND_ADDR`, Tailscale `tailscale status` |
| Errori Telegram | token valido, `TG_ADMIN_ID` corretto, 2FA attivo; mai incollare l'URL con il token |
| Pi sparita | Beszel sull'hub esterno, alimentazione, SD |

Lettura manuale (solo con servizio fermo, un solo processo alla volta):

```bash
sudo systemctl stop solarmon
INVERTER_DEV=/dev/inverter python3 solarmon.py probe
sudo systemctl start solarmon
```

## 8. Cosa non fare

- Non lanciare `mpp-solar` o un secondo `solarmon.py` mentre il servizio è attivo.
- Non abilitare `ALLOW_WRITE=1` senza aver verificato i comandi sul modello.
- Non esporre la porta 8000 sul router: usare Tailscale.
- Non committare `/etc/solarmon.env`, database, backup o dump dell'inverter.
