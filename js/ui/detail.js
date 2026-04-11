/**
 * js/ui/detail.js
 * Stock detail overlay / modal component.
 *
 * openStockDetail(symbol, stock, candles, prediction)
 *   - Opens a full-screen overlay with price, OHLCV stats, chart, prediction.
 *   - Accessible: traps focus, responds to Escape key, has ARIA role="dialog".
 *
 * closeStockDetail()
 *   - Removes the overlay from DOM and destroys its Chart.js instance.
 */

import { formatCurrency, formatPercent, formatDollarChange, formatLargeNumber } from '../utils/helpers.js';
import { renderDetailChart, renderFullChart, destroyContainerChart } from './charts.js';
import { isInWatchlist, addToWatchlist, removeFromWatchlist } from './watchlist.js';
import { renderNewsPanel } from './news.js';
import { fetchNewsHeadlines } from './news.js';
import { buildShareButtons } from './share.js';
import { aggregateSentiment, classifySentiment } from '../utils/sentiment.js';
import { getPredictionsBySymbol } from '../ml/tracker.js';

const OVERLAY_ID = 'stock-detail-overlay';

/** The element that triggered the modal; focus is returned here on close. */
let _triggerEl = null;

// ─── Public API ───────────────────────────────────────────────

/**
 * Open the stock detail modal.
 *
 * @param {string}  symbol
 * @param {Object}  stock        - StockData object (quote + candles)
 * @param {Array}   candles      - OHLCV candle array (may be empty)
 * @param {Object|null} prediction - Prediction object or null
 * @param {{ mode: 'demo'|'live' }} [appState]  - App state for feature flags
 */
