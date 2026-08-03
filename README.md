# Alert Telegram MWRD -5% "a cascata"

Sistema gratuito che controlla **una volta al giorno** (a mercato chiuso) il
prezzo dell'ETF **MWRD.MI** e invia un messaggio Telegram con questa logica:

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
5. Recupera il tuo `chat_id`: apri nel browser (sostituendo il token)
   `https://api.telegram.org/bot<IL_TUO_TOKEN>/getUpdates`
   e cerca nel JSON restituito il campo `"chat":{"id": ...}`. Quel numero è il
   tuo `TELEGRAM_CHAT_ID`.

## 2. Crea un repository GitHub (gratuito)

1. Vai su github.com, crea un nuovo repository (può essere privato).
2. Carica tutti i file di questo progetto (`alert_mwrd.py`, `requirements.txt`,
   `state.json`, la cartella `.github/workflows/check_alert.yml`) mantenendo
   la stessa struttura di cartelle.
   - Via web: usa "Add file" → "Upload files" e trascina tutto (GitHub
     ricrea automaticamente le sottocartelle se mantieni i path nei nomi file,
     altrimenti più comodo con `git`, vedi sotto).
   - Via git (da terminale, dentro la cartella del progetto):
     ```
     git init
     git add .
     git commit -m "Setup alert MWRD"
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
ogni 30 minuti, lun-ven, dalle 8:00 alle 18:00 UTC (orario che copre la Borsa
Italiana in CET/CEST).

Per testarlo subito senza aspettare: vai su **Actions** nel repository →
seleziona il workflow "Check MWRD alert" → **Run workflow** (pulsante manuale,
grazie a `workflow_dispatch`).

Al primo avvio lo script non invia nessun alert: inizializza semplicemente il
massimo con il prezzo corrente. Da lì in poi traccia i nuovi massimi e ti
avvisa quando scende del 5%.

## Note

- **Costo**: zero. Con un run al giorno l'utilizzo di GitHub Actions è
  trascurabile (pochi secondi/giorno), ben dentro il piano gratuito anche su
  repo privati.
- **Un solo alert per soglia**: dato che il check gira una volta al giorno
  sul prezzo di chiusura, ricevi al massimo un alert al giorno, esattamente
  quando si supera la prossima soglia della cascata.
- **Gap improvvisi**: se in un giorno solo il prezzo crolla più del 5% (es.
  -12% in una seduta), lo script invia comunque **un solo alert quel giorno**
  (drawdown effettivo riportato nel messaggio), non uno per ogni "scalino" del
  5% teoricamente attraversato. La cascata riparte comunque dal nuovo prezzo,
  quindi il giorno dopo, se il calo prosegue, arriverà un nuovo alert al
  prossimo -5%.
- **Retry automatici**: se Yahoo Finance risponde con errore temporaneo o
  rate-limit, lo script ritenta fino a 3 volte con 5 secondi di pausa prima
  di fallire (in tal caso il job GitHub Actions risulta "failed" e puoi
  vederlo nella tab Actions).
- **Cambiare soglia, ticker o finestra del massimo**: modifica `DROP_THRESHOLD`,
  `TICKER` e `LOOKBACK_DAYS` direttamente nel file
  `.github/workflows/check_alert.yml` (variabili d'ambiente del job).
- **Verifica del ticker**: uso `MWRD.MI` (Borsa Italiana). Se il tuo broker
  quota l'ETF su un altro mercato, sostituisci con `MWRD.PA` (Parigi) o
  `MWRD.DE` (Xetra) — il prezzo/valuta cambia leggermente tra piazze, ma la
  logica di drawdown resta identica.
- **Orario del check**: 17:00 UTC, dopo la chiusura di Borsa Italiana/Xetra.
  Se preferisci un altro orario (es. appena apre il mercato USA, o la mattina
  presto), basta cambiare l'espressione cron in `check_alert.yml`.
- **Sicurezza del token**: ricordati di non condividere mai screenshot o URL
  contenenti `TELEGRAM_TOKEN` — se il token attuale è mai stato esposto,
  rigeneralo da BotFather (`/mybots` → il tuo bot → API Token → Revoke) e
  aggiorna il secret su GitHub.
