# Chat Claude — solarmon (archivio)

- Fonte: https://claude.ai/share/7b0085cb-8130-4a3b-871d-60d7a8d974bb

- Archiviata: 2026-11-13

- Nota: i file allegati alla chat erano nascosti nella condivisione (`viewer_can_access_files=false`). Il contenuto dei file non è recuperabile da qui.


---


## Utente

ho una raspberry pi3b e un impianto a pannelli solari vecchio e da capire, non connesso alla rete. Ha un inverter mptt solar prima del 2020 e avevo usato un docker container per comunicare con home assistant collegandolo un pc che aveva il docker container direttamente via cavo all'inverter, ma questo metodo era fragile e voglio semplificarmi la vita.
Voglio semplicemente monitorare, cercare di capire eventuali errori che escono nel display dell'inverter (come stamattina che è uscito l'errore 58) e esser aiutato il più possibile per diagnosticare i problemi e capire l'andamento, l'efficienza e anzi, io non so neanche che pannelli sono montanti e quanti ne sono


## Claude

# Piano semplificato: Raspberry Pi 3B collegata direttamente all'inverter

Il pezzo fragile era il PC in mezzo. La Pi 3B ha già WiFi e USB, quindi può fare da ponte da sola, 24/7, a basso consumo.

## 1. Prima cosa: che inverter è?
Dalla descrizione ("MPPT solar", prima del 2020) potrebbe essere della famiglia **Voltronic / Axpert / MPP Solar / Voltacon / Effekta** (ne esistono decine di rebrand identici). Guarda l'etichetta sul fianco e dimmi marca e modello. Da questo dipende tutto il resto.

