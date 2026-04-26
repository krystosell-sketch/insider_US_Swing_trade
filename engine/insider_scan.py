"""
Étape 4 du pipeline : détection d'accumulation d'insiders via SEC EDGAR (Form 4).
Utilise edgartools pour interroger la base EDGAR sans API payante.
"""

import logging
import os
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def _setup_edgar_identity() -> None:
    """Configure l'identité SEC requise par edgartools."""
    identity = os.environ.get("EDGAR_IDENTITY") or os.environ.get("SEC_IDENTITY", "")
    if identity:
        try:
            from edgar import set_identity
            set_identity(identity)
        except Exception:
            os.environ["EDGAR_IDENTITY"] = identity


def _is_10b51_plan(transaction: Any) -> bool:
    """Détecte si une transaction fait partie d'un plan 10b5-1 (vente automatisée)."""
    try:
        # Code de transaction 'F' = disposition liée à une obligation fiscale (souvent 10b5-1)
        code = str(getattr(transaction, "transaction_code", "") or "").upper()
        if code == "F":
            return True
        # Vérifier les notes de bas de page
        footnotes = str(getattr(transaction, "footnotes", "") or "").lower()
        if "10b5-1" in footnotes or "rule 10b5" in footnotes:
            return True
        return False
    except Exception:
        return False


def _parse_form4_filings(filings: Any, window_days: int, exclude_10b51: bool) -> list[dict]:
    """
    Parse les filings Form 4 et retourne les transactions d'achat valides.
    """
    cutoff = date.today() - timedelta(days=window_days)
    transactions = []

    try:
        for filing in filings:
            try:
                doc = filing.obj()
                if doc is None:
                    continue

                # Date du filing
                filing_date_raw = getattr(filing, "filing_date", None)
                if filing_date_raw is None:
                    continue
                if hasattr(filing_date_raw, "date"):
                    filing_date = filing_date_raw.date()
                else:
                    from datetime import datetime
                    filing_date = datetime.strptime(str(filing_date_raw)[:10], "%Y-%m-%d").date()

                if filing_date < cutoff:
                    continue

                # Reporter info
                reporter_name = str(getattr(doc, "reporting_owner_name", "") or "")

                # Transactions
                tx_list = getattr(doc, "transactions", None) or []
                for tx in tx_list:
                    code = str(getattr(tx, "transaction_code", "") or "").upper()
                    # "P" = achat open-market
                    if code != "P":
                        continue
                    if exclude_10b51 and _is_10b51_plan(tx):
                        continue

                    shares = float(getattr(tx, "transaction_shares", 0) or 0)
                    price = float(getattr(tx, "transaction_price_per_share", 0) or 0)
                    value = shares * price

                    tx_date_raw = getattr(tx, "transaction_date", None)
                    if tx_date_raw is not None:
                        if hasattr(tx_date_raw, "date"):
                            tx_date = tx_date_raw.date()
                        else:
                            from datetime import datetime
                            tx_date = datetime.strptime(str(tx_date_raw)[:10], "%Y-%m-%d").date()
                    else:
                        tx_date = filing_date

                    if tx_date < cutoff:
                        continue

                    transactions.append({
                        "date": str(tx_date),
                        "reporter": reporter_name,
                        "shares": shares,
                        "price": price,
                        "value": value,
                    })

            except Exception as e:
                logger.debug(f"  Parsing filing échoué : {e}")
                continue

    except Exception as e:
        logger.warning(f"Itération filings échouée : {e}")

    return transactions


def scan_insider_accumulation(ticker: str, config: dict) -> dict | None:
    """
    Vérifie si un ticker présente une accumulation d'insiders (Form 4).
    Retourne un dict avec les détails si les seuils sont atteints, None sinon.
    """
    _setup_edgar_identity()
    ins_cfg = config["insiders"]
    window_days = ins_cfg["window_days"]
    min_buys = ins_cfg["min_buy_transactions"]
    min_value = ins_cfg["min_net_value"]
    exclude_10b51 = ins_cfg["exclude_10b51"]

    try:
        from edgar import Company
    except ImportError:
        logger.error("edgartools non installé. Lancer : pip install edgartools")
        return None

    try:
        company = Company(ticker)
        cutoff = (date.today() - timedelta(days=window_days)).strftime("%Y-%m-%d")
        filings = company.get_filings(form="4").filter(date=f"{cutoff}:")

        if filings is None:
            return None

        transactions = _parse_form4_filings(filings, window_days, exclude_10b51)

        if not transactions:
            return None

        buy_count = len(transactions)
        net_value = sum(t["value"] for t in transactions)
        reporters = list({t["reporter"] for t in transactions if t["reporter"]})

        if buy_count >= min_buys and net_value >= min_value:
            logger.debug(
                f"  {ticker} : {buy_count} achats insiders / ${net_value:,.0f} "
                f"— {', '.join(reporters[:3])}"
            )
            return {
                "buy_count": buy_count,
                "net_value": round(net_value, 2),
                "reporters": reporters,
                "transactions": sorted(transactions, key=lambda x: x["date"], reverse=True),
                "last_buy_date": transactions[0]["date"] if transactions else None,
            }

    except Exception as e:
        logger.warning(f"{ticker} : erreur scan insider — {e}")

    return None


def check_insider_cluster(ticker: str, config: dict) -> dict | None:
    """
    Vérifie si ≥ N achats d'insiders ont eu lieu dans les 7 derniers jours.
    Utilisé comme trigger PLAY.
    """
    _setup_edgar_identity()
    ins_cfg = config["insiders"]
    cluster_threshold = ins_cfg["cluster_buys_7d"]
    exclude_10b51 = ins_cfg["exclude_10b51"]

    try:
        from edgar import Company
        company = Company(ticker)
        cutoff_7d = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
        filings = company.get_filings(form="4").filter(date=f"{cutoff_7d}:")

        if filings is None:
            return None

        transactions = _parse_form4_filings(filings, window_days=7, exclude_10b51=exclude_10b51)

        if len(transactions) >= cluster_threshold:
            return {
                "count": len(transactions),
                "value": sum(t["value"] for t in transactions),
                "type": "insider_cluster",
            }

    except Exception as e:
        logger.debug(f"{ticker} : erreur cluster insider — {e}")

    return None
