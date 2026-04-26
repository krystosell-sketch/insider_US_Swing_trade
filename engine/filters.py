"""
Étape 3 du pipeline daily : filtres techniques sur les tickers TTM Squeeze.
Critères : prix > 5$, volume moyen > 500K, prix > SMA20 et SMA50, secteur ∈ Top 3.
"""

import logging
import time

import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)

_SLEEP_BETWEEN_TICKERS = 0.2


def _compute_sma(values: np.ndarray, period: int) -> float:
    if len(values) < period:
        return float("nan")
    return float(np.mean(values[-period:]))


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

    min_price = config["filters"]["min_price"]
    min_avg_vol = config["filters"]["min_avg_volume"]
    sma_periods = config["filters"]["sma_periods"]

    passed = []
    total = len(tickers)

    for i, ticker_data in enumerate(tickers):
        symbol = ticker_data["symbol"]
        logger.debug(f"Filtrage {symbol} ({i+1}/{total})")

        # Pré-filtre rapide sur les données Barchart
        if ticker_data.get("price", 0) < min_price:
            continue
        if ticker_data.get("avg_volume", 0) < min_avg_vol:
            continue

        try:
            df = yf.download(symbol, period="3mo", interval="1d", progress=False, auto_adjust=True)
            if df is None or len(df) < 55:
                time.sleep(_SLEEP_BETWEEN_TICKERS)
                continue

            close = df["Close"].squeeze().values
            volume = df["Volume"].squeeze().values

            current_price = float(close[-1])
            avg_vol_20 = float(np.mean(volume[-20:])) if len(volume) >= 20 else 0.0

            if current_price < min_price:
                time.sleep(_SLEEP_BETWEEN_TICKERS)
                continue
            if avg_vol_20 < min_avg_vol:
                time.sleep(_SLEEP_BETWEEN_TICKERS)
                continue

            # Calcul SMAs
            sma_values = {}
            above_all_sma = True
            for period in sma_periods:
                sma = _compute_sma(close, period)
                sma_values[period] = sma
                if np.isnan(sma) or current_price <= sma:
                    above_all_sma = False
                    logger.debug(f"  {symbol} rejeté : prix {current_price:.2f} ≤ SMA{period} {sma:.2f}")
                    break

            if not above_all_sma:
                time.sleep(_SLEEP_BETWEEN_TICKERS)
                continue

            # Filtre secteur
            sector_match = _match_sector(ticker_data.get("sector_barchart", ""), top_sectors)
            if sector_match is None:
                time.sleep(_SLEEP_BETWEEN_TICKERS)
                continue

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
                f"SMA20={sma_values[20]:.2f} SMA50={sma_values[50]:.2f} | {sector_match['symbol']}"
            )

        except Exception as e:
            logger.debug(f"  {symbol} : erreur — {e}")

        time.sleep(_SLEEP_BETWEEN_TICKERS)

    logger.info(f"Filtrage terminé : {len(passed)}/{total} tickers retenus")
    return passed


def _match_sector(barchart_sector: str, top_sectors: list[dict]) -> dict | None:
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
    etf_symbol = next((etf for key, etf in mapping.items() if key in sector_lower), None)
    if etf_symbol is None:
        return None
    return next((s for s in top_sectors if s["symbol"] == etf_symbol), None)