## 2. Cosa significa l'errore 58
Sugli Axpert/MPP Solar il **fault 58 = "Output voltage too low"** (tensione di uscita troppo bassa). Cause tipiche:
- sovraccarico o picco di assorbimento (motori, compressori, pompe all'avvio);
- tensione batteria troppo bassa o batterie degradate che crollano sotto carico;
- connessioni batteria allentate o ossidate, cavi sottodimensionati;
- raramente, guasto interno dell'inverter.

Se il modello è diverso la tabella dei codici può cambiare, quindi conferma con il manuale. Se mi dici cosa era acceso quando è comparso e che tensione aveva la batteria, restringiamo molto.

## 3. Come collegarlo (senza PC e senza Docker fragile)
- **Cavo**: molti di questi inverter hanno una porta **USB** (si presenta come `/dev/hidraw0`) o una **RS232/RJ45** (serve un adattatore USB-seriale). Un cavo USB-A/USB-B dalla Pi all'inverter basta spesso.
- **Software**: il progetto open source **mpp-solar** (python, GitHub `jblance/mpp-solar`) legge l'inverter e pubblica tutto su **MQTT**, con auto-discovery per Home Assistant. Gira come servizio systemd, più robusto di un container su un PC. Oppure **SolarAssistant** (a pagamento, molto curato, gira su Pi) se vuoi qualcosa di pronto.
- **Home Assistant**: con un broker MQTT (Mosquitto) i sensori compaiono da soli.

Comandi utili che il protocollo permette di interrogare:
- `QPIGS`: dati in tempo reale (tensione/corrente/potenza PV, batteria, carico, temperatura)
- `QPIRI`: configurazione nominale (tensione batteria, correnti, modalità)
- `QPIWS`: warning e fault attivi, quindi il tuo "errore 58" può diventare una notifica su Home Assistant
- `QMOD`: modalità (rete, batteria, standby, guasto)

## 4. Capire che pannelli hai (e quanti)
L'inverter non conosce il modello dei pannelli, ma ti dà indizi:
- **Fisicamente**: conta i pannelli e leggi l'etichetta sul retro o sul bordo (Wp, Voc, Isc). È la fonte più affidabile.
- **Elettricamente**: con sole forte, la tensione PV letta da `QPIGS` ti dice quanti pannelli sono **in serie** (Voc totale ≈ n × Voc singolo). La corrente e la potenza ti dicono il resto.
- Una volta noti i Wp totali, posso aiutarti a calcolare l'**efficienza reale** (potenza prodotta vs attesa, tenendo conto di temperatura, orientamento e sporco) e a notare se qualche stringa o pannello rende meno.

## 5. Cosa puoi monitorare in Home Assistant
Produzione PV (W e kWh), tensione e stato di carica della batteria, consumo del carico, temperatura inverter, modalità, fault e warning con notifica, e grafici giornalieri per vedere il degrado nel tempo.

Per procedere, ho bisogno di due cose: **marca e modello esatto dell'inverter** e **che porte di comunicazione ha** (USB, RS232, RJ45, WiFi). Con quelle ti scrivo i passi precisi di installazione.


## Utente

al momento non ho home assistant, voglio predispormi per home assistant ma sapere in maniera molto facilitata tramite smartphone come va e anche notificato in caso di errore o warning. Se si potesse anche modificare le impsotazioni dell'inverter ancora meglio.
Semplifichiamo il flusso, sono esperto di informatica e aiutami a capire, sono disposto a metter su un docker compose con diversi docker container se serve, come per gestire le notifiche push sullo smartphone oppure smeplicemente script direttamente su linux. vedi tu


## Claude

# Architettura consigliata

Tutto gira sulla Pi 3B, collegata all'inverter con un cavo USB (o RS232 con adattatore). La Pi 3B ha 1 GB di RAM, quindi conviene tenere lo stack leggero.

```
Inverter ──USB──> mpp-solar (daemon) ──> Mosquitto (MQTT) ──┬──> Home Assistant (futuro, auto-discovery)
                                                            ├──> Telegraf ──> VictoriaMetrics/Influx ──> Grafana (storico, smartphone)
                                                            └──> script/Node-RED alert ──> ntfy / Telegram (push)
Smartphone ──Tailscale──> Grafana, ntfy, comandi MQTT
```

Il broker MQTT è il punto centrale. Quando installerai Home Assistant ti basterà puntarlo allo stesso broker e i sensori compariranno da soli, senza rifare nulla.

## Scelte per i 3 requisiti

**1. Vedere come va dallo smartphone**
- **Grafana** (con VictoriaMetrics o InfluxDB per lo storico): dashboard responsive, ottime per capire andamento ed efficienza nel tempo. Su 1 GB di RAM VictoriaMetrics pesa molto meno di Influx.
- Per l'accesso da fuori casa usa **Tailscale** sulla Pi e sul telefono: niente porte aperte sul router, non serve nemmeno un IP pubblico. Per un impianto isolato dalla rete di casa è la soluzione più pulita (la Pi deve comunque avere WiFi o 4G).

**2. Notifiche push per errori e warning**
- **ntfy** (self-hosted, un container da pochi MB): invii una notifica con un semplice `curl`. App su Android e iOS. Su iOS, per avere la notifica istantanea, devi configurare `upstream-base-url: https://ntfy.sh`, perché Apple obbliga a passare da APNs.
- **Alternativa più semplice**: un bot **Telegram**. Zero self-hosting, funziona subito su qualsiasi telefono, e ti permette anche di mandare comandi al bot (utile per il punto 3).

**3. Modificare le impostazioni**
`mpp-solar` supporta i comandi di scrittura del protocollo (PI30 per gli Axpert), ad esempio:
- `POP00/01/02`: priorità sorgente di uscita (rete/solare/batteria)
- `PCP0x`: priorità di ricarica
- `PBT`: tipo batteria
- `PCVV`, `PBCV`, `PBDV`: tensioni di carica e soglie
- `MCHGC`, `MUCHGC`: correnti massime di carica

In modalità daemon puoi pubblicare il comando su un topic MQTT di comando. Da smartphone puoi usare l'app MQTT Dash, un bottone in Home Assistant più avanti, oppure comandi Telegram. Sconsiglio di esporre le scritture senza protezione: sbagliare tensioni di carica può danneggiare le batterie. Ti consiglio una whitelist di comandi permessi e di leggere sempre prima `QPIRI` per salvarti le impostazioni attuali.

## Docker Compose di partenza

```yaml
services:
  mosquitto:
    image: eclipse-mosquitto:2
    restart: unless-stopped
    ports: ["1883:1883"]
    volumes:
      - ./mosquitto/config:/mosquitto/config
      - ./mosquitto/data:/mosquitto/data

  mppsolar:
    image: <immagine mpp-solar o tua build>   # vedi nota sotto
    restart: unless-stopped
    devices:
      - /dev/hidraw0:/dev/hidraw0              # oppure /dev/ttyUSB0
    volumes:
      - ./mppsolar/mpp-solar.conf:/etc/mpp-solar/mpp-solar.conf
    depends_on: [mosquitto]

  ntfy:
    image: binwiederhier/ntfy
    command: serve
    restart: unless-stopped
    ports: ["8080:80"]
    volumes:
      - ./ntfy:/var/lib/ntfy

  alerter:
    image: python:3.12-alpine
    restart: unless-stopped
    volumes: ["./alerter:/app"]
    command: sh -c "pip install paho-mqtt requests && python /app/alert.py"
    depends_on: [mosquitto, ntfy]

  # opzionali, aggiungili dopo che la base funziona:
  # victoriametrics, telegraf, grafana
```

Sulla Pi usa l'immagine `eclipse-mosquitto` e immagini multi-arch ARM. Per `mpp-solar` è spesso più affidabile fare una build semplice (`pip install mppsolar` in un `python:3.12-slim`) che affidarsi a un'immagine di terzi. Controlla la documentazione del progetto per il formato attuale del file di configurazione, che è cambiato tra le versioni.

## Logica di allarme (alert.py)

Lo script si iscrive ai topic MQTT e invia una notifica quando:
- compare un **fault** (es. 58), con la descrizione leggibile tradotta dalla tabella codici;
- compaiono **warning** (da `QPIWS`);
- la **tensione batteria** scende sotto una soglia;
- l'inverter **non risponde** da N minuti (utile per rilevare quando il cavo o il servizio muoiono);
- cambia la **modalità** (rete → batteria, ecc.).

Aggiungi un'anti-spam (una notifica per evento, ripetuta al massimo ogni X minuti), altrimenti un fault persistente ti riempie il telefono.

## Ordine di lavoro che consiglio

1. Collegare la Pi all'inverter e verificare la lettura a mano: `mpp-solar -p /dev/hidraw0 -P PI30 -c QPIGS`. Se risponde, il resto è solo plumbing.
2. Compose con Mosquitto e mpp-solar, e controllare i dati con `mosquitto_sub -t '#' -v`.
3. ntfy (o bot Telegram) e lo script di alert.
4. Tailscale.
5. Grafana e storico, per l'efficienza e per capire quanti pannelli hai (il Voc in `QPIGS` a sole pieno).
6. Comandi di scrittura, per ultimi.

## Domande per proseguire

Mi servono tre cose: marca e modello esatto dell'inverter, che porta hai usato prima (USB o seriale) e se l'inverter risponde al protocollo PI30. Dal tuo vecchio setup Docker dovresti ricordare anche quale comando o immagine usavi. Inoltre: preferisci ntfy o Telegram per le notifiche? Con queste risposte ti preparo i file di configurazione completi, compreso `alert.py` con la tabella dei codici fault.


## Utente

ricordati però che devo far girare tutto su un raspberry pi 3b, non penso che tuttto questo giri con facilità o no?


## Claude

Sì, gira, ma con qualche scelta mirata. La Pi 3B ha 1 GB di RAM e una CPU lenta, e i veri problemi sono due: **Grafana è pesante** e **la SD card si consuma** con le scritture continue. Il resto è leggerissimo.

## Consumo di RAM indicativo

| Componente | RAM circa |
|---|---|
| Mosquitto | 5-10 MB |
| mpp-solar (Python) | 30-50 MB |
| Script alert (Python) | 20-30 MB |
| ntfy | 20-30 MB |
| Tailscale | 30-50 MB |
| VictoriaMetrics | 50-100 MB |
| Telegraf | 30-50 MB |
| **Grafana** | **150-250 MB, avvio lento, dashboard pesanti** |
| Docker daemon | 50-80 MB |

Tutto insieme ci starebbe (~500-600 MB), ma senza margine e con Grafana che rende l'interfaccia lenta. Meglio snellire.

## Versione consigliata per la Pi 3B

1. **Mosquitto + mpp-solar + alert come servizi systemd, senza Docker.** Il Docker daemon e il layer di rete costano RAM e aggiungono un punto di fragilità. Per tre processi semplici `apt install mosquitto`, `pip install mppsolar` in un venv e due unit systemd sono più robusti e partono più in fretta.
2. **Notifiche con un bot Telegram** (o ntfy, che resta leggerissimo). Con Telegram non c'è nessun container da gestire e puoi anche mandare comandi al bot per leggere lo stato o cambiare impostazioni.
3. **Niente Grafana sulla Pi, almeno all'inizio.** Per lo storico usa solo **VictoriaMetrics** (un binario singolo, ~50-100 MB), che ha una UI web integrata (vmui) usabile da smartphone per grafici semplici. Mosquitto e VictoriaMetrics possono essere collegati con un piccolo script Python, senza Telegraf.
4. **Grafana o Home Assistant su un'altra macchina**, quando e se vorrai. Entrambi possono puntare al broker MQTT della Pi via Tailscale o rete locale. **Home Assistant sulla stessa Pi 3B non lo consiglio**: ci gira, ma stretto, con la SD sotto stress.

## Protezione della SD card

- usa una SD **high endurance** (o meglio una chiavetta/SSD USB per `/var/lib`);
- installa **log2ram** per tenere i log in RAM;
- fai scrivere a VictoriaMetrics solo a intervalli di 15-30 secondi, per un inverter non serve di più;
- imposta una retention ragionevole (es. 1-2 anni, i dati sono pochissimi).

## Architettura finale

```
Inverter ─USB─> mpp-solar (systemd) ─> Mosquitto ─┬─> alert.py ─> Telegram (push + comandi)
                                                  ├─> VictoriaMetrics (storico, vmui da telefono)
                                                  └─> Home Assistant (futuro, altrove)
Smartphone ─Tailscale─> vmui / MQTT
```

Quattro servizi, ~150-200 MB di RAM totali, tutto tranquillo su una Pi 3B.

## Nota di correzione

Nel compose che ti avevo dato, `alerter` faceva `pip install` a ogni avvio: è uno spreco e fallisce se la rete non c'è. Con systemd e un venv questo problema sparisce.

Se ti va bene questa versione lean, dimmi marca/modello dell'inverter e che porta usi, e ti preparo le unit systemd, la config di mpp-solar e `alert.py` con Telegram e la tabella dei codici fault.


## Utente

Allora ti chiedo: la dashboard la puoi fare tu molto leggera e che mi monitora i dati da web? oppure se esiste una soluzione leggera? poi ti chiedo se ha senso considerare podman per risparmiare memoria o passare direttamente allo scripting. e' vero che voglio far veloce, almeno però voglio poter ripristinare lo stato della raspberry nel caso in cui avessi problemi


## Claude

# Dashboard, Podman e ripristino

## 1. Dashboard leggera: sì, e secondo me è la scelta migliore

Posso scriverla io. Una dashboard su misura è più leggera di qualsiasi prodotto pronto:

- **Backend**: un solo processo Python che si iscrive a MQTT, tiene l'ultimo valore di ogni misura e scrive campioni ogni 30 s in **SQLite** (pochi MB all'anno per un inverter). Serve le pagine con la libreria standard o `aiohttp`.
- **Frontend**: una pagina HTML statica con **uPlot** (~40 KB, grafici velocissimi anche su telefono), senza framework e senza build. Mostra stato attuale (PV, batteria, carico, modalità, fault), grafici di giornata, settimana e mese, e una vista produzione giornaliera in kWh.
- **Costo**: circa 20-40 MB di RAM, avvio istantaneo. Con SQLite puoi anche **eliminare VictoriaMetrics**, e lo stack si riduce a Mosquitto + mpp-solar + un'app unica che fa dashboard, storico e alert Telegram.
- **Accesso**: da telefono via Tailscale, con la pagina salvabile come icona sulla home.

