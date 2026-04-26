"""
Étape 1 du pipeline daily : calcul des secteurs forts.
Utilise yfinance pour comparer les 11 ETFs sectoriels vs SPY.
Pondération : 60% perf 3M + 40% perf 6M. Retourne Top N.
"""

import logging
import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)

N_BARS = "6mo"  # période yfinance


def _get_perf(symbol: str) -> tuple[float, float] | tuple[None, None]:
    """Retourne (perf_3m, perf_6m) absolues pour un symbole."""
    try:
        df = yf.download(symbol, period="6mo", interval="1d", progress=False, auto_adjust=True)
        if df is None or len(df) < 63:
            logger.warning(f"{symbol} : données insuffisantes ({len(df) if df is not None else 0} barres)")
            return None, None

        close = df["Close"].squeeze().values
        perf_3m = (close[-1] - close[-63]) / close[-63] if len(close) >= 63 else 0.0
        perf_6m = (close[-1] - close[0]) / close[0]
        return round(perf_3m, 4), round(perf_6m, 4)
    except Exception as e:
        logger.error(f"{symbol} : erreur — {e}")
        return None, None


def get_top_sectors(config: dict) -> list[dict]:
    """
    Calcule les performances relatives des ETFs sectoriels vs SPY.
    Retourne la liste triée par score (Top N défini dans config).
    """
    weight_3m = config["sectors"]["weight_3m"]
    weight_6m = config["sectors"]["weight_6m"]
    top_n = config["sectors"]["top_n"]
    benchmark = config["sectors"]["benchmark"]

    # Performance SPY comme référence
    spy_3m, spy_6m = _get_perf(benchmark)
    if spy_3m is None:
        logger.error("Données SPY indisponibles")
        return []
    logger.info(f"SPY : 3M={spy_3m:+.2%}, 6M={spy_6m:+.2%}")

    results = []
    for etf in config["sectors"]["etfs"]:
        symbol = etf["symbol"]
        name = etf["name"]

        p3m, p6m = _get_perf(symbol)
        if p3m is None:
            continue

        rel_3m = p3m - spy_3m
        rel_6m = p6m - spy_6m
        score = weight_3m * rel_3m + weight_6m * rel_6m

        results.append({
            "symbol": symbol,
            "name": name,
            "score": round(score, 4),
            "perf_3m": p3m,
            "perf_6m": p6m,
            "rel_3m": round(rel_3m, 4),
            "rel_6m": round(rel_6m, 4),
        })
        logger.info(f"  {symbol} : score={score:+.3f} (3M={p3m:+.1%}, 6M={p6m:+.1%})")

    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:top_n]

    for i, s in enumerate(top, 1):
        logger.info(f"  #{i} {s['symbol']} ({s['name']}) — score {s['score']:+.3f}")

    return top
