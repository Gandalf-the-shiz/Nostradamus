# 🔮 Nostradamus V2 — The Market Intelligence Engine

> **Get so much insight we have foresight.**

> **The single source of truth for all agents and context windows.** Every PR must read this file first, update the checkboxes, and keep this document accurate before merging.

---

## Project Overview

**Nostradamus V2** is no longer a 5-stock demo. V2 analyzes the **ENTIRE US stock market** (~7,000+ tickers across NYSE, NASDAQ, AMEX). The goal is to build a money-making machine that uses ML to predict price direction with enough accuracy to generate actionable alpha.

- **Live URL**: https://gandalf-the-shiz.github.io/Nostradamus/
- **Repo**: https://github.com/Gandalf-the-shiz/Nostradamus
- **Built entirely by GitHub Agents** — all coding happens via PRs opened from Issues
- **No server required** — 100% static frontend, CI/CD handles all heavy computation

**Core principle: Unlimited compute, zero excuses.** We design around every bottleneck and limitation.

---

## V1 Autopsy — What We're Fixing

| # | Issue | Severity | Root Cause | V2 Solution |
|---|---|---|---|---|
| 1 | Starter model weights are empty (0 bytes) | 🔴 Critical | `weights.bin` never generated, `weightsManifest: []` | New Phase 1: Build offline training pipeline that generates real pre-trained weights from full market data |
| 2 | Historical data directory is empty | 🔴 Critical | `FINNHUB_API_KEY` secret never configured; only 5 hardcoded tickers | New data pipeline: scrape entire market via yfinance + SEC EDGAR, commit compressed datasets to repo |
| 3 | Only 5 hardcoded symbols (AAPL, GOOGL, MSFT, AMZN, TSLA) | 🔴 Critical | `fetch-historical.js` has `const SYMBOLS = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA']` | Build universal ticker registry from SEC EDGAR (~7,000+ tickers), fetch history for ALL |
| 4 | Accuracy log has never recorded anything | 🟡 Major | CI workflow writes heartbeats only; real metrics are client-side only | Server-side accuracy computation in GitHub Actions using committed predictions vs actual prices |
| 5 | Retraining version recording uses blind 5-min setTimeout | 🟡 Major | `scheduledTrain()` is fire-and-forget | Refactor to use async/await with proper completion callback, record version only after training resolves |
| 6 | Single shared model for all stocks | 🟡 Major | One set of weights in localStorage overwritten per training | V2 uses a universal model trained on normalized cross-market data; per-sector fine-tuned variants |
| 7 | Confidence score is synthetic (not calibrated) | 🟡 Major | `Math.abs(pred - current) * 5` clamped to [0.5, 0.95] | Implement Monte Carlo dropout for real uncertainty estimation; calibrate with Platt scaling |
| 8 | No test suite | 🟡 Major | Zero test files | Add comprehensive test suite: unit tests for preprocessing math, integration tests for API fallback, ML pipeline validation |
| 9 | `Math.min(...values)` stack overflow on large arrays | 🟡 Major | Spread operator limit ~100K args | Replace with iterative `reduce()` for min/max in `preprocessing.js` |
| 10 | Prediction resolution timing is immediate, not next-day | 🟡 Major | Resolves on any fresh price, not next trading day close | Implement proper T+1 resolution: predictions resolve only after the next market close |
| 11 | Training data only comes from `sample.json` or live API | 🟡 Major | No committed historical dataset to bootstrap from | Build massive committed dataset via GitHub Actions data pipeline |
| 12 | No sentiment analysis (news exists but not used in ML features) | 🟠 Medium | News module renders headlines but doesn't feed NLP features to model | Add sentiment scoring pipeline that feeds into feature matrix |
| 13 | No fundamental data features (P/E, EPS, earnings dates) | 🟠 Medium | Model only sees price/volume technicals | Add fundamental indicators as features from free APIs |

---

## V2 Architecture Overview