Le alternative pronte sono più pesanti o meno adatte:
- **vmui** (di VictoriaMetrics) è leggero ma generico: grafici di query, non una dashboard "come va l'impianto".
- **Node-RED Dashboard** e **Grafana** consumano 150-250 MB e sono lenti su Pi 3B.
- **Home Assistant** resta il passo futuro, e funzionerà comunque, perché Mosquitto rimane lo stesso.

Il limite: non posso testarlo sul tuo hardware. Prima di scrivere la parte che legge i dati devo vedere l'output reale di `mpp-solar ... -c QPIGS` e i nomi dei topic MQTT che pubblica la tua versione. Con quelli la dashboard funziona al primo colpo, senza adattamenti a tentoni.

## 2. Podman o scripting?

**Direttamente systemd + venv.** Podman è daemonless e risparmia i ~50-80 MB di dockerd, ma ogni container ha comunque il suo overhead (rete, storage overlay, scritture su SD) e aggiunge complessità per accesso a `/dev/hidraw0`, permessi e avvio al boot. Qui i servizi sono 3 e tutti semplici, quindi il container non porta nulla. La riproducibilità che cerchi con i container la ottieni meglio con i punti sotto.

## 3. Ripristino dello stato della Pi

Consiglio quattro livelli, dal più rapido al più completo:

1. **Immagine "golden" della SD**: appena tutto funziona, fai un'immagine completa dalla SD (`dd` o `rpi-clone` da un PC, oppure Raspberry Pi Imager/`image-backup`). In caso di SD morta, ne flasci una nuova e sei di nuovo operativo in 15 minuti. Conserva anche una **SD di scorta** già clonata.
2. **Setup scriptato e versionato**: tutta la configurazione (unit systemd, `mosquitto.conf`, config mpp-solar, app dashboard/alert) in un repo git, con uno `setup.sh` idempotente. Così ricostruisci la Pi da zero anche partendo da un'OS pulito, e hai la storia delle modifiche.
3. **Backup periodici dei dati**: un cron notturno che copia il database SQLite (usando `sqlite3 .backup`, così il file è consistente) e le config su un'altra macchina via `rsync` o `restic`, passando da Tailscale. Così non perdi lo storico dell'impianto.
4. **Resistenza alla corruzione**: la causa più frequente di Pi morte è la SD corrotta dopo un blackout. Con `raspi-config` puoi attivare il filesystem **overlay (root in sola lettura)** e tenere i dati su una partizione o chiavetta USB separata, oltre a `log2ram`. Un'alimentazione stabile (alimentatore buono, magari un piccolo UPS HAT) aiuta più di tutto.

Un'aggiunta specifica per l'inverter: salva subito l'output di `QPIRI` e dei parametri impostati in un file di testo nel repo. Se un reset o un tuo errore cambia le impostazioni, hai il riferimento per riportarle com'erano.

## Come procedo

Per scrivere app e setup mi servono ancora **marca/modello dell'inverter** e **l'output di `QPIGS`** (anche se è solo testo copiato dal terminale). Se invece vuoi partire subito, posso prepararti lo scheletro con `setup.sh`, Mosquitto, unit systemd e backup, e aggiungere dashboard e alert appena abbiamo i dati reali. Come preferisci procedere?


## Utente

mi puoi dire dei comandi che posso lanciare su un pc linux per verificare tutto quello che mi chiedi? naturalmente intendo collegare il pc linux via cavo all'inverter


## Claude

# Raccolta dati dal PC Linux

Tutti i comandi sono **solo in lettura** (query `Q...`): non scrivono nulla nell'inverter, quindi puoi lanciarli senza rischi. Non usare comandi che iniziano con `P` finché non abbiamo salvato le impostazioni.

## 1. Riconoscere il cavo e la porta

Collega il cavo, poi:

