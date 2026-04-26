"""
Phase 8 : Alertes Discord avec embeds riches colorés par état.
Utilise discord-webhook pour envoyer des messages formatés.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _color(config: dict, key: str) -> int:
    return config.get("discord", {}).get("embed_colors", {}).get(key, 0x5865F2)


def _send_embed(webhook_url: str, embed) -> None:
    """Envoie un embed Discord avec gestion d'erreur."""
    try:
        from discord_webhook import DiscordWebhook
        wh = DiscordWebhook(url=webhook_url)
        wh.add_embed(embed)
        resp = wh.execute()
        if resp and hasattr(resp, "status_code") and resp.status_code >= 400:
            logger.warning(f"Discord webhook HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"Erreur envoi Discord : {e}")


def send_new_attente(ticker: str, data: dict, webhook_url: str, config: dict) -> None:
    """🟡 Nouveau ticker entré en ATTENTE."""
    try:
        from discord_webhook import DiscordEmbed
        embed = DiscordEmbed(
            title=f"🟡 Nouveau ATTENTE : {ticker}",
            description=f"**{data.get('name', ticker)}** — Setup technique validé",
            color=_color(config, "attente"),
        )
        embed.add_embed_field(name="Secteur", value=f"{data.get('sector_name', '')} ({data.get('sector', '')})", inline=True)
        embed.add_embed_field(name="Prix", value=f"${data.get('price', 0):.2f}", inline=True)
        embed.add_embed_field(name="Vol. moyen 20j", value=f"{data.get('avg_volume', 0):,}", inline=True)
        embed.add_embed_field(name="SMA20", value=f"${data.get('sma20', 0):.2f}", inline=True)
        embed.add_embed_field(name="SMA50", value=f"${data.get('sma50', 0):.2f}", inline=True)
        embed.add_embed_field(name="TTM Squeeze", value="🟡 ON", inline=True)
        embed.set_footer(text=f"Swing Dashboard • {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
        _send_embed(webhook_url, embed)
    except Exception as e:
        logger.error(f"send_new_attente {ticker} : {e}")


def send_new_setup(ticker: str, data: dict, insider_data: dict, webhook_url: str, config: dict) -> None:
    """🟠 Promotion ATTENTE → SETUP (insiders détectés)."""
    try:
        from discord_webhook import DiscordEmbed
        reporters = ", ".join(insider_data.get("reporters", [])[:3])
        embed = DiscordEmbed(
            title=f"🟠 SETUP : {ticker} — Insiders détectés",
            description=f"**{data.get('name', ticker)}** — Smart money en accumulation",
            color=_color(config, "setup"),
        )
        embed.add_embed_field(name="Achats insiders", value=str(insider_data.get("buy_count", 0)), inline=True)
        embed.add_embed_field(name="Valeur nette", value=f"${insider_data.get('net_value', 0):,.0f}", inline=True)
        embed.add_embed_field(name="Dernier achat", value=insider_data.get("last_buy_date", "N/A"), inline=True)
        embed.add_embed_field(name="Insiders", value=reporters or "N/A", inline=False)
        embed.add_embed_field(name="Secteur", value=f"{data.get('sector_name', '')} ({data.get('sector', '')})", inline=True)
        embed.add_embed_field(name="Prix", value=f"${data.get('price', 0):.2f}", inline=True)
        embed.set_footer(text=f"Swing Dashboard • {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
        _send_embed(webhook_url, embed)
    except Exception as e:
        logger.error(f"send_new_setup {ticker} : {e}")


def send_new_play(ticker: str, data: dict, trigger: dict, webhook_url: str, config: dict) -> None:
    """🟢 Promotion SETUP → PLAY (trigger détecté)."""
    try:
        from discord_webhook import DiscordEmbed
        trigger_type = trigger.get("type", "unknown")
        type_labels = {
            "volume_spike": "📈 Volume Spike",
            "news_catalyst": "📰 News Catalyseur",
            "insider_cluster": "👥 Cluster Insider",
        }
        label = type_labels.get(trigger_type, trigger_type.replace("_", " ").title())

        embed = DiscordEmbed(
            title=f"🟢 PLAY : {ticker} — {label}",
            description=f"**{data.get('name', ticker)}** — Actionnable maintenant !",
            color=_color(config, "play"),
        )
        embed.add_embed_field(name="Type de trigger", value=label, inline=True)
        embed.add_embed_field(name="Secteur", value=f"{data.get('sector_name', '')} ({data.get('sector', '')})", inline=True)
        embed.add_embed_field(name="Prix", value=f"${data.get('price', 0):.2f}", inline=True)

        if trigger_type == "volume_spike":
            embed.add_embed_field(name="Volume spike", value=f"{trigger.get('ratio', 0):.1f}× la moyenne", inline=True)
            embed.add_embed_field(name="Volume jour", value=f"{trigger.get('volume_today', 0):,}", inline=True)
        elif trigger_type == "news_catalyst":
            embed.add_embed_field(name="Headline", value=trigger.get("headline", "")[:200], inline=False)
            keywords = ", ".join(trigger.get("keywords", [])[:5])
            if keywords:
                embed.add_embed_field(name="Mots-clés", value=keywords, inline=True)
        elif trigger_type == "insider_cluster":
            embed.add_embed_field(name="Achats (7j)", value=str(trigger.get("count", 0)), inline=True)
            embed.add_embed_field(name="Valeur cluster", value=f"${trigger.get('value', 0):,.0f}", inline=True)

        embed.add_embed_field(name="Détail", value=trigger.get("detail", ""), inline=False)
        embed.set_footer(text=f"Swing Dashboard • {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
        _send_embed(webhook_url, embed)
    except Exception as e:
        logger.error(f"send_new_play {ticker} : {e}")


def send_expiry(ticker: str, old_state: str, days: int, webhook_url: str, config: dict) -> None:
    """⏰ Expiration d'un ticker."""
    try:
        from discord_webhook import DiscordEmbed
        max_days = {"ATTENTE": 15, "SETUP": 15, "PLAY": 5}.get(old_state, 15)
        embed = DiscordEmbed(
            title=f"⏰ Expiré : {ticker} — {old_state}",
            description=f"Le setup n'a pas progressé dans le délai imparti.",
            color=_color(config, "expired"),
        )
        embed.add_embed_field(name="État précédent", value=old_state, inline=True)
        embed.add_embed_field(name="Jours écoulés", value=str(days), inline=True)
        embed.add_embed_field(name="Délai max", value=f"{max_days}j", inline=True)
        embed.set_footer(text=f"Swing Dashboard • {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
        _send_embed(webhook_url, embed)
    except Exception as e:
        logger.error(f"send_expiry {ticker} : {e}")


def send_daily_summary(stats: dict, top_sectors: list[dict], webhook_url: str, config: dict) -> None:
    """📊 Résumé quotidien du scan."""
    try:
        from discord_webhook import DiscordEmbed
        sectors_text = " | ".join(
            f"#{i+1} {s['symbol']} ({s['perf_3m']:+.1%})"
            for i, s in enumerate(top_sectors[:3])
        )
        embed = DiscordEmbed(
            title="📊 Daily Scan — Résumé",
            description=f"**Secteurs forts :** {sectors_text}",
            color=_color(config, "summary"),
        )
        embed.add_embed_field(name="🟡 ATTENTE", value=str(stats.get("attente", 0)), inline=True)
        embed.add_embed_field(name="🟠 SETUP", value=str(stats.get("setup", 0)), inline=True)
        embed.add_embed_field(name="🟢 PLAY", value=str(stats.get("play", 0)), inline=True)
        embed.add_embed_field(name="Nouveaux ATTENTE", value=str(stats.get("new_attente", 0)), inline=True)
        embed.add_embed_field(name="Expirés", value=str(stats.get("expired", 0)), inline=True)
        embed.add_embed_field(name="TTM Squeeze total", value=str(stats.get("ttm_total", 0)), inline=True)
        embed.set_footer(text=f"Swing Dashboard • {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
        _send_embed(webhook_url, embed)
    except Exception as e:
        logger.error(f"send_daily_summary : {e}")


def send_discord_alerts(changes: list[dict], top_sectors: list[dict], webhook_url: str, config: dict) -> None:
    """
    Dispatch les alertes Discord pour chaque changement.
    Envoie aussi un résumé quotidien si des changes sont présents.
    """
    if not webhook_url:
        logger.warning("DISCORD_WEBHOOK non défini — alertes désactivées")
        return

    stats = {"new_attente": 0, "new_setup": 0, "new_play": 0, "expired": 0}

    for change in changes:
        ctype = change.get("type", "")
        ticker = change.get("ticker", "?")

        if ctype == "new_attente":
            send_new_attente(ticker, change.get("data", {}), webhook_url, config)
            stats["new_attente"] += 1

        elif ctype == "new_setup":
            send_new_setup(ticker, change.get("data", {}), change.get("insider_data", {}), webhook_url, config)
            stats["new_setup"] += 1

        elif ctype in ("new_play", "promoted_to_play"):
            trigger = change.get("trigger", {})
            send_new_play(ticker, change.get("data", {}), trigger, webhook_url, config)
            stats["new_play"] += 1

        elif ctype == "expired":
            send_expiry(ticker, change.get("from", "?"), change.get("days", 0), webhook_url, config)
            stats["expired"] += 1

    # Résumé si changements notables
    if any(stats.values()):
        from engine.state_manager import load_state
        state = load_state()
        all_stocks = state.get("stocks", {})
        summary_stats = {
            "attente": sum(1 for d in all_stocks.values() if d["state"] == "ATTENTE"),
            "setup": sum(1 for d in all_stocks.values() if d["state"] == "SETUP"),
            "play": sum(1 for d in all_stocks.values() if d["state"] == "PLAY"),
            **stats,
        }
        send_daily_summary(summary_stats, top_sectors, webhook_url, config)

    logger.info(
        f"Alertes Discord envoyées : {stats['new_attente']} ATTENTE, "
        f"{stats['new_setup']} SETUP, {stats['new_play']} PLAY, "
        f"{stats['expired']} expirés"
    )
