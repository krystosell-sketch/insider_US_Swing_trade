"""
Étape 3 du pipeline daily : filtres techniques sur les tickers TTM Squeeze.
Critères : prix > 5$, volume moyen > 500K, prix > SMA20 et SMA50, secteur ∈ Top 3.
"""

import logging
import time
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Exchanges à essayer si le premier échoue
_EXCHANGES = ["NASDAQ", "NYSE", "AMEX", "NYSE ARCA"]
_SLEEP_BETWEEN_TICKERS = 0.3


def _get_tv_data(tv, symbol: str, n_bars: int) -> Any | None:
    """Récupère les données daily d'un ticker via tvDatafeed, essaie plusieurs exchanges."""
    try:
        from tvDatafeed import Interval
    except ImportError:
        return None

    for exchange in _EXCHANGES:
        try:
            df = tv.get_hist(symbol=symbol, exchange=exchange, interval=Interval.in_daily, n_bars=n_bars)
            if df is not None and len(df) >= 55:
                return df
        except Exception:
            continue
    return None


def _compute_sma(values: np.ndarray, period: int) -> np.ndarray:
    """Calcule la SMA glissante."""
    if len(values) < period:
        return np.full(len(values), np.nan)
    result = np.full(len(values), np.nan)
    for i in range(period - 1, len(values)):
        result[i] = np.mean(values[i - period + 1 : i + 1])
    return result


def _build_tv_connection(config: dict) -> Any | None:
    """Crée une instance tvDatafeed."""
    try:
        from tvDatafeed import TvDatafeed
        tv_cfg = config.get("tradingview", {})
        username = tv_cfg.get("username", "")
        password = tv_cfg.get("password", "")
        if username and password:
            return TvDatafeed(username=username, password=password)
        return TvDatafeed()
    except Exception as e:
        logger.error(f"Connexion TradingView échouée : {e}")
        return None


def apply_filters(
    tickers: list[dict],
    top_sectors: list[dict],
    config: dict,
) -> list[dict]:
    """
    Filtre la liste de tickers TTM Squeeze selon les critères techniques.
    Retourne les tickers qui passent tous les filtres avec leurs métriques enrichies.
    """
    if not tickers:
        return []

    top_sector_symbols = {s["symbol"] for s in top_sectors}
    top_sector_names = {s["name"] for s in top_sectors}

    min_price = config["filters"]["min_price"]
    min_avg_vol = config["filters"]["min_avg_volume"]
    sma_periods = config["filters"]["sma_periods"]
    n_bars = max(sma_periods) + 10  # suffisant pour SMA50

    tv = _build_tv_connection(config)
    if tv is None:
        logger.error("tvDatafeed non disponible — filtrage impossible")
        return []

    passed = []
    total = len(tickers)

    for i, ticker_data in enumerate(tickers):
        symbol = ticker_data["symbol"]
        logger.debug(f"Filtrage {symbol} ({i+1}/{total})")

        # Pré-filtre rapide sur les données Barchart (prix / volume)
        if ticker_data.get("price", 0) < min_price:
            logger.debug(f"  {symbol} rejeté : prix {ticker_data['price']:.2f} < {min_price}$")
            continue

        if ticker_data.get("avg_volume", 0) < min_avg_vol:
            logger.debug(f"  {symbol} rejeté : volume {ticker_data['avg_volume']:,} < {min_avg_vol:,}")
            continue

        # Récupérer données TV pour SMA
        df = _get_tv_data(tv, symbol, n_bars)
        if df is None:
            logger.debug(f"  {symbol} : données TV indisponibles — skip")
            time.sleep(_SLEEP_BETWEEN_TICKERS)
            continue

        close = df["close"].values
        volume = df["volume"].values

        current_price = close[-1]
        avg_vol_20 = float(np.mean(volume[-20:])) if len(volume) >= 20 else 0

        # Filtre prix
        if current_price < min_price:
            logger.debug(f"  {symbol} rejeté : prix TV {current_price:.2f} < {min_price}$")
            time.sleep(_SLEEP_BETWEEN_TICKERS)
            continue

        # Filtre volume
        if avg_vol_20 < min_avg_vol:
            logger.debug(f"  {symbol} rejeté : avg vol 20j {avg_vol_20:,.0f} < {min_avg_vol:,}")
            time.sleep(_SLEEP_BETWEEN_TICKERS)
            continue

        # Calcul SMAs
        sma_values = {}
        above_all_sma = True
        for period in sma_periods:
            sma = _compute_sma(close, period)
            sma_last = sma[-1]
            sma_values[period] = sma_last
            if np.isnan(sma_last) or current_price <= sma_last:
                above_all_sma = False
                logger.debug(f"  {symbol} rejeté : prix {current_price:.2f} ≤ SMA{period} {sma_last:.2f}")
                break

        if not above_all_sma:
            time.sleep(_SLEEP_BETWEEN_TICKERS)
            continue

        # Filtre secteur — mapper le secteur Barchart vers les ETFs sectoriels
        sector_match = _match_sector(ticker_data.get("sector_barchart", ""), top_sectors)
        if sector_match is None:
            logger.debug(f"  {symbol} rejeté : secteur '{ticker_data.get('sector_barchart', '')}' hors Top 3")
            time.sleep(_SLEEP_BETWEEN_TICKERS)
            continue

        # Ticker passé — enrichir avec métriques calculées
        enriched = {
            **ticker_data,
            "price": round(current_price, 2),
            "avg_volume": int(avg_vol_20),
            "sector_etf": sector_match["symbol"],
            "sector_name": sector_match["name"],
            **{f"sma{p}": round(sma_values[p], 2) for p in sma_periods},
        }
        passed.append(enriched)
        logger.info(
            f"  ✓ {symbol} — {current_price:.2f}$ | vol {avg_vol_20:,.0f} | "
            f"SMA20 {sma_values[20]:.2f} SMA50 {sma_values[50]:.2f} | {sector_match['symbol']}"
        )
        time.sleep(_SLEEP_BETWEEN_TICKERS)

    logger.info(f"Filtrage terminé : {len(passed)}/{total} tickers retenus")
    return passed


def _match_sector(barchart_sector: str, top_sectors: list[dict]) -> dict | None:
    """
    Mappe un secteur Barchart (texte) vers l'ETF sectoriel correspondant.
    Retourne l'ETF si il est dans le Top 3, None sinon.
    """
    mapping = {
        "technology": "XLK",
        "financial": "XLF",
        "financials": "XLF",
        "energy": "XLE",
        "healthcare": "XLV",
        "health care": "XLV",
        "industrial": "XLI",
        "industrials": "XLI",
        "consumer discretionary": "XLY",
        "consumer cyclical": "XLY",
        "consumer defensive": "XLP",
        "consumer staples": "XLP",
        "utilities": "XLU",
        "real estate": "XLRE",
        "communication": "XLC",
        "communication services": "XLC",
        "basic materials": "XLB",
        "materials": "XLB",
    }

    sector_lower = barchart_sector.lower().strip()
    etf_symbol = None

    for key, etf in mapping.items():
        if key in sector_lower:
            etf_symbol = etf
            break

    if etf_symbol is None:
        return None

    for s in top_sectors:
        if s["symbol"] == etf_symbol:
            return s

    return None