```bash
dmesg | tail -n 30
lsusb
ls -l /dev/hidraw* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

Come leggere il risultato:
- compare **`/dev/hidraw0`**: porta USB nativa dell'inverter (la più comune sugli Axpert);
- compare **`/dev/ttyUSB0`**: adattatore USB-seriale (RS232 o RJ45);
- non compare niente: cavo, porta o adattatore non riconosciuti. Incolla l'output di `dmesg`.

Per i dettagli del dispositivo:

```bash
lsusb -v 2>/dev/null | grep -E "idVendor|idProduct|iProduct|iManufacturer"
```

Un'USB nativa di solito appare come `0665:5161` (Cypress) oppure `06a2:0801`. Annotali.

## 2. Permessi

Per i test puoi usare `sudo`. Per non usarlo:

```bash
sudo usermod -aG dialout $USER     # per /dev/ttyUSB0, poi logout/login
sudo chmod 666 /dev/hidraw0        # per hidraw, temporaneo fino al riavvio
```

## 3. Installare mpp-solar in un venv

```bash
sudo apt install -y python3-venv python3-pip
python3 -m venv ~/mpp && source ~/mpp/bin/activate
pip install mppsolar
mpp-solar --help | head -n 40
mpp-solar -L          # elenca i protocolli supportati
```

La sintassi delle opzioni cambia un po' tra versioni, quindi se un flag non esiste guarda l'`--help` e incollami l'errore.

## 4. Capire il protocollo e il modello

Con porta **hidraw** (sostituisci con il tuo device):

```bash
mpp-solar -p /dev/hidraw0 -P PI30 -c QPI
mpp-solar -p /dev/hidraw0 -P PI30 -c QID
mpp-solar -p /dev/hidraw0 -P PI30 -c QVFW
```

Con porta **seriale** aggiungi la velocità, normalmente 2400:

```bash
mpp-solar -p /dev/ttyUSB0 -b 2400 -P PI30 -c QPI
```

`QPI` restituisce la versione del protocollo (`PI30` è la risposta attesa). `QID` dà il numero di serie e `QVFW` la versione firmware. Se `PI30` non risponde, prova gli altri protocolli:

```bash
for P in PI30 PI30MAX PI30REVO PI18 PI17; do
  echo "== $P =="; mpp-solar -p /dev/hidraw0 -P $P -c QPI 2>&1 | head -n 5
done
```

## 5. I dati che mi servono

```bash
mpp-solar -p /dev/hidraw0 -P PI30 -c QPIRI   # configurazione nominale
mpp-solar -p /dev/hidraw0 -P PI30 -c QPIGS   # dati in tempo reale
mpp-solar -p /dev/hidraw0 -P PI30 -c QPIWS   # warning e fault attivi
mpp-solar -p /dev/hidraw0 -P PI30 -c QMOD    # modalità di funzionamento
mpp-solar -p /dev/hidraw0 -P PI30 -c QFLAG   # flag abilitati
mpp-solar -p /dev/hidraw0 -P PI30 -c QDI     # valori di default di fabbrica
```

Per avere tutto in un file da incollarmi:

```bash
{
  date
  for C in QPI QID QVFW QPIRI QPIGS QPIWS QMOD QFLAG QDI; do
    echo "=== $C ==="; mpp-solar -p /dev/hidraw0 -P PI30 -c $C 2>&1
  done
} | tee ~/inverter_dump.txt
```

Se vuoi l'output grezzo con i byte (utile per il debug): aggiungi `-D` (debug) o `-o json`.

## 6. Capire i pannelli: registro nel tempo

La tensione PV dice quanti pannelli sono in serie, ma va letta **a sole alto con carico leggero**. Lascia girare questo per una giornata:

```bash
while true; do
  echo "$(date -Is) $(mpp-solar -p /dev/hidraw0 -P PI30 -c QPIGS -o json 2>&1 | tr -d '\n')" >> ~/qpigs_log.txt
  sleep 60
