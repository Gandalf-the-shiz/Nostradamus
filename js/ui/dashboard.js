/**
 * js/ui/dashboard.js
 * Main dashboard rendering and layout controller.
 *
 * Responsibilities:
 *  - Load stock data (demo or live)
 *  - Render the market overview strip
 *  - Render stock cards grid
 *  - Coordinate with charts.js and prediction.js
 *
 * Phase 1: Renders demo data from data/sample.json.
 * Phase 2+: Pulls live data via api/manager.js.
 * Phase 4+: Adds prediction overlays on each card.
 */

import { loadDemoData } from '../api/manager.js';
import { demoPrediction } from '../ml/prediction.js';
import { renderStockCard } from './stockcard.js';

/**
 * Initialize the dashboard with the given app state.
 * @param {{ mode: 'demo'|'live', tfReady: boolean, chartReady: boolean }} appState
 */
export async function initDashboard(appState) {
  console.log('[Dashboard] Initializing…');

  const stockGrid = document.getElementById('stock-grid');
  if (!stockGrid) return;

  // Clear loading skeletons
  stockGrid.innerHTML = '';

  let stocks = [];

  if (appState.mode === 'demo') {
    const demoData = await loadDemoData();
    stocks = demoData.stocks || [];
  } else {
    // TODO (Phase 2): load live data via api/manager.js
    console.warn('[Dashboard] Live mode not yet implemented. Falling back to demo data.');
    const demoData = await loadDemoData();
    stocks = demoData.stocks || [];
  }

  if (stocks.length === 0) {
    renderEmptyState(stockGrid);
    return;
  }

  renderMarketOverview(stocks);

  // Render each stock card
  stocks.forEach(stock => {
    const prediction = demoPrediction(stock.symbol, stock.quote.current);
    const card = renderStockCard(stock, prediction, appState.chartReady);
    stockGrid.appendChild(card);
  });

  console.log(`[Dashboard] Rendered ${stocks.length} stock cards.`);
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

  const items = [
    { label: 'Gainers',    value: String(gainers), positive: true },
    { label: 'Losers',     value: String(losers),  positive: false },
    { label: 'Avg Change', value: `${avgChange >= 0 ? '+' : ''}${avgChange.toFixed(2)}%`, positive: avgChange >= 0 },
    { label: 'Tracked',    value: String(stocks.length), positive: null },
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
