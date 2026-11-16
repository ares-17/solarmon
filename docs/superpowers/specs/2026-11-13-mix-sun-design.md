# Mix del consumo e ore di luce — design

Data: 2026-11-13
Stato: approvato dall'utente, da pianificare

## Obiettivo

1. Mostrare, per la finestra selezionata (24 h / 7 gg / 30 gg), da dove viene l'energia
   consumata dalla casa: FV diretto, scarica batteria, rete.
2. Ombreggiare le ore di luce nel grafico "Produzione e carico" usando la posizione
   dell'impianto, senza meteo e senza rete.
3. Rimuovere la frase lunga sotto la striscia di flusso (`#flow-sentence`): non viene letta.

## Non obiettivi (registrati, non implementati ora)

- Suggerimenti di elettrodomestici da accendere quando l'energia è "gratis".
  Idea futura: budget = surplus FV istantaneo + margine batteria (SoC e potenza di scarica
  residua) confrontato con profili di consumo (lavastoviglie ~1,2 kWh in 2 h, lavatrice
  ~0,8 kWh, forno ~2 kWh); solo suggerimento passivo, nessun comando.
- Dati meteo (nuvolosità, pioggia), previsioni, API esterne.
- Modifica della raccolta: gli stessi campioni già in SQLite bastano.

## Vincoli

- Solo libreria standard Python; nessuna richiesta di rete dal server.
- Nessuna scrittura via HTTP; le nuove rotte sono GET di sola lettura.
- UI in italiano, tema chiaro/scuro, nessuna build.

## Backend

### Configurazione (solarmon.env)

| Variabile | Esempio | Significato |
|---|---|---|
| `SOLAR_PLACE` | `Roma, RM` | Comune e sigla provincia. La tabella inclusa copre i 107 capoluoghi. |
| `SOLAR_LAT` | `41.90` | Latitudine in gradi decimali; sovrascrive `SOLAR_PLACE`. |
| `SOLAR_LON` | `12.49` | Longitudine in gradi decimali; sovrascrive `SOLAR_PLACE`. |

- `SOLAR_PLACE` viene normalizzato (maiuscole, spazi) e risolto sulla sigla di provincia;
  il comune serve solo come etichetta, le coordinate sono quelle del capoluogo
  (approssimazione dichiarata: errore < ~10 km, irrilevante per alba/tramonto).
- Se `SOLAR_LAT`/`SOLAR_LON` sono presenti e valide (lat −90..90, lon −180..180), vincono su
  `SOLAR_PLACE`; valori non numerici o fuori range vengono ignorati con un warning a log.
- Se manca tutto: `configured=false`, nessuna ombreggiatura, nessun errore.

### `GET /api/sun?h=N`

- `h` validato come `/api/series` (1..8760, default 24).
- Risposta:

```json
{"configured": true, "place": "Roma, RM", "lat": 41.9, "lon": 12.49,
 "days": [{"date": "2026-11-13", "rise": 1794646320, "set": 1794682260}]}
```

- `rise`/`set` sono epoch UTC dell'istante assoluto; il client li formatta nell'ora locale.
- Algoritmo NOAA semplificato (declinazione + equazione del tempo, zenith 90.833°),
  solo `math`. Giorni polari o calcolo non finito: il giorno è omesso.
- Cache in memoria per `(data, lat, lon)`, svuotata oltre ~800 voci.
- Le date coperte sono i giorni UTC che intersecano la finestra `h`; per l'Italia le ore di
  luce cadono nello stesso giorno UTC e locale, quindi non serve altro.

### `GET /api/mix?h=N`

- `h` come sopra. Aggregazione sull'intera finestra, un solo record.
- Attribuzione per campione, con peso pari al tempo reale trascorso tra letture
  (integrale della potenza, non `STORE_INTERVAL` fisso):

| Voce | Regola |
|---|---|
| FV diretto | `min(pv_w, out_w)` se `mode != 'L'` |
| Batteria | `max(0, out_w - pv_w)` se `mode != 'L'` |
| Rete | `out_w` se `mode == 'L'` (bypass: tutto il carico è rete) |

- La somma delle tre voci è sempre il carico; le ricariche (FV→batteria o rete→batteria)
  non entrano, perché la torta risponde a "da dove viene l'energia consumata".
