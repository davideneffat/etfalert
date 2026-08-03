# Alert Telegram multi-ETF "a cascata"

Sistema gratuito che controlla **una volta al giorno** (a mercato chiuso) il
prezzo di più ETF — attualmente **MWRD.MI** e **EMAE.MI** — e invia un
messaggio Telegram con questa logica (indipendente per ciascun ticker):

1. Il riferimento iniziale è il **massimo di prezzo dell'ultimo anno** (365
   giorni, ricalcolato ogni volta sui dati reali).
2. Quando il prezzo scende di almeno il 5% da quel riferimento, arriva un
   alert e il riferimento **si sposta al prezzo appena notificato**.
3. Il prossimo alert scatta quando si scende un altro 5% da quel nuovo
   valore, e così via — è una cascata di soglie via via più basse.
4. Se il prezzo risale sopra il massimo attuale a 1 anno (nuovo massimo), il
   riferimento si resetta al nuovo massimo e la cascata riparte da zero.
   (Questa è una scelta di default sensata ma non esplicitamente richiesta:
   se preferisci che la cascata NON si resetti mai fino a un tuo intervento
   manuale, dimmelo e tolgo questa parte.)

## 1. Crea il bot Telegram (2 minuti)

1. Apri Telegram, cerca **@BotFather** e avvia una chat.
2. Manda `/newbot`, segui le istruzioni (nome e username del bot).
3. BotFather ti darà un **token** tipo `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.
   Salvalo, è il tuo `TELEGRAM_TOKEN`.
4. Cerca il tuo bot appena creato su Telegram e mandagli un messaggio qualsiasi
   (es. "ciao") — serve per "sbloccarlo" e permettergli di scriverti.
5. Recupera il tuo `chat_id` **da terminale** (evita il browser per non
   lasciare il token in chiaro nella cronologia/screenshot):
   ```
   curl "https://api.telegram.org/bot<IL_TUO_TOKEN>/getUpdates"
   ```
   e cerca nel JSON restituito il campo `"chat":{"id": ...}`. Quel numero è il
   tuo `TELEGRAM_CHAT_ID`.

## 2. Crea un repository GitHub (gratuito)

1. Vai su github.com, crea un nuovo repository (può essere privato).
2. Carica tutti i file di questo progetto (`alert_etf.py`, `requirements.txt`,
   `state.json`, la cartella `.github/workflows/check_alert.yml`) mantenendo
   la stessa struttura di cartelle.
   - Via web: usa "Add file" → "Upload files" e trascina tutto.
   - Via git (da terminale, dentro la cartella del progetto):
     ```
     git init
     git add .
     git commit -m "Setup alert ETF"
     git branch -M main
     git remote add origin https://github.com/<tuo-utente>/<tuo-repo>.git
     git push -u origin main
     ```

## 3. Configura i secrets su GitHub

Nel repository: **Settings → Secrets and variables → Actions → New repository secret**

- `TELEGRAM_TOKEN` → il token ottenuto da BotFather
- `TELEGRAM_CHAT_ID` → il chat_id ottenuto sopra

## 4. Attiva il workflow

Il file `.github/workflows/check_alert.yml` è già pronto: gira automaticamente
una volta al giorno, lun-ven, alle 17:00 UTC (a mercato chiuso), controllando
entrambi i ticker in un unico run.

Per testarlo subito senza aspettare: vai su **Actions** nel repository →
seleziona il workflow "Check ETF alerts" → **Run workflow** (pulsante
manuale, grazie a `workflow_dispatch`).

Al primo avvio lo script non invia nessun alert per nessuno dei due ticker:
inizializza semplicemente il riferimento con il massimo a 1 anno di ciascuno.
Da lì in poi traccia la cascata e ti avvisa quando scende del 5%.

## Note

- **Costo**: zero. Con un run al giorno l'utilizzo di GitHub Actions è
  trascurabile (pochi secondi/giorno), ben dentro il piano gratuito anche su
  repo privati.
- **Multi-ticker indipendente**: ogni ticker ha il proprio riferimento e la
  propria cascata in `state.json` (struttura `{"MWRD.MI": {...}, "EMAE.MI":
  {...}}`), quindi un drawdown su uno non influenza l'altro.
- **Aggiungere altri ETF**: basta aggiungere il ticker (con suffisso Yahoo
  Finance corretto, es. `.MI` per Borsa Italiana) alla variabile `TICKERS`
  nel workflow, separato da virgola — es. `"MWRD.MI,EMAE.MI,XXXX.MI"`. Lo
  stato per il nuovo ticker si inizializza da solo al primo run.
- **Resilienza per ticker**: se il download dati fallisce per un ticker (es.
  Yahoo temporaneamente irraggiungibile), lo script salta solo quel ticker,
  mantiene il suo stato precedente e continua con gli altri; il job GitHub
  Actions risulta comunque "failed" per farti sapere che qualcosa è andato
  storto, ma senza perdere lo storico di chi ha funzionato.
- **Un solo alert per soglia al giorno**: dato che il check gira una volta al
  giorno sul prezzo di chiusura, ricevi al massimo un alert al giorno per
  ticker, esattamente quando si supera la prossima soglia della cascata.
- **Gap improvvisi**: se in un giorno solo il prezzo crolla più del 5%, lo
  script invia comunque **un solo alert quel giorno** (drawdown effettivo
  riportato nel messaggio), non uno per ogni "scalino" teoricamente
  attraversato. La cascata riparte comunque dal nuovo prezzo.
- **Retry automatici**: se Yahoo Finance risponde con errore temporaneo o
  rate-limit, lo script ritenta fino a 3 volte con 5 secondi di pausa per
  ogni ticker prima di arrendersi su quello specifico.
- **Cambiare soglia, ticker o finestra del massimo**: modifica `DROP_THRESHOLD`,
  `TICKERS` e `LOOKBACK_DAYS` direttamente nel file
  `.github/workflows/check_alert.yml` (variabili d'ambiente del job).
- **Orario del check**: 17:00 UTC, dopo la chiusura di Borsa Italiana/Xetra.
  Se preferisci un altro orario, basta cambiare l'espressione cron in
  `check_alert.yml`.
- **Sicurezza del token**: ricordati di non condividere mai screenshot o URL
  contenenti `TELEGRAM_TOKEN` — se il token attuale è mai stato esposto,
  rigeneralo da BotFather (`/mybots` → il tuo bot → API Token → Revoke) e
  aggiorna il secret su GitHub.
