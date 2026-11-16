# Analisi del periodo 7/30 giorni — design

Data: 2026-11-16
Stato: approvato dall'utente, da pianificare

## Obiettivo

Con 7 o 30 giorni selezionati la dashboard deve raccontare il periodo, non l'istante:

1. nascondere le card di potenza istantanea (flusso FV/Casa/Rete/Batteria e batteria)
   che con quelle finestre non hanno significato;
2. mostrare **gli stessi grafici** per 7 e 30 giorni, sugli stessi assi normalizzati,
   così i due periodi si confrontano davvero;
3. rispondere a quattro domande:
   - consumo per fasce orarie, con barre verticali impilate per fonte;
   - in quali ore la casa è stata alimentata **solo dal FV, senza rete**;
   - quanti cambi batteria→rete al giorno, in media;
   - energia al giorno per fonte, per vedere l'autosufficienza giorno per giorno;
4. aggiungere il prezzo dell'energia in `solarmon.env` e mostrare una **stima di costo
   solo nella vista a 30 giorni**.

## Non obiettivi

- Nessuna modifica al 24 ore: layout, card e grafici restano come oggi.
- Nessuna previsione meteo, nessun consiglio automatico, nessun controllo dell'inverter.
- Nessuna migrazione del database: i dati necessari (`mode`, `grid_v`, Wh per fonte)
  sono già salvati.
- Nessun costo di FV o batteria: la stima riguarda solo l'energia prelevata dalla rete.
  Il valore dell'energia coperta da FV+batteria è mostrato come informazione separata.
- Niente tariffe F1/F2/F3, niente costi fissi, tasse o oneri: un solo prezzo €/kWh.

## Vincoli

- Solo libreria standard Python, nessuna dipendenza nuova, nessuna build frontend.
- HTTP resta di sola lettura. Il nuovo endpoint è GET e non scrive nulla.
- UI in italiano, tema chiaro/scuro, token CSS esistenti.
- La dashboard deve restare leggibile su 390 px e non superare i 1180 px di larghezza.
- Un buco di comunicazione non produce dati inventati: vale `max_stored_gap()`.

## Approcci considerati

### A — endpoint `/api/analytics` dedicato (scelto)

Una sola rotta legge i campioni della finestra e restituisce fasce, profilo "solo FV",
cambi, energia giornaliera per fonte, totali e prezzo. Il frontend disegna soltanto.

**Perché.** I dati sono nel backend e `energy_rows()`/`window_energy()` sanno già
integrare l'energia sul tempo reale. Una richiesta, una scansione, una logica sola,
testabile con pytest come le altre rotte.

### B — estendere `/api/mix`, `/api/daily` e aggiungere `/api/mode`

Tre richieste e tre scansioni della stessa finestra, con la logica delle fasce e dei
cambi sparsa tra le rotte. Più superficie per divergenze. Scartato.

### C — calcolare tutto nel browser da `/api/raw`

Trenta giorni a 60 s sono ~43.000 righe, la rotta richiede il token e la logica di
integrazione andrebbe duplicata in JavaScript. Scartato.

## Configurazione

In `solarmon.env.example`, nuova sezione:

```text
# --- costi (facoltativo) ---
# Prezzo dell'energia prelevata dalla rete, in euro/kWh.
# Vuoto = nessuna stima di costo. Accetta sia "0.25" sia "0,25".
GRID_PRICE_EUR_KWH=
```

- Letto all'avvio accanto agli altri parametri.
- Valore assente, vuoto, non numerico, non finito o ≤ 0 → `None` e nessuna stima.
  Un valore non valido produce un warning nel log, non blocca l'avvio.
- Il prezzo è incluso nella risposta di `/api/analytics`; non viene aggiunto a
  `/api/now` né ad altre rotte.
- Il frontend mostra i costi **solo con `H === 720`**. Con 7 giorni il prezzo può
  essere configurato ma non compare.

### Limite noto della stima

`e_grid_wh` conta solo il carico passato dalla rete in bypass: `power_split()` non
include la ricarica AC della batteria e `ac_chg` non è salvato nello storico. Di
conseguenza, se la batteria viene caricata dalla rete, il costo mostrato è una
**stima per difetto** e il valore dell'energia coperta è per eccesso. Non si può
correggere senza una migrazione dello schema, che resta fuori da questo lavoro.
La dashboard lo dichiara nella caption della card 30 giorni:
"Stima indicativa: prezzo applicato ai soli prelievi di rete; non include le
ricariche da rete." Lo stesso limite va in `DECISIONS.md`.

