/**
 * js/ui/dashboard.js
 * Main dashboard rendering and layout controller.
 *
 * Responsibilities:
 *  - Load stock data (demo or live)
 *  - Render the market overview strip
 *  - Render stock cards grid with staggered animation
 *  - Coordinate with charts.js and prediction.js
 *  - Wire card clicks to the stock detail overlay
 *
 * Phase 1: Renders demo data from data/sample.json.
 * Phase 2: Pulls live data via api/manager.js.
 * Phase 3: Stagger animation, detail view wiring.
 * Phase 4+: Adds prediction overlays on each card.
 */

import { loadDemoData, getQuote, getCandles } from '../api/manager.js';
import { getItem } from '../storage/cache.js';
import { runPrediction, demoPrediction } from '../ml/prediction.js';
import { renderStockCard } from './stockcard.js';
import { openStockDetail } from './detail.js';
import { storePrediction } from '../ml/tracker.js';
import { resolveAll } from '../ml/tracker.js';
import { autoRetrain } from '../ml/retraining.js';

const DEFAULT_WATCHLIST = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA'];

/**
 * Initialize the dashboard with the given app state.
 * @param {{ mode: 'demo'|'live', tfReady: boolean, chartReady: boolean }} appState
 */
export async function initDashboard(appState) {
  console.log('[Dashboard] Initializing…');

  const stockGrid = document.getElementById('stock-grid');
  if (!stockGrid) return;

  // Show loading skeletons
  showLoadingSkeletons(stockGrid);

  let stocks = [];

  if (appState.mode === 'demo') {
    const demoData = await loadDemoData();
    stocks = demoData.stocks || [];
  } else {
    stocks = await loadLiveStocks(appState, stockGrid);
  }

  // Clear skeletons
  stockGrid.innerHTML = '';

  if (stocks.length === 0) {
    renderEmptyState(stockGrid);
    return;
  }

  renderMarketOverview(stocks);

  // Build a price map for resolving any pending predictions from earlier runs
  const priceMap = {};
  for (const stock of stocks) {
    if (stock.symbol && stock.quote?.current) {
      priceMap[stock.symbol] = stock.quote.current;
    }
  }
  try { resolveAll(priceMap); } catch (e) { console.warn('[Dashboard] resolveAll failed:', e); }

  // Collect candles for auto-retraining
  const allCandles = [];
  for (const stock of stocks) {
    if (Array.isArray(stock.candles) && stock.candles.length > 0) {
      allCandles.push(...stock.candles);
    }
  }

  // Render each stock card with staggered animation
  for (let i = 0; i < stocks.length; i++) {
    const stock = stocks[i];
    let prediction;
    if (appState.tfReady && stock.candles && stock.candles.length >= 30) {
      try {
        prediction = await runPrediction(stock.symbol, stock.candles);
      } catch (err) {
        console.warn(`[Dashboard] ML prediction failed for ${stock.symbol}, using demo:`, err.message);
        prediction = demoPrediction(stock.symbol, stock.quote.current);
      }
    } else {
      prediction = demoPrediction(stock.symbol, stock.quote.current);
    }

    // Track the prediction (graceful — never break the render loop)
    try { storePrediction(prediction); } catch (e) { console.warn('[Dashboard] storePrediction failed:', e); }

    const card = renderStockCard(stock, prediction, appState.chartReady);
    card.style.animationDelay = `${i * 50}ms`;
    card.classList.add('stock-card--animate-in');
    stockGrid.appendChild(card);
  }

  // Trigger background retraining if needed (after rendering, non-blocking)
  if (appState.tfReady && allCandles.length >= 40) {
    try { autoRetrain(allCandles); } catch (e) { console.warn('[Dashboard] autoRetrain failed:', e); }
  }

  // Wire card clicks to detail overlay
  stockGrid.addEventListener('stock-card-click', e => {
    const { stock, prediction } = e.detail;
    const candles = stock.candles || [];
    openStockDetail(stock.symbol, stock, candles, prediction, appState);
  });

  console.log(`[Dashboard] Rendered ${stocks.length} stock cards.`);
}

/**
 * Load live stock data for the watchlist, with per-symbol error handling.
 * Falls back to demo data on total failure.
 * @param {{ mode: string, chartReady: boolean }} appState
 * @param {HTMLElement} stockGrid
 * @returns {Promise<Array>}
 */
