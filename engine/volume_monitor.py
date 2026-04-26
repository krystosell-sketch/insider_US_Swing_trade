"""
Surveillance intraday : détection de volume spike.
Volume du jour courant > 1.5× la moyenne 20j daily.
"""

import logging
from datetime import date

import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)


def check_volume_spike(ticker: str, avg_volume_20d: float, config: dict) -> dict | None:
    """
    Vérifie si le volume intraday courant dépasse spike_ratio × la moyenne 20j.
    Utilise les données 5min pour estimer le volume du jour.
    """
    spike_ratio = config["triggers"]["volume_spike_ratio"]

    if avg_volume_20d <= 0:
        logger.debug(f"{ticker} : avg_volume_20d=0, spike non vérifiable")
        return None

    try:
        # Données intraday 5min du jour courant
        df = yf.download(ticker, period="1d", interval="5m", progress=False, auto_adjust=True)
        if df is None or df.empty:
            logger.debug(f"{ticker} : données intraday indisponibles")
            return None

        volume_today = int(df["Volume"].sum())
        ratio = volume_today / avg_volume_20d

        logger.debug(f"{ticker} : vol jour {volume_today:,} / avg20d {avg_volume_20d:,.0f} = {ratio:.2f}x")

        if ratio >= spike_ratio:
            return {
                "type": "volume_spike",
                "ratio": round(ratio, 2),
                "volume_today": volume_today,
                "avg_volume_20d": int(avg_volume_20d),
                "detail": f"Volume {ratio:.1f}x la moyenne 20j ({volume_today:,} vs {avg_volume_20d:,.0f})",
            }

    except Exception as e:
        logger.debug(f"{ticker} : erreur volume monitor — {e}")

    return None