- `mode` sconosciuto (`?`) viene trattato come non-bypass, quindi FV/batteria.
- Risposta:

```json
{"h": 24, "load_kwh": 1.23, "solar_kwh": 0.61, "batt_kwh": 0.42,
 "grid_kwh": 0.20, "samples": 1440, "from": 1794590000, "to": 1794676400}
```

- Valori arrotondati a 3 decimali; `samples=0` → tutte le voci a 0.

## Frontend (index.html)

### Card "Da dove viene l'energia"

- Fascia a tutta larghezza subito sotto la striscia di flusso, prima di "Produzione e carico".
- Desktop: donut SVG (r 54, spessore 14) a sinistra, legenda a destra con pallino, nome,
  percentuale e kWh; totale "1,2 kWh consumati · 24 ore" sopra o accanto.
- Mobile (<640 px): donut nascosto, barra orizzontale impilata alta ~12 px con percentuale
  dentro i segmenti quando la fetta è ≥ 12%, legenda compatta a tre voci sotto.
- Colori: FV `var(--accent)`, batteria `var(--text)` al 55%, rete `var(--muted)`; testo dei
  segmenti scelto per contrasto (scuro su ambra, chiaro sugli altri).
- Percentuali arrotondate con il metodo del resto maggiore, così sommano 100.
- Segmenti a 0 omessi. Totale 0 → "nessun consumo nel periodo", niente grafico.
- Il donut e la barra si ridisegnano a ogni cambio di finestra e al resize.

### Ombreggiatura solare

- `lineChart` accetta `opts.sun = [{rise, set}, ...]`.
- Le bande sono rettangoli dal bordo superiore a quello inferiore dell'area del grafico,
  disegnati dopo la griglia e prima delle linee, riempiti con un gradiente verticale ambra
  (10% in alto → 2% in basso), definito una volta in `<defs>`.
- La mappa tempo→x interpola linearmente sull'array `ts` (che è equidistanziato), con clamp
  ai bordi dell'area; un giorno senza intersezione con la finestra viene saltato.
- Caption: per 24 h `sole 07:12–16:47`; per 7/30 gg `ore di luce locali`; nessuna banda e
  testo "Imposta SOLAR_PLACE in solarmon.env per le ore di luce" se `configured=false`.
- Solo il grafico "Produzione e carico" è ombreggiato; gli altri restano invariati.

### Rimozione

- `#flow-sentence`: rimossi markup, CSS e il blocco che compone la frase.
- Restano nodi, frecce, etichette dinamiche e la riga batteria; `gridW`, `acCharge` e
  `onGrid` servono ancora al nodo Rete.

### Caricamento dati

- `load()` esegue in parallelo `/api/now`, `/api/series?h=`, `/api/daily`, `/api/mix?h=`,
  `/api/sun?h=`; un errore su mix o sun non blocca la dashboard (card vuota / niente bande).
- Cambio finestra: stesse cinque chiamate.

## Gestione errori

- Backend: eccezioni → 500 con log, come le rotte esistenti; parametri non numerici → default.
- Frontend: risposta mancante o `samples=0` → stato vuoto esplicito; `configured=false` →
  nessuna banda e hint.

## Test

- `tests/test_parsers.py`:
  - `/api/mix` con DB di prova: `solar_kwh + batt_kwh + grid_kwh == load_kwh` (tolleranza 1e-6),
    campioni `mode='L'` tutti in `grid_kwh`, nessun campione → zeri.
  - `/api/sun` con `SOLAR_LAT`/`SOLAR_LON` impostate: `rise < set`, date attese, JSON valido.
  - `/api/sun` senza posizione: `configured=false`, `days=[]`.
- Verifica manuale: mock in `/tmp` esteso con mix e sun; `lint.mjs --app` e
  `inspect.mjs --app` a 1440/768/390, tema chiaro e scuro, con controllo visivo delle bande
  (devono coprire le ore di sole e non sbordare).

## Rilascio

- Modifiche a `solarmon.py` (config, due rotte, tabella capoluoghi), `index.html`,
  `solarmon.env.example`, `docs/DECISIONS.md` (nota su approssimazione capoluogo e
  attribuzione bypass), test.
- Nessuna migrazione del database.