async function loadLiveStocks(appState, stockGrid) {
  const savedWatchlist = getItem('watchlist');
  const watchlist = Array.isArray(savedWatchlist) && savedWatchlist.length > 0
    ? savedWatchlist
    : DEFAULT_WATCHLIST;

  const stocks = [];

  await Promise.allSettled(
    watchlist.map(async symbol => {
      try {
        const [quote, candles] = await Promise.all([
          getQuote(symbol),
          getCandles(symbol),
        ]);

        if (!quote) {
          console.warn(`[Dashboard] No quote data for ${symbol}, skipping.`);
          return;
        }

        stocks.push({
          symbol,
          name:      quote.symbol || symbol,
          exchange:  quote.exchange || null,
          industry:  null,
          marketCap: null,
          quote: {
            current:       quote.current       || 0,
            open:          quote.open          || 0,
            high:          quote.high          || 0,
            low:           quote.low           || 0,
            previousClose: quote.previousClose || 0,
            change:        quote.change        || 0,
            changePercent: quote.changePercent || 0,
            volume:        quote.volume        || 0,
            history:       Array.isArray(candles) ? candles.map(c => c.close) : [],
          },
          candles: candles || [],
        });
      } catch (err) {
        console.error(`[Dashboard] Failed to load ${symbol}:`, err.message);
        renderErrorCard(stockGrid, symbol, err.message);
      }
    })
  );

  // If live loading produced nothing, fall back to demo
  if (stocks.length === 0) {
    console.warn('[Dashboard] All live loads failed. Falling back to demo data.');
    const demoData = await loadDemoData();
    return demoData.stocks || [];
  }

  return stocks;
}

/**
 * Show loading skeleton cards while data is being fetched.
 * @param {HTMLElement} container
 */
function showLoadingSkeletons(container) {
  container.innerHTML = '';
  for (let i = 0; i < 5; i++) {
    const skeleton = document.createElement('div');
    skeleton.className = 'stock-card stock-card--skeleton';
    skeleton.setAttribute('aria-hidden', 'true');
    skeleton.innerHTML = `
      <div class="skeleton-line skeleton-line--short"></div>
      <div class="skeleton-line skeleton-line--long"></div>
      <div class="skeleton-line skeleton-line--medium"></div>
    `;
    container.appendChild(skeleton);
  }
}

/**
 * Render an error card for a symbol that failed to load.
 * @param {HTMLElement} container
 * @param {string} symbol
 * @param {string} message
 */
function renderErrorCard(container, symbol, message) {
  const card = document.createElement('div');
  card.className = 'stock-card stock-card--error';
  card.innerHTML = `
    <div class="stock-card__header">
      <span class="stock-card__symbol">${symbol}</span>
    </div>
    <p class="stock-card__error-text">Failed to load data.</p>
    <p class="stock-card__error-detail" style="font-size:0.75rem;color:var(--color-text-muted)">${message || ''}</p>
  `;
  container.appendChild(card);
}

/**
 * Render the horizontal market overview strip (index values, etc.).
 * @param {Array} stocks
 */
function renderMarketOverview(stocks) {
  const container = document.getElementById('market-overview');
  if (!container) return;

  container.innerHTML = '';

  // Calculate simple market stats from the demo stocks
  const gainers = stocks.filter(s => s.quote.change >= 0).length;
  const losers  = stocks.length - gainers;
  const avgChange = stocks.reduce((sum, s) => sum + s.quote.changePercent, 0) / stocks.length;
  const now = new Date();
  const timeStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });

  const items = [
    { label: 'Gainers',    value: String(gainers), positive: true },
    { label: 'Losers',     value: String(losers),  positive: false },
    { label: 'Avg Change', value: `${avgChange >= 0 ? '+' : ''}${avgChange.toFixed(2)}%`, positive: avgChange >= 0 },
    { label: 'Tracked',    value: String(stocks.length), positive: null },
    { label: 'Updated',    value: timeStr, positive: null },
  ];

  items.forEach(item => {
    const el = document.createElement('div');
    el.className = 'market-overview__item';
    el.innerHTML = `
      <span class="market-overview__item-label">${item.label}</span>
      <span class="market-overview__item-value" style="color: ${
        item.positive === null
          ? 'var(--color-text)'
          : item.positive
            ? 'var(--color-up)'
            : 'var(--color-down)'
      }">${item.value}</span>
    `;
    container.appendChild(el);
  });
}

/**
 * Render an empty state when no stocks are available.
 * @param {HTMLElement} container
 */
function renderEmptyState(container) {
  container.innerHTML = `
    <div class="empty-state" style="grid-column: 1/-1;">
      <span class="empty-state__icon">📭</span>
      <h2 class="empty-state__title">No stocks to display</h2>
      <p class="empty-state__text">Search for a stock to add it to your watchlist, or configure an API key to load live data.</p>
    </div>
  `;
}