done
```

In pratica mi bastano anche solo 3-4 letture di `QPIGS` fatte a mezzogiorno in una giornata serena. In parallelo, **fotografa le etichette dei pannelli** (Wp, Voc, Isc) e conta quanti ne vedi sul tetto.

## 7. Se l'errore 58 ricompare

Lancia subito, prima di spegnere o resettare qualsiasi cosa:

```bash
mpp-solar -p /dev/hidraw0 -P PI30 -c QPIWS
mpp-solar -p /dev/hidraw0 -P PI30 -c QPIGS
mpp-solar -p /dev/hidraw0 -P PI30 -c QMOD
```

E annota cosa era acceso, l'ora e la tensione batteria sul display.

Una precisazione su quanto ti avevo scritto prima: il protocollo PI30 non sempre espone direttamente il **numero** del fault come lo vedi sul display. `QPIWS` restituisce una maschera di flag (inverter fault, bus over/under, over temperature, overload, ecc.), quindi la notifica potrebbe dire "fault attivo, output voltage low" più che "58". Lo verifichiamo con l'output reale quando l'errore è presente.

## Cosa incollarmi

1. L'etichetta dell'inverter (marca e modello) e l'esito di `lsusb`/`ls /dev/hidraw*`;
2. il file `~/inverter_dump.txt`;
3. eventuali errori o timeout comparsi, perché dicono se sbagliamo protocollo o baud rate.

Con questi dati ti preparo la configurazione definitiva per la Pi.


## Utente

output dei comandi in ordine:
[131783.493995] usb 3-1: new low-speed USB device number 3 using xhci_hcd 
[131784.095386] usb 3-1: New USB device found, idVendor=0665, idProduct=5161, bcdDevice= 0.02 
[131784.095403] usb 3-1: New USB device strings: Mfr=3, Product=1, SerialNumber=0 
[131784.125614] hid-generic 0003:0665:5161.0002: hiddev96,hidraw1: USB HID v1.11 Device [HID 0665:5161] on usb-0000:e4:00.4-1/input0 
[131825.628987] usb 1-4: reset full-speed USB device number 3 using xhci_hcd
 
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub 
Bus 001 Device 002: ID 0e8d:223c MediaTek Inc. Wireless_Device 
Bus 001 Device 003: ID 04f3:0c82 Elan Microelectronics Corp. ELAN:ARM-M4 
Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub 
Bus 003 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub 
Bus 003 Device 002: ID 05e3:0610 Genesys Logic, Inc. Hub 
Bus 003 Device 003: ID 0665:5161 Cypress Semiconductor USB to Serial 
Bus 004 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub 
Bus 005 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub 
Bus 005 Device 002: ID 30c9:00d3 Luxvisions Innotech Limited HP FHD Camera 
Bus 006 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub 
Bus 007 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub 
Bus 008 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub 
Bus 009 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
 
ls -l /dev/hidraw* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null 
zsh: no matches found: /dev/ttyUSB*
lsusb -v 2>/dev/null | grep -E "idVendor|idProduct|iProduct|iManufacturer" 
  idVendor           0x1d6b Linux Foundation 
  idProduct          0x0002 2.0 root hub 
  iManufacturer           3 Linux 6.19.13-100.fc42.x86_64 xhci-hcd 
  iProduct                2 xHCI Host Controller 
  idVendor           0x0e8d MediaTek Inc. 
  idProduct          0x223c Wireless_Device 
  iManufacturer           5 MediaTek Inc. 
  iProduct                6 Wireless_Device 
  idVendor           0x04f3 Elan Microelectronics Corp. 
  idProduct          0x0c82 ELAN:ARM-M4 
  iManufacturer           1 ELAN 
  iProduct                2 ELAN:ARM-M4 
  idVendor           0x1d6b Linux Foundation 
  idProduct          0x0003 3.0 root hub 
  iManufacturer           3 Linux 6.19.13-100.fc42.x86_64 xhci-hcd 
  iProduct                2 xHCI Host Controller 
  idVendor           0x1d6b Linux Foundation 
  idProduct          0x0002 2.0 root hub 
  iManufacturer           3 Linux 6.19.13-100.fc42.x86_64 xhci-hcd 
  iProduct                2 xHCI Host Controller 
  idVendor           0x05e3 Genesys Logic, Inc. 
  idProduct          0x0610 Hub 
  iManufacturer           0  
  iProduct                1 USB2.0 Hub 
  idVendor           0x0665 Cypress Semiconductor 
  idProduct          0x5161 USB to Serial 
  iManufacturer           3  
  iProduct                1  
  idVendor           0x1d6b Linux Foundation 
  idProduct          0x0003 3.0 root hub 
  iManufacturer           3 Linux 6.19.13-100.fc42.x86_64 xhci-hcd 
  iProduct                2 xHCI Host Controller 
  idVendor           0x1d6b Linux Foundation 
  idProduct          0x0002 2.0 root hub 
  iManufacturer           3 Linux 6.19.13-100.fc42.x86_64 xhci-hcd 
  iProduct                2 xHCI Host Controller 
  idVendor           0x30c9 Luxvisions Innotech Limited 
  idProduct          0x00d3 HP FHD Camera 
  iManufacturer           3 DTAQQ0A9IJFXFC 
  iProduct                1 HP FHD Camera 
  idVendor           0x1d6b Linux Foundation 
  idProduct          0x0002 2.0 root hub 
  iManufacturer           3 Linux 6.19.13-100.fc42.x86_64 xhci-hcd 
  iProduct                2 xHCI Host Controller 
  idVendor           0x1d6b Linux Foundation 
  idProduct          0x0003 3.0 root hub 
  iManufacturer           3 Linux 6.19.13-100.fc42.x86_64 xhci-hcd 
  iProduct                2 xHCI Host Controller 
  idVendor           0x1d6b Linux Foundation 
  idProduct          0x0002 2.0 root hub 
  iManufacturer           3 Linux 6.19.13-100.fc42.x86_64 xhci-hcd 
  iProduct                2 xHCI Host Controller 
  idVendor           0x1d6b Linux Foundation 
  idProduct          0x0003 3.0 root hub 
  iManufacturer           3 Linux 6.19.13-100.fc42.x86_64 xhci-hcd 
  iProduct                2 xHCI Host Controller 

il resto delle altre informazioni lo fornirò dopo. Come posso semplificarmi il setup sulla raspberry pi 3b? poi senza giri di parole dimmi se una istanza di beszel che ho su un altro pc nella stessa rete può esser utile


## Claude

# Semplificare il setup sulla Pi

**Il tuo cavo è a posto.** Il dispositivo `0665:5161` è l'USB nativa degli inverter Axpert/Voltronic e il kernel l'ha agganciato come **`/dev/hidraw1`**, non `hidraw0` come negli esempi che ti avevo dato. Usa `hidraw1` nei comandi sul PC, e così non c'è bisogno di `ttyUSB` né di baud rate. Il `reset full-speed USB device` su `usb 1-4` riguarda un altro dispositivo del PC (webcam o WiFi), non l'inverter.

## Come ridurre il setup al minimo

1. **Raspberry Pi OS Lite 64-bit**, flashato con Raspberry Pi Imager. Nelle impostazioni avanzate imposti hostname, utente, chiave SSH e WiFi, così al primo avvio la Pi è già raggiungibile e non serve monitor né tastiera. Il WiFi della Pi 3B è solo 2.4 GHz.
2. **Una regola udev** che dà all'inverter un nome stabile, perché `hidraw0/1` può cambiare tra un riavvio e l'altro:
   ```bash
   echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0665", ATTRS{idProduct}=="5161", SYMLINK+="inverter", MODE="0666"' | sudo tee /etc/udev/rules.d/99-inverter.rules
   sudo udevadm control --reload && sudo udevadm trigger
   ```
   Da lì in poi tutto usa `/dev/inverter`.
3. **Un solo `setup.sh` nel repo git**, che installa Mosquitto con apt, crea il venv, installa le unit systemd e attiva tutto. Poi `log2ram` e Tailscale (`curl -fsSL https://tailscale.com/install.sh | sh`).
4. **Un'unica app Python invece di tre servizi**: legge l'inverter direttamente, scrive su SQLite, serve la dashboard, manda gli alert Telegram e pubblica su MQTT con auto-discovery per Home Assistant. Mosquitto resta solo come "presa" per il futuro HA. Questa scelta ha anche un motivo tecnico: **solo un processo alla volta può parlare con l'inverter**. Con il daemon mpp-solar attivo, un comando manuale dal terminale collide con le sue letture. Con un'app sola c'è un unico proprietario della porta e anche le scritture passano da lì, con la whitelist.

Quindi il sistema finale è: Mosquitto (apt) + la mia app (una unit systemd). Due cose da gestire, tutto qui.

## Beszel: utile?

**Sì, ma solo per la salute della Pi, non per l'inverter.** Beszel non sa niente di inverter.

- Installa solo l'**agent** sulla Pi (un binario Go, circa 10-20 MB di RAM, supporta ARM) e lascia l'hub sull'altro PC.
- Ti dà temperatura CPU, RAM, uso e stato della SD, e soprattutto **un alert se la Pi smette di rispondere**. Questo ha valore reale, perché la mia app non può avvisarti se muore la Pi stessa. Se la SD si corrompe o salta la corrente, solo un osservatore esterno come Beszel se ne accorge.
- Non lo userei per dashboard o storico dell'impianto: quello lo fa la mia app.

Quindi sì, mettilo. Costa quasi niente e copre il buco dell'osservatore esterno.

## Cosa mi serve ora

Rilancia il dump con il device corretto e incollami il risultato:

```bash
{
  date
  for C in QPI QID QVFW QPIRI QPIGS QPIWS QMOD QFLAG QDI; do
    echo "=== $C ==="; mpp-solar -p /dev/hidraw1 -P PI30 -c $C 2>&1
  done
} | tee ~/inverter_dump.txt
```

Con quello e l'etichetta dell'inverter ti scrivo `setup.sh`, l'app e le unit systemd.


## Utente

