# Swing Trading Dashboard

Pipeline automatisé de détection de setups pré-breakout, publié sur **GitHub Pages**.

---

## 🗺️ La stratégie — 3 états progressifs

| État | Couleur | Conditions |
|------|---------|------------|
| **ATTENTE** | 🟡 | TTM Squeeze ON + secteur fort (Top 3) + prix > 5$ + vol > 500K + prix > SMA20 & SMA50 |
| **SETUP** | 🟠 | ATTENTE + ≥ 2 achats insiders (Form 4), valeur nette > 10 000$ dans les 30j |
| **PLAY** | 🟢 | SETUP + trigger : volume spike (>1.5× avg20) OU news catalyseur OU cluster insider (≥3 en 7j) |

**Expirations :** ATTENTE et SETUP expirent après 15 jours sans progression. PLAY expire après 5 jours.

---

## ⚙️ Setup initial

### 1. Fork & Clone

```bash
git clone https://github.com/<votre-user>/<votre-repo>.git
cd <votre-repo>
```

### 2. Configurer les secrets GitHub

Dans **Settings → Secrets and variables → Actions**, créer :

| Secret | Valeur | Requis par |
|--------|--------|------------|
| `DISCORD_WEBHOOK` | URL webhook Discord (ex: `https://discord.com/api/webhooks/...`) | Alertes Discord |
| `SEC_IDENTITY` | `"Prénom Nom email@exemple.com"` | edgartools / SEC EDGAR |

> **Pourquoi SEC_IDENTITY ?** La SEC exige une identification pour les requêtes automatisées vers EDGAR. Format libre, mais doit être une vraie adresse email.

### 3. Activer GitHub Pages

Dans **Settings → Pages** :
- Source : `Deploy from a branch`
- Branch : `gh-pages` / `/ (root)`

Le dashboard sera accessible à : `https://<user>.github.io/<repo>/`

### 4. Activer les workflows

Dans **Actions**, activer les workflows si nécessaire (premier démarrage).

Tester manuellement via **Actions → Daily Scan → Run workflow**.

---

## 🔧 Configuration (`config.yaml`)

Tous les paramètres sont dans [`config.yaml`](config.yaml) :

```yaml
# Top N secteurs retenus (défaut: 3)
sectors:
  top_n: 3
  weight_3m: 0.6   # Pondération perf 3 mois
  weight_6m: 0.4   # Pondération perf 6 mois

# Seuils de filtrage technique
filters:
  min_price: 5.0          # Prix minimum ($)
  min_avg_volume: 500000  # Volume moyen 20j minimum

# Critères insiders
insiders:
  window_days: 30         # Fenêtre d'analyse (jours)
  min_buy_transactions: 2 # Nb minimum d'achats
  min_net_value: 10000    # Valeur nette minimum ($)
  exclude_10b51: true     # Exclure plans automatisés

# Triggers PLAY
triggers:
  volume_spike_ratio: 1.5 # Volume spike : Nx la moyenne
  news_lookback_hours: 24 # Fenêtre de recherche des news

# Durées maximum par état
states:
  max_days_attente: 15
  max_days_setup: 15
  max_days_play: 5
```

---

## 📊 Lire le dashboard

Le dashboard ([`output/index.html`](output/index.html)) s'actualise toutes les **5 minutes** automatiquement.

```
┌─────────────────────────────────────────────────────────┐
│  🔥 Swing Dashboard      📅 Dernière MàJ : HH:MM UTC   │
│  Secteurs forts : #1 XLK (+12%) #2 XLI (+8%) #3 XLF   │
├─────────────────┬──────────────────┬────────────────────┤
│ 🟡 ATTENTE (22) │ 🟠 SETUP (7)    │ 🟢 PLAY (2)       │
│ Ticker | Secteur│ Ticker | Secteur │ Ticker | Trigger   │
│ Prix   | VolAvg │ Prix   | #Insider│ Type   | Détail    │
│ SMA20  | SMA50  │ Valeur$| Dernier │                    │
│ Jours            │ Jours           │ Jours              │
├─────────────────┴──────────────────┴────────────────────┤
│  📰 HISTORIQUE DES ÉVÉNEMENTS (48h)                     │
│  [14:32] ACME: SETUP → PLAY — Volume 1.8× avg20        │
│  [09:15] XYZ:  ATTENTE → SETUP — 3 achats (42K$)       │
└─────────────────────────────────────────────────────────┘
```

---

## 🔔 Alertes Discord

| Alerte | Couleur | Déclencheur |
|--------|---------|-------------|
| 🟡 Nouveau ATTENTE | Jaune | Ticker passant tous les filtres |
| 🟠 Nouveau SETUP | Orange | Accumulation insiders détectée |
| 🟢 PLAY | Vert | Volume spike / news / cluster insider |
| ⏰ Expiré | Gris | Délai max dépassé sans progression |
| 📊 Résumé daily | Bleu | Après chaque scan complet |

---

## 🏗️ Architecture

```
/
├── main.py                       # Orchestrateur (--mode daily/intraday)
├── config.yaml                   # Paramètres centralisés
├── requirements.txt
├── data/
│   └── stocks_state.json         # État persistant (versionné git)
├── engine/
│   ├── sector_strength.py        # Top 3 ETFs sectoriels (tvDatafeed)
│   ├── ttm_loader.py             # Scraping Barchart TTM Squeeze
│   ├── filters.py                # Filtres techniques (prix/vol/SMA/secteur)
│   ├── insider_scan.py           # Form 4 EDGAR (edgartools)
│   ├── state_manager.py          # Machine à états + persistence JSON
│   ├── volume_monitor.py         # Spike volume intraday
│   └── news_monitor.py           # Catalyseurs news (finvizfinance)
├── alerts/
│   └── discord_alerts.py         # Embeds Discord riches
├── dashboard/
│   └── generate_html.py          # Dashboard HTML statique (Plotly)
├── output/
│   └── index.html                # Dashboard publié sur GitHub Pages
└── .github/workflows/
    ├── daily_scan.yml            # Cron 08:00 EST (lun-ven)
    └── intraday_monitor.yml      # Cron toutes les 15 min (heures de marché)
```

### Sources de données (100% gratuites)

| Source | Utilisation | Librairie |
|--------|-------------|-----------|
| TradingView | Prix, volume, SMA | `tvDatafeed` (anonyme) |
| SEC EDGAR | Form 4 insiders | `edgartools` |
| Finviz | News par ticker | `finvizfinance` |
| Barchart | Liste TTM Squeeze ON | `requests` + scraping |

---

## 🚀 Exécution locale

```bash
# Installer les dépendances
pip install -r requirements.txt

# Variables d'environnement
export SEC_IDENTITY="Prénom Nom email@example.com"
export DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."

# Scan complet
python main.py --mode daily

# Monitoring intraday
python main.py --mode intraday
```

---

## ⚠️ Limites connues

- **Barchart** : le scraping XSRF peut se bloquer lors de changements du site. En cas d'échec, le pipeline log l'erreur et continue sans les données TTM.
- **tvDatafeed** : fonctionne en mode anonyme mais peut être rate-limited. Ajouter `tradingview.username` / `tradingview.password` dans `config.yaml` pour une connexion authentifiée.
- **edgartools** : requiert `SEC_IDENTITY`. Les filings EDGAR sont mis à jour en J+1 à J+2 selon les émetteurs.
- **GitHub Actions Free Tier** : ~2000 min/mois incluses. Le cron intraday (15 min) consomme ~150 min/jour de marché. Adapter la fréquence si nécessaire.
