# Notifiche essenziali e stato immediato in dashboard — design

Data: 2026-11-14
Stato: approvato dall'utente, da pianificare

## Obiettivo

1. Ridurre le notifiche Telegram ai soli eventi che richiedono attenzione:
   passaggio rete/batteria, guasti e avvisi raggruppati, inverter muto.
   Rimuovere il messaggio `Batteria bassa: 40.0 V (10%)`, basato sulla tensione,
   ripetuto ogni ora e fuorviante quando la batteria è sotto carico.
2. Rendere immediatamente leggibile in dashboard se la casa è alimentata da rete
   o batteria e se il FV produce eccedenza, senza frasi lunghe né calcoli a carico
   dell'utente.

## Non obiettivi (registrati, non implementati ora)

- Digest periodico, silenzio notturno, notifiche push alternative (ntfy, Home Assistant).
- Storico delle notifiche o dei cambi di stato: resta il log applicativo.
- Nuove rotte HTTP o modifiche al database.
- Previsioni meteo, suggerimenti di elettrodomestici, comandi automatici.
- Modifica delle soglie dell'inverter o della priorità di uscita.

## Vincoli

- Solo libreria standard Python; nessuna dipendenza nuova.
- Nessuna migrazione del database; lo stato delle notifiche è in memoria.
- HTTP resta di sola lettura; la dashboard usa `/api/now` già esistente.
- UI in italiano, tema chiaro/scuro, nessuna build.

## Notifiche Telegram

### Configurazione

- `BATT_LOW_V` e `ALERT_REPEAT_MIN` vengono rimossi da `solarmon.py` e da
  `solarmon.env.example`. Se restano in un file `.env` esistente vengono ignorati.
- Non ci sono nuove soglie configurabili: le notifiche sono eventi, non stati.
- Costanti interne: conferma transizione `GRID_CONFIRM = 3` letture consecutive;
  tensione AC presente `GRID_MIN_V = 90` V (la stessa già usata dalla dashboard).

### Eventi mantenuti

| Evento | Quando | Messaggio | Ripetizione |
|---|---|---|---|
| Passaggio alla rete | `on_grid` da falso a vero, confermato | `Passato alla rete: batteria al 18% (46,2 V).` | nessuna |
| Ritorno alla batteria | `on_grid` da vero a falso con `mode='B'`, confermato | `Tornato alla batteria: 52,1 V (63%).` | nessuna |
| Allarmi inverter | cambia l'insieme degli allarmi attivi | messaggio unico con guasti e avvisi | nessuna |
| Inverter muto | 60 s senza risposta | `Inverter non risponde da 60 s (6 letture).` | nessuna |
| Comunicazione ripristinata | prima lettura buona dopo un muto | `Comunicazione con l'inverter ripristinata.` | nessuna |

### Eventi rimossi

- Avvio del servizio (`solarmon avviato`).
- Cambi di modalità generici (`Modalita': Batteria -> Rete`).
- Modifiche di configurazione lette da `QPIRI`.
- `Batteria bassa` e ogni notifica basata su `batt_v < BATT_LOW_V`.
- Un messaggio separato per ogni bit di `QPIWS`.
- Ripetizione periodica di qualunque allarme.

### Dettagli di comportamento

- **Stato rete**: `on_grid = mode == 'L' and grid_v > 90`.
  La transizione deve restare stabile per `GRID_CONFIRM` letture consecutive
  (≈30 s con `INTERVAL=10`); un cambio prima della conferma azzera il conteggio,
  così un ping-pong rete/batteria non genera messaggi.
- **Baseline all'avvio**: la prima lettura imposta lo stato corrente senza inviare
  il messaggio di transizione. Se però ci sono già allarmi attivi, parte un unico
  messaggio raggruppato: un guasto presente all'avvio è un problema reale.
- **Ritorno**: il messaggio `Tornato alla batteria` parte solo se la modalità
  confermata è `B`. Se l'inverter esce dalla rete verso Standby, Risparmio o FAULT,
  non si inventa un ritorno alla batteria; la dashboard mostra la modalità reale e
  l'eventuale guasto è coperto dal messaggio allarmi.
- **Testo passaggio**: include carica e tensione batteria quando disponibili.
  Se manca la percentuale, `Passato alla rete: batteria a 46,2 V.`
  Se manca la tensione, `Passato alla rete: batteria al 18%.`
  Se mancano entrambe, `Passato alla rete.`