ALTRI OUTPUT:
(mpp) root@fedora:/home/aress/Documenti/progetti# mpp-solar -p /dev/hidraw1 -P PI30 -c QPI
Command: QPI - Protocol ID inquiry
--------------------------------------------------------------------------------
Parameter      Value          Unit
validity_check Error: NAK     
--------------------------------------------------------------------------------


(mpp) root@fedora:/home/aress/Documenti/progetti# mpp-solar -p /dev/hidraw1 -P PI30 -c QID
Command: QID - Device Serial Number inquiry
--------------------------------------------------------------------------------
Parameter     Value          Unit
serial_number <SERIAL_REDACTED> 
--------------------------------------------------------------------------------


(mpp) root@fedora:/home/aress/Documenti/progetti# mpp-solar -p /dev/hidraw1 -P PI30 -c QVFW
Command: QVFW - Main CPU firmware version inquiry
--------------------------------------------------------------------------------
Parameter                 Value          Unit
main_cpu_firmware_version VERFW:00072.10 
--------------------------------------------------------------------------------

(mpp) root@fedora:/home/aress/Documenti/progetti# for P in PI30 PI30MAX PI30REVO PI18 PI17; do   echo "== $P =="; mpp-solar -p /dev/hidraw1 -P $P -c QPI 2>&1 | head -n 5; 
done 
== PI30 == 
Command: QPI - Protocol ID inquiry 
-------------------------------------------------------------------------------- 
Parameter   Value          Unit 
protocol_id PI30            
-------------------------------------------------------------------------------- 
== PI30MAX == 
Command: QPI - Protocol ID inquiry 
-------------------------------------------------------------------------------- 
Parameter   Value          Unit 
protocol_id PI30            
-------------------------------------------------------------------------------- 
== PI30REVO == 
Command: QPI - Protocol ID inquiry 
-------------------------------------------------------------------------------- 
Parameter   Value          Unit 
protocol_id PI30            
-------------------------------------------------------------------------------- 
== PI18 == 
2026-11-13 13:33:16,883:ERROR:device:run_command@82: Full command not found for QPI in protocol b'PI18' 
Command: Unknown command - No description found 
-------------------------------------------------------------------------------- 
Parameter Value          Unit 
error     Full command not found for QPI in protocol b'PI18' 
== PI17 == 
2026-11-13 13:33:16,999:ERROR:device:run_command@82: Full command not found for QPI in protocol b'PI17' 
Command: Unknown command - No description found 
-------------------------------------------------------------------------------- 
Parameter Value          Unit 
error     Full command not found for QPI in protocol b'PI17'
 
alcuni errori che vedi derivano dal fatto che utilizzavo prima la porta con indice 0


## Claude

Prima di scrivere il resto guardo il dump, poi preparo i file.

Dai dati risulta un inverter da 5 kVA/5 kW, 48 V, protocollo PI30, firmware 00072.10, off-grid con MPPT e batteria AGM. Ho preparato app, dashboard e setup per la Pi, ma non li ho potuti provare sul tuo inverter.

## Cosa dicono i tuoi dati

- **Pannelli:** non si possono ricavare dai dati attuali. La batteria è al 100% e in float, quindi l'MPPT produce solo quanto serve al carico (340-450 W contro 290-410 W di carico), non quanto potrebbero dare i pannelli.
- **Corrente FV:** `pv_input_current_for_battery` (8 A) non è la corrente delle stringhe. È la potenza FV divisa per la tensione di batteria. La corrente reale è circa 453 W / 104 V ≈ 4,4 A.
- **Come misurare i pannelli:** a mezzogiorno, con sole pieno, accendi per 10-15 minuti un carico grosso (≥2 kW). L'MPPT è così costretto a produrre il massimo e `pv_w` mostra la vera potenza dell'array. I 104 V sono la tensione di lavoro, non il Voc, che è più alto.
- **Etichette:** serve comunque leggere le etichette dei pannelli e contarli.
- **AC in:** `ac_input_voltage` è 233 V, quindi sull'ingresso AC c'è qualcosa (rete o generatore). Mi avevi detto che non è collegato alla rete: forse intendevi che non immette in rete. Dimmi cosa c'è collegato.
- **Modo Batteria:** con priorità SBU l'inverter alimenta il carico da solare e batteria anche con la rete presente. Qui è normale.
- **Errore 58:** sugli Axpert è "output voltage too low". In `QPIWS` dovrebbe corrispondere a `inverter_voltage_too_low_fault`, ma la mappatura dei bit non l'ho verificata. L'app salva sempre la stringa grezza di `QPIWS` nell'avviso.
- **Comunicazione:** nel tuo log un'interrogazione è andata in timeout 3 volte (13:38) e un `QPI` ha dato NAK. L'USB di questi inverter è a volte lenta, e l'app ritenta ogni comando 3 volte.
- **Impostazione da valutare:** `over_temperature_restart` è disabilitato, quindi dopo un surriscaldamento l'inverter non riparte da solo.

## Cosa fa l'app

`solarmon.py` è l'unico processo che parla con l'inverter. Salva i dati in SQLite e serve la dashboard sulla porta 8000. Manda gli alert su Telegram quando compare un fault o un warning, quando la batteria scende sotto soglia, quando l'inverter smette di rispondere o cambia modalità. Gli alert non vengono ripetuti più di una volta all'ora finché il problema persiste. Non ha dipendenze oltre alla libreria standard e usa solo comandi di lettura.

Ho verificato i CRC (`QPIGS` e `QMOD`), il parsing sui tuoi valori reali e le API della dashboard. Il canale hidraw non l'ho potuto provare.

## Prossimi passi

1. **Test sul PC** (con mpp-solar fermo): `INVERTER_DEV=/dev/hidraw1 python3 solarmon.py probe`. Stampa le risposte grezze e il parsing, ed è il vero collaudo del canale. Incollami l'output.
2. **Sulla Pi:** `sudo bash setup.sh`. Installa Mosquitto, la regola udev `/dev/inverter` e il servizio systemd. Poi inserisci `TG_TOKEN` e `TG_CHAT` in `/etc/solarmon.env`.
3. **Beszel:** installa l'agent sulla Pi, come detto prima.

## Cosa ho lasciato fuori

- Auto-discovery MQTT per Home Assistant: per ora l'app pubblica solo lo stato su `solar/inverter/state`.
- Comandi di scrittura sull'inverter.
- Script di backup del database.

Per il ripristino vale intanto l'immagine "golden" della SD. Dimmi quale di questi vuoi aggiungere per primo.


## Utente

al momento per provare sul mio pc fedora connesso all'inverter cosa devo fare? complimeni comunque


## Claude

Grazie! Sul PC non serve installare nulla: Python 3 c'è già su Fedora e l'app usa solo la libreria standard. Ti basta la cartella con i file scaricati.

## 1. Collaudo del canale (2 minuti)

