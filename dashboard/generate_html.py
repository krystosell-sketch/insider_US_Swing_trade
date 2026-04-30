"""
Phase 9 : Génération du dashboard HTML statique avec Plotly.
Thème sombre, 3 colonnes (ATTENTE/SETUP/PLAY), feed d'événements, auto-refresh.
Tout est inline dans un seul fichier HTML (pas de CDN).
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "output"

# Palette thème sombre
COLORS = {
    "bg": "#1a1a2e",
    "card": "#16213e",
    "card2": "#0f3460",
    "text": "#e0e0e0",
    "subtext": "#a0a0b0",
    "attente": "#FEE75C",
    "setup": "#F0883E",
    "play": "#57F287",
    "expired": "#95A5A6",
    "border": "#2a2a4a",
    "accent": "#5865F2",
}


# ──────────────────────────────────────────────
# Tables Plotly
# ──────────────────────────────────────────────

def _ticker_link(symbol: str) -> str:
    url = f"https://www.tradingview.com/chart/?symbol={symbol}"
    return f'<a href="{url}" target="_blank" class="ticker-link">{symbol}</a>'


def _make_attente_table(stocks: dict) -> str:
    rows = [
        (ticker, d)
        for ticker, d in stocks.items()
        if d.get("state") == "ATTENTE"
    ]
    rows.sort(key=lambda x: x[1].get("since", ""), reverse=True)

    if not rows:
        return _empty_table("Aucun titre en ATTENTE", COLORS["attente"])

    header = "<tr><th>Ticker</th><th>Secteur</th><th>Prix</th><th>Vol Moy 20j</th><th>SMA20</th><th>SMA50</th><th>Jours</th></tr>"
    body_rows = []
    for ticker, d in rows:
        body_rows.append(
            f"<tr>"
            f"<td>{_ticker_link(ticker)}</td>"
            f"<td>{d.get('sector', '')}</td>"
            f"<td class='num'>${d.get('price', 0):.2f}</td>"
            f"<td class='num'>{d.get('avg_volume', 0):,}</td>"
            f"<td class='num'>${d.get('sma20', 0):.2f}</td>"
            f"<td class='num'>${d.get('sma50', 0):.2f}</td>"
            f"<td class='ctr'>{_days_since(d.get('since', ''))}</td>"
            f"</tr>"
        )
    return f'<table class="data-table"><thead>{header}</thead><tbody>{"".join(body_rows)}</tbody></table>'


def _make_setup_table(stocks: dict) -> str:
    rows = [
        (ticker, d)
        for ticker, d in stocks.items()
        if d.get("state") == "SETUP"
    ]
    rows.sort(key=lambda x: x[1].get("since", ""), reverse=True)

    if not rows:
        return _empty_table("Aucun titre en SETUP", COLORS["setup"])

    header = "<tr><th>Ticker</th><th>Secteur</th><th>Prix</th><th>Achats Insider</th><th>Valeur $</th><th>Dernier Achat</th><th>Jours</th></tr>"
    body_rows = []
    for ticker, d in rows:
        ins = d.get("insider_data") or {}
        buy_count = ins.get("buy_count", 0)
        net_value = f"${ins.get('net_value', 0):,.0f}" if ins else "N/A"
        last_buy = ins.get("last_buy_date", "N/A") if ins else "N/A"
        body_rows.append(
            f"<tr>"
            f"<td>{_ticker_link(ticker)}</td>"
            f"<td>{d.get('sector', '')}</td>"
            f"<td class='num'>${d.get('price', 0):.2f}</td>"
            f"<td class='ctr'>{buy_count}</td>"
            f"<td class='num'>{net_value}</td>"
            f"<td class='ctr'>{last_buy}</td>"
            f"<td class='ctr'>{_days_since(d.get('since', ''))}</td>"
            f"</tr>"
        )
    return f'<table class="data-table"><thead>{header}</thead><tbody>{"".join(body_rows)}</tbody></table>'


def _make_play_table(stocks: dict) -> str:
    rows = [
        (ticker, d)
        for ticker, d in stocks.items()
        if d.get("state") == "PLAY"
    ]
    rows.sort(key=lambda x: x[1].get("since", ""), reverse=True)

    if not rows:
        return _empty_table("Aucun titre en PLAY", COLORS["play"])

    type_labels = {
        "volume_spike":   "📈 Vol Spike",
        "news_catalyst":  "📰 News",
        "insider_cluster": "👥 Cluster",
    }

    header = "<tr><th>Ticker</th><th>Secteur</th><th>Prix</th><th>Trigger</th><th>Détail</th><th>Jours</th></tr>"
    body_rows = []
    for ticker, d in rows:
        td = d.get("trigger_data") or {}
        ttype = type_labels.get(td.get("type", ""), td.get("type", "N/A"))
        detail = (td.get("detail", "") or "N/A")[:60]
        body_rows.append(
            f"<tr>"
            f"<td>{_ticker_link(ticker)}</td>"
            f"<td>{d.get('sector', '')}</td>"
            f"<td class='num'>${d.get('price', 0):.2f}</td>"
            f"<td class='ctr'>{ttype}</td>"
            f"<td>{detail}</td>"
            f"<td class='ctr'>{_days_since(d.get('since', ''))}</td>"
            f"</tr>"
        )
    return f'<table class="data-table"><thead>{header}</thead><tbody>{"".join(body_rows)}</tbody></table>'


def _empty_table(message: str, color: str) -> str:
    """Table vide avec message."""
    fig = go.Figure(data=[go.Table(
        header=dict(values=[""], fill_color=COLORS["card2"], font=dict(color=color), height=30),
        cells=dict(values=[[message]], fill_color=COLORS["card"], font=dict(color=COLORS["subtext"], size=12), height=40),
    )])
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor=COLORS["bg"],
        height=80,
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, config={"displayModeBar": False})


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _days_since(since_str: str) -> str:
    if not since_str:
        return "N/A"
    try:
        from datetime import date
        since = date.fromisoformat(since_str[:10])
        d = (date.today() - since).days
        return f"{d}j"
    except Exception:
        return "N/A"


def _format_history(history: list, hours: int = 48) -> str:
    """Génère le HTML du feed d'événements."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    events = []

    state_icons = {"ATTENTE": "🟡", "SETUP": "🟠", "PLAY": "🟢"}

    for event in reversed(history):
        try:
            ts_str = event.get("ts", "")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts < cutoff:
                continue

            ticker = event.get("ticker", "?")
            from_s = event.get("from")
            to_s = event.get("to")
            reason = event.get("reason", "")
            hour = ts.strftime("%H:%M")

            if to_s is None:
                icon = "⏰"
                msg = f"<span style='color:{COLORS['expired']}'>{ticker}</span> expiré depuis {from_s or '?'}"
            elif from_s is None:
                icon = state_icons.get(to_s, "▸")
                color = COLORS.get(to_s.lower(), COLORS["text"])
                msg = f"<span style='color:{color}'>{ticker}</span> → {to_s} ({reason})"
            else:
                icon = state_icons.get(to_s, "▸")
                color = COLORS.get(to_s.lower(), COLORS["text"])
                msg = f"<span style='color:{color}'>{ticker}</span> : {from_s} → {to_s} — {reason[:80]}"

            events.append(
                f"<div class='event'>"
                f"<span class='event-time'>[{hour}]</span> {icon} {msg}"
                f"</div>"
            )
        except Exception:
            continue

    if not events:
        return "<div class='event' style='color: var(--subtext)'>Aucun événement dans les 48 dernières heures</div>"

    return "\n".join(events[:50])  # Max 50 entrées affichées


