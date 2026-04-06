# 🔮 Nostradamus — The AI Stock Oracle

> **The single source of truth for all agents and context windows.** Every PR must read this file first, update the checkboxes, and keep this document accurate before merging.

---

## Project Overview

**Nostradamus** is a 100% client-side stock market monitoring and prediction app hosted on GitHub Pages. It uses TensorFlow.js for in-browser machine learning to predict which stocks will go up or down — and by how many dollars. The app is self-learning: it continuously improves its model as more data is fed in.

- **Live URL**: https://gandalf-the-shiz.github.io/Nostradamus/
- **Repo**: https://github.com/Gandalf-the-shiz/Nostradamus
- **Built entirely by GitHub Agents** — all coding happens via PRs opened from Issues
- **No server required** — 100% static, runs entirely in the browser

---

## Architecture Overview

| Layer | Technology | Notes |
|---|---|---|
| **Hosting** | GitHub Pages | Static site, zero server cost |
| **Frontend** | Vanilla HTML/CSS/JavaScript | No build step, ES modules, mobile-first |
| **Charting** | Chart.js (CDN) | Price history + prediction overlay |
| **ML Engine** | TensorFlow.js (CDN) | LSTM neural network, runs 100% in-browser |
| **Primary API** | Finnhub | 60 calls/min free, WebSocket real-time, CORS ✅ |
| **Secondary API** | Twelve Data | 800 calls/day free, CORS ✅ |
| **Tertiary API** | Polygon.io | Free tier US equities, CORS ✅ |
| **Data Persistence** | localStorage | Model weights + user preferences + API cache |
| **Historical Data** | GitHub Actions → JSON files committed to repo | Scheduled workflow fetches and commits daily prices |
| **CI/CD** | GitHub Actions | Auto-deploy to Pages on push to `main` |

### Why These APIs?
GitHub Pages serves files with no backend proxy. All API calls happen directly from the user's browser, so **CORS support is mandatory**. Finnhub, Twelve Data, and Polygon.io all support CORS from browser clients. Alpha Vantage does NOT support CORS and cannot be used.

### API Key Strategy
- API keys are **entered by the user** in the app's Settings panel and stored in `localStorage`
- Keys are never hardcoded in the source
- If no API key is configured, the app runs in **Demo Mode** with `data/sample.json`

---

## Rate Limit Strategy

| Technique | Description |
|---|---|
| **Request Batching** | Batch multiple symbol lookups into one API call where possible |
| **localStorage Cache + TTL** | Don't re-fetch data within 5-minute windows; store with expiry timestamp |
| **Staggered / Lazy Loading** | Only fetch data for stocks currently visible in the viewport |
| **Exponential Backoff** | On API errors (429, 5xx), retry with increasing delay |
| **Fallback Chain** | Finnhub → Twelve Data → Polygon.io → cached data → demo data |

---

## The 6-Phase Execution Plan

> **Agents: update these checkboxes in every PR before merging.**

### ✅ Phase 1: Project Scaffold & Infrastructure
- [x] Repository structure created
- [x] README.md master plan written
- [x] `index.html` base page created
- [x] CSS foundation with mobile-first responsive design (`css/styles.css`)
- [x] JavaScript module structure established (all stubs in `js/`)
- [x] GitHub Pages deployment configured
- [x] GitHub Actions CI/CD workflow for Pages deployment (`.github/workflows/deploy.yml`)
- [x] GitHub Actions scheduled workflow stub for data fetching (`.github/workflows/fetch-data.yml`)
- [x] Demo data file created (`data/sample.json`)
- [x] MIT License added

### ✅ Phase 2: Data Layer & API Integration
- [x] Finnhub API integration module (quotes, company profile, historical data)
- [x] Twelve Data API fallback module
- [x] Polygon.io API fallback module
- [x] Smart request batching and rate-limit manager
- [x] localStorage caching layer with TTL
- [x] API fallback chain logic (primary → secondary → tertiary → cache)
- [x] GitHub Actions workflow to pre-fetch and commit historical price data as JSON
- [x] Error handling and user-friendly API error messages

### ✅ Phase 3: Frontend Dashboard UI
- [x] Stock search bar with autocomplete
- [x] Stock cards showing current price, change, prediction
- [x] Watchlist functionality (add/remove stocks, persisted in localStorage)
- [x] Chart.js integration for price history visualization
- [x] Prediction display overlay on charts (predicted vs actual)
- [x] Mobile-optimized layout and touch interactions
- [x] Dark/light theme toggle
- [x] Loading states, skeletons, and error states

### ✅ Phase 4: ML Prediction Engine
- [x] TensorFlow.js integration and model architecture (LSTM)
- [x] Data preprocessing pipeline (normalization, windowing, feature engineering)
- [x] Feature set: price history, volume, moving averages, RSI, MACD
- [x] Training pipeline that runs in-browser on historical data
- [x] Prediction output: UP/DOWN direction + dollar amount change
- [x] Model weight serialization to localStorage
- [x] Pre-trained starter model weights committed to repo
- [x] Prediction confidence score display

