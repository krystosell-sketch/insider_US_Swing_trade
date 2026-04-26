"""
Surveillance intraday : détection de volume spike.
Volume du jour courant > 1.5× la moyenne 20j daily.
"""

import logging
from datetime import date

import numpy as np

logger = logging.getLogger(__name__)

_EXCHANGES = ["NASDAQ", "NYSE", "AMEX", "NYSE ARCA"]


def _get_tv(config: dict):
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


def check_volume_spike(ticker: str, avg_volume_20d: float, config: dict) -> dict | None:
    """
    Vérifie si le volume intraday courant dépasse 1.5× la moyenne 20j.
    Utilise les données 15min pour estimer le volume du jour.

    Retourne un dict avec les détails du spike, ou None.
    """
    spike_ratio = config["triggers"]["volume_spike_ratio"]

    if avg_volume_20d <= 0:
        logger.debug(f"{ticker} : avg_volume_20d=0, spike non vérifiable")
        return None

    tv = _get_tv(config)
    if tv is None:
        return None

    # Essayer données 15min intraday
    for exchange in _EXCHANGES:
        try:
            from tvDatafeed import Interval
            df = tv.get_hist(
                symbol=ticker,
                exchange=exchange,
                interval=Interval.in_15_minute,
                n_bars=40,  # ~10h de séance (40 × 15min)
            )
            if df is None or len(df) < 2:
                continue

            # Filtrer les barres du jour courant
            today = str(date.today())
            df_today = df[df.index.strftime("%Y-%m-%d") == today]

            if df_today.empty:
                # Prendre les 26 dernières barres comme proxy d'une séance (6.5h)
                df_today = df.tail(26)

            volume_today = int(df_today["volume"].sum())
            ratio = volume_today / avg_volume_20d if avg_volume_20d > 0 else 0

            logger.debug(f"{ticker} : volume jour {volume_today:,} / avg20d {avg_volume_20d:,.0f} = {ratio:.2f}x")

            if ratio >= spike_ratio:
                return {
                    "type": "volume_spike",
                    "ratio": round(ratio, 2),
                    "volume_today": volume_today,
                    "avg_volume_20d": int(avg_volume_20d),
                    "detail": f"Volume {ratio:.1f}x la moyenne 20j ({volume_today:,} vs {avg_volume_20d:,.0f})",
                }
            return None  # Données trouvées, pas de spike

        except Exception as e:
            logger.debug(f"{ticker}@{exchange} : {e}")
            continue

    logger.debug(f"{ticker} : données intraday indisponibles")
    return None
