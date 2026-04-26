"""
Étape 2 du pipeline daily : récupération des tickers en TTM Squeeze ON sur Barchart.
Méthode : session requests → cookie XSRF → double-décodage → appel API JSON interne.
"""

import logging
import time
from urllib.parse import unquote

import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.barchart.com"
_IDEA_URL = f"{_BASE_URL}/investing-ideas/ttm-squeeze/on"
_API_URL = f"{_BASE_URL}/proxies/core-api/v1/quotes/get"

_FIELDS = ",".join([
    "symbol", "symbolName", "lastPrice", "priceChange", "percentChange",
    "percentChange5d", "tradeTime", "symbolCode", "symbolType",
    "averageVolume", "volume", "sector", "industry",
])

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _IDEA_URL,
    "Origin": _BASE_URL,
}

_MAX_RETRIES = 3
_PAGE_LIMIT = 100
_SLEEP_BETWEEN_PAGES = 1.2


def _get_xsrf_token(session: requests.Session) -> str | None:
    """Charge la page principale pour obtenir le cookie XSRF-TOKEN."""
    for attempt in range(_MAX_RETRIES):
        try:
            resp = session.get(_IDEA_URL, headers={"User-Agent": _HEADERS["User-Agent"]}, timeout=20)
            resp.raise_for_status()
            raw = session.cookies.get("XSRF-TOKEN")
            if raw:
                token = unquote(unquote(raw))
                logger.info("XSRF-TOKEN obtenu")
                return token
            logger.warning(f"Cookie XSRF-TOKEN absent (tentative {attempt+1})")
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"Erreur XSRF (tentative {attempt+1}) : {e} — retry dans {wait}s")
            time.sleep(wait)
    return None


def _fetch_page(session: requests.Session, token: str, page: int, order_by: str, order_dir: str, list_name: str = "ttm.squeeze.long") -> dict | None:
    """Appel à l'API JSON interne de Barchart pour une page donnée."""
    params = {
        "fields": _FIELDS,
        "list": list_name,
        "orderBy": order_by,
        "orderDir": order_dir,
        "page": page,
        "limit": _PAGE_LIMIT,
        "raw": "1",
        "meta": "field.shortName,lists.lastUpdate",
    }
    headers = {**_HEADERS, "x-xsrf-token": token}

    for attempt in range(_MAX_RETRIES):
        try:
            resp = session.get(_API_URL, params=params, headers=headers, timeout=20)
            if resp.status_code == 403:
                logger.warning("HTTP 403 — token expiré, re-fetch XSRF")
                new_token = _get_xsrf_token(session)
                if new_token:
                    headers["x-xsrf-token"] = new_token
                continue
            resp.raise_for_status()
            data = resp.json()
            # Log de débogage : structure de la réponse
            if page == 1:
                total = data.get("meta", {}).get("total", "?")
                logger.info(f"API Barchart [{list_name}] — total={total}, keys={list(data.keys())}")
            return data
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"Erreur page {page} (tentative {attempt+1}) : {e} — retry dans {wait}s")
            time.sleep(wait)
    return None


def _parse_ticker(row: dict) -> dict | None:
    """Extrait les champs utiles d'une ligne de résultat Barchart."""
    try:
        raw = row.get("raw", {})
        return {
            "symbol": raw.get("symbol", "").upper().strip(),
            "name": raw.get("symbolName", ""),
            "price": float(raw.get("lastPrice", 0) or 0),
            "change_pct": float(raw.get("percentChange", 0) or 0),
            "change_5d_pct": float(raw.get("percentChange5d", 0) or 0),
            "volume": int(raw.get("volume", 0) or 0),
            "avg_volume": int(raw.get("averageVolume", 0) or 0),
            "sector_barchart": raw.get("sector", ""),
            "industry": raw.get("industry", ""),
        }
    except Exception as e:
        logger.debug(f"Parsing ticker échoué : {e} — {row}")
        return None


def get_ttm_squeeze_tickers(config: dict) -> list[dict]:
    """
    Scrape Barchart pour récupérer tous les tickers en TTM Squeeze ON.
    Essaie plusieurs valeurs de list en cascade jusqu'à obtenir des données.
    """
    order_by = config["ttm_squeeze"]["order_by"]
    order_dir = config["ttm_squeeze"]["order_dir"]

    # Ordre de priorité des list Barchart à essayer
    list_candidates = [
        "ttm.squeeze.long",       # LONG SQUEEZE tab (squeeze actif haussier)
        "ttm.squeeze.on",         # alias possible
        "ttm.squeeze.triggered",  # TRIGGERED tab (vient de se déclencher)
    ]

    session = requests.Session()
    token = _get_xsrf_token(session)
    if not token:
        logger.error("Impossible d'obtenir le token XSRF — abandon TTM loader")
        return []

    tickers = []

    for list_name in list_candidates:
        logger.info(f"Essai list Barchart : '{list_name}'")
        page = 1
        tickers = []

        while True:
            logger.info(f"TTM Squeeze [{list_name}] page {page}")
            data = _fetch_page(session, token, page, order_by, order_dir, list_name)

            if data is None:
                logger.error(f"Échec récupération page {page} — arrêt pagination")
                break

            rows = data.get("data", [])
            if not rows:
                logger.info(f"Page {page} vide — fin de pagination")
                break

            for row in rows:
                t = _parse_ticker(row)
                if t and t["symbol"]:
                    tickers.append(t)

            total = data.get("meta", {}).get("total", 0)
            logger.info(f"  Page {page} : {len(rows)} tickers (total Barchart : {total})")

            if len(tickers) >= total or len(rows) < _PAGE_LIMIT:
                break

            page += 1
            time.sleep(_SLEEP_BETWEEN_PAGES)

        if tickers:
            logger.info(f"Données obtenues avec list='{list_name}' : {len(tickers)} tickers bruts")
            break
        else:
            logger.warning(f"list='{list_name}' retourne 0 tickers — essai suivant")

    # Dédupliquer (garde le premier)
    seen = set()
    unique = []
    for t in tickers:
        if t["symbol"] not in seen:
            seen.add(t["symbol"])
            unique.append(t)

    # Filtrer les entrées sans symbole valide
    unique = [t for t in unique if len(t["symbol"]) <= 5 and t["symbol"].isalpha()]

    logger.info(f"Total TTM Squeeze ON : {len(unique)} tickers")
    return unique
