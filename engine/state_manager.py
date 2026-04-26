"""
Étape 5 du pipeline : machine à états ATTENTE → SETUP → PLAY.
Gère la persistence dans data/stocks_state.json et les expirations.
"""

import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent.parent / "data" / "stocks_state.json"

STATES = ("ATTENTE", "SETUP", "PLAY")


# ──────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────

def load_state() -> dict:
    """Charge stocks_state.json. Retourne une structure vide si absent."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Lecture state échouée : {e}")
    return {"stocks": {}, "history": [], "last_updated": None, "top_sectors": []}


def save_state(state: dict) -> None:
    """Sauvegarde l'état dans stocks_state.json."""
    state["last_updated"] = datetime.utcnow().isoformat() + "Z"
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        logger.debug("State sauvegardé")
    except Exception as e:
        logger.error(f"Sauvegarde state échouée : {e}")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def get_days_in_state(stock_data: dict) -> int:
    """Retourne le nombre de jours depuis l'entrée dans l'état courant."""
    since_str = stock_data.get("since")
    if not since_str:
        return 0
    try:
        since = date.fromisoformat(since_str[:10])
        return (date.today() - since).days
    except Exception:
        return 0


def _add_history_event(state: dict, ticker: str, from_state: str | None, to_state: str | None, reason: str) -> None:
    """Ajoute un événement dans l'historique global."""
    event = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "ticker": ticker,
        "from": from_state,
        "to": to_state,
        "reason": reason,
    }
    state.setdefault("history", []).append(event)
    # Garder max 500 événements
    if len(state["history"]) > 500:
        state["history"] = state["history"][-500:]


def promote_stock(state: dict, ticker: str, new_state: str, extra_data: dict | None = None) -> None:
    """Promeut un ticker vers un nouvel état dans le state dict (in-place)."""
    old_state = state["stocks"].get(ticker, {}).get("state")
    if ticker not in state["stocks"]:
        state["stocks"][ticker] = {}
    state["stocks"][ticker]["state"] = new_state
    state["stocks"][ticker]["since"] = date.today().isoformat()
    if extra_data:
        if new_state == "SETUP":
            state["stocks"][ticker]["insider_data"] = extra_data
        elif new_state == "PLAY":
            state["stocks"][ticker]["trigger_data"] = extra_data
    _add_history_event(state, ticker, old_state, new_state, str(extra_data or ""))
    logger.info(f"{ticker} : {old_state} → {new_state}")


# ──────────────────────────────────────────────
# Mise à jour principale
# ──────────────────────────────────────────────

def update_states(
    filtered_tickers: list[dict],
    top_sectors: list[dict],
    insider_results: dict[str, dict],
    config: dict,
) -> list[dict]:
    """
    Orchestre la mise à jour complète des états :
    1. Expirations
    2. Retraits des tickers hors TTM Squeeze
    3. Nouvelles entrées en ATTENTE
    4. Promotions ATTENTE → SETUP
    5. Met à jour top_sectors dans le state

    Retourne la liste des changements pour les alertes Discord.
    """
    state = load_state()
    changes = []
    today = date.today().isoformat()

    max_attente = config["states"]["max_days_attente"]
    max_setup = config["states"]["max_days_setup"]
    max_play = config["states"]["max_days_play"]

    filtered_symbols = {t["symbol"] for t in filtered_tickers}

    # ── 1. Expirations ──
    for ticker in list(state["stocks"].keys()):
        data = state["stocks"][ticker]
        days = get_days_in_state(data)
        current = data["state"]

        expired = (
            (current == "ATTENTE" and days > max_attente)
            or (current == "SETUP" and days > max_setup)
            or (current == "PLAY" and days > max_play)
        )

        if expired:
            logger.info(f"{ticker} expiré : {current} depuis {days}j")
            changes.append({
                "type": "expired",
                "ticker": ticker,
                "from": current,
                "days": days,
            })
            _add_history_event(state, ticker, current, None, f"Expiré après {days}j")
            del state["stocks"][ticker]

    # ── 2. Retrait des titres sortis du TTM Squeeze (état ATTENTE uniquement) ──
    for ticker in list(state["stocks"].keys()):
        if state["stocks"][ticker]["state"] == "ATTENTE" and ticker not in filtered_symbols:
            logger.info(f"{ticker} retiré : hors TTM Squeeze ON")
            changes.append({
                "type": "removed",
                "ticker": ticker,
                "from": "ATTENTE",
                "reason": "Plus en TTM Squeeze ON",
            })
            _add_history_event(state, ticker, "ATTENTE", None, "Hors TTM Squeeze ON")
            del state["stocks"][ticker]

    # ── 3. Nouveaux titres → ATTENTE ──
    for t in filtered_tickers:
        ticker = t["symbol"]
        if ticker not in state["stocks"]:
            state["stocks"][ticker] = {
                "state": "ATTENTE",
                "since": today,
                "sector": t.get("sector_etf", ""),
                "sector_name": t.get("sector_name", ""),
                "price": t.get("price", 0),
                "avg_volume": t.get("avg_volume", 0),
                "sma20": t.get("sma20"),
                "sma50": t.get("sma50"),
                "name": t.get("name", ""),
                "insider_data": None,
                "trigger_data": None,
            }
            logger.info(f"{ticker} : nouveau ATTENTE — {t.get('sector_etf', '')}")
            changes.append({"type": "new_attente", "ticker": ticker, "data": state["stocks"][ticker]})
            _add_history_event(state, ticker, None, "ATTENTE", "TTM Squeeze + filtres")
        else:
            # Mettre à jour les métriques de marché
            state["stocks"][ticker].update({
                "price": t.get("price", state["stocks"][ticker].get("price")),
                "avg_volume": t.get("avg_volume", state["stocks"][ticker].get("avg_volume")),
                "sma20": t.get("sma20", state["stocks"][ticker].get("sma20")),
                "sma50": t.get("sma50", state["stocks"][ticker].get("sma50")),
            })

    # ── 4. Promotions ATTENTE → SETUP ──
    for ticker, insider_data in insider_results.items():
        if ticker in state["stocks"] and state["stocks"][ticker]["state"] == "ATTENTE":
            promote_stock(state, ticker, "SETUP", insider_data)
            changes.append({
                "type": "new_setup",
                "ticker": ticker,
                "from": "ATTENTE",
                "insider_data": insider_data,
                "data": state["stocks"][ticker],
            })

    # ── 5. Mettre à jour top_sectors ──
    state["top_sectors"] = top_sectors

    save_state(state)

    if changes:
        set_state_changed()

    return changes


def set_state_changed() -> None:
    """Notifie GitHub Actions qu'un changement a eu lieu."""
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as f:
            f.write("STATE_CHANGED=true\n")
    os.environ["STATE_CHANGED"] = "true"
