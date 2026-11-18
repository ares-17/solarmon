# Report dell'impianto e simulazioni — design

Data: 2026-11-18
Stato: approvato dall'utente, da pianificare

## Obiettivo

Dare un modo semplice per **capire l'impianto e decidere gli interventi** senza toccare
il monitoraggio che già funziona. Ogni volta che serve, si prende uno snapshot del
database dalla Raspberry e si rigenera un report **sempre uguale nella forma**, con i
dati aggiornati e con le simulazioni.

Il report deve rispondere a quattro domande:

1. Dove va l'energia: quanto FV, quanta batteria, quanta rete.
2. La batteria è sana? Quanto vale davvero, rispetto ai 4,8 kWh nominali?
3. I pannelli producono quello che possono, o vengono strozzati?
4. Cosa cambierebbe con una batteria più grande, o con più FV? Quanto costerebbe in
   kWh di rete evitati?

Il report è un file HTML autonomo, più un riepilogo Markdown e un JSON con i numeri.
Si apre nel browser, anche dal telefono, e da lì si può stampare in PDF.

## Non obiettivi

- **Nessuna modifica a `solarmon.py`, `index.html`, `Dockerfile`, `docker-compose.yml`
  o al database.** Il report legge soltanto colonne già esistenti.
- Nessun container, nessun servizio sempre acceso, nessuno scheduler, nessun push dalla
  Raspberry. Il trasferimento dei dati resta un comando manuale (o uno script di comodo).
- Nessuna seconda dashboard live: quella attuale resta l'unica vista istantanea.
- Nessun controllo dell'inverter, nessuna scrittura, nessuna modifica di soglie.
- Nessuna previsione meteo e nessuna estrapolazione annuale presentata come dato.
- Nessuna generazione di PDF da codice: il PDF si ottiene dal browser.
- Nessuna stima del costo dell'hardware o del ritorno economico dell'investimento.
- Niente tariffe F1/F2/F3 nella simulazione: la bolletta serve solo come confronto
  mensile, non come modello di costo orario.

## Anti-obiettivi

- Un report che nasconde l'incertezza o che spaccia 2 giorni di osservazioni per una
  stima annuale.
- Un secondo posto dove guardare i dati in tempo reale.
- Un modello di simulazione che produce numeri senza dichiarare le ipotesi.

## Vincoli

- Solo libreria standard Python 3.10+, nessuna dipendenza nuova. Il container usa
  Python 3.12; il report gira anche in locale con 3.12/3.13.
- Il report deve funzionare offline e senza server: un solo file HTML con CSS e grafici
  SVG inline, nessuna risorsa esterna, nessun CDN.
- Deve funzionare su un PC qualsiasi, non solo sulla Raspberry.
- Deve accettare sia uno snapshot appena copiato sia il database locale del PC.
- I buchi di comunicazione non producono energia inventata: vale la stessa regola di
  `max_stored_gap()` usata da `solarmon`.
- I dati grezzi e i report generati restano fuori dal repository (`.gitignore`).
- UI e testi in italiano; unità kWh, W, V, °C, €.

## Approcci considerati

### A — tutto nel database e nel dashboard, sulla Raspberry

Aggiungere colonne e una scheda "simulazione" a `index.html`, calcolando tutto sulla Pi.

**Perché no.** La Pi deve restare leggera e stabile; un anno di campioni a 60 s sono
~525.000 righe e il processo che parla con l'inverter non deve competere con un report
pesante. Inoltre la SD non è un archivio affidabile e il report sarebbe raggiungibile
solo dal telefono via Tailscale.

### B — laboratorio separato con container, pull notturno e report schedulato

Una seconda macchina con Docker che riceve i dati, li archivia e serve i report.

**Perché no (per ora).** È la destinazione giusta quando ci saranno mesi di dati, ma
prima bisogna sapere se il modello funziona. Aggiunge un servizio da mantenere, un
backup in più e un secondo punto di accesso, senza risolvere il problema immediato:
capire l'impianto con i dati che ci sono.

### C — report offline rigenerabile (scelto)