## Backend

### Rotta

`GET /api/analytics?h=168|720`, con `h` validato come nelle altre rotte
(intero, 1…8760, default 24). Per `h <= 24` la rotta risponde comunque, ma la
dashboard non la usa.

### Risposta

```json
{
  "h": 168,
  "from": 1763200000,
  "to": 1763804800,
  "days": 6.98,
  "price_eur_kwh": 0.25,
  "totals": {
    "load_kwh": 86.6,
    "pv_kwh": 106.2,
    "solar_kwh": 49.6,
    "batt_kwh": 14.0,
    "grid_kwh": 23.0,
    "self_sufficiency": 73.4,
    "grid_cost_eur": 5.75,
    "covered_value_eur": 15.9,
    "solar_only_hours": 6.2,
    "solar_only_pct": 3.7
  },
  "bands": [
    {"start": 0, "label": "00–04", "solar_kwh": 0.0, "batt_kwh": 0.4, "grid_kwh": 0.3},
    {"start": 4, "label": "04–08", "solar_kwh": 0.2, "batt_kwh": 0.3, "grid_kwh": 0.2},
    {"start": 8, "label": "08–12", "solar_kwh": 2.1, "batt_kwh": 0.1, "grid_kwh": 0.0},
    {"start": 12, "label": "12–16", "solar_kwh": 2.8, "batt_kwh": 0.0, "grid_kwh": 0.0},
    {"start": 16, "label": "16–20", "solar_kwh": 1.6, "batt_kwh": 0.4, "grid_kwh": 0.6},
    {"start": 20, "label": "20–24", "solar_kwh": 0.4, "batt_kwh": 0.8, "grid_kwh": 2.2}
  ],
  "solar_only": {
    "minutes_per_day": [0, 0, 0, 0, 0, 0, 0, 12.5, 38.2, 51.0, 55.1, 54.0,
                        49.7, 46.3, 40.1, 31.4, 18.8, 4.2, 0, 0, 0, 0, 0, 0]
  },
  "switches": {
    "days": [{"ts": 1763203200, "count": 1}, {"ts": 1763289600, "count": 2}],
    "total": 9,
    "per_day": 1.3
  },
  "daily": {
    "ts": [1763203200, 1763289600],
    "solar": [6.8, 7.4],
    "batt": [2.1, 1.9],
    "grid": [3.8, 2.9]
  }
}
```

- Arrotondamenti: kWh 3 decimali, percentuali 1, ore 2, euro 2.
- Con `price_eur_kwh: null`, `grid_cost_eur` e `covered_value_eur` sono `null`.
- Liste `bands` sempre di 6 elementi, anche senza dati.
- `switches.days` e `daily.ts` coprono solo i giorni di calendario con almeno un
  campione visibile, in ordine crescente. Niente giorni inventati a zero.
- Se non ci sono intervalli validi: totali a zero, `days: 0`, `self_sufficiency`,
  `solar_only_pct`, `switches.per_day`, `grid_cost_eur` e `covered_value_eur` a
  `null`, liste giornaliere vuote, `solar_only.minutes_per_day` di 24 zeri.
- `from`/`to` sono la finestra richiesta (`now - h*3600`, `now`), non il primo/ultimo
  campione, così il frontend sa cosa stava guardando.
- Nell'esempio le liste `switches.days` e `daily` sono abbreviate a due giorni; la
  risposta reale contiene una voce per ogni giorno di calendario con campioni.

### Definizioni e calcolo

Una sola query prende `ts, pv_w, out_w, grid_v, mode` più le colonne energia per
`ts > since - max_stored_gap()`. Le righe vengono riusate da tutti i calcoli.

**Giorni equivalenti osservati.** Le medie giornaliere non usano `h/24` né il numero
di date di calendario: una finestra di 7 giorni tocca quasi sempre 8 date, e dividere
per 8 falserebbe i valori. Si usa il tempo realmente osservato:

`observed_seconds` = somma dei `dt` di tutte le coppie di campioni consecutivi con
`0 < dt <= max_stored_gap()`, ritagliate su `[since, now]`.
`days = observed_seconds / 86400`, arrotondato a 2 decimali.

