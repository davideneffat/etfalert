# Alert Telegram multi-ETF a cascata

Il progetto controlla una volta al giorno uno o più ETF e invia un messaggio
Telegram quando la chiusura scende almeno della percentuale configurata. Ogni
ticker mantiene una cascata e uno stato indipendenti.

## Come funziona

Al primo controllo il riferimento viene impostato al massimo dei prezzi di
chiusura rettificati nel periodo configurato e non viene inviato alcun alert.
Quando il prezzo scende almeno del 5% dal riferimento, viene inviato un solo
alert e il riferimento passa alla chiusura appena notificata. Un calo ulteriore
del 5% genera lo scalino successivo.

`peak_price` conserva il massimo più alto osservato dal sistema. La cascata si
azzera solo quando i dati scaricati contengono un massimo superiore a questo
valore. Non si azzera semplicemente perché un vecchio massimo è ancora nella
finestra mobile.

Un forte ribasso che attraversa più scalini produce un solo alert per quella
quotazione. Lo stato registra anche la data dell'ultima quotazione notificata,
così una nuova esecuzione sulla stessa chiusura non ripete l'alert quando lo
stato precedente è stato salvato correttamente.

## Configurazione

Creare un bot con [@BotFather](https://t.me/BotFather), inviargli un primo
messaggio e configurare questi repository secret in **Settings → Secrets and
variables → Actions**:

- `TELEGRAM_TOKEN`: token del bot;
- `TELEGRAM_CHAT_ID`: identificativo della chat destinataria.

Il workflow usa queste variabili d'ambiente:

| Variabile | Default | Significato |
|---|---:|---|
| `TICKERS` | `MWRD.MI,EMAE.MI` | Ticker Yahoo Finance separati da virgole |
| `DROP_THRESHOLD` | `0.05` | Calo necessario per un alert |
| `LOOKBACK_DAYS` | `365` | Periodo richiesto a Yahoo Finance |
| `MAX_PRICE_AGE_DAYS` | `7` | Età massima accettata per l'ultima quotazione |
| `STATE_FILE` | `state.json` accanto allo script | Percorso dello stato |

La soglia deve essere compresa tra 0 e 1, il periodo deve essere di almeno 30
giorni e l'età massima non può essere negativa. Ticker duplicati vengono
rimossi. I token Telegram vengono richiesti solo nelle esecuzioni reali.

## Esecuzione

Installare le dipendenze:

```bash
python -m pip install -r requirements.txt
```

Per verificare prezzi, logica e messaggio senza inviare nulla e senza modificare
`state.json`:

```bash
python alert_etf.py --dry-run
```

Per un'esecuzione reale:

```bash
TELEGRAM_TOKEN="..." TELEGRAM_CHAT_ID="..." python alert_etf.py
```

I test non usano rete né Telegram:

```bash
python -m unittest discover -s tests -v
```

## Automazione GitHub

[Il workflow](.github/workflows/check_alert.yml) parte dal lunedì al venerdì
alle 17:00 UTC e può essere avviato manualmente dalla pagina Actions. Le
esecuzioni sono serializzate per impedire che due job aggiornino
contemporaneamente `state.json`. Al termine, lo stato viene salvato con un
commit automatico.

Se un ticker fallisce, gli altri vengono comunque elaborati, lo stato del
ticker fallito viene conservato e il job termina con errore. Prezzi vuoti,
non numerici, non positivi o più vecchi di `MAX_PRICE_AGE_DAYS` vengono
rifiutati. Lo stato viene scritto atomicamente per evitare file JSON parziali.

Il workflow esegue anche i test a ogni modifica dei file applicativi. Le
dipendenze dirette sono bloccate a versioni precise per rendere le installazioni
ripetibili; gli aggiornamenti vanno applicati e verificati esplicitamente.

## Limiti operativi

Yahoo Finance non offre una garanzia di servizio per questo utilizzo. I prezzi
sono quelli restituiti da `yfinance` con rettifica automatica; una rettifica
storica può modificare i massimi calcolati rispetto a esecuzioni precedenti.

Telegram non espone una chiave di idempotenza per `sendMessage`. La data
dell'ultima quotazione riduce i duplicati nelle normali riesecuzioni, ma resta
un piccolo intervallo tra consegna del messaggio e salvataggio dello stato:
un arresto proprio in quell'intervallo può causare un duplicato.

Non inserire mai il token Telegram nel repository, nei log o negli screenshot.
Se è stato esposto, revocarlo con BotFather e aggiornare il secret.