Un pacchetto `analysis/` che legge lo snapshot e produce report + simulazioni. Si lancia
quando serve; lo stesso codice potrà girare in un container in futuro, senza riscritture.

**Perché.** Zero rischio per il monitoraggio, zero infrastruttura, funziona subito con i
due giorni già raccolti e migliora da solo man mano che lo storico cresce. La forma del
report è stabile, i numeri cambiano. Il pull dei dati resta un comando.

## Dati di partenza

### Database (`samples`)

Colonne già presenti e usate: `ts`, `pv_w`, `pv_v`, `batt_v`, `out_w`, `load_pct`,
`chg_a`, `dis_a`, `temp_c`, `grid_v`, `mode`, `ws`, `e_pv_wh`, `e_solar_wh`,
`e_batt_wh`, `e_grid_wh`.

Dati ricavabili senza modifiche:

- potenza di carica batteria `p_chg ≈ chg_a × batt_v`;
- potenza di scarica `p_dis ≈ dis_a × batt_v`;
- throughput della batteria per integrazione nel tempo;
- produzione FV, carico, rete e ripartizione, già presenti;
- stato di rete da `mode` e `grid_v`, con la stessa regola di `solarmon`;
- allarmi da `ws`.

### File opzionali

- `now.json` (output di `/api/now`): serve per mostrare la configurazione reale
  (`QPIRI`) e per leggere le soglie di ritorno rete/batteria.
- `consumu_annuali.csv` (bolletta): confronto mensile F1/F2/F3.
- coordinate: fornite dall'utente — Cellole (CE), `41.201880`, `13.849262`; servono
  per stimare il potenziale FV, con `--lat/--lon` che restano sovrascrivibili.
- `--price`: prezzo €/kWh per le colonne di costo; assente → nessun costo.

## Architettura

```text
solar-snapshot.db ──┐
now.json ───────────┼──▶ analysis/ ──▶ reports/YYYY-MM-DD_HHMM/
consumu_annuali.csv ┘                   ├── report.html
                                        ├── report.md
                                        └── data.json
```

Nessun processo resta acceso. Ogni esecuzione è indipendente e deterministica: stesso
input → stesso report, a parte la data di generazione.

### Moduli

- `analysis/__init__.py` — versione del report e costanti condivise.
- `analysis/db.py` — apertura in sola lettura, caricamento righe, gestione colonne
  mancanti e buchi.
- `analysis/metrics.py` — flussi, profilo orario, fasce, cambi di modo, statistiche
  giornaliere. Riusa le definizioni già fissate in `DECISIONS.md`.
- `analysis/battery.py` — diagnostica del pacco e modello di simulazione.
- `analysis/pv.py` — produzione osservata, stima del potenziale a cielo chiaro,
  calibrazione della taglia efficace.
- `analysis/scenarios.py` — costruzione e esecuzione degli scenari.
- `analysis/report.py` — orchestrazione e CLI.
- `analysis/render.py` — HTML autonomo, SVG, CSS di stampa, Markdown.

`analysis` non importa `solarmon.py`: evita effetti collaterali (env, logging, hardware)
e permette di usarlo su qualsiasi macchina.

## Diagnostica della batteria

Il punto che oggi conta più di tutti. Il report **misura**, non deduce una capacità da
una curva di tensione: sotto carica la tensione non è lo stato di carica, e con un pacco
guasto la curva è inaffidabile.

### Grandezze

- **throughput**: `E_chg` ed `E_dis`, integrando `chg_a × batt_v` e `dis_a × batt_v` sul
  tempo reale, con la regola dei buchi già usata da `solarmon`.
- **energia del ciclo più profondo** (`E_dis_max`): la massima energia scaricata tra un
  massimo e un minimo di tensione nello stesso giorno. È una misura diretta di quanto il
  pacco riesce a erogare; **non viene chiamata "capacità"** e non viene convertita in SOC.
- **riferimento sano** (`E_rif`): `capacità nominale × 0,5`, cioè 2,4 kWh per il pacco
  AGM attuale. È un'ipotesi dichiarata, non un dato. Il rapporto
  `E_dis_max / E_rif` va letto sapendo che la finestra dell'inverter (45–49 V) è più
  stretta del 50% di DoD: il rapporto **sottostima** la salute, non la gonfia.