`days` è il denominatore di fasce (kWh/giorno), cambi al giorno e minuti/giorno del
profilo "solo FV". Se non esiste nessuna coppia valida, `days = 0` e le medie sono
`null`. I grafici per giorno usano invece i giorni di calendario: un giorno parziale
ai bordi della finestra ha una barra più bassa, ed è corretto che sia così.

**Energia e totali.** Si riusa `energy_rows()`; ogni intervallo viene ritagliato su
`[since, now]` come in `window_energy()`. `load_kwh = solar + batt + grid`.
`pv_kwh` è la somma di `e_pv`. L'autosufficienza è
`(solar + batt) / load * 100`, coerente con il mix (in bypass tutto il carico è rete).
Se `load_kwh == 0` l'autosufficienza è `null`, non uno zero inventato.

**Fasce da 4 ore.** Sei fasce locali fisse: `[0,4) [4,8) [8,12) [12,16) [16,20) [20,24)`.
Ogni intervallo energia viene spezzato ai confini di fascia con la data/ora locale,
come `daily_payload()` fa con la mezzanotte. I valori restituiti sono **kWh al giorno**
(totali di fascia / `days`), così 7 e 30 giorni usano la stessa scala.

**Solo FV, senza rete.** Per ogni coppia di campioni consecutivi `(prev, cur)` con
`0 < dt <= max_stored_gap()`:

- `grid_on(prev)` e `grid_on(cur)` entrambi falsi (stessa regola del notifier:
  `mode='L'` e `grid_v > 90`);
- `pv_w > 0` e `out_w > 0` in entrambi;
- `pv_w >= out_w - 50` in entrambi (tolleranza di 50 W per i transitori).

Se vale, `dt` viene attribuito alle ore locali attraversate, spezzando ai confini
di ora. `minutes_per_day[ora] = secondi[ora] / 60 / days`.
`solar_only_hours = somma secondi / 3600`.
`solar_only_pct = secondi / observed_seconds * 100`, dove `observed_seconds` è la
somma di tutti i `dt` validi nella finestra, non `giorni × 86400`: così i giorni
parziali e i buchi non falsano la percentuale. Se `observed_seconds == 0`,
`solar_only_pct` è `null`.

**Cambi batteria→rete.** Si percorrono i campioni visibili in ordine e si applica la
stessa conferma del `Notifier`, ma sui campioni salvati:

- lo stato confermato parte dal primo campione;
- quando lo stato cambia, si contano i campioni consecutivi nel nuovo stato;
- al terzo campione consecutivo la transizione è confermata e, se il nuovo stato è
  "in rete", si conta **un** cambio batteria→rete, attribuito al giorno locale del
  terzo campione;
- un ritorno allo stato precedente prima della conferma azzera il conteggio;
- un buco maggiore di `max_stored_gap()` azzera la conferma e riallinea lo stato
  confermato al campione corrente, senza contare nulla.

I campioni fino a `max_stored_gap()` prima di `since` servono solo a stabilire lo
stato iniziale; un cambio conta solo se la conferma cade dentro la finestra.

`per_day = total / days`, `null` se `days == 0`.
Solo le transizioni verso la rete sono conteggiate; i ritorni alla batteria no.

**Energia al giorno per fonte.** Gli stessi intervalli energia vengono spezzati alla
mezzanotte locale (riuso della logica di `daily_payload`) e sommati per
`solar`, `batt`, `grid`. I giorni sono quelli con almeno un campione visibile.

### Helper testabili

Nuove funzioni pure in `solarmon.py`, separate dalla rotta:

- `analytics_payload(h)` — query e composizione della risposta;
- `band_bounds(ts)` / `band_index(ts)` — fascia locale di un istante;
- `split_interval(start, end, fn)` — ripartisce un intervallo su più bucket;
- `solar_only(prev, cur)` — condizione sui due campioni;
- `count_switches(rows)` — transizioni confermate e conteggio per giorno;
- `daily_by_source(rows, since, now)` — serie giornaliere per fonte.

`count_switches` riusa la soglia `GRID_CONFIRM = 3`; nessuna nuova costante.

## Dashboard

### Struttura per periodo

