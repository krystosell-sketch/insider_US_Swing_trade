"""
Surveillance intraday : détection de news catalyseurs via Finviz.
Analyse les titres de news pour identifier des événements matériels.
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Mots-clés indiquant un catalyseur matériel (ordre de priorité)
_CATALYST_KEYWORDS = [
    # Earnings positifs
    "beats", "beat", "exceeds", "surpasses", "record",
    # Approbations réglementaires
    "fda", "approval", "approved", "clearance", "granted",
    # Croissance business
    "contract", "partnership", "agreement", "deal", "wins", "awarded",
    "acquisition", "merger", "acquires",
    # Fondamentaux
    "guidance", "raises", "upgraded", "buyback", "dividend",
    # Données cliniques/scientifiques
    "trial", "data", "results", "positive",
]


def check_news_catalyst(ticker: str, config: dict) -> dict | None:
    """
    Vérifie si un ticker a reçu une news catalyseur dans les N dernières heures.
    Utilise finvizfinance pour récupérer les titres de news.

    Retourne un dict avec la news, ou None.
    """
    lookback_hours = config["triggers"]["news_lookback_hours"]
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)

    try:
        from finvizfinance.quote import finvizfinance
        stock = finvizfinance(ticker)
        news_df = stock.ticker_news()

        if news_df is None or news_df.empty:
            return None

    except Exception as e:
        logger.debug(f"{ticker} : erreur Finviz news — {e}")
        return None

    # Colonnes attendues : Date, Title, Link
    try:
        for _, row in news_df.iterrows():
            headline = str(row.get("Title", "") or "")
            date_raw = row.get("Date", "")

            # Parser la date Finviz (format : "Apr-26-24 08:30AM" ou datetime)
            pub_time = _parse_finviz_date(date_raw)
            if pub_time is None or pub_time < cutoff:
                continue

            # Détecter catalyseur
            headline_lower = headline.lower()
            matched_keywords = [kw for kw in _CATALYST_KEYWORDS if kw in headline_lower]

            if matched_keywords:
                logger.info(f"{ticker} : news catalyseur détectée — {headline[:80]}")
                return {
                    "type": "news_catalyst",
                    "headline": headline,
                    "keywords": matched_keywords,
                    "published_at": pub_time.isoformat() if pub_time else None,
                    "detail": f"News : {headline[:100]}",
                }

    except Exception as e:
        logger.debug(f"{ticker} : erreur parsing news — {e}")

    return None


def _parse_finviz_date(date_raw) -> datetime | None:
    """Parse les formats de date Finviz en datetime UTC."""
    if date_raw is None:
        return None

    if isinstance(date_raw, datetime):
        if date_raw.tzinfo is None:
            return date_raw.replace(tzinfo=timezone.utc)
        return date_raw

    date_str = str(date_raw).strip()
    if not date_str:
        return None

    formats = [
        "%b-%d-%y %I:%M%p",   # Apr-26-24 08:30AM
        "%b-%d-%y %I:%M %p",  # Apr-26-24 08:30 AM
        "%Y-%m-%d %H:%M:%S",  # 2024-04-26 08:30:00
        "%Y-%m-%dT%H:%M:%S",  # ISO
        "%b-%d-%y",            # Apr-26-24 (date seule)
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    logger.debug(f"Format de date Finviz non reconnu : '{date_str}'")
    return None