- **salti di tensione**: eventi con `ΔV ≥ 4 V` in ≤ 120 s. Conteggio al giorno.
- **tempo sotto soglia**: percentuale dei campioni notturni (22:00–06:00) con
  `batt_v < ritorno a rete + 1 V`. Richiede `--config`; senza, non viene calcolato.
- **commutazioni**: cambi batteria↔rete al giorno, con la conferma a 3 campioni già
  usata dal notifier.
- **cicli equivalenti**: `E_dis / capacità utile dello scenario`; per l'osservato si
  riporta il throughput giornaliero, non un numero di cicli inventato.

### Verdetto

Quattro livelli, con trigger numerici:

- **sana** — nessun salto, `E_dis_max / E_rif ≥ 50%`, notti sopra soglia.
- **da controllare** — 1–4 salti/giorno, oppure `E_dis_max / E_rif` tra 20% e 50%.
- **da sostituire** — ≥ 5 salti/giorno, oppure `E_dis_max / E_rif < 20%`, oppure almeno
  il 50% dei campioni notturni sotto soglia per 3 notti.
- **indeterminato** — meno di 24 ore osservate; oppure nessun giorno con escursione
  ≥ 5 V e tentativo di scarica **e** zero salti. Se `--config` manca si salta solo il
  criterio notturno: un rapporto misurato resta decisivo. In questo caso il report
  mostra i numeri e dice **cosa manca**, senza forzare un livello.

Il verdetto è sempre accompagnato dai numeri che lo giustificano, mai da solo. Il
"da sostituire" è un'indicazione tecnica, non un consiglio economico: il costo e il
ritorno dell'investimento restano fuori dal report.

## Modello FV

### Produzione osservata

È un **limite inferiore**: in off-grid il MPPT produce solo ciò che carico e batteria
assorbono. Il report lo dice esplicitamente.

### Potenziale stimato (solo con coordinate)

- Geometria solare e irradianza a cielo chiaro (modello semplificato, senza dipendenze).
- Rendimento di sistema `η = 0,85` (temperatura, cablaggi, inversione), dichiarato.
- Taglia efficace `kWp_eff` calibrata sull'inviluppo superiore della produzione
  osservata: per ogni campione diurno si calcola `pv_w / (cielo_chiaro × η)` e si prende
  un percentile alto (95°) per ignorare le nuvole.
- Produzione disponibile = `min(kWp_eff × cielo_chiaro × η, limite MPPT)`; il limite
  dell'inverter è 4.000 W (5 kVA, da manuale).
- **Energia strozzata** = disponibile − osservata, sommata nel periodo.

Senza coordinate la sezione mostra solo l'osservato e dichiara: "potenziale non
calcolabile: mancano le coordinate". Con `--kwp` l'utente può fornire la taglia reale e
il modello la usa al posto della stima.

La stima è presentata come **ordine di grandezza**, con la nota che giorni nuvolosi
nascondono il potenziale e che la calibrazione va rifatta quando lo storico cresce.

## Confronto con la bolletta

Il CSV della bolletta contiene **kWh consumati per mese**, divisi per fascia F1/F2/F3;
non sono euro. Il report li usa come contesto, non come modello.

- Confronto su **totale mensile** e **media giornaliera del mese** (`kWh / giorni del
  mese`), non per fascia: ricostruire F1/F2/F3 richiede il calendario italiano di
  festivi e sabati, che resta fuori da questa versione.
- La bolletta misura i **prelievi dal contatore**: include la pompa e le eventuali
  ricariche da rete. Il report misura solo il carico passato dall'inverter. La differenza
  è dichiarata, non nascosta: `bolletta − carico inverter ≈ pompa + ricariche + conguagli`.
- Con meno di 7 giorni osservati il confronto è mostrato come **riferimento**, senza
  dire che il periodo osservato rappresenta il mese.
- Mesi mancanti o righe a zero non vengono interpolati.