```bash
cd ~/solarmon                        # dove hai messo solarmon.py e index.html
pgrep -af mpp-solar                  # niente deve usare l'inverter: se c'è qualcosa, fermalo
ls -l /dev/hidraw*                   # conferma che l'inverter sia ancora hidraw1
sudo INVERTER_DEV=/dev/hidraw1 python3 solarmon.py probe
```

Se non vuoi usare `sudo`, prima fai `sudo chmod 666 /dev/hidraw1`.

Il comando stampa le quattro risposte grezze (`QPIGS`, `QMOD`, `QPIWS`, `QPIRI`) e poi il parsing. Incollami l'output. Se vedi i valori giusti (PV, batteria, carico), il canale funziona. Se compaiono timeout o "risposta non valida", incollami comunque l'output: indica se il problema sta nel modo in cui scrivo sul device.

## 2. App completa con dashboard

```bash
sudo INVERTER_DEV=/dev/hidraw1 DB_PATH=/tmp/solar/solar.db INTERVAL=10 python3 solarmon.py
```

Poi apri `http://localhost:8000` nel browser. Con `INTERVAL=10` i grafici si riempiono in fretta, ma sulla Pi lascia il valore di default di 60 s. Per vederla dal telefono, usa `http://IP-DEL-PC:8000` (se Fedora blocca la porta: `sudo firewall-cmd --add-port=8000/tcp`).

## 3. Telegram (facoltativo, per provare gli alert)

1. Su Telegram scrivi a **@BotFather**, invia `/newbot` e copia il token.
2. Scrivi un messaggio qualsiasi al tuo nuovo bot.
3. Apri `https://api.telegram.org/bot<TOKEN>/getUpdates` e copia il numero in `"chat":{"id":...}`.
4. Aggiungi al comando: `TG_TOKEN=... TG_CHAT=...`

All'avvio dovresti ricevere "solarmon avviato". Per provare l'alert di batteria bassa, avvia con `BATT_LOW_V=60`: arriva subito una notifica "Batteria bassa".

## Cose da controllare

- **Collisioni:** se l'app gira, non lanciare `mpp-solar` a mano in parallelo, perché solo un processo alla volta può parlare con l'inverter.
- **Warning in `QPIWS`:** la mappatura dei bit è da specifica. Se compare un allarme reale, confronta il testo che arriva con quello che mostra il display e dimmi se non coincidono.
- **Pannelli:** quando fai la prova con il carico grosso a mezzogiorno, tieni aperta la dashboard. Il picco di `pv_w` è il dato che ci serve.


## Utente

output:
INVERTER_DEV=/dev/hidraw1 python3 solarmon.py probe
{
 "QPIGS": "233.2 50.0 229.7 50.0 0551 0339 011 376 53.90 000 100 0039 0007 103.4 53.97 00000 00110110 00 00 00383 110",
 "QMOD": "B",
 "QPIWS": "00000000000000000000000000000000",
 "QPIRI": "230.0 21.7 230.0 50.0 21.7 5000 5000 48.0 45.0 42.0 56.4 54.0 0 10 020 1 2 3 9 01 0 0 49.0 0 1 000"
}
{'grid_v': 233.2, 'out_v': 229.7, 'out_va': 551.0, 'out_w': 339.0, 'load_pct': 11.0, 'batt_v': 53.9, 'chg_a': 0.0, 'batt_pct': 100.0, 'temp_c': 39.0, 'pv_v': 103.4, 'dis_a': 0.0, 'pv_w': 383.0, 'scc_on': 1, 'ac_chg': 0}
{'AC in V': '230.0', 'AC in A': '21.7', 'Uscita V': '230.0', 'Frequenza Hz': '50.0', 'Uscita A': '21.7', 'VA nominali': '5000', 'W nominali': '5000', 'Batteria nominale V': '48.0', 'Ritorno a rete sotto V': '45.0', 'Cutoff batteria V': '42.0', 'Bulk V': '56.4', 'Float V': '54.0', 'Tipo batteria': 'AGM', 'Max carica AC A': '10', 'Max carica A': '020', 'Range ingresso': 'UPS', "Priorita' uscita": 'SBU', "Priorita' carica": 'Solo solare'}

ho avviato col comando e funziona correttamente.
Vorrei aggiungere la lettura di un  file di environment e un file di env di esempio così possosemplificare i parametri. ti chiedo poi a quanti secondi di precisione possiamo scendere senza causare problemi.
Visto che l'index.html sarà rivisto notevolmente assicurati che ora, prima che stacco il pc, ci predfisponiamo per:

1. avere un modo per condivedere i dati grezzi di N secondi passati all'AI (esempio una rotta per visualizzare i dati json)
2. predisporci per far comandare dal bot telegram la modifica di parametri o tutto quello che si può fare. vistgo che sono comandi delicati voglio garantire sicurezza al bot (solo io in quella chat li posso modificare) neanche da rete locale posso farlo bypassando telegram. C'è altro che mi consigli?


## Claude

Ho aggiornato `solarmon.py`, aggiunto `solarmon.env.example` e modificato `setup.sh`. `index.html` è invariato. Ho collaudato parser, sicurezza del bot, flusso `/set` e `/ok` e la rotta `/api/raw` con un inverter finto. Non ho potuto provare le scritture sul tuo inverter vero.

## File env
`solarmon.py` legge `solarmon.env` accanto allo script (o il file indicato in `SOLARMON_ENV`). Le variabili d'ambiente reali hanno la precedenza. Sul PC fai:

```bash
cp solarmon.env.example solarmon.env && chmod 600 solarmon.env
# imposta INVERTER_DEV=/dev/hidraw1 e DB_PATH=./solar.db, poi:
sudo python3 solarmon.py
```

Sulla Pi `setup.sh` copia l'esempio in `/etc/solarmon.env` con permessi 600, e systemd lo legge. I commenti nel file stanno su righe proprie: un commento dopo il valore verrebbe letto come parte del valore.

## Quanto si può scendere con l'intervallo
Il limite pratico è circa **5 s**, e il default ora è 10 s. Il minimo è forzato a 3 s.

- **Cosa cambia con l'intervallo:** non conosco il tempo reale di un ciclo (QPIGS, QMOD e QPIWS) sul tuo inverter. Ho aggiunto `cycle_s` a `/api/now` per misurarlo: se resta sotto 2 s, 5 s è sostenibile.
- **Errori brevi:** `QPIWS` mostra un errore solo finché è attivo. Un fault che dura meno dell'intervallo può sfuggire all'app, ma l'inverter lo registra sul display (`record_fault_code` è attivo nel tuo).
- **Database:** scrive ogni `STORE_INTERVAL` (60 s), non a ogni lettura, per non consumare la SD. Le letture fini restano in RAM per `RAW_KEEP` secondi (3600).

## 1. Dati grezzi per l'AI
`/api/raw` accetta questi parametri:
- `seconds` è la finestra (default 300).
- `step` raggruppa in medie a N secondi.
- `compact=1` restituisce colonne e righe invece di un dizionario per campione: è molto più corto da incollare.
- `token` è richiesto solo se imposti `RAW_TOKEN`.