| Elemento | 24 ore | 7 / 30 giorni |
|---|---|---|
| Pillole "Adesso" e "FV" | visibili | visibili (contesto istantaneo) |
| Card flusso FV/Casa/Rete/Batteria | visibile | **nascosta** |
| Card mix del consumo | visibile | visibile |
| Card batteria istantanea | visibile | **nascosta** |
| Tensione batteria | visibile | visibile |
| Produzione e carico | visibile | visibile |
| Nuova sezione analisi | nascosta | **visibile** |
| Energia al giorno | FV degli ultimi 30 giorni (come oggi) | impilata per fonte, sulla finestra scelta |

Il cambio periodo mostra/nasconde subito le sezioni, poi aggiorna i dati.

### Sezione analisi (solo 7/30 giorni)

Sotto la card mix, prima dei grafici esistenti:

```text
[ Consumo ] [ FV prodotto ] [ Autosufficienza ] [ Prelievo rete ] [ Cambi/giorno ] [ Solo FV ]
[ Consumo per fasce orarie — barre verticali impilate FV / batteria / rete ]
[ Solo FV, senza rete — 24 barre, minuti al giorno per ora ]
[ Cambi batteria → rete — barre per giorno + linea media ]
```

- **KPI.** Consumo (kWh), FV prodotto (kWh), autosufficienza (%), prelievo rete (kWh),
  cambi al giorno, ore "solo FV". Sottotitoli: quota coperta da FV+batteria; conteggio
  totale dei cambi; percentuale del tempo solo FV. A 30 giorni, il KPI consumo mostra
  anche il valore coperto stimato (`≈ 15,90 €`) e il KPI prelievo il costo
  (`≈ 5,75 €`). Se il prezzo non è configurato, i sottotitoli di costo spariscono
  senza lasciare "–" inutili. Con 30 giorni e prezzo configurato, una nota sotto i
  KPI ricorda che la stima non include le ricariche della batteria da rete.
- **Fasce.** Barre verticali a 6 posizioni, impilate nell'ordine FV diretto, batteria,
  rete (colori `--mix-solar`, `--mix-batt`, `--mix-grid`), asse y in kWh/giorno,
  legenda nella testata. Caption: "Media giornaliera sui giorni osservati; i totali
  sono nei KPI."
- **Solo FV.** 24 barre verticali, una per ora locale, asse y in minuti/giorno,
  etichette 00, 06, 12, 18, 23. Caption con definizione e totale:
  "Solo FV e senza rete: carico coperto dai pannelli, batteria non necessaria.
  X h nel periodo, Y% del tempo osservato."
- **Cambi.** Barre per giorno (7 o 30), asse y in cambi/giorno, linea tratteggiata
  sulla media con etichetta. Caption: "Cambi confermati da 3 campioni consecutivi
  (≈3 min); media X al giorno."
- **Energia al giorno.** La card esistente `#c-day` cambia resa: barre impilate per
  fonte, stessa legenda del mix, asse y in kWh. Caption "Energia consumata ogni
  giorno, divisa per fonte." Con 24 ore resta la produzione FV degli ultimi 30 giorni.

### Comportamento

- `load()` recupera `/api/analytics?h=` solo con `H > 24`; con 24 ore non fa la
  richiesta. Un errore durante un aggiornamento **dello stesso periodo** non cancella
  i grafici già disegnati: le meta diventano "dati non disponibili" e la dashboard
  continua a funzionare.
- **Cambio periodo**: prima della richiesta la sezione analisi viene svuotata e
  mostrata con i segnaposto `–`, così non restano mai grafici a 7 giorni sotto
  l'etichetta "30 giorni". Se la richiesta fallisce, restano i segnaposto e il
  messaggio di errore.
- **Nessun dato** (`days === 0`): i totali energetici restano `0 kWh`, rapporti e
  medie mostrano `–`; le fasce e il grafico giornaliero mostrano "Nessun dato in
  questo periodo", il profilo "solo FV" mostra 24 barre a zero con caption
  "nessun intervallo osservato". Non si finge un consumo nullo.
- **Consumo zero** (`load_kwh === 0` ma `days > 0`): fasce e grafico giornaliero
  mostrano "Nessun consumo nel periodo"; l'autosufficienza è `–`.
- Resize e cambio tema ridisegnano anche la sezione analisi, come già avviene per
  gli altri grafici.
- Tutti i valori mancanti diventano `–`; nessun `NaN` o `undefined` visibile.
- Ogni grafico ha `role="img"` e `aria-labelledby` sulla propria caption; i KPI sono
  un gruppo con `aria-label`. Il colore non è l'unico indicatore: legenda e testi
  dicono sempre cosa rappresentano le barre.