## Modello di simulazione

Simulazione a passi sui campioni reali (60 s, in avanti fino al campione successivo),
senza inventare dati nei buchi oltre `max_stored_gap()`.

### Ingressi

- carico osservato `out_w`;
- FV disponibile: osservato oppure stimato (sez. precedente);
- batteria: capacità nominale, **DoD utilizzabile** (LFP 90%; AGM 50% come riferimento),
  rendimento di round-trip (LFP 0,90; AGM 0,80), diviso in parti uguali tra carica e
  scarica;
- **limite di carica**: `min(corrente massima di carica, C-rate × capacità) × tensione
  nominale`. La corrente viene da `--config` (`Max carica A`), dal default 20 A oppure
  da `--max-charge-a`. Per gli scenari LFP si assume di alzare il Programma 02 a **60 A**
  (≈3 kW a 51,2 V): è un intervento richiesto e il report lo scrive accanto alla tabella.
  Senza questo, una 16 kWh con 20 A si carica in 16 ore e il modello sottostima il
  beneficio;
- **limite di scarica**: `min(5.000 W dell'inverter, C-rate di scarica × capacità)`
  (LFP 1C, AGM 0,3C);
- ricarica da rete: spenta di default, coerente con "Solo solare" in `QPIRI`; attivabile
  solo con `--allow-grid-charge`;
- SOC iniziale: 50%, dichiarata.

### Unità di tempo e fuso

Tutti i confini di giorno, ora, notte e mese usano **`Europe/Rome`** per default,
implementato con la regola CET/CEST (ultima domenica di marzo e di ottobre), senza
dipendere dal database dei fusi di sistema. `--tz local` usa il fuso della macchina;
`--tz <Area/Città>` accetta un nome IANA dove disponibile. Il fuso usato è scritto in
`data.json` e in testa al report. Stesso snapshot e stesso `--tz` producono gli stessi
bucket su qualunque PC.

### Regola di dispatch

Per ogni passo:

1. il FV copre il carico;
2. l'eccedenza carica la batteria fino al massimo;
3. il deficit scarica la batteria fino al minimo;
4. la rete copre ciò che resta;
5. il FV che non entra nella batteria viene **sprecato** e contato.

La simulazione non riproduce la tensione: lavora in energia e SOC. È l'unico modo onesto
di simulare una chimica diversa (LFP) senza inventare curve di tensione.

### Scenari

| Scenario | Cosa cambia |
|---|---|
| Osservato | nessuna simulazione: flussi misurati |
| AGM riparata | 4,8 kWh nominali, **2,4 kWh utili** (50% DoD), rendimento 0,80 |
| LFP 16 kWh, carica 20 A | batteria nuova ma con il Programma 02 attuale |
| **LFP 16 kWh, carica 60 A** | **scenario di riferimento** — config consigliata |
| LFP 10 kWh, carica 60 A | alternativa più piccola |
| LFP 20 kWh, carica 60 A | limite superiore ragionevole |
| 16 kWh + FV ×1,5 | solo con taglia FV stimata o fornita |
| 16 kWh + FV ×2 | solo con taglia FV stimata o fornita |

La riga "AGM riparata" non promette una capacità che il pacco non ha: usa il DoD di
riferimento del 50%, coerente con `E_rif`. Le righe LFP dichiarano il limite di carica
e il rendimento usati. Le due righe a 20 A e 60 A servono a mostrare **quanto costa non
cambiare il Programma 02**: stessa batteria, stessa spesa, metà del beneficio.

### Batteria 16 kWh compatibile con l'inverter

Lo scenario di riferimento è una **LiFePO4 51,2 V (16 celle) da 16 kWh**, la tensione
nominale giusta per un Axpert a 48 V:

| Parametro | Valore | Perché |
|---|---|---|
| Tensione nominale | 51,2 V | standard 48 V, 16S |
| Energia nominale | 16 kWh | richiesta |
| Energia utile | 14,4 kWh | DoD 90% |
| Corrente di carica | 60 A (≈3,1 kW) | richiede Programma 02 a 60 A |
| Corrente di scarica | 100 A | il limite effettivo resta l'inverter, 5 kW |
| Rendimento round-trip | 0,90 | ipotesi dichiarata |
| BMS | 16S, ≥100 A | protezione celle |