### ✅ Phase 5: Self-Learning & Continuous Improvement
- [x] Prediction tracking system (store predictions with timestamps)
- [x] Accuracy comparison engine (predicted vs actual next-day price)
- [x] Automatic model retraining trigger when new data is available
- [x] Model versioning (track accuracy over time)
- [x] Rolling accuracy dashboard (show model improvement over weeks/months)
- [x] A/B model comparison (keep best performing model)
- [x] GitHub Actions workflow to log daily accuracy metrics

### 🔲 Phase 6: Polish, Docs & Advanced Features
- [ ] Performance optimization (lazy loading, code splitting)
- [ ] PWA support (offline mode, installable on phone)
- [ ] Sector/industry analysis view
- [ ] News sentiment integration (Finnhub news API)
- [ ] Export predictions to CSV
- [ ] Comprehensive inline code documentation
- [ ] User guide / help section in app
- [ ] Social sharing of predictions

---

## File Structure

```
Nostradamus/
├── index.html                  # Main app entry point
├── README.md                   # Master plan (this file)
├── LICENSE                     # MIT License
├── .github/
│   └── workflows/
│       ├── deploy.yml          # GitHub Pages deployment (push to main → auto-deploy)
│       └── fetch-data.yml      # Scheduled data fetching (stub — Phase 2)
├── css/
│   └── styles.css              # All styles, mobile-first, dark theme default
├── js/
│   ├── app.js                  # Main app initialization & shell
│   ├── api/
│   │   ├── finnhub.js          # Finnhub API module (primary data source)
│   │   ├── twelvedata.js       # Twelve Data API module (secondary fallback)
│   │   ├── polygon.js          # Polygon.io API module (tertiary fallback)
│   │   └── manager.js          # API manager: fallback chain, rate limiting, batching
│   ├── ml/
│   │   ├── model.js            # TensorFlow.js LSTM model definition
│   │   ├── training.js         # In-browser training pipeline
│   │   ├── prediction.js       # Prediction engine (UP/DOWN + dollar amount)
│   │   ├── preprocessing.js    # Data normalization, windowing, feature engineering
│   │   ├── tracker.js          # Prediction tracking system (Phase 5)
│   │   ├── accuracy.js         # Accuracy comparison engine (Phase 5)
│   │   ├── versioning.js       # Model versioning & A/B comparison (Phase 5)
│   │   └── retraining.js       # Automatic retraining trigger logic (Phase 5)
│   ├── ui/
│   │   ├── dashboard.js        # Main dashboard rendering & layout
│   │   ├── charts.js           # Chart.js price history + prediction overlay
│   │   ├── stockcard.js        # Stock card component (OHLCV, range bar, watchlist)
│   │   ├── search.js           # Search bar with autocomplete
│   │   ├── detail.js           # Stock detail modal/overlay (Phase 3)
│   │   ├── watchlist.js        # Watchlist view & persistence (Phase 3)
│   │   ├── theme.js            # Dark/light theme toggle (Phase 3)
│   │   └── accuracy-dashboard.js # Rolling accuracy dashboard (Phase 5)
│   ├── storage/
│   │   └── cache.js            # localStorage manager with TTL
│   └── utils/
│       └── helpers.js          # Shared utility functions (formatting, math, etc.)
├── data/
│   ├── sample.json             # Demo stock data (AAPL, GOOGL, MSFT, AMZN, TSLA)
│   └── accuracy/
│       └── accuracy-log.json   # Daily accuracy heartbeat log (Phase 5)
└── models/
    └── starter/                # Pre-trained starter model weights (Phase 4)
        ├── model.json          # Model topology
        └── weights.bin         # Binary weights (placeholder until Phase 4)
```

---

## Technical Notes for Future Agents

1. **No build step** — All code is vanilla JS served directly by GitHub Pages. No webpack, no transpilation. Use ES module `import/export` syntax via `<script type="module">` or classic script tags.
2. **Mobile-first** — Assume the user is on a phone browser. All UI must work on 375px width screens. Touch interactions must be considered.
3. **API keys via Settings UI** — Never hardcode API keys. The user enters them in a Settings panel; they are stored in `localStorage`. See `js/storage/cache.js` for the storage API.
4. **Demo mode** — If `localStorage` has no API keys configured, the app loads `data/sample.json` and renders with demo data. A visible banner alerts the user they are in Demo Mode.
5. **Graceful degradation** — Every feature should fail gracefully. If TensorFlow.js fails to load, show a message but still show price data. If API fails, fall back to cache or demo data.
6. **README is the contract** — Every PR must update the phase checkboxes and keep this document accurate. Future agents must be able to read this file and know exactly what has been built and what to build next.
7. **CDN versions** (do not change without testing):
   - TensorFlow.js: `https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js`
   - Chart.js: `https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js`

---

## Current Status

**Phase 5 complete.** Self-learning system implemented: predictions are tracked in localStorage, accuracy metrics (hit rate, MAE) are computed over resolved predictions, models are versioned with A/B champion comparison, automatic background retraining triggers when new data arrives, and a rolling accuracy dashboard (with Chart.js charts) is accessible via the 📊 nav button.

**Next step for agents: Implement Phase 6 (Polish, Docs & Advanced Features)**
