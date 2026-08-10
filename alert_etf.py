#!/usr/bin/env python3
"""
Alert Telegram "a cascata" su più ETF (MWRD, EMAE, ...).

Per ciascun ticker in TICKERS (lista separata da virgola):
1. Il riferimento iniziale è il massimo di prezzo dell'ultimo anno (365
   giorni, ricalcolato ogni volta sui dati reali). Questo valore viene anche
   salvato come "peak_price" (il vero massimo storico osservato).
2. Quando il prezzo scende di almeno il 5% dal riferimento, arriva un alert
   e il riferimento si sposta al prezzo appena notificato (la cascata scende),
   mentre peak_price NON cambia.
3. Il prossimo alert scatta quando si scende un altro 5% da quel nuovo
   valore, e così via (cascata).
4. Se il prezzo risale sopra peak_price (un genuino nuovo massimo, mai
   toccato prima), sia il riferimento che peak_price si resettano al nuovo
   massimo e la cascata riparte da zero.

Nota: peak_price è distinto dal riferimento della cascata apposta per non
confondere "il massimo a 1 anno è ancora più alto del riferimento attuale
perché la cascata è scesa" con "è stato appena fatto un nuovo massimo vero".

Lo stato di ogni ticker è indipendente e persistito in state.json, con
struttura: {"MWRD.MI": {...}, "EMAE.MI": {...}}.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yfinance as yf

# ---------- CONFIGURAZIONE ----------
TICKERS = [t.strip() for t in os.environ.get("TICKERS", "MWRD.MI,EMAE.MI").split(",") if t.strip()]
DROP_THRESHOLD = float(os.environ.get("DROP_THRESHOLD", "0.05"))  # 5%
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "365"))
STATE_FILE = Path(__file__).parent / "state.json"

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MAX_RETRIES = 3
RETRY_DELAY_SEC = 5
# -------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("etf-alert")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def fetch_history(ticker: str, lookback_days: int):
    """Scarica lo storico prezzi con qualche retry, per resistere a
    rate-limit o errori temporanei dell'endpoint Yahoo."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            data = yf.Ticker(ticker).history(
                period=f"{lookback_days}d", interval="1d", auto_adjust=True
            )
            if data.empty:
                raise RuntimeError("Dati vuoti restituiti da yfinance")
            return data
        except Exception as e:  # noqa: BLE001
            last_error = e
            log.warning(f"[{ticker}] Tentativo {attempt}/{MAX_RETRIES} fallito: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SEC)
    raise RuntimeError(f"Impossibile scaricare dati per {ticker}: {last_error}")


def send_telegram_message(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    resp.raise_for_status()


def process_ticker(ticker: str, ticker_state: dict) -> dict:
    """Elabora un singolo ticker e restituisce il suo stato aggiornato."""
    history = fetch_history(ticker, LOOKBACK_DAYS)
    current_price = float(history["Close"].iloc[-1])
    year_high = float(history["Close"].max())
    year_high_date = history["Close"].idxmax().strftime("%Y-%m-%d")

    reference_price = ticker_state.get("reference_price")
    peak_price = ticker_state.get("peak_price")

    # Primo avvio per questo ticker: inizializza col massimo a 1 anno.
    # peak_price è il "vero" massimo mai osservato da quando tracciamo questo
    # ticker: serve a distinguere un genuino nuovo massimo da un vecchio
    # massimo che è semplicemente ancora dentro la finestra di 365 giorni
    # (altrimenti, dopo che la cascata scende, year_high resterebbe sempre
    # più alto del reference_price attuale e triggererebbe un reset ogni
    # giorno anche senza nessun nuovo massimo reale).
    if reference_price is None:
        log.info(
            f"[{ticker}] Inizializzazione: riferimento impostato al massimo "
            f"a 1 anno {year_high:.2f} (del {year_high_date})"
        )
        return {"reference_price": year_high, "peak_price": year_high, "alert_count": 0}

    alert_count = ticker_state.get("alert_count", 0)

    # Reset della cascata SOLO se è stato fatto un nuovo massimo genuino,
    # cioè superiore al massimo più alto mai registrato finora (non al
    # riferimento attuale, che per design scende con la cascata).
    if year_high > peak_price:
        log.info(
            f"[{ticker}] Nuovo massimo a 1 anno: {year_high:.2f} (precedente "
            f"massimo registrato {peak_price:.2f}). Reset della cascata."
        )
        reference_price = year_high
        peak_price = year_high
        alert_count = 0

    drawdown = (reference_price - current_price) / reference_price
    log.info(
        f"[{ticker}] Prezzo: {current_price:.2f} | Riferimento: "
        f"{reference_price:.2f} | Drawdown: {drawdown:.2%} | Massimo 1y: {year_high:.2f}"
    )

    if drawdown >= DROP_THRESHOLD:
        alert_count += 1
        msg = (
            f"⚠️ <b>{ticker}</b> — sceso del <b>{drawdown:.2%}</b> "
            f"dal riferimento precedente\n\n"
            f"Prezzo attuale: {current_price:.2f}\n"
            f"Riferimento precedente: {reference_price:.2f}\n"
            f"Massimo ultimo anno: {year_high:.2f} (del {year_high_date})\n"
            f"Notifica #{alert_count} in questa fase di ribasso"
        )
        send_telegram_message(msg)
        log.info(f"[{ticker}] Alert inviato su Telegram.")
        reference_price = current_price  # la cascata scende

    return {"reference_price": reference_price, "peak_price": peak_price, "alert_count": alert_count}


def main() -> None:
    state = load_state()
    had_error = False

    for ticker in TICKERS:
        ticker_state = state.get(ticker, {})
        try:
            state[ticker] = process_ticker(ticker, ticker_state)
        except Exception as e:  # noqa: BLE001
            had_error = True
            log.error(f"[{ticker}] Errore, salto questo ticker: {e}")
            # mantengo lo stato precedente per questo ticker, se esisteva
            if ticker_state:
                state[ticker] = ticker_state

    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    if had_error:
        sys.exit(1)  # segnala il job come "failed" su GitHub Actions


if __name__ == "__main__":
    main()