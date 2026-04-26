"""
Étape 2 du pipeline daily : calcul du TTM Squeeze sur l'univers S&P 500 + mid-caps.
Remplace le scraping Barchart (API bloquée sans login).
TTM Squeeze ON = Bandes de Bollinger (20,2) à l'intérieur des Bandes de Keltner (20, 1.5×ATR14).
"""

import logging
import time
from io import StringIO

import numpy as np
import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

_SLEEP_BATCH = 1.0  # secondes entre batches yfinance
_BATCH_SIZE = 50    # tickers par batch


def _get_sp500_tickers() -> list[str]:
    """Récupère les tickers du S&P 500 depuis Wikipedia."""
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        resp = requests.get(url, timeout=15)
        tables = pd.read_html(StringIO(resp.text))
        tickers = tables[0]["Symbol"].tolist()
        # Nettoyer les tickers (BRK.B → BRK-B pour yfinance)
        tickers = [t.replace(".", "-") for t in tickers]
        logger.info(f"S&P 500 : {len(tickers)} tickers récupérés depuis Wikipedia")
        return tickers
    except Exception as e:
        logger.error(f"Erreur récupération S&P 500 : {e}")
        return []


def _get_sp400_tickers() -> list[str]:
    """Récupère les tickers du S&P 400 Mid-Cap depuis Wikipedia."""
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
        resp = requests.get(url, timeout=15)
        tables = pd.read_html(StringIO(resp.text))
        tickers = tables[0]["Symbol"].tolist()
        tickers = [t.replace(".", "-") for t in tickers]
        logger.info(f"S&P 400 Mid-Cap : {len(tickers)} tickers récupérés")
        return tickers
    except Exception as e:
        logger.warning(f"S&P 400 indisponible : {e}")
        return []


def _compute_ema(values: np.ndarray, period: int) -> float:
    """EMA simple (méthode Wilder)."""
    if len(values) < period:
        return float(np.mean(values))
    k = 2 / (period + 1)
    ema = float(np.mean(values[:period]))
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _is_ttm_squeeze_on(close: np.ndarray, high: np.ndarray, low: np.ndarray) -> bool:
    """
    Calcule si le TTM Squeeze est ON.
    Squeeze ON = Bollinger Bands (20,2) entièrement à l'intérieur des Keltner Channels (20 EMA, 1.5×ATR14).
    """
    if len(close) < 21:
        return False

    # Bollinger Bands (20 périodes, 2 écarts-types)
    sma20 = float(np.mean(close[-20:]))
    std20 = float(np.std(close[-20:], ddof=1))
    bb_upper = sma20 + 2.0 * std20
    bb_lower = sma20 - 2.0 * std20
    bb_width = bb_upper - bb_lower

    if bb_width == 0:
        return False

    # Keltner Channels (EMA20, ATR14 × 1.5)
    ema20 = _compute_ema(close[-21:], 20)

    # ATR14
    tr_list = []
    for i in range(-14, 0):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        tr_list.append(tr)
    atr14 = float(np.mean(tr_list))

    kc_upper = ema20 + 1.5 * atr14
    kc_lower = ema20 - 1.5 * atr14

    # Squeeze ON si BB entièrement dans KC
    return bb_upper < kc_upper and bb_lower > kc_lower


def _download_batch(tickers: list[str]) -> dict:
    """
    Télécharge les données OHLCV pour un batch de tickers.
    Retourne un dict {ticker: df}.
    """
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
            # yfinance retourne un DataFrame simple pour 1 ticker
            if data is not None and not data.empty:
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
        logger.warning(f"Batch download échoué : {e}")
        return {}


def get_ttm_squeeze_tickers(config: dict) -> list[dict]:
    """
    Calcule le TTM Squeeze sur l'univers S&P 500 + S&P 400.
    Retourne les tickers dont le squeeze est actuellement ON.
    """
    # Univers de tickers
    tickers = _get_sp500_tickers()
    tickers += _get_sp400_tickers()
    tickers = list(dict.fromkeys(tickers))  # dédupliquer en gardant l'ordre
    logger.info(f"Univers total : {len(tickers)} tickers à analyser")

    if not tickers:
        logger.error("Aucun ticker disponible — abandon")
        return []

    squeeze_on = []
    batches = [tickers[i:i + _BATCH_SIZE] for i in range(0, len(tickers), _BATCH_SIZE)]

    for batch_num, batch in enumerate(batches, 1):
        logger.info(f"Batch {batch_num}/{len(batches)} ({len(batch)} tickers)")
        batch_data = _download_batch(batch)

        for ticker, df in batch_data.items():
            try:
                close = df["Close"].squeeze().values.astype(float)
                high = df["High"].squeeze().values.astype(float)
                low = df["Low"].squeeze().values.astype(float)
                volume = df["Volume"].squeeze().values.astype(float)

                if not _is_ttm_squeeze_on(close, high, low):
                    continue

                avg_vol = float(np.mean(volume[-20:])) if len(volume) >= 20 else 0.0
                squeeze_on.append({
                    "symbol": ticker,
                    "name": ticker,
                    "price": round(float(close[-1]), 2),
                    "change_pct": round((close[-1] - close[-2]) / close[-2] * 100, 2) if len(close) >= 2 else 0.0,
                    "change_5d_pct": round((close[-1] - close[-6]) / close[-6] * 100, 2) if len(close) >= 6 else 0.0,
                    "volume": int(volume[-1]),
                    "avg_volume": int(avg_vol),
                    "sector_barchart": "",  # récupéré dans filters.py via yfinance.Ticker.info
                    "industry": "",
                })
            except Exception as e:
                logger.debug(f"  {ticker} : erreur calcul squeeze — {e}")
                continue

        time.sleep(_SLEEP_BATCH)

    logger.info(f"TTM Squeeze ON : {len(squeeze_on)}/{len(tickers)} tickers")
    return squeeze_on