Impostazioni inverter richieste (dal pannello: `solarmon` non le scrive di proposito):
tipo batteria **USER**, bulk **56,0 V**, float **54,4 V**, cutoff **46,0 V**, ritorno a
rete **47,0 V**, ritorno a batteria **51,0 V**. Sono tutti dentro i range del manuale
PIP-MS. Il BMS non comunica con l'inverter: le soglie sono convenzionali e la protezione
vera resta nel BMS.

Se il Programma 02 resta a 20 A, la batteria si carica a circa 1 kW e non assorbe
l'eccedenza di mezzogiorno: è esattamente ciò che la riga "carica 20 A" quantifica.

Per ogni scenario: prelievo rete kWh/giorno, autosufficienza %, FV sprecato kWh/giorno,
cicli equivalenti/giorno, ore/giorno con batteria vuota, costo €/giorno se il prezzo è
impostato. In coda alla tabella, una riga di ipotesi con tutti i parametri usati.

### Validazione (non taratura)

Non si aggiusta un parametro per far tornare i conti: sarebbe una simulazione che si
auto-conferma. Il modello di base gira con i valori **misurati** (`E_usable = E_dis_max`,
rendimento AGM 0,80, limiti da `QPIRI`) e viene confrontato con l'osservato:

- energia scaricata e prelievo di rete simulati entro ±20% dei misurati → "modello
  validato" sull'osservato;
- oltre ±20% → il report scrive "modello non validato" e marca gli scenari come
  esercizio;
- nessun ciclo di scarica significativo (meno di 24 ore o `E_dis_max` trascurabile) →
  validazione saltata, dichiarata.

### Affidabilità

In testa al report e accanto alla tabella:

- **bassa** — meno di 7 giorni osservati;
- **media** — 7–30 giorni;
- **buona** — più di 30 giorni, con almeno un mese completo.

Con affidabilità bassa la tabella resta visibile ma con la scritta "esercizio, non
decisione", nessuna estrapolazione annuale e **tutte** le azioni della sezione "Cosa
fare" marcate allo stesso modo. Il livello non cambia solo il tono: impedisce che due
giorni di dati producano un consiglio d'acquisto presentato come conclusione.

## Struttura del report

```text
┌──────────────────────────────────────────────────────────────┐
│ IMPIANTO SOLARE — <dal> → <al>                               │
│ <giorni> giorni osservati · affidabilità: <livello>          │
├──────────────────────────────────────────────────────────────┤
│ KPI: autosufficienza · rete · FV · batteria                  │
│ Verdetto batteria in una riga, con i numeri che lo motivano  │
├──────────────────────────────────────────────────────────────┤
│ Come leggere questo report (5 righe)                         │
│ 1. FLUSSI           barre giornaliere FV/batteria/rete       │
│ 2. BATTERIA         tensione nel tempo, throughput, salti,   │
│                     commutazioni, energia del ciclo profondo │
│ 3. FOTOVOLTAICO     osservato vs cielo chiaro, picco,        │
│                     energia strozzata, kWp efficace          │
│ 4. CONSUMI          profilo 24h, notte/giorno, picchi;       │
│                     confronto con la bolletta se fornita     │
│ 5. SIMULAZIONI      tabella scenari + ipotesi + affidabilità │
│ 6. COSA FARE        massimo 3 azioni, in ordine di rapporto  │
│                     beneficio/costo, con i kWh stimati        │
│ 7. DATI E LIMITI    cosa manca, cosa non è misurabile        │
└──────────────────────────────────────────────────────────────┘
```

- I grafici sono SVG statici generati in Python, senza JavaScript.
- Ogni grafico ha titolo, unità, legenda testuale e caption con la definizione.
- I colori riprendono i token del dashboard (`solar`, `batt`, `grid`) per continuità.
- I numeri mancanti sono `–`, mai `NaN` o `0` inventati.
- In stampa: A4 verticale, sezioni che non si spezzano a metà, intestazione ripetuta.