La risposta include legenda, unità e configurazione dell'inverter, così l'AI ha il contesto. Esempio:

```
http://IP:8000/api/raw?seconds=3600&step=30&compact=1
```

Se la finestra supera la RAM, i dati vengono dal database a 60 s di risoluzione.

## 2. Bot Telegram: sicurezza
- **Nessuna scrittura via rete:** il server HTTP ha solo rotte GET di lettura. Le modifiche passano solo da Telegram, e il bot è una connessione in uscita, quindi non apre porte.
- **Solo tu:** il bot risponde solo se l'id utente è `TG_ADMIN_ID` e il messaggio arriva dalla tua chat privata. Gli altri vengono ignorati senza risposta. Scarta anche i messaggi più vecchi di 2 minuti.
- **Doppia conferma:** `/set uscita sbu` mostra vecchio e nuovo valore con un codice a 4 cifre. Poi serve `/ok CODICE` entro 60 s; il codice è monouso.
- **Scrittura spenta di default:** serve `ALLOW_WRITE=1`.
- **Parametri limitati:**
  - Sono ammessi solo sette parametri, con valori in lista.
  - Ci sono controlli di coerenza, per esempio il cutoff deve restare sotto il ritorno a rete.
  - Tipo batteria e tensioni bulk/float sono esclusi di proposito: falli dal pannello.
  - Per aggiungerne uno basta una riga in `SETTINGS`.
- **Tracciabilità:** ogni modifica salva `QPIRI` prima e dopo, e il risultato in una tabella `audit`. Se qualcuno cambia le impostazioni dal display, l'app lo segnala entro 10 minuti.

**Prima scrittura:** formato e valori dei comandi (`MCHGC020`, `PBCV46.0`...) vengono dalla specifica PI30 e non li ho verificati sul tuo modello. Se l'inverter li rifiuta, risponde NAK e non cambia nulla. Come primo test fai una modifica senza effetto, tipo `/set corrente_carica 20` (è già 20). Se risponde ACK, il canale di scrittura funziona.

## Altri consigli
- Attiva la verifica in due passaggi su Telegram, perché il punto debole residuo è il tuo account.
- Tieni segreti `TG_TOKEN` e il file env. Se il token trapela, rigeneralo da @BotFather.
- Imposta `BIND_ADDR` sull'IP Tailscale della Pi, così la dashboard non è visibile in LAN. Imposta anche `RAW_TOKEN`.
- Dopo il primo `/set` vero, confronta `/config` con il display dell'inverter.


## Utente

ci sono prove che devo fare o posso staccare l'inverter ora?
ti aggiungo che le batterie sono 4 chiamate 12fit100/19 e vedo 6 stringhe dei pannelli


## Claude

Prima di staccare l'inverter conviene fare solo due prove, perché sono le uniche che richiedono l'inverter collegato al PC. Tutto il resto lo verifichi dopo sulla Pi.

## Da fare ora sul PC

**1. Scritture senza effetto (5 minuti).** Con `ALLOW_WRITE=1` e Telegram configurato nel `solarmon.env`, invia ogni comando con il valore che l'inverter ha già, poi conferma con `/ok CODICE`:

```
/set uscita sbu
/set carica solo_solare
/set corrente_carica 20
/set corrente_carica_ac 10
/set ritorno_rete_v 45
/set ritorno_batteria_v 49
/set cutoff_v 42
```

Dopo ogni conferma il bot deve rispondere `ACK` e mostrare "Nessuna differenza in QPIRI". Se un comando risponde `NAK`, incollami quale: significa che formato o valori di quel comando vanno corretti sul tuo modello. Un NAK non cambia nulla. Questa è l'unica prova che non posso fare io, e meglio farla ora con il PC a portata di mano.

**2. Allarmi.** Avvia con `BATT_LOW_V=60` per qualche secondo: deve arrivare "Batteria bassa", e poi "risalita" quando rimetti il valore normale. Controlla anche `curl localhost:8000/api/now` e guarda `cycle_s`, poi prova `INTERVAL=5`.

**3. Prova dei pannelli (solo se c'è ancora sole).** Accendi un carico grosso (≥2 kW) per 10-15 minuti con l'app attiva. Poi lancia `curl "localhost:8000/api/raw?seconds=1200&step=30&compact=1"` e incollami il risultato: il picco di `pv_w` è la potenza reale dell'array. Se non c'è sole, falla un altro giorno a mezzogiorno.

**Prima di chiudere:** conserva `inverter_dump.txt`, che è lo stato di partenza delle impostazioni, e fotografa le etichette dell'inverter e dei pannelli.

## Da fare sulla Pi, non servono sul PC
- Riavvio e blackout (stacca l'alimentazione): la Pi deve ripartire da sola con servizio e dashboard.
- `/dev/inverter` deve esistere dopo il setup.
- Prova di cavo staccato: stacca il cavo USB. Dopo circa un minuto deve arrivare l'allarme "non risponde", e al ricollegamento "ripristinata". Sul PC non ha senso, perché il nome `hidraw1` cambierebbe.
- Immagine della SD a impianto funzionante.

## Le batterie
Dalla ricerca risulta che le 12FIT100/19 sono batterie AGM al piombo da 12 V e 100 Ah. È la serie FIAMM FIT, che è pensata per armadi e rack da telecomunicazioni, quindi sono batterie da standby, non da ciclo profondo. Per il resto vedi sotto.

- **Capacità:** quattro in serie fanno 48 V e 100 Ah, circa 4,8 kWh nominali. Su piombo se ne usano utilmente 2-2,5 kWh senza consumarle in fretta.
- **Carica:** il tuo limite di 20 A (0,2C) è ragionevole.
- **Tensione di float:** per la sorella 12FIT100/23 il costruttore indica 2,27 V per cella, cioè circa 54,5 V sul pacco, quindi i tuoi 54,0 V sono in linea. Il bulk a 56,4 V (14,1 V a batteria) è plausibile, ma controlla il datasheet della /19, perché non l'ho trovato.
- **Soglie di scarica:** cutoff a 42 V e ritorno a rete a 45 V sono molto basse per una batteria da standby (circa 10,5 V e 11,25 V per blocco). Su batterie non giovani peggiorano la vita e possono anche contribuire a un errore 58 sotto carico. Non cambiarle ora: guarda l'andamento di qualche giorno, poi decidiamo se alzarle con `/set`.

## I pannelli
Non mi è chiaro se "6 stringhe" siano 6 pannelli o 6 stringhe in parallelo. Un'ipotesi compatibile con i 104 V: 6 pannelli in serie da circa 17 V ciascuno (vecchi pannelli a 36 celle). Per saperlo servono le etichette (Wp, Vmp, Voc, Isc) e il numero di pannelli per stringa.
