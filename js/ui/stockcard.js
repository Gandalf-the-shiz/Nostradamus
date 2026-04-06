/**
 * js/ui/stockcard.js
 * Stock card component — renders a single stock card DOM element.
 *
 * Each card displays:
 *  - Symbol + company name
 *  - Current price + change ($ and %)
 *  - Mini sparkline chart (if Chart.js available)
 *  - OHLCV compact row (Open, High, Low, Volume)
 *  - Daily range bar with current price marker
 *  - ML prediction (UP/DOWN + dollar amount)
 *  - Watchlist toggle button (persisted in localStorage)
 *
 * Phase 1: Renders from demo data with demo predictions.
 * Phase 3: Adds watchlist persistence, OHLCV row, range bar, glow effects, stagger animation.
 * Phase 4+: Real ML predictions replace demo predictions.
 */

import { formatCurrency, formatPercent, formatDollarChange, formatLargeNumber } from '../utils/helpers.js';
import { renderSparkline } from './charts.js';
import { isInWatchlist, addToWatchlist, removeFromWatchlist } from './watchlist.js';

/**
 * @typedef {Object} StockData
 * @property {string} symbol
 * @property {string} name
 * @property {Object} quote
 * @property {number} quote.current
 * @property {number} quote.open
 * @property {number} quote.high
 * @property {number} quote.low
 * @property {number} quote.previousClose
 * @property {number} quote.change
 * @property {number} quote.changePercent
 * @property {number} quote.volume
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
  const isUp   = stock.quote.change >= 0;
  const predUp = prediction.direction === 'UP';
  const inWL   = isInWatchlist(stock.symbol);

  const card = document.createElement('div');
  card.className = `stock-card stock-card--${isUp ? 'gainer' : 'loser'}`;
  card.setAttribute('role', 'article');
  card.setAttribute('aria-label', `${stock.symbol} stock card`);
  card.dataset.symbol = stock.symbol;

  // Range bar calculation
  const low     = stock.quote.low  || 0;
  const high    = stock.quote.high || 0;
  const current = stock.quote.current || 0;
  const rangeWidth = high > low ? Math.round(((current - low) / (high - low)) * 100) : 50;

  card.innerHTML = `
    <div class="stock-card__header">
      <div>
        <div class="stock-card__symbol">${escapeHtml(stock.symbol)}</div>
        <div class="stock-card__name" title="${escapeHtml(stock.name)}">${escapeHtml(stock.name)}</div>
      </div>
      <button
        class="stock-card__watchlist-btn${inWL ? ' stock-card__watchlist-btn--active' : ''}"
        aria-label="${inWL ? 'Remove' : 'Add'} ${escapeHtml(stock.symbol)} ${inWL ? 'from' : 'to'} watchlist"
        data-symbol="${escapeHtml(stock.symbol)}"
      >${inWL ? '★' : '☆'}</button>
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

    <div class="stock-card__ohlcv-row">
      <div class="stock-card__ohlcv-item"><span class="stock-card__ohlcv-label">O</span><span class="stock-card__ohlcv-value">${formatCurrency(stock.quote.open || 0)}</span></div>
      <div class="stock-card__ohlcv-item"><span class="stock-card__ohlcv-label">H</span><span class="stock-card__ohlcv-value stock-card__ohlcv-value--up">${formatCurrency(stock.quote.high || 0)}</span></div>
      <div class="stock-card__ohlcv-item"><span class="stock-card__ohlcv-label">L</span><span class="stock-card__ohlcv-value stock-card__ohlcv-value--down">${formatCurrency(stock.quote.low || 0)}</span></div>
      <div class="stock-card__ohlcv-item"><span class="stock-card__ohlcv-label">Vol</span><span class="stock-card__ohlcv-value">${formatLargeNumber(stock.quote.volume || 0)}</span></div>
    </div>

    <div class="stock-card__range-bar" aria-label="Daily range: low ${formatCurrency(low)} to high ${formatCurrency(high)}">
      <span class="stock-card__range-label">${formatCurrency(low)}</span>
      <div class="stock-card__range-track">
        <div class="stock-card__range-fill" style="width:${rangeWidth}%"></div>
        <div class="stock-card__range-marker" style="left:${rangeWidth}%"></div>
      </div>
      <span class="stock-card__range-label">${formatCurrency(high)}</span>
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
    _toggleWatchlist(stock.symbol, watchBtn);
  });

  // Card click → open detail view (wired by dashboard.js via data-symbol)
  card.addEventListener('click', () => {
    card.dispatchEvent(new CustomEvent('stock-card-click', {
      bubbles: true,
      detail: { stock, prediction },
    }));
  });

  return card;
}

/**
 * Toggle a stock in/out of the watchlist (with localStorage persistence).
 * @param {string} symbol
 * @param {HTMLButtonElement} btn
 */
function _toggleWatchlist(symbol, btn) {
  const willAdd = !isInWatchlist(symbol);
  if (willAdd) {
    addToWatchlist(symbol);
  } else {
    removeFromWatchlist(symbol);
  }
  btn.classList.toggle('stock-card__watchlist-btn--active', willAdd);
  btn.textContent = willAdd ? '★' : '☆';
  btn.setAttribute('aria-label', `${willAdd ? 'Remove' : 'Add'} ${symbol} ${willAdd ? 'from' : 'to'} watchlist`);
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
