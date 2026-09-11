#!/usr/bin/env python3
"""Invia alert Telegram a cascata quando uno o più ETF scendono di una soglia."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Callable

import requests
import yfinance as yf

DEFAULT_STATE_FILE = Path(__file__).parent / "state.json"
MAX_RETRIES = 3
RETRY_DELAY_SEC = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("etf-alert")


@dataclass(frozen=True)
class Config:
    tickers: tuple[str, ...]
    drop_threshold: float
    lookback_days: int
    max_price_age_days: int
    state_file: Path
    telegram_token: str | None
    telegram_chat_id: str | None
    dry_run: bool = False


@dataclass(frozen=True)
class PriceSnapshot:
    current_price: float
    quote_date: str
    year_high: float
    year_high_date: str
    currency: str | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="calcola e mostra il risultato senza inviare alert o modificare lo stato",
    )
    return parser.parse_args(argv)


def load_config(dry_run: bool = False) -> Config:
    tickers = tuple(
        dict.fromkeys(
            t.strip().upper()
            for t in os.getenv("TICKERS", "MWRD.MI,EMAE.MI").split(",")
            if t.strip()
        )
    )
    if not tickers:
        raise ValueError("TICKERS deve contenere almeno un ticker")
    try:
        threshold = float(os.getenv("DROP_THRESHOLD", "0.05"))
        lookback = int(os.getenv("LOOKBACK_DAYS", "365"))
        max_age = int(os.getenv("MAX_PRICE_AGE_DAYS", "7"))
    except ValueError as exc:
        raise ValueError(
            "DROP_THRESHOLD, LOOKBACK_DAYS e MAX_PRICE_AGE_DAYS devono essere numerici"
        ) from exc
    if not 0 < threshold < 1:
        raise ValueError("DROP_THRESHOLD deve essere maggiore di 0 e minore di 1")
    if lookback < 30:
        raise ValueError("LOOKBACK_DAYS deve essere almeno 30")
    if max_age < 0:
        raise ValueError("MAX_PRICE_AGE_DAYS non può essere negativo")

    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not dry_run and (not token or not chat_id):
        raise ValueError("TELEGRAM_TOKEN e TELEGRAM_CHAT_ID sono obbligatori")

    state_path = Path(os.getenv("STATE_FILE", str(DEFAULT_STATE_FILE))).expanduser()
    return Config(tickers, threshold, lookback, max_age, state_path, token, chat_id, dry_run)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Stato non leggibile in {path}: {exc}") from exc
    if not isinstance(state, dict):
        raise RuntimeError("state.json deve contenere un oggetto JSON")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Salva lo stato atomicamente, evitando file parziali in caso di arresto."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary:
            json.dump(state, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _positive_number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} non è numerico") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} deve essere un numero positivo e finito")
    return number


def normalize_ticker_state(raw: Any) -> dict[str, Any]:
    """Valida lo stato e migra la vecchia forma priva di peak_price."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("lo stato del ticker deve essere un oggetto")
    reference = _positive_number(raw.get("reference_price"), "reference_price")
    peak = _positive_number(raw.get("peak_price", reference), "peak_price")
    try:
        count = int(raw.get("alert_count", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("alert_count deve essere un intero") from exc
    if count < 0:
        raise ValueError("alert_count non può essere negativo")
    normalized = {
        "reference_price": reference,
        "peak_price": max(peak, reference),
        "alert_count": count,
    }
    for key in ("last_alert_quote_date", "last_successful_check"):
        if raw.get(key):
            normalized[key] = str(raw[key])
    return normalized


def fetch_snapshot(ticker: str, lookback_days: int, max_age_days: int) -> PriceSnapshot:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            instrument = yf.Ticker(ticker)
            history = instrument.history(
                period=f"{lookback_days}d", interval="1d", auto_adjust=True
            )
            if history.empty or "Close" not in history:
                raise RuntimeError("yfinance non ha restituito prezzi di chiusura")
            closes = history["Close"].dropna()
            if closes.empty:
                raise RuntimeError("tutti i prezzi di chiusura sono mancanti")
            current = _positive_number(closes.iloc[-1], "prezzo corrente")
            high = _positive_number(closes.max(), "massimo del periodo")
            quote_timestamp = closes.index[-1]
            high_timestamp = closes.idxmax()
            quote_date = quote_timestamp.date()
            age = datetime.now(timezone.utc).date() - quote_date
            if age.days < 0 or age.days > max_age_days:
                raise RuntimeError(
                    f"ultima quotazione del {quote_date.isoformat()} troppo vecchia ({age.days} giorni)"
                )
            currency = None
            try:
                currency = instrument.fast_info.get("currency")
            except Exception:
                log.warning("[%s] Valuta non disponibile", ticker)
            return PriceSnapshot(
                current,
                quote_date.isoformat(),
                high,
                high_timestamp.date().isoformat(),
                currency,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            log.warning(
                "[%s] Tentativo %s/%s fallito: %s",
                ticker,
                attempt,
                MAX_RETRIES,
                exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SEC)
    raise RuntimeError(f"impossibile scaricare dati validi: {last_error}")


def evaluate_ticker(
    ticker: str, raw_state: Any, snapshot: PriceSnapshot, threshold: float
) -> tuple[dict[str, Any], str | None]:
    state = normalize_ticker_state(raw_state)
    checked_at = datetime.now(timezone.utc).isoformat()
    if not state:
        log.info(
            "[%s] Inizializzazione al massimo %s del %s",
            ticker,
            snapshot.year_high,
            snapshot.year_high_date,
        )
        return {
            "reference_price": snapshot.year_high,
            "peak_price": snapshot.year_high,
            "alert_count": 0,
            "last_successful_check": checked_at,
        }, None

    reference = state["reference_price"]
    peak = state["peak_price"]
    count = state["alert_count"]
    if snapshot.year_high > peak:
        reference = peak = snapshot.year_high
        count = 0
        log.info("[%s] Nuovo massimo %.4f: cascata azzerata", ticker, peak)

    drawdown = (reference - snapshot.current_price) / reference
    next_threshold = reference * (1 - threshold)
    log.info(
        "[%s] Chiusura %.4f del %s | riferimento %.4f | calo %.2f%% | prossima soglia %.4f",
        ticker,
        snapshot.current_price,
        snapshot.quote_date,
        reference,
        drawdown * 100,
        next_threshold,
    )

    message = None
    already_alerted = state.get("last_alert_quote_date") == snapshot.quote_date
    if drawdown >= threshold and not already_alerted:
        count += 1
        currency = f" {escape(snapshot.currency)}" if snapshot.currency else ""
        following_threshold = snapshot.current_price * (1 - threshold)
        message = (
            f"⚠️ <b>{escape(ticker)}</b> — calo del <b>{drawdown:.2%}</b>\n\n"
            f"Chiusura del {snapshot.quote_date}: {snapshot.current_price:.2f}{currency}\n"
            f"Riferimento precedente: {reference:.2f}{currency}\n"
            f"Massimo osservato nel periodo: {snapshot.year_high:.2f}{currency} "
            f"({snapshot.year_high_date})\n"
            f"Prossima soglia: {following_threshold:.2f}{currency}\n"
            f"Notifica #{count} nella fase di ribasso"
        )
        reference = snapshot.current_price

    updated = {
        "reference_price": reference,
        "peak_price": peak,
        "alert_count": count,
        "last_successful_check": checked_at,
    }
    if message:
        updated["last_alert_quote_date"] = snapshot.quote_date
    elif state.get("last_alert_quote_date"):
        updated["last_alert_quote_date"] = state["last_alert_quote_date"]
    return updated, message


def send_telegram_message(token: str, chat_id: str, text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    response.raise_for_status()


def run(
    config: Config,
    fetcher: Callable[[str, int, int], PriceSnapshot] = fetch_snapshot,
) -> int:
    state = load_state(config.state_file)
    working_state = json.loads(json.dumps(state))
    had_error = False
    for ticker in config.tickers:
        try:
            snapshot = fetcher(ticker, config.lookback_days, config.max_price_age_days)
            new_state, message = evaluate_ticker(
                ticker, working_state.get(ticker), snapshot, config.drop_threshold
            )
            if message:
                if config.dry_run:
                    log.info("[%s] DRY RUN, alert previsto:\n%s", ticker, message)
                else:
                    assert config.telegram_token and config.telegram_chat_id
                    send_telegram_message(
                        config.telegram_token, config.telegram_chat_id, message
                    )
                    log.info("[%s] Alert inviato", ticker)
            working_state[ticker] = new_state
        except Exception as exc:  # noqa: BLE001
            had_error = True
            log.error("[%s] Errore, stato precedente conservato: %s", ticker, exc)

    if config.dry_run:
        log.info("DRY RUN completato: state.json non modificato")
    else:
        working_state["last_run"] = datetime.now(timezone.utc).isoformat()
        save_state(config.state_file, working_state)
    return 1 if had_error else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(load_config(args.dry_run))
    except (ValueError, RuntimeError, OSError) as exc:
        log.error("Errore di configurazione o stato: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
