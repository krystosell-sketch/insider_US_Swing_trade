"""
Étape 1 du pipeline daily : calcul des secteurs forts.
Utilise tvDatafeed pour comparer les 11 ETFs sectoriels vs SPY.
Pondération : 60% perf 3M + 40% perf 6M. Retourne Top N.
"""

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Nombre de barres daily pour couvrir ~6 mois (~126 séances)
N_BARS = 135


def _get_relative_perf(symbol: str, benchmark_close: np.ndarray, tv) -> dict | None:
    """Calcule la performance relative d'un ETF vs benchmark."""
    try:
        from tvDatafeed import Interval
        df = tv.get_hist(symbol=symbol, exchange="AMEX", interval=Interval.in_daily, n_bars=N_BARS)
        if df is None or len(df) < 63:
            logger.warning(f"{symbol} : données insuffisantes ({len(df) if df is not None else 0} barres)")
            return None

        etf_close = df["close"].values
        spy_close = benchmark_close

        # Aligner les longueurs (prendre le min)
        min_len = min(len(etf_close), len(spy_close))
        etf_close = etf_close[-min_len:]
        spy_close = spy_close[-min_len:]

        # Performance absolue
        perf_3m_abs = (etf_close[-1] - etf_close[-63]) / etf_close[-63] if min_len >= 63 else 0.0
        perf_6m_abs = (etf_close[-1] - etf_close[-126]) / etf_close[-126] if min_len >= 126 else perf_3m_abs

        # Performance SPY sur même période
        spy_3m = (spy_close[-1] - spy_close[-63]) / spy_close[-63] if min_len >= 63 else 0.0
        spy_6m = (spy_close[-1] - spy_close[-126]) / spy_close[-126] if min_len >= 126 else spy_3m

        # Performance relative
        rel_3m = perf_3m_abs - spy_3m
        rel_6m = perf_6m_abs - spy_6m

        return {
            "perf_3m": round(perf_3m_abs, 4),
            "perf_6m": round(perf_6m_abs, 4),
            "rel_3m": round(rel_3m, 4),
            "rel_6m": round(rel_6m, 4),
        }
    except Exception as e:
        logger.error(f"{symbol} : erreur récupération données — {e}")
        return None


def get_top_sectors(config: dict) -> list[dict]:
    """
    Calcule les performances relatives des ETFs sectoriels vs SPY.
    Retourne la liste triée par score (Top N défini dans config).
    """
    try:
        from tvDatafeed import TvDatafeed, Interval
    except ImportError:
        logger.error("tvDatafeed non installé. Lancer : pip install tvDatafeed")
        return []

    tv_cfg = config.get("tradingview", {})
    username = tv_cfg.get("username", "")
    password = tv_cfg.get("password", "")

    try:
        if username and password:
            tv = TvDatafeed(username=username, password=password)
        else:
            tv = TvDatafeed()
        logger.info("Connexion TradingView établie (mode anonyme)")
    except Exception as e:
        logger.error(f"Connexion TradingView échouée : {e}")
        return []

    # Récupérer SPY en premier
    benchmark = config["sectors"]["benchmark"]
    try:
        spy_df = tv.get_hist(symbol=benchmark, exchange="AMEX", interval=Interval.in_daily, n_bars=N_BARS)
        if spy_df is None or len(spy_df) < 63:
            logger.error("Données SPY insuffisantes")
            return []
        spy_close = spy_df["close"].values
        logger.info(f"SPY : {len(spy_close)} barres récupérées")
    except Exception as e:
        logger.error(f"Erreur récupération SPY : {e}")
        return []

    weight_3m = config["sectors"]["weight_3m"]
    weight_6m = config["sectors"]["weight_6m"]
    top_n = config["sectors"]["top_n"]

    results = []
    for etf in config["sectors"]["etfs"]:
        symbol = etf["symbol"]
        name = etf["name"]
        logger.info(f"Calcul {symbol} ({name})")

        perf = _get_relative_perf(symbol, spy_close, tv)
        if perf is None:
            continue

        score = weight_3m * perf["rel_3m"] + weight_6m * perf["rel_6m"]
        results.append({
            "symbol": symbol,
            "name": name,
            "score": round(score, 4),
            "perf_3m": perf["perf_3m"],
            "perf_6m": perf["perf_6m"],
            "rel_3m": perf["rel_3m"],
            "rel_6m": perf["rel_6m"],
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:top_n]

    for i, s in enumerate(top, 1):
        logger.info(
            f"  #{i} {s['symbol']} — score {s['score']:+.3f} "
            f"(3M: {s['perf_3m']:+.1%}, 6M: {s['perf_6m']:+.1%})"
        )

    return top
