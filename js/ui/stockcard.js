/**
 * js/ui/stockcard.js
 * Stock card component — renders a single stock card DOM element.
 *
 * Each card displays:
 *  - Symbol + company name
 *  - Current price + change ($ and %)
 *  - Mini sparkline chart (if Chart.js available)
 *  - ML prediction (UP/DOWN + dollar amount)
 *  - Watchlist toggle button
 *
 * Phase 1: Renders from demo data with demo predictions.
 * Phase 3+: Adds watchlist persistence, click → detail view.
 * Phase 4+: Real ML predictions replace demo predictions.
 */

import { formatCurrency, formatPercent, formatDollarChange } from '../utils/helpers.js';
import { renderSparkline } from './charts.js';

/**
 * @typedef {Object} StockData
 * @property {string} symbol
 * @property {string} name
 * @property {Object} quote
 * @property {number} quote.current
 * @property {number} quote.change
 * @property {number} quote.changePercent
 * @property {number[]} quote.history  - Array of recent close prices for sparkline
 */

/**
 * @typedef {import('../ml/prediction.js').Prediction} Prediction
 */

/**
 * Create and return a stock card DOM element.
 * @param {StockData} stock
 * @param {Prediction} prediction
 * @param {boolean} chartAvailable  - Whether Chart.js is loaded
 * @returns {HTMLElement}
 */
export function renderStockCard(stock, prediction, chartAvailable) {
  const isUp = stock.quote.change >= 0;
  const predUp = prediction.direction === 'UP';

  const card = document.createElement('div');
  card.className = 'stock-card';
  card.setAttribute('role', 'article');
  card.setAttribute('aria-label', `${stock.symbol} stock card`);
  card.dataset.symbol = stock.symbol;

  card.innerHTML = `
    <div class="stock-card__header">
      <div>
        <div class="stock-card__symbol">${escapeHtml(stock.symbol)}</div>
        <div class="stock-card__name" title="${escapeHtml(stock.name)}">${escapeHtml(stock.name)}</div>
      </div>
      <button
        class="stock-card__watchlist-btn"
        aria-label="Add ${escapeHtml(stock.symbol)} to watchlist"
        data-symbol="${escapeHtml(stock.symbol)}"
      >☆</button>
    </div>

    <div class="stock-card__price-row">
      <span class="stock-card__price">${formatCurrency(stock.quote.current)}</span>
      <span class="stock-card__change stock-card__change--${isUp ? 'up' : 'down'}">
        ${formatDollarChange(stock.quote.change)} (${formatPercent(stock.quote.changePercent)})
      </span>
    </div>

    <div class="stock-card__chart-container" id="chart-${escapeHtml(stock.symbol)}">
      ${chartAvailable ? '' : '<p style="font-size:11px;color:var(--color-text-faint);text-align:center;padding:8px 0;">Chart unavailable</p>'}
    </div>

    <div class="stock-card__prediction">
      <span class="stock-card__prediction-label">AI Prediction:</span>
      <span class="stock-card__prediction-value stock-card__prediction-value--${predUp ? 'up' : 'down'}">
        ${predUp ? '▲' : '▼'} ${formatDollarChange(predUp ? prediction.delta : -prediction.delta)}
      </span>
      ${prediction.isDemo ? '<span class="stock-card__prediction-badge">Demo</span>' : `<span class="stock-card__prediction-badge">${Math.round(prediction.confidence * 100)}%</span>`}
    </div>
  `;

  // Render sparkline chart
  if (chartAvailable && stock.quote.history && stock.quote.history.length > 0) {
    const chartContainer = card.querySelector(`#chart-${stock.symbol}`);
    if (chartContainer) {
      renderSparkline(chartContainer, stock.quote.history, isUp);
    }
  }

  // Watchlist toggle
  const watchBtn = card.querySelector('.stock-card__watchlist-btn');
  watchBtn?.addEventListener('click', e => {
    e.stopPropagation();
    toggleWatchlist(stock.symbol, watchBtn);
  });

  // Card click → TODO (Phase 3): open detail view
  card.addEventListener('click', () => {
    console.log(`[StockCard] Clicked: ${stock.symbol}. Detail view coming in Phase 3.`);
  });

  return card;
}

/**
 * Toggle a stock in/out of the watchlist.
 * @param {string} symbol
 * @param {HTMLButtonElement} btn
 */
function toggleWatchlist(symbol, btn) {
  // TODO (Phase 3): persist watchlist to localStorage
  const isActive = btn.classList.toggle('stock-card__watchlist-btn--active');
  btn.textContent = isActive ? '★' : '☆';
  btn.setAttribute('aria-label', isActive ? `Remove ${symbol} from watchlist` : `Add ${symbol} to watchlist`);
}

/**
 * Escape HTML special characters to prevent XSS.
 * @param {string} str
 * @returns {string}
 */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