- Su mobile i KPI vanno a capo (due colonne), i grafici usano l'altezza ridotta già
  prevista (`168–190 px`) e le 6 fasce restano leggibili senza etichette ruotate.

## Gestione errori

- Backend: valori non finiti, righe legacy senza colonne energia e buchi di
  comunicazione seguono le regole già esistenti; nessuna eccezione HTTP nuova.
- Prezzo non valido: warning nel log, `price_eur_kwh: null`, dashboard senza costi.
- Frontend: se `/api/analytics` fallisce, la sezione resta visibile con messaggi
  "dati non disponibili" e gli altri grafici continuano ad aggiornarsi.

## Test

### Python (`tests/test_parsers.py`)

- `solar_only`: vero solo fuori rete, con FV che copre il carico; falso in bypass,
  con FV insufficiente o carico nullo.
- `count_switches`: `B,B,L,L,L` conta 1; `B,L,B,L` non conta (flapping);
  un buco oltre `max_stored_gap` non collega i due lati; i ritorni rete→batteria
  non incrementano il totale.
- Fasce: un'ora a cavallo di un confine viene divisa metà e metà; le 6 fasce coprono
  l'intera giornata.
- `analytics_payload` con DB sintetico su più giorni:
  - `load_kwh == solar + batt + grid` (tolleranza 1e-6);
  - `bands` ha 6 elementi e la somma dei kWh/giorno coincide con il totale / `days`;
  - in una finestra continua di 7 giorni `days` vale ≈7, non 8 date di calendario;
  - `daily` contiene solo giorni di calendario con campioni e le tre serie sommano
    al consumo;
  - `self_sufficiency` è coerente con i totali ed è `null` se `load_kwh == 0`;
  - `per_day` è `total / days` ed è `null` con `days == 0`.
- Prezzo: con `GRID_PRICE_EUR_KWH=0.25` costo e valore coperto sono calcolati;
  senza variabile o con valore non valido sono `null`.
- Rotta: `/api/analytics?h=abc` risponde 200 con il default; con DB vuoto restituisce
  strutture vuote/zero senza errori, con `days: 0`, rapporti `null` e 24 zeri nel
  profilo "solo FV".
- Regressione: `pytest -q` e `ruff check` restano verdi.

### Dashboard

- Estrazione dello `<script>` e `node --check`.
- Mock locale con gli endpoint esistenti più `/api/analytics`: verifica che con
  24 ore la sezione analisi sia nascosta e le card istantanee visibili; con 168/720
  il contrario.
- Cambio periodo 7→30 con endpoint in errore: la sezione non mostra i grafici del
  periodo precedente, ma solo i segnaposto e il messaggio di errore.
- Controllo visivo a 1440, 768 e 390 px, tema chiaro e scuro: nessuna sovrapposizione,
  etichette leggibili, KPI a capo su mobile.
- Verifica dei testi: prezzo mostrato solo a 720; con prezzo assente nessun "€ –".

## Rilascio

File toccati:

- `solarmon.py`: prezzo, helper, rotta `/api/analytics`.
- `index.html`: sezione analisi, visibilità per periodo, grafici impilati, nuova
  resa di "Energia al giorno".
- `solarmon.env.example`: `GRID_PRICE_EUR_KWH`.
- `tests/test_parsers.py`: test dei nuovi helper e della rotta.
- `docs/DECISIONS.md`: decisione su medie giornaliere (giorni equivalenti osservati,
  non date di calendario), fasce, definizione "solo FV", conteggio cambi, costo
  limitato alla rete e alla vista mensile, limite noto sulle ricariche da rete.
- `README.md`: una riga nella configurazione per il prezzo.

Nessuna migrazione, nessuna dipendenza nuova, nessuna modifica al 24 ore.

## Lasciato al builder

- Nomi e firme esatte degli helper, struttura interna dei grafici SVG e classi CSS,
  riusando `lineChart`/`barChart` e i token esistenti.
- Arrotondamenti interni e formato dei numeri con `fmt()`.
- Dettagli di impaginazione della striscia KPI e altezze dei grafici, nel rispetto
  delle soglie desktop/mobile già presenti.
- Scelta se calcolare i bucket in un solo passaggio o in più passaggi sulle stesse
  righe, purché la risposta resti quella descritta.
