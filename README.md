# Alert Telegram MWRD -5% dal massimo

Sistema gratuito che controlla ogni 30 minuti (orario di mercato) se l'ETF
**MWRD.MI** è sceso di almeno il 5% dal suo massimo osservato, e in tal caso
invia un messaggio Telegram.

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

- **Costo**: zero. GitHub Actions dà 2.000 minuti/mese gratuiti sui repo
  privati (illimitati su repo pubblici) — questo job usa pochi secondi a
  esecuzione, quindi resti ampiamente nel piano free anche a 30 min di
  frequenza in orario di mercato.
- **Anti-spam**: una volta inviato l'alert per un certo drawdown, non lo
  reinvia finché il prezzo non fa un nuovo massimo (altrimenti riceveresti un
  messaggio ogni 30 minuti finché resta sotto soglia).
- **Cambiare soglia o ticker**: modifica `DROP_THRESHOLD` e `TICKER`
  direttamente nel file `.github/workflows/check_alert.yml` (variabili
  d'ambiente del job).
- **Verifica del ticker**: uso `MWRD.MI` (Borsa Italiana). Se il tuo broker
  quota l'ETF su un altro mercato, sostituisci con `MWRD.PA` (Parigi) o
  `MWRD.DE` (Xetra) — il prezzo/valuta cambia leggermente tra piazze, ma la
  logica di drawdown resta identica.
- **Massimo "storico" vs "rolling"**: questo script traccia il massimo da
  quando lo fai partire (max assoluto osservato). Se invece vuoi un massimo su
  una finestra mobile (es. ultimi 12 mesi), si può modificare facilmente la
  funzione `get_current_price` per scaricare uno storico e ricalcolare il
  massimo della finestra ad ogni run — dimmelo se ti serve questa variante.
