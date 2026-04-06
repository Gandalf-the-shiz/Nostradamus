/**
 * js/ui/watchlist.js
 * Watchlist management — localStorage persistence + view rendering.
 *
 * localStorage key: `nostradamus_watchlist` (raw array, no cache TTL wrapper).
 *
 * Exports:
 *   getWatchlist()          → string[]
 *   isInWatchlist(symbol)   → boolean
 *   addToWatchlist(symbol)
 *   removeFromWatchlist(symbol)
 *   initWatchlist(appState)
 */

import { getQuote, getCandles, loadDemoData } from '../api/manager.js';
import { demoPrediction } from '../ml/prediction.js';
import { renderStockCard } from './stockcard.js';
import { showToast } from '../utils/helpers.js';

const WL_KEY = 'nostradamus_watchlist';   // raw localStorage key
const CUSTOM_EVENT = 'watchlist-changed';

// ─── Persistence helpers ──────────────────────────────────────

/**
 * Return the current watchlist array from localStorage.
 * @returns {string[]}
 */
export function getWatchlist() {
  try {
    const raw = localStorage.getItem(WL_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/**
 * Check if a symbol is in the watchlist.
 * @param {string} symbol
 * @returns {boolean}
 */
export function isInWatchlist(symbol) {
  return getWatchlist().includes(symbol.toUpperCase());
}

/**
 * Add a symbol to the watchlist.
 * Dispatches 'watchlist-changed' custom event on document.
 * @param {string} symbol
 */
export function addToWatchlist(symbol) {
  const sym = symbol.toUpperCase();
  const list = getWatchlist();
  if (!list.includes(sym)) {
    list.push(sym);
    _save(list);
    _dispatch(sym, 'added');
  }
}

/**
 * Remove a symbol from the watchlist.
 * Dispatches 'watchlist-changed' custom event on document.
 * @param {string} symbol
 */
export function removeFromWatchlist(symbol) {
  const sym = symbol.toUpperCase();
  const list = getWatchlist().filter(s => s !== sym);
  _save(list);
  _dispatch(sym, 'removed');
}

// ─── View rendering ───────────────────────────────────────────

/**
 * Initialise / refresh the Watchlist view section.
 * Called from app.js whenever the user navigates to the Watchlist tab.
 * @param {{ mode: 'demo'|'live', chartReady: boolean }} appState
 */
export async function initWatchlist(appState) {
  const container = document.getElementById('watchlist-grid');
  if (!container) return;

  const list = getWatchlist();

  if (list.length === 0) {
    _renderEmpty(container);
    return;
  }

  _showSkeletons(container, list.length);

  let stocks = [];

  if (appState.mode === 'demo') {
    // Filter demo data to watchlisted symbols
    try {
      const demoData = await loadDemoData();
      const demoStocks = demoData.stocks || [];
      stocks = demoStocks.filter(s => list.includes(s.symbol));
      // For any symbol in watchlist not in demo, fabricate a minimal entry
      for (const sym of list) {
        if (!stocks.find(s => s.symbol === sym)) {
          stocks.push(_fakeDemoStock(sym));
        }
      }
    } catch {
      stocks = list.map(_fakeDemoStock);
    }
  } else {
    await Promise.allSettled(
      list.map(async symbol => {
        try {
          const [quote, candles] = await Promise.all([
            getQuote(symbol),
            getCandles(symbol),
          ]);
          if (!quote) return;
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
          console.warn(`[Watchlist] Failed to load ${symbol}:`, err.message);
        }
      })
    );

    if (stocks.length === 0) {
      _renderEmpty(container, 'Could not load watchlist data. Check your API keys.');
      return;
    }
  }

  container.innerHTML = '';

  stocks.forEach((stock, i) => {
    const prediction = demoPrediction(stock.symbol, stock.quote.current);
    const card = renderStockCard(stock, prediction, appState.chartReady);
    card.style.animationDelay = `${i * 50}ms`;
    card.classList.add('stock-card--animate-in');
    container.appendChild(card);
  });

  _appendClearButton(container);
}

// ─── Private helpers ──────────────────────────────────────────

function _save(list) {
  try {
    localStorage.setItem(WL_KEY, JSON.stringify(list));
  } catch {
    // ignore
  }
}

function _dispatch(symbol, action) {
  document.dispatchEvent(new CustomEvent(CUSTOM_EVENT, {
    detail: { symbol, action },
    bubbles: true,
  }));
}

function _renderEmpty(container, message) {
  container.innerHTML = `
    <div class="watchlist-empty" style="grid-column: 1/-1;">
      <span class="watchlist-empty__icon">📋</span>
      <p class="watchlist-empty__text">${message || 'Your watchlist is empty. Search for stocks and tap ☆ to add them.'}</p>
    </div>
  `;
}

function _showSkeletons(container, count) {
  container.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const sk = document.createElement('div');
    sk.className = 'stock-card stock-card--skeleton';
    sk.setAttribute('aria-hidden', 'true');
    sk.innerHTML = `
      <div class="skeleton-line skeleton-line--short"></div>
      <div class="skeleton-line skeleton-line--long"></div>
      <div class="skeleton-line skeleton-line--medium"></div>
    `;
    container.appendChild(sk);
  }
}

function _appendClearButton(container) {
  const wrap = document.createElement('div');
  wrap.className = 'watchlist-header';
  wrap.style.gridColumn = '1/-1';
  const btn = document.createElement('button');
  btn.className = 'btn btn--danger';
  btn.textContent = 'Clear Watchlist';
  btn.addEventListener('click', () => {
    _save([]);
    _dispatch('*', 'cleared');
    showToast('Watchlist cleared.', 'info');
    _renderEmpty(container);
  });
  wrap.appendChild(btn);
  container.appendChild(wrap);
}

function _fakeDemoStock(sym) {
  const price = 100 + (sym.charCodeAt(0) % 400);
  return {
    symbol: sym,
    name: sym,
    exchange: null,
    industry: null,
    marketCap: null,
    quote: {
      current: price, open: price - 1, high: price + 2,
      low: price - 2, previousClose: price - 0.5,
      change: 0.5, changePercent: 0.5,
      volume: 1000000, history: [],
    },
    candles: [],
  };
}