### "Cosa fare"

Massimo tre azioni, scelte da regole esplicite e sempre con i numeri a supporto:

1. se la batteria è "da sostituire" → sostituzione, con i kWh/giorno recuperabili stimati
   dallo scenario LFP 16. Il verdetto tecnico può essere netto anche con pochi giorni
   (un pacco che crolla di 8 V in un minuto è un fatto), ma la raccomandazione d'acquisto
   è marcata "esercizio, non decisione" se l'affidabilità è bassa;
2. se il FV è strozzato e l'affidabilità è almeno media → più FV, con i kWh/giorno;
3. se ci sono picchi serali o notturni spostabili → spostamento dei carichi a mezzogiorno,
   indicando la finestra oraria osservata.

Nessun consiglio se i dati non lo sostengono, nessun ritorno economico dell'investimento,
nessun prezzo dell'hardware: il report dice quanti kWh si evitano, non se conviene
comprarli.

## CLI

```bash
python3 -m analysis.report --db solar-snapshot.db --out reports/
```

Opzioni:

| Opzione | Default | Uso |
|---|---|---|
| `--db` | obbligatoria | snapshot o DB locale |
| `--out` | `reports/` | cartella di destinazione |
| `--config` | — | `now.json` con `QPIRI` |
| `--bill` | — | CSV della bolletta |
| `--lat`, `--lon` | — | coordinate per il potenziale FV |
| `--kwp` | — | taglia FV reale, sostituisce la stima |
| `--nominal-kwh` | 4.8 | capacità nominale del pacco attuale |
| `--max-charge-a` | da `--config`, altrimenti 20 | corrente di carica osservata |
| `--allow-grid-charge` | spenta | abilita la ricarica da rete nella simulazione |
| `--tz` | `Europe/Rome` | fuso di giorni, ore, notte e mesi |
| `--price` | — | €/kWh per le colonne di costo |
| `--capacity` | 10,16,20 | capacità degli scenari LFP |

Comportamento:

- crea `reports/YYYY-MM-DD_HHMM/` con `report.html`, `report.md`, `data.json`;
- stampa a schermo un riepilogo di ~10 righe con percorso del report e affidabilità;
- esce con codice 2 e messaggio chiaro se il DB non esiste, è vuoto o non ha la tabella
  `samples`.

### Script di comodo

`scripts/pull-snapshot.sh [host] [percorso-db-remoto]`:

- esegue il backup SQLite sul host remoto via SSH (stessa API `sqlite3.backup` usata a
  mano), senza fermare il container;
- copia lo snapshot in `snapshots/YYYY-MM-DD.db`;
- non contiene credenziali e non apre porte.

Se la disposizione dei file sulla Raspberry è diversa, restano validi i due comandi
manuali già usati.

## Gestione errori

- DB assente, illeggibile o senza `samples` → errore esplicito, nessun report parziale.
- Meno di un giorno di dati → report generato con affidabilità "bassa" e simulazioni
  marcate come esercizio.
- Colonne energia NULL (righe legacy) → energia ricavata dai timestamp, come fa
  `solarmon`.
- `now.json` assente o malformato → configurazione "non disponibile", il report prosegue.
- CSV bolletta malformato → warning, sezione saltata, il resto prosegue.
- Coordinate assenti → potenziale FV non calcolato, dichiarato.
- Prezzo assente o non valido → nessuna colonna di costo, nessun "€ –".
- Nessuna scrittura fuori da `--out`; la connessione al DB è in sola lettura.

## Test

### Unitari

- `battery.py`: conservazione dell'energia, SOC mai fuori da [0,1], eccedenza FV
  contata come sprecata solo a batteria piena, nessuna scarica oltre il minimo.
- `battery.py`: con profilo sintetico noto il throughput simulato coincide con quello
  atteso; con l'energia del ciclo profondo misurata il modello rientra nel ±20%.
- `pv.py`: cielo chiaro nullo di notte, massimo a mezzogiorno, calibratura stabile su
  una serie sintetica; senza coordinate la stima è disabilitata.
