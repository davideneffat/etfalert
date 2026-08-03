#!/usr/bin/env python3
"""
Alert Telegram quando l'ETF MWRD scende del X% dal massimo osservato.

Logica:
1. Scarica il prezzo corrente (close più recente) via yfinance.
2. Legge da state.json il massimo storico osservato finora.
3. Se il prezzo corrente è un nuovo massimo, aggiorna state.json.
4. Se il prezzo corrente è sceso di almeno DROP_THRESHOLD dal massimo,
   invia un messaggio Telegram (con anti-spam: un solo alert per livello,
   finché non si riazzera facendo un nuovo massimo).
"""

import json
import os
import sys
from pathlib import Path

import requests
import yfinance as yf

# ---------- CONFIGURAZIONE ----------
TICKER = os.environ.get("TICKER", "MWRD.MI")
DROP_THRESHOLD = float(os.environ.get("DROP_THRESHOLD", "0.05"))  # 5%
STATE_FILE = Path(__file__).parent / "state.json"

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]  # obbligatorio, da secret
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]  # obbligatorio, da secret
# -------------------------------------


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"max_price": None, "alert_sent_for_this_drawdown": False}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_current_price(ticker: str) -> float:
    data = yf.Ticker(ticker).history(period="5d", interval="1d")
    if data.empty:
        raise RuntimeError(f"Nessun dato restituito per {ticker}")
    return float(data["Close"].iloc[-1])


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
    price = get_current_price(TICKER)

    max_price = state.get("max_price")

    # Primo avvio: inizializza il massimo con il prezzo corrente
    if max_price is None:
        state["max_price"] = price
        state["alert_sent_for_this_drawdown"] = False
        save_state(state)
        print(f"Inizializzazione: massimo impostato a {price:.2f}")
        return

    # Nuovo massimo -> aggiorna e resetta il flag di alert
    if price > max_price:
        state["max_price"] = price
        state["alert_sent_for_this_drawdown"] = False
        save_state(state)
        print(f"Nuovo massimo: {price:.2f} (precedente {max_price:.2f})")
        return

    drawdown = (max_price - price) / max_price
    print(f"Prezzo: {price:.2f} | Massimo: {max_price:.2f} | Drawdown: {drawdown:.2%}")

    if drawdown >= DROP_THRESHOLD and not state.get("alert_sent_for_this_drawdown", False):
        msg = (
            f"⚠️ <b>{TICKER}</b> in calo del <b>{drawdown:.2%}</b> dal massimo!\n\n"
            f"Prezzo attuale: {price:.2f}\n"
            f"Massimo di riferimento: {max_price:.2f}\n"
            f"Soglia impostata: {DROP_THRESHOLD:.0%}"
        )
        send_telegram_message(msg)
        state["alert_sent_for_this_drawdown"] = True
        save_state(state)
        print("Alert inviato su Telegram.")
    else:
        save_state(state)  # nessun cambiamento sostanziale, ma teniamo lo stato coerente


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Errore: {e}", file=sys.stderr)
        sys.exit(1)