| Layer | Technology | Change from V1 |
|---|---|---|
| **Hosting** | GitHub Pages | Same |
| **Frontend** | Vanilla HTML/CSS/JS | Same |
| **Charting** | Chart.js (CDN) | Same |
| **ML Engine** | TensorFlow.js (CDN) | **Upgraded model: Transformer-LSTM hybrid, 30-day sliding window, 15+ features** |
| **Ticker Registry** | SEC EDGAR `company_tickers_exchange.json` | **NEW: ~7,000+ US exchange tickers auto-updated weekly** |
| **Historical Data Pipeline** | GitHub Actions + Python (`yfinance`) | **NEW: Bulk download all tickers, compress to JSON, commit to repo** |
| **Pre-trained Model** | GitHub Actions + Python (`tensorflow/keras`) | **NEW: Server-side training on full market, export TF.js model to `models/`** |
| **Primary API** | Finnhub | Same |
| **Secondary API** | Twelve Data | Same |
| **Tertiary API** | Polygon.io | Same |
| **NEW: Quaternary API** | Alpha Vantage | **NEW: 25 calls/day free, technical indicators endpoint** |
| **Data Persistence** | localStorage + IndexedDB | **UPGRADED: IndexedDB for large datasets (model weights, historical data)** |
| **CI/CD** | GitHub Actions | **UPGRADED: 5 workflows (deploy, fetch-tickers, fetch-history, train-model, score-accuracy)** |

### Why These APIs?
GitHub Pages serves files with no backend proxy. All API calls happen directly from the user's browser, so **CORS support is mandatory**. Finnhub, Twelve Data, and Polygon.io all support CORS from browser clients.

> **Note on Alpha Vantage:** Alpha Vantage does NOT support CORS and **cannot be called from the browser**. It is used exclusively in GitHub Actions (server-side Python scripts) for enriching feature data during training — never in the browser JS.

### API Key Strategy
- API keys are **entered by the user** in the app's Settings panel and stored in `localStorage`
- Keys are never hardcoded in the source
- If no API key is configured, the app runs in **Demo Mode** loading from committed historical data

---

## Rate Limit Strategy

| Technique | Description |
|---|---|
| **Request Batching** | Batch multiple symbol lookups into one API call where possible |
| **localStorage Cache + TTL** | Don't re-fetch data within 5-minute windows; store with expiry timestamp |
| **Staggered / Lazy Loading** | Only fetch data for stocks currently visible in the viewport |
| **Exponential Backoff** | On API errors (429, 5xx), retry with increasing delay |
| **Fallback Chain** | Finnhub → Twelve Data → Polygon.io → cached data → demo data |
| **Committed Historical Data** | Historical OHLCV comes from committed dataset, not live API calls — eliminates rate limit bottleneck entirely |

---

## Free Data Source Strategy — Zero-Cost Full Market Coverage

### 1. SEC EDGAR Ticker Registry
**URL:** https://www.sec.gov/files/company_tickers_exchange.json

- Free, no API key, no rate limit, updated daily by the SEC
- Contains ticker, CIK, company name, and exchange for all US-listed companies
- GitHub Actions workflow fetches weekly, commits to `data/tickers/us_tickers.json`
- Filter to NYSE, NASDAQ, AMEX exchanges only (remove OTC/pink sheets)

### 2. yfinance (Yahoo Finance) for Historical OHLCV
- Free, no API key required, no official rate limit (but must throttle)
- Can bulk download full history for any US ticker
- GitHub Actions workflow runs nightly, fetches 1 year of daily data for all tickers
- **Strategy:** Fetch in batches of 50 tickers at a time, 2-second delay between batches
- Store as compressed JSON in `data/historical/` (split by sector: `technology.json`, `healthcare.json`, etc.)
- Raw uncompressed size: ~400–500MB (7,000 tickers × 252 days × 5 OHLCV values × ~50 bytes/value). With aggressive JSON compression (gzip/deflate, ~75–80% reduction), this comes down to ~50–100MB. Git LFS is very likely required — configure it before committing historical data.

