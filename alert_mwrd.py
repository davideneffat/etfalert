#!/usr/bin/env python3
"""
Alert Telegram "a cascata" per MWRD:

1. Il primo riferimento è il massimo di prezzo dell'ultimo anno (365 giorni,
   ricalcolato ad ogni run sui dati reali, quindi si aggiorna da solo nel
   tempo mano a mano che la finestra scorre).
2. Se il prezzo scende almeno del 5% da quel riferimento, invia un alert e
   il riferimento si "sposta" al prezzo appena notificato.
3. Da lì in poi il prossimo alert scatta quando si scende un altro 5% da
   QUEL valore (cascata), e così via.
4. Se il prezzo risale sopra il massimo storico attuale (nuovo massimo a 1
   anno), il riferimento si resetta al nuovo massimo e la cascata riparte
   da zero. Questo evita che un vecchio riferimento basso resti "congelato"
   dopo un forte recupero.

State persistito in state.json: reference_price, alert_count, last_run.
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
TICKER = os.environ.get("TICKER", "MWRD.MI")
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
log = logging.getLogger("mwrd-alert")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"reference_price": None, "alert_count": 0, "last_run": None}


def save_state(state: dict) -> None:
    state["last_run"] = datetime.now(timezone.utc).isoformat()
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
            log.warning(f"Tentativo {attempt}/{MAX_RETRIES} fallito: {e}")
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


def main() -> None:
    state = load_state()

    history = fetch_history(TICKER, LOOKBACK_DAYS)
    current_price = float(history["Close"].iloc[-1])
    year_high = float(history["Close"].max())
    year_high_date = history["Close"].idxmax().strftime("%Y-%m-%d")

    reference_price = state.get("reference_price")

    # Primo avvio: inizializza il riferimento con il massimo a 1 anno
    if reference_price is None:
        state["reference_price"] = year_high
        state["alert_count"] = 0
        save_state(state)
        log.info(
            f"Inizializzazione: riferimento impostato al massimo a 1 anno "
            f"{year_high:.2f} (del {year_high_date})"
        )
        return

    # Nuovo massimo a 1 anno superiore al riferimento attuale -> reset cascata
    if year_high > reference_price:
        log.info(
            f"Nuovo massimo a 1 anno: {year_high:.2f} (precedente riferimento "
            f"{reference_price:.2f}). Reset della cascata."
        )
        reference_price = year_high
        state["alert_count"] = 0

    drawdown = (reference_price - current_price) / reference_price
    log.info(
        f"Prezzo: {current_price:.2f} | Riferimento: {reference_price:.2f} | "
        f"Drawdown da riferimento: {drawdown:.2%} | Massimo 1y: {year_high:.2f}"
    )

    if drawdown >= DROP_THRESHOLD:
        state["alert_count"] = state.get("alert_count", 0) + 1
        msg = (
            f"⚠️ <b>{TICKER}</b> — sceso del <b>{drawdown:.2%}</b> "
            f"dal riferimento precedente\n\n"
            f"Prezzo attuale: {current_price:.2f}\n"
            f"Riferimento precedente: {reference_price:.2f}\n"
            f"Massimo ultimo anno: {year_high:.2f} (del {year_high_date})\n"
            f"Notifica #{state['alert_count']} in questa fase di ribasso"
        )
        send_telegram_message(msg)
        log.info("Alert inviato su Telegram.")
        state["reference_price"] = current_price  # la cascata scende
    else:
        state["reference_price"] = reference_price

    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log.error(f"Errore: {e}")
        sys.exit(1)
