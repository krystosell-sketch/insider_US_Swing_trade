"""
Étape 2 du pipeline daily : récupération des tickers via TradingView Screener + calcul TTM Squeeze.

Étape 2a — TradingView Screener (tradingview-screener, sans auth) :
  Filtre NYSE+NASDAQ par : prix > 5$, vol moy > 500K, prix > SMA20 > SMA50

Étape 2b — Calcul TTM Squeeze (yfinance, 3 mois) :
  TTM Squeeze ON = Bollinger Bands (20,2) entièrement dans Keltner Channels (20 EMA, 1.5×ATR14)
"""

import logging
import time

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_SLEEP_BATCH = 0.5
_BATCH_SIZE  = 100


# ──────────────────────────────────────────────
# Étape 2a : Screener TradingView
# ──────────────────────────────────────────────

def _screener_prefilter(min_price: float, min_volume: int) -> list[dict]:
    """
    Interroge TradingView Screener pour obtenir les actions NYSE+NASDAQ
    qui passent les filtres de base : prix, volume moyen, prix > SMA20 > SMA50.
    Retourne une liste de dicts avec symbol, price, avg_volume, sector.
    """
    try:
        from tradingview_screener import Query, Column
    except ImportError:
        logger.error("tradingview-screener non installé — pip install tradingview-screener")
        return []

    try:
        count, df = (
            Query()
            .select(
                "name", "close", "volume",
                "average_volume_10d_calc",
                "sector", "industry",
                "SMA20", "SMA50",
                "exchange", "type",
            )
            .where(
                Column("exchange").isin(["NYSE", "NASDAQ"]),
                Column("type") == "stock",
                Column("close") > min_price,
                Column("average_volume_10d_calc") > min_volume,
                Column("close") > Column("SMA20"),
                Column("close") > Column("SMA50"),
                Column("SMA20") > Column("SMA50"),
            )
            .limit(5000)
            .get_scanner_data()
        )
        logger.info(f"TradingView Screener : {count} actions passent les filtres de base")

        results = []
        for _, row in df.iterrows():
            ticker = str(row.get("name", "")).strip()
            if not ticker or not ticker.replace("-", "").isalpha() or len(ticker) > 5:
                continue
            results.append({
                "symbol": ticker,
                "name": ticker,
                "price": float(row.get("close", 0) or 0),
                "avg_volume": int(row.get("average_volume_10d_calc", 0) or 0),
                "sector_barchart": str(row.get("sector", "") or ""),
                "industry": str(row.get("industry", "") or ""),
                "sma20_tv": float(row.get("SMA20", 0) or 0),
                "sma50_tv": float(row.get("SMA50", 0) or 0),
            })
        return results

    except Exception as e:
        logger.error(f"TradingView Screener échoué : {e}")
        return []


# ──────────────────────────────────────────────
# Étape 2b : Calcul TTM Squeeze
# ──────────────────────────────────────────────

def _compute_ema(values: np.ndarray, period: int) -> float:
    if len(values) < period:
        return float(np.mean(values))
    k = 2 / (period + 1)
    ema = float(np.mean(values[:period]))
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _is_ttm_squeeze_on(close: np.ndarray, high: np.ndarray, low: np.ndarray) -> bool:
    """
    TTM Squeeze ON = BB (20,2) entièrement à l'intérieur des KC (EMA20, 1.5×ATR14).
    """
    if len(close) < 21:
        return False

    sma20 = float(np.mean(close[-20:]))
    std20 = float(np.std(close[-20:], ddof=1))
    bb_upper = sma20 + 2.0 * std20
    bb_lower = sma20 - 2.0 * std20
    if (bb_upper - bb_lower) == 0:
        return False

    ema20 = _compute_ema(close[-21:], 20)
    tr_list = [
        max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        for i in range(-14, 0)
    ]
    atr14 = float(np.mean(tr_list))

    kc_upper = ema20 + 1.5 * atr14
    kc_lower = ema20 - 1.5 * atr14

    return bb_upper < kc_upper and bb_lower > kc_lower


def _download_batch(tickers: list[str]) -> dict:
    """Télécharge 3 mois OHLCV pour un batch de tickers."""
    try:
        data = yf.download(
            tickers,
            period="3mo",
            interval="1d",
            group_by="ticker",
            progress=False,
            auto_adjust=True,
            threads=True,
        )
        result = {}
        if len(tickers) == 1:
            if data is not None and not data.empty and len(data) >= 21:
                result[tickers[0]] = data
        else:
            for ticker in tickers:
                try:
                    df = data[ticker].dropna()
                    if df is not None and len(df) >= 21:
                        result[ticker] = df
                except Exception:
                    continue
        return result
    except Exception as e:
        logger.debug(f"Batch download échoué : {e}")
        return {}


# ──────────────────────────────────────────────
# Entrée principale
# ──────────────────────────────────────────────

def get_ttm_squeeze_tickers(config: dict) -> list[dict]:
    """
    1. Screener TradingView → actions NYSE+NASDAQ avec filtres prix/vol/SMA
    2. Calcul TTM Squeeze via yfinance sur le sous-ensemble filtré
    Retourne les tickers en TTM Squeeze ON avec métadonnées.
    """
    min_price  = config["filters"]["min_price"]
    min_volume = config["filters"]["min_avg_volume"]

    # ── Étape 2a : screener TradingView ──
    candidates = _screener_prefilter(min_price, min_volume)
    if not candidates:
        logger.warning("Screener TradingView : aucun candidat — abandon")
        return []

    # Index symbol → metadata pour enrichissement final
    meta = {c["symbol"]: c for c in candidates}
    symbols = list(meta.keys())
    logger.info(f"Calcul TTM Squeeze sur {len(symbols)} candidats")

    # ── Étape 2b : calcul TTM Squeeze par batch ──
    squeeze_on = []
    batches = [symbols[i:i + _BATCH_SIZE] for i in range(0, len(symbols), _BATCH_SIZE)]

    for batch_num, batch in enumerate(batches, 1):
        logger.info(f"  Squeeze batch {batch_num}/{len(batches)} ({len(batch)} tickers)")
        batch_data = _download_batch(batch)

        for ticker, df in batch_data.items():
            try:
                close  = df["Close"].squeeze().values.astype(float)
                high   = df["High"].squeeze().values.astype(float)
                low    = df["Low"].squeeze().values.astype(float)
                volume = df["Volume"].squeeze().values.astype(float)

                if not _is_ttm_squeeze_on(close, high, low):
                    continue

                avg_vol = float(np.mean(volume[-20:])) if len(volume) >= 20 else float(np.mean(volume))
                base = meta[ticker]
                squeeze_on.append({
                    **base,
                    "price":      round(float(close[-1]), 2),
                    "avg_volume": int(avg_vol),
                    "volume":     int(volume[-1]),
                    "change_pct": round((close[-1] - close[-2]) / close[-2] * 100, 2) if len(close) >= 2 else 0.0,
                })
            except Exception as e:
                logger.debug(f"  {ticker} : {e}")

        time.sleep(_SLEEP_BATCH)

    logger.info(f"TTM Squeeze ON : {len(squeeze_on)}/{len(symbols)} tickers")
    return squeeze_on