- **Formato numeri**: virgola decimale, percentuale intera, tensione a un decimale,
  coerente con la dashboard (`46,2 V`, `18%`).
- **Allarmi**: `faults(ws)` fornisce i nomi. I bit con gravità 1 sono guasti, quelli
  con gravità 0 avvisi. Se `mode='F'` e il bit `Inverter fault` non è già presente,
  si aggiunge `Modalità FAULT`. Quando l'insieme cambia si invia **un solo**
  messaggio con l'elenco completo corrente; se alcuni allarmi sono rientrati,
  si aggiunge una riga `Rientrati: ...`. Nessuna ripetizione finché l'insieme
  non cambia.
- **Inverter muto**: la soglia resta 60 s di letture fallite consecutive.
  Un solo messaggio all'ingresso e uno al rientro; nessuna ripetizione mentre
  l'inverter resta muto.
- **Errore Telegram**: resta il comportamento attuale, log dell'errore e nessun
  retry; un errore di invio non blocca il loop di lettura.
- **Configurazione inverter**: il refresh periodico di `QPIRI` ogni 600 s resta,
  perché alimenta la dashboard. Sparisce solo il calcolo del diff e la notifica
  `Configurazione inverter cambiata`.
- **Helper testabili**: `grid_on(gs, mode)`, `grid_switch_text(new_on_grid, gs, mode)`
  (chiamato solo alla transizione confermata), `alarm_groups(ws, mode)`,
  `alarm_text(prev, groups)`. `alert(key, on, text_on, text_off)` diventa un
  semplice cambio di stato senza tempo di ripetizione.

### Esempi

```text
Passato alla rete: batteria al 18% (46,2 V).
Tornato alla batteria: 52,1 V (63%).
```

```text
Allarmi inverter
Guasti: Sovraccarico; Sovratemperatura
Avvisi: Mancanza rete
Rientrati: Mancanza rete.
```

Quando l'insieme corrente è vuoto:

```text
Allarmi rientrati: Sovraccarico; Sovratemperatura.
```

## Dashboard

### Markup

Al posto della frase `<p class="finding" id="finding">` sotto il titolo:

```html
<div class="status" id="status" role="group" aria-label="Stato attuale">
  <p class="status-item" id="status-source">
    <span class="status-k">Adesso</span>
    <span class="status-v" id="status-source-v">–</span>
  </p>
  <p class="status-item" id="status-fv">
    <span class="status-k">FV</span>
    <span class="status-v" id="status-fv-v">–</span>
  </p>
</div>
```

- Resta dentro `.title-main`, subito sotto `h1`, sopra la striscia di flusso.
- Il selettore 24 h / 7 gg / 30 gg resta a destra; su mobile i blocchi vanno a capo.
- La frase lunga e `paintFinding` vengono rimossi. La classe `.finding` resta nel
  CSS perché è usata dalla pagina impostazioni.

### Fonte di alimentazione

| Condizione | Testo | Colore |
|---|---|---|
| `grid_v > 90` e `mode='L'` | `Rete` | ambra (`warn`) |
| `mode='B'` | `Batteria` | verde (`good`) |
| `mode='L'` ma `grid_v <= 90` | `Rete assente` | ambra (`warn`) |
| `mode='F'` | `FAULT` | rosso (`bad`) |
| `mode` Standby/Risparmio/Accensione | nome modalità | neutro |
| dati mancanti | `–` | neutro |

### Eccedenza FV

| Condizione | Testo | Colore |
|---|---|---|
| In rete, `ac_chg=0`, `chg_a>0,2`, `pv_w>0` | `X W in carica` | verde |
| In rete, altrimenti | `0 W in carica` | neutro |
| Non in rete, `pv_w - out_w > 50` | `X W in più` | verde |
| Non in rete, `pv_w - out_w < -50` | `mancano X W` | neutro |
| Non in rete, differenza entro ±50 W | `copre la casa` | neutro |
| `pv_w` o `out_w` non validi | `–` | neutro |

- La soglia di 50 W evita che il testo cambi continuamente per pochi watt.
- In rete il FV non alimenta la casa: se la batteria si sta caricando da AC
  (`ac_chg=1`) il contributo FV non è separabile, quindi non si dichiara
  un'eccedenza FV; il testo resta `0 W in carica`.
- `ac_chg` assente vale 0, come nel resto della dashboard.
- `X` è la potenza di carica `chg_a * batt_v`, non `pv_w - out_w`, perché in bypass
  il carico è preso dalla rete. Se `chg_a` o `batt_v` non sono validi, il testo è `–`.