export function openStockDetail(symbol, stock, candles, prediction, appState = { mode: 'demo' }) {
  // Close any existing overlay first
  closeStockDetail();

  _triggerEl = document.activeElement;

  const overlay = _buildOverlay(symbol, stock, candles, prediction, appState);
  document.body.appendChild(overlay);
  document.body.style.overflow = 'hidden';

  // Focus first focusable element
  requestAnimationFrame(() => {
    overlay.removeAttribute('hidden');
    const first = overlay.querySelector('button, [tabindex="0"]');
    first?.focus();
  });

  // Escape key closes
  overlay._keyHandler = e => {
    if (e.key === 'Escape') closeStockDetail();
    if (e.key === 'Tab')    _trapFocus(e, overlay);
  };
  document.addEventListener('keydown', overlay._keyHandler);

  // Re-render chart after overlay is in DOM (so dimensions are known)
  const chartContainer = overlay.querySelector('.detail-overlay__chart-inner');
  if (chartContainer) {
    // Build past-predictions array for this symbol, aligned to candle dates
    const trackedPreds = getPredictionsBySymbol(symbol);
    const pastPredictions = trackedPreds
      .filter(p => p.predictedPrice != null)
      .map(p => ({
        date: new Date(p.generatedAt).toISOString().slice(0, 10),
        predictedPrice: p.predictedPrice,
      }));

    if (candles && candles.length > 0) {
      renderFullChart(chartContainer, candles, prediction, pastPredictions);
    } else if (stock.quote.history && stock.quote.history.length > 0) {
      const history = stock.quote.history.map((close, i) => ({ date: String(i), close }));
      renderDetailChart(chartContainer, history, prediction, pastPredictions);
    } else {
      // V2 prediction-only mode — no live price history available
      chartContainer.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:8px;color:var(--color-text-muted);font-size:13px;text-align:center;padding:16px;">
          <span style="font-size:2rem;">📊</span>
          <span>Live price history unavailable in prediction-only mode.</span>
          <span style="font-size:11px;opacity:0.6;">Add API keys in Settings to enable charts.</span>
        </div>`;
    }
  }

  // Async: populate news panel after overlay is shown
  const newsContainer = overlay.querySelector('.detail-overlay__news-body');
  if (newsContainer) {
    renderNewsPanel(newsContainer, symbol, appState);
  }

  // Async: compute and display sentiment badge from recent headlines
  const sentimentEl = overlay.querySelector('.detail-overlay__sentiment');
  if (sentimentEl) {
    fetchNewsHeadlines(symbol, appState).then(headlines => {
      if (!headlines.length) return;
      const result = aggregateSentiment(headlines);
      const label  = classifySentiment(result.average);
      const emoji  = label === 'bullish' ? '😊' : label === 'bearish' ? '😟' : '😐';
      const pct    = Math.round((result.average + 1) * 50); // map [-1,1] → [0,100]
      sentimentEl.querySelector('.sentiment-badge__text').textContent =
        `${emoji} ${label.charAt(0).toUpperCase() + label.slice(1)}`;
      sentimentEl.querySelector('.sentiment-badge__score').textContent =
        `${result.average >= 0 ? '+' : ''}${result.average.toFixed(2)}`;
      const bar = sentimentEl.querySelector('.sentiment-gauge__fill');
      if (bar) {
        bar.style.width = `${pct}%`;
        bar.className = `sentiment-gauge__fill sentiment-gauge__fill--${label}`;
      }
      sentimentEl.removeAttribute('hidden');
    }).catch(() => { /* sentiment is optional — fail silently */ });
  }
}

/**
 * Close the stock detail modal.
 */
export function closeStockDetail() {
  const overlay = document.getElementById(OVERLAY_ID);
  if (!overlay) return;

  // Destroy chart
  const chartContainer = overlay.querySelector('.detail-overlay__chart-inner');
  if (chartContainer) destroyContainerChart(chartContainer);

  // Remove key listener
  if (overlay._keyHandler) {
    document.removeEventListener('keydown', overlay._keyHandler);
  }

  // Animate out
  overlay.classList.add('detail-overlay--closing');
  setTimeout(() => {
    overlay.remove();
    document.body.style.overflow = '';
    _triggerEl?.focus();
    _triggerEl = null;
  }, 280);
}

// ─── DOM builders ─────────────────────────────────────────────

function _buildOverlay(symbol, stock, candles, prediction, appState) {
  const q       = stock.quote || {};
  const isUp    = (q.change || 0) >= 0;
  const predUp  = prediction?.direction === 'UP';

  // V2 mode: no live prices — only pipeline prediction data available
  const isV2 = !q.current && stock._v2Prediction;

  const overlay = document.createElement('div');
  overlay.id        = OVERLAY_ID;
  overlay.className = 'detail-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', `${symbol} stock detail`);
  overlay.hidden    = true;

  // Build prediction details section (for both V2 and live modes)
  const confPct  = Math.round((prediction?.confidence ?? 0) * 100);
  const confTier = (prediction?.confidence ?? 0) >= 0.75 ? 'high' : (prediction?.confidence ?? 0) >= 0.6 ? 'medium' : 'low';
  const predReturnPct = prediction?.predictedReturn != null
    ? `${predUp ? '+' : ''}${(prediction.predictedReturn * 100).toFixed(2)}%`
    : null;

  const predictionBlock = prediction ? `
    <div class="detail-overlay__prediction">
      <div class="detail-overlay__prediction-header">
        <span class="detail-overlay__prediction-title">🔮 AI Prediction</span>
        <span class="detail-overlay__prediction-badge${prediction.isDemo ? '' : ' detail-overlay__prediction-badge--live'}">${prediction.isDemo ? 'Demo' : confPct + '%'}</span>
      </div>
      <div class="detail-overlay__prediction-body">
        <span class="detail-overlay__prediction-direction detail-overlay__prediction-direction--${predUp ? 'up' : 'down'}">
          ${predUp ? '▲ UP' : '▼ DOWN'}
        </span>
        ${isV2 && predReturnPct
          ? `<span class="detail-overlay__prediction-price">${_esc(predReturnPct)}</span>`
          : !isV2
            ? `<span class="detail-overlay__prediction-price">${formatCurrency(prediction.predictedPrice || 0)}</span>
               <span class="detail-overlay__prediction-delta detail-overlay__prediction-delta--${predUp ? 'up' : 'down'}">
                 ${formatDollarChange(predUp ? prediction.delta : -(prediction.delta || 0))}
               </span>`
            : ''
        }
      </div>
      ${isV2 ? `
      <div style="margin-top:var(--space-2);">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:var(--space-1);font-size:var(--font-size-sm);color:var(--color-text-muted);">
          <span>Confidence</span><span>${confPct}%</span>
        </div>
        <div class="conf-gauge">
          <div class="conf-gauge__fill conf-gauge__fill--${confTier}" style="width:${confPct}%"></div>
        </div>
        ${prediction.probability != null ? `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:var(--space-2);font-size:var(--font-size-sm);color:var(--color-text-muted);">
          <span>Probability</span><span>${Math.round((prediction.probability ?? 0.5) * 100)}%</span>
        </div>` : ''}
      </div>` : ''}
    </div>
  ` : '';

  overlay.innerHTML = `
    <div class="detail-overlay__backdrop" aria-hidden="true"></div>
    <div class="detail-overlay__panel">

      <!-- Header -->
      <div class="detail-overlay__header">
        <div class="detail-overlay__header-info">
          <span class="detail-overlay__symbol">${_esc(symbol)}</span>
          <span class="detail-overlay__name">${_esc(stock.name || symbol)}</span>
          ${stock.exchange ? `<span class="detail-overlay__exchange">${_esc(stock.exchange)}</span>` : ''}
        </div>
        <button class="detail-overlay__close" aria-label="Close detail view" id="detail-close-btn">✕</button>
      </div>

      ${isV2 ? '' : `
      <!-- Price (live mode only) -->
      <div class="detail-overlay__price">
        <span class="detail-overlay__price-value">${formatCurrency(q.current || 0)}</span>
        <span class="detail-overlay__price-change detail-overlay__price-change--${isUp ? 'up' : 'down'}">
          ${formatDollarChange(q.change || 0)} (${formatPercent(q.changePercent || 0)})
        </span>
      </div>

      <!-- OHLCV Stats (live mode only) -->
      <div class="detail-overlay__stats">
        ${_statItem('Open',       formatCurrency(q.open || 0))}
        ${_statItem('High',       formatCurrency(q.high || 0))}
        ${_statItem('Low',        formatCurrency(q.low  || 0))}
        ${_statItem('Prev Close', formatCurrency(q.previousClose || 0))}
        ${_statItem('Volume',     formatLargeNumber(q.volume || 0))}
        ${_statItem('Market Cap', stock.marketCap ? formatLargeNumber(stock.marketCap) : '—')}
      </div>`}

      <!-- AI Prediction -->
      ${predictionBlock}

      <!-- Chart -->
      <div class="detail-overlay__chart">
        <div class="detail-overlay__chart-inner" style="height:${isV2 ? '160px' : '240px'};position:relative;"></div>
      </div>

      <!-- Sentiment Badge (populated asynchronously) -->
      <div class="detail-overlay__sentiment sentiment-badge" hidden aria-live="polite">
        <span class="sentiment-badge__label">📰 News Sentiment:</span>
        <span class="sentiment-badge__text">—</span>
        <span class="sentiment-badge__score"></span>
        <div class="sentiment-gauge" aria-hidden="true">
          <div class="sentiment-gauge__fill"></div>
        </div>
      </div>

      <!-- Actions -->
      <div class="detail-overlay__actions">
        <button class="btn btn--secondary detail-overlay__watchlist-btn" data-symbol="${_esc(symbol)}" id="detail-watchlist-btn">
          ${isInWatchlist(symbol) ? '★ Remove from Watchlist' : '☆ Add to Watchlist'}
        </button>
      </div>

      <!-- News -->
      <div class="detail-overlay__news">
        <h3 class="detail-overlay__section-title">📰 Recent News &amp; Sentiment</h3>
        <div class="detail-overlay__news-body">
          <!-- populated async by renderNewsPanel -->
        </div>
      </div>

    </div>
  `;

  // Close on backdrop click
  overlay.querySelector('.detail-overlay__backdrop')?.addEventListener('click', closeStockDetail);
  overlay.querySelector('#detail-close-btn')?.addEventListener('click', closeStockDetail);

  // Watchlist toggle
  overlay.querySelector('#detail-watchlist-btn')?.addEventListener('click', e => {
    e.stopPropagation();
    _toggleWatchlistBtn(symbol, overlay.querySelector('#detail-watchlist-btn'));
  });

  // Share buttons (append to actions row)
  if (prediction) {
    const actionsEl = overlay.querySelector('.detail-overlay__actions');
    if (actionsEl) {
      actionsEl.appendChild(buildShareButtons(symbol, prediction));
    }
  }

  return overlay;
}

function _statItem(label, value) {
  return `
    <div class="detail-overlay__stat">
      <span class="detail-overlay__stat-label">${label}</span>
      <span class="detail-overlay__stat-value">${value}</span>
    </div>
  `;
}

function _toggleWatchlistBtn(symbol, btn) {
  if (isInWatchlist(symbol)) {
    removeFromWatchlist(symbol);
    btn.textContent = '☆ Add to Watchlist';
  } else {
    addToWatchlist(symbol);
    btn.textContent = '★ Remove from Watchlist';
  }
}

// ─── Focus trap ───────────────────────────────────────────────

function _trapFocus(e, modal) {
  const focusable = Array.from(
    modal.querySelectorAll('a[href], button:not([disabled]), input, [tabindex="0"]')
  ).filter(el => !el.closest('[hidden]'));
  if (focusable.length === 0) return;
  const first = focusable[0];
  const last  = focusable[focusable.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

// ─── Escape helper ────────────────────────────────────────────

function _esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