### 3. Existing APIs (Finnhub, Twelve Data, Polygon.io) for Real-Time Quotes
- Same fallback chain as V1, but now used **only** for live/real-time data
- Historical data comes from the committed dataset, not live API calls
- This eliminates the rate limit bottleneck for historical data entirely

### 4. Alpha Vantage (New Quaternary Fallback — CI Only)
- Free API key, 25 calls/day
- Valuable for: RSI, MACD, Bollinger Bands, SMA/EMA pre-computed
- Used in GitHub Actions for enriching feature data during training
- **Never called from the browser** (no CORS support)

---

## The 10-Phase Execution Plan

> **Agents: update these checkboxes in every PR before merging.**

### ✅ Phase 1: V1 Foundation (COMPLETE — inherited from V1)
- [x] Repository structure, GitHub Pages, CI/CD
- [x] Frontend scaffold (HTML/CSS/JS, mobile-first)
- [x] API integration modules (Finnhub, Twelve Data, Polygon.io)
- [x] localStorage cache with TTL
- [x] Demo mode with sample.json
- [x] Chart.js and TensorFlow.js CDN integration

### Phase 2: Universal Ticker Registry
- [x] Create `scripts/fetch-tickers.py` — downloads SEC EDGAR `company_tickers_exchange.json`
- [x] Filter to NYSE + NASDAQ + AMEX, exclude OTC/test tickers, output to `data/tickers/us_tickers.json`
- [x] Create `.github/workflows/fetch-tickers.yml` — runs weekly (Sunday midnight UTC)
- [x] Update frontend search to use committed ticker list for instant offline autocomplete
- [x] Add sector/industry classification from SEC SIC codes
- [x] Target: ~7,000+ actively traded US tickers