- Di notte, con FV a 0 e casa alimentata dalla batteria, il testo è
  `mancano X W`: risponde alla domanda "quanto FV manca", senza fingere un guasto.
  Per questo il deficit è neutro, non ambra: di notte è la condizione normale.

### Layout e colori

- Due blocchi in linea, ciascuno con etichetta piccola (`Adesso`, `FV`) e valore
  grande (20 px desktop, 18 px mobile), bordo sottile e sfondo `--raised`.
- Un pallino colorato precede il valore; il testo dice sempre lo stato, quindi il
  colore non è l'unico indicatore.
- Classi: `good` usa `--positive`, `warn` usa `--warn-ink`, `bad` usa `--negative`.
  Nessun token nuovo.
- Il resto della pagina (flusso FV/Casa/Rete/Batteria, card mix, grafici) resta
  invariato e diventa il dettaglio sotto le due risposte.

### Accessibilità e aggiornamento

- Il gruppo ha `aria-label="Stato attuale"`; niente `aria-live`, perché i valori
  cambiano ogni 10 s e un lettore di schermo verrebbe interrotto di continuo.
- I valori si aggiornano con `render()` a ogni `/api/now`, come il resto della
  dashboard.
- In caso di errore di rete resta l'avviso esistente `Dati non aggiornabili`;
  i blocchi mantengono l'ultimo valore letto.
- Gli allarmi restano nel banner `notice` già esistente; non vengono duplicati
  nella nuova striscia, tranne `FAULT` come fonte.

## Gestione errori

- Backend: un errore di lettura non cambia la logica di notifica oltre a quanto
  descritto; un errore di invio Telegram viene loggato e non interrompe il loop.
- Frontend: campi mancanti o non numerici producono `–`; nessun `NaN` o `undefined`
  visibile. Un errore di `/api/now` non azzera i blocchi.
- Nessuna nuova eccezione HTTP: non ci sono nuove rotte.

## Test

### Python (`tests/test_parsers.py`)

- `grid_on`: vero solo con `mode='L'` e `grid_v>90`; falso con `mode='B'` anche se
  la rete è presente.
- `grid_switch_text`: include carica e tensione quando disponibili; omette la parte
  mancante; testo base senza dati.
- Conferma transizione: una sola lettura o un ping-pong non notifica; tre letture
  consecutive sì. Il ritorno notifica solo con `mode='B'`.
- `alarm_groups`/`alarm_text`: più bit gravi e non gravi producono **un** messaggio
  con `Guasti:` e `Avvisi:`; nessuna ripetizione con lo stesso insieme; il rientro
  elenca i nomi; `mode='F'` senza bit 1 aggiunge `Modalità FAULT` una sola volta.
- `alert`: due chiamate `on` consecutive inviano un solo messaggio; `off` invia il
  messaggio di rientro una volta.
- Regressione: `BATT_LOW` non esiste più e nessun percorso compone
  `Batteria bassa`.

### Dashboard

- Mock in `/tmp` con `/api/now` e gli altri endpoint esistenti, sei stati:
  batteria con eccedenza, batteria in deficit, batteria bilanciata, rete in carica,
  rete senza carica, dati mancanti. In più uno stato `mode='S'` e uno `mode='F'`.
- Verifica del testo esatto dei due blocchi e del colore del pallino.
- `node --check` sullo script estratto; `lint.mjs --app` e `inspect.mjs --app`
  a 1440/768/390, tema chiaro e scuro, senza FAIL/WARN.
- Controllo visivo che i due blocchi siano sopra la piega e che su mobile non
  sbordino.

## Rilascio

- Modifiche a `solarmon.py` (notifiche, helper, rimozione soglie), `index.html`
  (striscia di stato, rimozione `paintFinding`), `solarmon.env.example`,
  `docs/DECISIONS.md`, test.
- Nessuna migrazione del database.
- Documentare in `DECISIONS.md`:
  - la soglia di tensione è stata rimossa perché sotto carico produce falsi
    "batteria bassa" e ripetizioni;
  - l'evento utile è il passaggio effettivo alla rete, con conferma di 3 letture;
  - gli allarmi sono raggruppati e non ripetuti;
  - in bypass il FV è dichiarato "in carica" solo quando `ac_chg=0`, perché la
    ricarica da AC non è separabile dalla produzione FV.