- `metrics.py`: energia totale = FV + batteria + rete; i buchi non producono energia;
  i cambi di modo seguono la conferma a 3 campioni.
- `diagnostica`: un salto di 8 V in 60 s viene rilevato; una salita lenta no; un pacco
  sintetico sano dà "sana", uno che crolla sotto carico dà "da sostituire", uno mai
  usato dà "indeterminato".
- `scenari`: con DoD e rendimento noti il prelievo di rete diminuisce al crescere della
  capacità; il limite di carica a 20 A produce più FV sprecato di quello a 60 A.
- `validazione`: il modello di base non modifica i parametri misurati; oltre ±20%
  restituisce "non validato" senza alterare gli scenari.
- `bolletta`: decimali italiani e separatore `;`; totale mensile e media giornaliera
  corretti; un mese a zero resta zero.
- `fuso`: gli stessi campioni danno gli stessi bucket con `TZ` della macchina diverso;
  `--tz Europe/Rome` attraversa correttamente il cambio ora legale.

### End-to-end

- DB sintetico di 3 giorni → il report viene creato, contiene le 7 sezioni, nessun
  `NaN`, nessuna risorsa esterna (`http://`, `https://`, `<script src=`).
- Stesso input due volte → HTML identico a parte il timestamp di generazione.
- DB con sole colonne storiche (senza `e_*`) → nessuna eccezione.
- DB vuoto → codice di uscita 2 e messaggio.

### Collaudo

- `pytest -q` e `ruff check` verdi.
- Report reale sullo snapshot del 18/11: i totali coincidono con una query SQL manuale.
- Apertura dell'HTML su desktop e telefono, tema chiaro, stampa in PDF leggibile.

## Rilascio

File nuovi:

- `analysis/` (pacchetto e moduli sopra);
- `scripts/pull-snapshot.sh`;
- `tests/test_analysis.py`;
- questo documento e il piano di implementazione.

File modificati:

- `.gitignore`: `snapshots/`, `reports/`, `*.db`;
- `README.md`: una sezione "Report e simulazioni" con i due comandi;
- `docs/DECISIONS.md`: report offline, nessuna modifica al bordo, ipotesi del modello,
  limite del FV osservato come limite inferiore.

**Nessuna modifica a `solarmon.py`, `index.html`, `Dockerfile`, `docker-compose.yml`.**

## Lasciato al builder

- Nomi e firme esatte dei moduli e delle funzioni.
- Struttura interna dell'HTML e degli SVG, riusando palette e stile del dashboard.
- Formato dei numeri e arrotondamenti (kWh 1–2 decimali, % 1, € 2).
- Scelta del modello di cielo chiaro più semplice e sufficiente.
- Dettagli della finestra mobile per la diagnostica dei salti di tensione.
- Contenuto esatto delle caption, purché dica la verità sui limiti.

## Questioni aperte

- Taglia reale dei pannelli: se arriva, sostituisce la stima con un dato. Le coordinate
  di Cellole (CE) sono già disponibili, quindi la stima del potenziale è calcolabile.
- Affidabilità del modello quando lo storico arriverà a un mese e a una stagione:
  la validazione va rifatta, non congelata.
- Assunzione dei 60 A di carica negli scenari LFP: da confermare sul campo con il
  Programma 02, e da rivedere se l'inverter o il BMS impongono un limite inferiore.

## Scelte prese dal builder (da controllare)

- La "capacità utile" non si ricava dalla tensione: si misura l'energia del ciclo più
  profondo e la si confronta con un riferimento AGM dichiarato (50% di 4,8 kWh).
- Il verdetto ha quattro livelli, incluso "indeterminato", e trigger numerici espliciti.
- La validazione non aggiusta parametri: usa i valori misurati e dichiara se non torna.
- Il fuso di riferimento è `Europe/Rome`, indipendente dalla macchina.
- La bolletta è kWh, confrontata sul totale mensile e sulla media giornaliera, senza
  ricostruire F1/F2/F3.
- Con affidabilità bassa tutte le azioni sono marcate "esercizio, non decisione".
