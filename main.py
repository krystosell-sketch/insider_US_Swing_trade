"""
Swing Trading Dashboard — Orchestrateur principal
Usage:
  python main.py --mode daily      # Scan complet quotidien
  python main.py --mode intraday   # Surveillance intraday (15 min)
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")

BASE_DIR = Path(__file__).parent


def load_config() -> dict:
    with open(BASE_DIR / "config.yaml", "r") as f:
        return yaml.safe_load(f)


def set_github_env(key: str, value: str) -> None:
    """Exporte une variable vers $GITHUB_ENV pour les steps suivants."""
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as f:
            f.write(f"{key}={value}\n")
    os.environ[key] = value


def run_daily(config: dict) -> None:
    from engine.sector_strength import get_top_sectors
    from engine.ttm_loader import get_ttm_squeeze_tickers
    from engine.filters import apply_filters
    from engine.insider_scan import scan_insider_accumulation
    from engine.state_manager import update_states, load_state
    from dashboard.generate_html import generate_html
    from alerts.discord_alerts import send_discord_alerts

    logger.info("=== DAILY SCAN START ===")
    webhook_url = os.environ.get("DISCORD_WEBHOOK", "")

    # Étape 1 : Top secteurs
    logger.info("Étape 1/7 : Calcul des secteurs forts")
    top_sectors = get_top_sectors(config)
    logger.info(f"Top {config['sectors']['top_n']} secteurs : {[s['symbol'] for s in top_sectors]}")

    # Étape 2 : TTM Squeeze tickers
    logger.info("Étape 2/7 : Récupération TTM Squeeze Barchart")
    ttm_tickers = get_ttm_squeeze_tickers(config)
    logger.info(f"{len(ttm_tickers)} tickers en TTM Squeeze ON")

    # Étape 3 : Filtres techniques
    logger.info("Étape 3/7 : Application des filtres techniques")
    filtered = apply_filters(ttm_tickers, top_sectors, config)
    logger.info(f"{len(filtered)} tickers après filtrage")

    # Étape 4 : Insider scan
    logger.info("Étape 4/7 : Scan des insiders (Form 4 EDGAR)")
    insider_results = {}
    for item in filtered:
        ticker = item["symbol"]
        result = scan_insider_accumulation(ticker, config)
        if result:
            insider_results[ticker] = result
            logger.info(f"  {ticker} : accumulation détectée — {result['buy_count']} achats / ${result['net_value']:,.0f}")

    # Étape 5 : Mise à jour états
    logger.info("Étape 5/7 : Mise à jour machine à états")
    changes = update_states(filtered, top_sectors, insider_results, config)
    if changes:
        set_github_env("STATE_CHANGED", "true")
        logger.info(f"{len(changes)} changements d'état")
    else:
        logger.info("Aucun changement d'état")

    # Étape 6 : Génération dashboard
    logger.info("Étape 6/7 : Génération du dashboard HTML")
    state = load_state()
    generate_html(state, top_sectors, config)
    logger.info("Dashboard généré → output/index.html")

    # Étape 7 : Alertes Discord
    logger.info("Étape 7/7 : Envoi alertes Discord")
    if webhook_url:
        send_discord_alerts(changes, top_sectors, webhook_url, config)
    else:
        logger.warning("DISCORD_WEBHOOK non défini — alertes désactivées")

    logger.info("=== DAILY SCAN DONE ===")


def run_intraday(config: dict) -> None:
    from engine.state_manager import load_state, save_state, get_days_in_state
    from engine.volume_monitor import check_volume_spike
    from engine.news_monitor import check_news_catalyst
    from engine.insider_scan import check_insider_cluster
    from dashboard.generate_html import generate_html
    from alerts.discord_alerts import send_discord_alerts

    logger.info("=== INTRADAY MONITOR START ===")
    webhook_url = os.environ.get("DISCORD_WEBHOOK", "")

    state = load_state()
    changes = []

    for ticker, data in list(state["stocks"].items()):
        current_state = data["state"]

        if current_state == "SETUP":
            # Vérifier triggers pour promotion vers PLAY
            trigger = None

            vol = check_volume_spike(ticker, data.get("avg_volume", 0), config)
            if vol:
                trigger = vol
                logger.info(f"{ticker} : volume spike détecté ({vol['ratio']:.2f}x)")

            if not trigger:
                news = check_news_catalyst(ticker, config)
                if news:
                    trigger = news
                    logger.info(f"{ticker} : news catalyseur — {news['headline'][:60]}")

            if not trigger:
                cluster = check_insider_cluster(ticker, config)
                if cluster:
                    trigger = {"type": "insider_cluster", "detail": f"{cluster['count']} achats en 7j"}
                    logger.info(f"{ticker} : cluster insider ({cluster['count']} achats)")

            if trigger:
                from engine.state_manager import promote_stock
                promote_stock(state, ticker, "PLAY", trigger)
                changes.append({"ticker": ticker, "from": "SETUP", "to": "PLAY", "trigger": trigger})
                set_github_env("STATE_CHANGED", "true")

        elif current_state == "ATTENTE":
            # Vérifier si insiders ont commencé à acheter
            from engine.insider_scan import scan_insider_accumulation
            insider = scan_insider_accumulation(ticker, config)
            if insider:
                from engine.state_manager import promote_stock
                promote_stock(state, ticker, "SETUP", insider)
                changes.append({"ticker": ticker, "from": "ATTENTE", "to": "SETUP", "insider": insider})
                set_github_env("STATE_CHANGED", "true")
                logger.info(f"{ticker} : ATTENTE → SETUP (insiders détectés)")

    if changes:
        save_state(state)
        top_sectors = state.get("top_sectors", [])
        generate_html(state, top_sectors, config)
        if webhook_url:
            send_discord_alerts(changes, top_sectors, webhook_url, config)
        logger.info(f"{len(changes)} changements — dashboard et alertes mis à jour")
    else:
        logger.info("Aucun changement intraday")

    logger.info("=== INTRADAY MONITOR DONE ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="Swing Trading Dashboard Pipeline")
    parser.add_argument("--mode", choices=["daily", "intraday"], required=True)
    args = parser.parse_args()

    # SEC_IDENTITY requis par edgartools
    sec_identity = os.environ.get("SEC_IDENTITY", "")
    if sec_identity:
        os.environ["EDGAR_IDENTITY"] = sec_identity

    config = load_config()

    if args.mode == "daily":
        run_daily(config)
    elif args.mode == "intraday":
        run_intraday(config)


if __name__ == "__main__":
    main()