# ──────────────────────────────────────────────
# Génération principale
# ──────────────────────────────────────────────

def generate_html(state: dict, top_sectors: list[dict], config: dict) -> None:
    """Génère output/index.html complet avec toutes les données de state."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    stocks = state.get("stocks", {})
    history = state.get("history", [])
    last_updated = state.get("last_updated") or datetime.utcnow().isoformat() + "Z"

    # Comptes par état
    counts = {
        "attente": sum(1 for d in stocks.values() if d.get("state") == "ATTENTE"),
        "setup": sum(1 for d in stocks.values() if d.get("state") == "SETUP"),
        "play": sum(1 for d in stocks.values() if d.get("state") == "PLAY"),
    }

    # Top secteurs
    sectors_html = _format_sectors(top_sectors)

    # Tables Plotly
    table_attente = _make_attente_table(stocks)
    table_setup = _make_setup_table(stocks)
    table_play = _make_play_table(stocks)

    # Historique
    history_days = config.get("dashboard", {}).get("history_days", 7)
    history_html = _format_history(history, hours=history_days * 24)

    # Timestamp affiché
    try:
        from zoneinfo import ZoneInfo
        ts = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
        ts_montreal = ts.astimezone(ZoneInfo("America/Toronto"))
        ts_display = ts_montreal.strftime("%Y-%m-%d %H:%M") + " (Montréal)"
    except Exception:
        ts_display = last_updated

    # Plotly JS inline
    plotly_js = pio.to_html(go.Figure(), full_html=True, include_plotlyjs=True)
    import re
    js_match = re.search(r'<script[^>]*>([\s\S]*?plotly[\s\S]*?)</script>', plotly_js)
    plotly_js_content = js_match.group(0) if js_match else '<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>'

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="300">
  <title>Swing Trading Dashboard</title>
  {plotly_js_content}
  <style>
    :root {{
      --bg: {COLORS["bg"]};
      --card: {COLORS["card"]};
      --card2: {COLORS["card2"]};
      --text: {COLORS["text"]};
      --subtext: {COLORS["subtext"]};
      --attente: {COLORS["attente"]};
      --setup: {COLORS["setup"]};
      --play: {COLORS["play"]};
      --expired: {COLORS["expired"]};
      --border: {COLORS["border"]};
      --accent: {COLORS["accent"]};
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }}
    .header {{
      background: var(--card);
      border-bottom: 1px solid var(--border);
      padding: 16px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .header h1 {{
      font-size: 20px;
      font-weight: 700;
      color: var(--text);
      letter-spacing: 0.5px;
    }}
    .header-right {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 4px;
    }}
    .timestamp {{
      color: var(--subtext);
      font-size: 12px;
    }}
    .sectors-bar {{
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
    }}
    .sector-badge {{
      background: var(--card2);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 4px 12px;
      font-size: 13px;
      font-weight: 600;
    }}
    .sector-badge .rank {{ color: var(--subtext); margin-right: 4px; }}
    .sector-badge .sym {{ color: var(--accent); }}
    .sector-badge .perf {{ color: var(--play); }}
    .main {{
      padding: 20px 24px;
      max-width: 1600px;
      margin: 0 auto;
    }}
    .columns {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 16px;
      margin-bottom: 24px;
    }}
    @media (max-width: 1100px) {{
      .columns {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 768px) {{
      .header {{ padding: 12px 16px; }}
      .main {{ padding: 12px 16px; }}
    }}
    .column {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
    }}
    .column-header {{
      padding: 12px 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
    }}
    .column-title {{
      font-size: 15px;
      font-weight: 700;
    }}
    .column-count {{
      background: var(--card2);
      border-radius: 12px;
      padding: 2px 10px;
      font-size: 13px;
      font-weight: 600;
    }}
    .attente-col .column-title, .attente-col .column-count {{ color: var(--attente); }}
    .setup-col .column-title, .setup-col .column-count {{ color: var(--setup); }}
    .play-col .column-title, .play-col .column-count {{ color: var(--play); }}
    .column-body {{ padding: 8px; }}
    .history-section {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
    }}
    .history-header {{
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      font-size: 14px;
      font-weight: 700;
      color: var(--text);
    }}
    .history-feed {{
      padding: 12px 16px;
      max-height: 300px;
      overflow-y: auto;
    }}
    .event {{
      padding: 5px 0;
      border-bottom: 1px solid var(--border);
      font-size: 13px;
      color: var(--text);
    }}
    .event:last-child {{ border-bottom: none; }}
    .event-time {{
      color: var(--subtext);
      font-family: monospace;
      font-size: 12px;
      margin-right: 6px;
    }}
    .refresh-notice {{
      text-align: center;
      padding: 12px;
      color: var(--subtext);
      font-size: 12px;
    }}
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    .data-table th {{
      background: var(--card2);
      padding: 8px 10px;
      text-align: left;
      font-size: 12px;
      font-weight: 600;
      color: var(--subtext);
      white-space: nowrap;
    }}
    .data-table td {{
      background: var(--card);
      padding: 6px 10px;
      border-bottom: 1px solid var(--border);
      color: var(--text);
      vertical-align: middle;
    }}
    .data-table tr:last-child td {{ border-bottom: none; }}
    .data-table td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .data-table td.ctr {{ text-align: center; }}
    .ticker-link {{
      color: var(--accent);
      text-decoration: none;
      font-weight: 700;
      letter-spacing: 0.5px;
    }}
    .ticker-link:hover {{ text-decoration: underline; color: #fff; }}
  </style>
</head>
<body>

<div class="header">
  <h1>🔥 Swing Trading Dashboard</h1>
  <div class="header-right">
    <div class="timestamp">📅 Dernière mise à jour : {ts_display}</div>
    <div class="sectors-bar">{sectors_html}</div>
  </div>
</div>

<div class="main">
  <div class="columns">

    <div class="column attente-col">
      <div class="column-header">
        <span class="column-title">🟡 ATTENTE</span>
        <span class="column-count">{counts["attente"]}</span>
      </div>
      <div class="column-body">{table_attente}</div>
    </div>

    <div class="column setup-col">
      <div class="column-header">
        <span class="column-title">🟠 SETUP</span>
        <span class="column-count">{counts["setup"]}</span>
      </div>
      <div class="column-body">{table_setup}</div>
    </div>

    <div class="column play-col">
      <div class="column-header">
        <span class="column-title">🟢 PLAY</span>
        <span class="column-count">{counts["play"]}</span>
      </div>
      <div class="column-body">{table_play}</div>
    </div>

  </div>

  <div class="history-section">
    <div class="history-header">📰 Historique des événements ({history_days}j)</div>
    <div class="history-feed">
      {history_html}
    </div>
  </div>

  <div class="refresh-notice">Auto-refresh toutes les 5 minutes</div>
</div>

</body>
</html>"""

    output_path = OUTPUT_DIR / "index.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"Dashboard généré : {output_path} ({len(html) // 1024} KB)")


def _format_sectors(top_sectors: list[dict]) -> str:
    """HTML des badges de secteurs."""
    if not top_sectors:
        return "<span style='color: var(--subtext)'>Secteurs non calculés</span>"
    badges = []
    for i, s in enumerate(top_sectors[:3], 1):
        perf = s.get("perf_3m", 0)
        sign = "+" if perf >= 0 else ""
        badges.append(
            f"<div class='sector-badge'>"
            f"<span class='rank'>#{i}</span>"
            f"<span class='sym'>{s['symbol']}</span>"
            f" <span class='perf'>({sign}{perf:.1%})</span>"
            f"</div>"
        )
    return "\n".join(badges)