### Phase 3: Full-Market Historical Data Pipeline
- [x] Create `scripts/fetch-history.py` — uses `yfinance` to bulk download 1 year OHLCV for all tickers
- [x] Implement batched downloading: 50 tickers per batch, 2-second inter-batch delay
- [x] Implement retry logic with exponential backoff for failed tickers
- [x] Store data as sector-chunked compressed JSON files in `data/historical/` (e.g., `technology.json`, `healthcare.json`, `financials.json`)
- [x] Add incremental update mode: only fetch new data since last run (don't re-download everything)
- [x] Create `.github/workflows/fetch-history.yml` — runs nightly Mon-Fri at 9:30 PM UTC
- [x] Add data validation: reject tickers with < 100 trading days of data
- [x] Add `data/historical/manifest.json` — metadata file listing all available tickers, date ranges, last update timestamps
- [ ] Configure Git LFS for `data/historical/*.json` if total size exceeds 100MB
- [x] Target: 1 year of daily OHLCV data for ~7,000 tickers

### Phase 4: Feature Engineering Pipeline (Server-Side)
- [x] Create `scripts/build-features.py` — reads raw OHLCV, computes full feature matrix
- [x] Implement 15+ features per ticker per day:
  - OHLCV (5 features: open, high, low, close, volume)
  - RSI-14
  - MACD (signal line, histogram)
  - SMA-5, SMA-20, SMA-50, SMA-200
  - EMA-12, EMA-26
  - Bollinger Bands (upper, lower, bandwidth)
  - ATR-14 (Average True Range)
  - OBV (On-Balance Volume)
  - Stochastic Oscillator (%K, %D)
  - Rate of Change (ROC-10)
  - Day-of-week encoding (one-hot, 5 features)
  - Month encoding (cyclical sin/cos, 2 features)
  - 30-day realized volatility
  - 5-day price momentum
  - Volume ratio (current / 20-day average)
- [x] Normalize all features using min-max scaling per-ticker (store scaling params)
- [x] Create windowed sequences: 30-day lookback windows → next-day direction label
- [x] Output to `data/features/` as compressed numpy-compatible JSON
- [x] Add `data/features/scaling_params.json` — global scaling parameters for the model
- [x] Create `.github/workflows/build-features.yml` — runs after fetch-history completes

### Phase 5: Server-Side Model Training (The Real Brain)
- [ ] Create `scripts/train-model.py` — full TensorFlow/Keras training pipeline
- [ ] Model architecture: **Bidirectional LSTM with Attention**
  - Input: (batch, 30 timesteps, N features)
  - Layer 1: Bidirectional LSTM (128 units, return_sequences=True)
  - Layer 2: Multi-head self-attention (4 heads)
  - Layer 3: LSTM (64 units, return_sequences=False)
  - Layer 4: Dropout (0.3)
  - Layer 5: Dense (32, relu)
  - Layer 6: Dropout (0.2)
  - Layer 7: Dense (1, sigmoid) — P(price goes UP tomorrow)
  - Optimizer: Adam (lr=0.001 with ReduceLROnPlateau)
  - Loss: Binary crossentropy
  - Metrics: Accuracy, AUC, Precision, Recall
- [ ] Training strategy:
  - Train/validation/test split: 70% / 15% / 15% (time-series aware — no future leakage)
  - Walk-forward validation: train on months 1-10, validate on 11, test on 12
  - Class balancing: UP days slightly outnumber DOWN days historically; use class weights
  - Early stopping with patience=10 on validation AUC
  - Save best model checkpoint
- [ ] Export trained model to TensorFlow.js format using `tensorflowjs_converter`
  - Output to `models/v2/model.json` + `models/v2/group1-shard1of1.bin` (etc.)
  - Also export `models/v2/metadata.json` with training date, accuracy, feature list, scaling params
- [ ] Create `.github/workflows/train-model.yml` — runs weekly (Sunday after fetch-history and build-features)
- [ ] Log training metrics to `data/training-logs/` (loss curves, confusion matrix, per-sector accuracy)
- [ ] Target: >55% directional accuracy on held-out test set (note: the true random baseline is ~52% because US markets trend up more days than down historically; the model must beat the naive "always predict UP" baseline, not just 50%)
- [ ] Stretch goal: >60% accuracy with sector-specific fine-tuning

### Phase 6: Upgraded Browser ML Engine
- [ ] Update `js/ml/model.js` to load new V2 model architecture
- [ ] Update `js/ml/preprocessing.js`:
  - Replace `Math.min(...spread)` with iterative `reduce()` min/max
  - Support all 15+ features matching the server-side pipeline
  - Load scaling params from `models/v2/metadata.json`
- [ ] Update `js/ml/prediction.js`:
  - Implement Monte Carlo dropout (run prediction N=20 times with dropout enabled, average results)
  - Calculate real confidence intervals from the MC dropout distribution
  - Replace synthetic confidence with calibrated probability
- [ ] Update `js/ml/training.js`:
  - Support incremental fine-tuning in browser (user's personalized model layer on top of base model)
  - Proper async/await completion tracking (fix the 5-min setTimeout hack)
- [ ] Update `js/ml/tracker.js`:
  - Implement proper T+1 resolution: predictions resolve only at next market close
  - Track predictions per-sector for sector-level accuracy
- [ ] Implement Transfer Learning: browser loads pre-trained base model, user can fine-tune on their watchlist stocks
- [ ] Migrate model weight storage from localStorage to IndexedDB (support models >5MB)

### Phase 7: Full-Market Dashboard Overhaul
- [ ] Replace 5-stock dashboard with full-market views:
  - **Market Heatmap**: Treemap visualization of all sectors/stocks by prediction strength (like finviz.com)
  - **Top Predictions**: Ranked list of stocks with strongest UP/DOWN signals + highest confidence
  - **Sector Rotation**: Show which sectors the model is most bullish/bearish on
  - **Momentum Scanner**: Stocks with strongest technical momentum alignment
  - **Earnings Calendar**: Upcoming earnings dates with pre-earnings predictions
- [ ] Add stock screener with filters:
  - Prediction direction (UP/DOWN)
  - Confidence threshold (>60%, >70%, >80%)
  - Sector filter
  - Market cap filter
  - Volume filter
- [ ] Pagination and virtual scrolling for 7,000+ ticker list
- [ ] Lazy-load stock cards as user scrolls (IntersectionObserver)

### Phase 8: Sentiment & Alternative Data
- [ ] Integrate Finnhub company news into ML feature pipeline
- [ ] Build simple client-side sentiment scorer:
  - Keyword-based scoring from headline text (bullish/bearish word lists)
  - Aggregate daily sentiment score per ticker
  - Feed as additional feature to model
- [ ] Track sentiment-prediction correlation in accuracy dashboard
- [ ] Add "Market Mood" indicator to dashboard header (aggregate sentiment)

### Phase 9: Backtesting Engine
- [ ] Create `js/backtest/engine.js` — full backtesting framework
  - Run model predictions against historical data
  - Simulate portfolio: start with $10,000, buy/sell based on model signals
  - Track: total return, Sharpe ratio, max drawdown, win rate
- [ ] Add backtesting UI view:
  - Date range selector
  - Strategy configuration (confidence threshold, max positions, sector filter)
  - Equity curve chart
  - Trade log table
- [ ] Compare strategies: model-only vs model+sentiment vs buy-and-hold benchmark
- [ ] Export backtest results to CSV

### Phase 10: Continuous Intelligence Loop
- [ ] Automated daily prediction generation via GitHub Actions
  - After market close: fetch latest prices, run model, generate predictions for next day
  - Commit predictions to `data/predictions/YYYY-MM-DD.json`
- [ ] Automated accuracy scoring:
  - After market close: compare previous day's predictions to actual results
  - Commit accuracy report to `data/accuracy/YYYY-MM-DD.json`
  - Track rolling 7-day, 30-day, 90-day accuracy metrics
- [ ] Model auto-retraining:
  - If rolling 30-day accuracy drops below 53% (chosen as slightly above the ~52% naive "always UP" baseline, providing a minimal positive-alpha margin), trigger automatic retraining workflow
  - Use latest 6 months of data for retraining
  - Only promote new model if it beats current model on held-out test set
- [ ] Weekly "Market Intelligence Report" auto-generated:
  - Top 10 predicted movers (up and down)
  - Sector rotation signals
  - Model confidence distribution
  - Accuracy trend chart
  - Committed to `data/reports/weekly/YYYY-WW.json`

---

## File Structure

```
Nostradamus/
├── index.html
├── README.md                          # THIS FILE — the master plan
├── LICENSE
├── manifest.json
├── sw.js
├── icons/
│   ├── icon-192.svg
│   └── icon-512.svg
├── .github/
│   └── workflows/
│       ├── deploy.yml                 # GitHub Pages deployment
│       ├── fetch-tickers.yml          # Weekly: SEC EDGAR ticker refresh
│       ├── fetch-history.yml          # Nightly: yfinance OHLCV download
│       ├── build-features.yml         # After fetch-history: compute features
│       ├── train-model.yml            # Weekly: full model training
│       └── score-accuracy.yml         # Daily: prediction accuracy scoring
├── css/
│   └── styles.css
├── js/
│   ├── app.js
│   ├── api/
│   │   ├── finnhub.js
│   │   ├── twelvedata.js
│   │   ├── polygon.js
│   │   └── manager.js
│   ├── ml/
│   │   ├── model.js                   # V2 model architecture loader
│   │   ├── training.js                # Browser-side fine-tuning
│   │   ├── prediction.js              # MC dropout + calibrated confidence
│   │   ├── preprocessing.js           # 15+ feature engineering (browser)
│   │   ├── tracker.js                 # T+1 prediction resolution
│   │   ├── accuracy.js
│   │   ├── versioning.js
│   │   └── retraining.js              # Fixed async completion tracking
│   ├── ui/
│   │   ├── dashboard.js               # Full-market heatmap + top predictions
│   │   ├── charts.js
│   │   ├── stockcard.js
│   │   ├── search.js                  # Offline autocomplete from ticker registry
│   │   ├── detail.js
│   │   ├── watchlist.js
│   │   ├── theme.js
│   │   ├── accuracy-dashboard.js
│   │   ├── sectors.js
│   │   ├── screener.js                # NEW: stock screener with filters
│   │   ├── heatmap.js                 # NEW: treemap market heatmap
│   │   ├── backtest-ui.js             # NEW: backtesting interface
│   │   ├── news.js
│   │   ├── help.js
│   │   ├── share.js
│   │   └── export.js
│   ├── backtest/
│   │   └── engine.js                  # NEW: backtesting engine
│   ├── storage/
│   │   ├── cache.js
│   │   └── indexeddb.js               # NEW: IndexedDB for large data
│   └── utils/
│       ├── helpers.js
│       └── sentiment.js               # NEW: keyword sentiment scorer
├── scripts/                           # Server-side Python scripts (run in CI)
│   ├── fetch-tickers.py               # SEC EDGAR ticker download
│   ├── fetch-history.py               # yfinance bulk OHLCV download
│   ├── build-features.py              # Feature engineering pipeline
│   ├── train-model.py                 # TensorFlow/Keras model training
│   ├── generate-predictions.py        # Daily prediction generation
│   ├── score-accuracy.py              # Compare predictions to actuals
│   └── requirements.txt               # Python dependencies
├── data/
│   ├── sample.json                    # Demo data (V1 compat)
│   ├── tickers/
│   │   └── us_tickers.json            # All ~7,000+ US exchange tickers
│   ├── historical/
│   │   ├── manifest.json              # Metadata: tickers, date ranges, sizes
│   │   ├── technology.json            # Sector-chunked historical data
│   │   ├── healthcare.json
│   │   ├── financials.json
│   │   ├── consumer_discretionary.json
│   │   ├── consumer_staples.json
│   │   ├── energy.json
│   │   ├── industrials.json
│   │   ├── materials.json
│   │   ├── real_estate.json
│   │   ├── utilities.json
│   │   └── communication_services.json
│   ├── features/
│   │   ├── feature_matrix.json        # Computed features (compressed)
│   │   └── scaling_params.json        # Normalization parameters
│   ├── predictions/
│   │   └── YYYY-MM-DD.json            # Daily prediction files
│   ├── accuracy/
│   │   ├── accuracy-log.json          # Rolling accuracy metrics
│   │   └── YYYY-MM-DD.json            # Daily accuracy reports
│   ├── training-logs/
│   │   └── YYYY-MM-DD.json            # Training run metrics
│   └── reports/
│       └── weekly/
│           └── YYYY-WW.json           # Weekly intelligence reports
├── models/
│   ├── starter/                       # V1 model (deprecated)
│   │   ├── model.json
│   │   └── weights.bin
│   └── v2/                            # V2 pre-trained model
│       ├── model.json                 # TF.js model topology
│       ├── group1-shard1of1.bin       # Model weights (real, trained)
│       └── metadata.json              # Training date, accuracy, features, scaling
└── tests/                             # NEW: test suite
    ├── preprocessing.test.js
    ├── api-manager.test.js
    ├── prediction.test.js
    └── backtest.test.js
```

---

## Technical Notes for Future Agents

1. **No build step** — Same as V1. Vanilla JS, ES modules, GitHub Pages.
2. **Mobile-first** — Same as V1. 375px minimum width.
3. **API keys via Settings UI** — Same as V1. Never hardcode API keys. The user enters them in a Settings panel; they are stored in `localStorage`. See `js/storage/cache.js` for the storage API.
4. **Demo mode** — Same as V1, but now demo mode loads from committed historical data instead of tiny `sample.json`.
5. **Graceful degradation** — Same as V1. Every feature should fail gracefully.
6. **README is the contract** — Same as V1. Every PR must update checkboxes and keep this document accurate.
7. **CDN versions** (do not change without testing):
   - TensorFlow.js: `https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js`
   - Chart.js: `https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js`
8. **NEW: Python scripts run in GitHub Actions only** — The `scripts/` directory contains Python code that runs server-side in CI. It is NEVER loaded in the browser. Keep Python and JS code completely separate.
9. **NEW: Git LFS** — If `data/historical/` exceeds 100MB total, configure Git LFS for `.json` files in that directory.
10. **NEW: IndexedDB for large data** — Model weights and large datasets should use IndexedDB, not localStorage (which has a ~5MB limit per origin).
11. **NEW: Feature parity** — The browser-side `preprocessing.js` must compute features IDENTICALLY to the server-side `build-features.py`. Any difference will cause model predictions to be garbage. Validate with `tests/preprocessing.test.js`: feed the same sample OHLCV data through both implementations and assert all output features match within floating-point tolerance (±1e-6). This test must pass before any Phase 5 model is promoted.
12. **NEW: Time-series splitting** — NEVER use random train/test splits for time series data. Always split chronologically. The test set must be strictly AFTER the training set in time.
13. **NEW: The model predicts P(UP)** — Output is sigmoid ∈ [0, 1]. Values > 0.5 = predicted UP, < 0.5 = predicted DOWN. The confidence is the distance from 0.5 (e.g., 0.85 = 85% confident UP, 0.15 = 85% confident DOWN).

---

## Current Status

| Phase | Description | Status |
|---|---|---|
| V1 Phase 1 | Project scaffold, GitHub Pages, CI/CD | ✅ Complete (with caveats — see autopsy) |
| V1 Phase 2 | Data layer, API fallback chain, caching | ✅ Complete (with caveats — see autopsy) |
| V1 Phase 3 | Frontend dashboard, search, stock cards | ✅ Complete (with caveats — see autopsy) |
| V1 Phase 4 | TensorFlow.js ML engine | ✅ Complete (with caveats — see autopsy) |
| V1 Phase 5 | Self-learning, accuracy tracking | ✅ Complete (with caveats — see autopsy) |
| V1 Phase 6 | Polish, PWA, sector analysis, news | ✅ Complete (with caveats — see autopsy) |
| **V2 Phase 2** | **Universal Ticker Registry** | 🟢 Complete |
| **V2 Phase 3** | **Full-Market Historical Data** | ✅ Complete |
| **V2 Phase 4** | **Server-Side Feature Engineering** | ✅ Complete |
| **V2 Phase 5** | **Server-Side Model Training** | ⬜ Not started |
| **V2 Phase 6** | **Upgraded Browser ML Engine** | ⬜ Not started |
| **V2 Phase 7** | **Full-Market Dashboard Overhaul** | ⬜ Not started |
| **V2 Phase 8** | **Sentiment & Alternative Data** | ⬜ Not started |
| **V2 Phase 9** | **Backtesting Engine** | ⬜ Not started |
| **V2 Phase 10** | **Continuous Intelligence Loop** | ⬜ Not started |

---

## Implementation Priority Order — The Critical Path

**Nothing else matters until we have data and a trained model.** Build in this order:

1. **Phase 2 → Phase 3 → Phase 4 → Phase 5 (DATA PIPELINE)**
   - Tickers → History → Features → Training
   - Without a real trained model, everything downstream is a demo
2. **Phase 6 (Browser ML Upgrade)**
   - Must happen after Phase 5 so the browser can load the real model
3. **Phase 7 (Dashboard Overhaul)**
   - Can start in parallel with Phase 6
4. **Phase 8 (Sentiment) + Phase 9 (Backtesting)**
   - Independent of each other; can be done in parallel after Phase 6
5. **Phase 10 (Continuous Intelligence Loop)**
   - The capstone — wires everything together; requires all prior phases

---

> ⚠️ **Not financial advice.** Nostradamus is a research and educational project. All predictions are experimental ML outputs and should never be used as the sole basis for investment decisions. Past model accuracy does not guarantee future performance.
