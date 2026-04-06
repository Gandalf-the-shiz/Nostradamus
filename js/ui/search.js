/**
 * js/ui/search.js
 * Stock search bar with autocomplete suggestions.
 *
 * Phase 1: Wires up the search input with a no-op handler.
 * Phase 2: Calls api/manager.js searchSymbols for live autocomplete.
 * Phase 3+: Clicking a suggestion opens the stock detail view.
 */

import { searchSymbols, getQuote, getCandles } from '../api/manager.js';
import { demoPrediction } from '../ml/prediction.js';
import { renderStockCard } from './stockcard.js';

/** Minimum characters before triggering a search. */
const MIN_QUERY_LENGTH = 2;
/** Debounce delay in ms to avoid firing on every keystroke. */
const DEBOUNCE_MS = 300;

/**
 * Initialize the search bar.
 * @param {{ mode: 'demo'|'live' }} appState
 */
export function initSearch(appState) {
  const input       = document.getElementById('stock-search');
  const suggestions = document.getElementById('search-suggestions');

  if (!input || !suggestions) return;

  let debounceTimer = null;

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const query = input.value.trim();

    if (query.length < MIN_QUERY_LENGTH) {
      hideSuggestions(suggestions);
      return;
    }

    debounceTimer = setTimeout(() => {
      handleSearch(query, suggestions, appState);
    }, DEBOUNCE_MS);
  });

  // Close suggestions when clicking outside
  document.addEventListener('click', e => {
    if (!input.contains(e.target) && !suggestions.contains(e.target)) {
      hideSuggestions(suggestions);
    }
  });

  // Keyboard navigation within suggestions
  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') hideSuggestions(suggestions);
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const first = suggestions.querySelector('[role="option"]');
      first?.focus();
    }
  });

  console.log('[Search] Initialized.');
}

/**
 * Handle a search query.
 * @param {string} query
 * @param {HTMLElement} suggestions
 * @param {{ mode: string }} appState
 */
async function handleSearch(query, suggestions, appState) {
  suggestions.hidden = false;
  suggestions.innerHTML = '<div class="search-suggestion-item" style="color:var(--color-text-muted)">Searching…</div>';

  try {
    let results;
    if (appState.mode === 'live') {
      results = await searchSymbols(query);
      // Fall back to demo results if API returned nothing
      if (!results || results.length === 0) {
        results = await getDemoSearchResults(query);
      }
    } else {
      results = await getDemoSearchResults(query);
    }

    if (results.length === 0) {
      suggestions.innerHTML = `<div class="search-suggestion-item" style="color:var(--color-text-muted)">No results for "${escapeHtml(query)}"</div>`;
      return;
    }

    renderSuggestions(suggestions, results, appState);
  } catch (err) {
    console.error('[Search] Error:', err);
    // Try demo fallback on error
    try {
      const results = await getDemoSearchResults(query);
      if (results.length > 0) {
        renderSuggestions(suggestions, results, appState);
        return;
      }
    } catch {
      // ignore
    }
    suggestions.innerHTML = '<div class="search-suggestion-item" style="color:var(--color-down)">Search failed. Try again.</div>';
  }
}

/**
 * Simple in-memory search over well-known demo symbols.
 * Used in Phase 1; replaced by API in Phase 2.
 * @param {string} query
 * @returns {Promise<Array<{symbol: string, name: string}>>}
 */
async function getDemoSearchResults(query) {
  const KNOWN = [
    { symbol: 'AAPL',  name: 'Apple Inc.' },
    { symbol: 'GOOGL', name: 'Alphabet Inc.' },
    { symbol: 'MSFT',  name: 'Microsoft Corporation' },
    { symbol: 'AMZN',  name: 'Amazon.com Inc.' },
    { symbol: 'TSLA',  name: 'Tesla, Inc.' },
    { symbol: 'META',  name: 'Meta Platforms Inc.' },
    { symbol: 'NVDA',  name: 'NVIDIA Corporation' },
    { symbol: 'NFLX',  name: 'Netflix, Inc.' },
    { symbol: 'BRKB',  name: 'Berkshire Hathaway Inc.' },
    { symbol: 'JPM',   name: 'JPMorgan Chase & Co.' },
  ];
  const q = query.toUpperCase();
  return KNOWN.filter(s => s.symbol.startsWith(q) || s.name.toUpperCase().includes(q));
}

/**
 * Render autocomplete suggestions into the dropdown.
 * @param {HTMLElement} container
 * @param {Array<{symbol: string, name: string}>} results
 * @param {{ mode: string }} appState
 */
function renderSuggestions(container, results, appState) {
  container.innerHTML = '';
  results.slice(0, 6).forEach((item, index) => {
    const el = document.createElement('div');
    el.className = 'search-suggestion-item';
    el.setAttribute('role', 'option');
    el.setAttribute('tabindex', '0');
    el.setAttribute('aria-selected', 'false');
    el.innerHTML = `
      <span class="search-suggestion-item__symbol">${escapeHtml(item.symbol)}</span>
      <span class="search-suggestion-item__name">${escapeHtml(item.name)}</span>
    `;

    el.addEventListener('click', () => {
      onSelectSymbol(item.symbol, container, appState);
    });

    el.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onSelectSymbol(item.symbol, container, appState);
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        el.nextElementSibling?.focus();
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        const prev = el.previousElementSibling;
        if (prev) prev.focus();
        else document.getElementById('stock-search')?.focus();
      }
    });

    container.appendChild(el);
  });
}

/**
 * Handle selecting a symbol from the suggestions.
 * In live mode, fetches the stock data and adds a card to the dashboard.
 * @param {string} symbol
 * @param {HTMLElement} suggestionsEl
 * @param {{ mode: string }} appState
 */
async function onSelectSymbol(symbol, suggestionsEl, appState) {
  const input = document.getElementById('stock-search');
  if (input) input.value = symbol;
  hideSuggestions(suggestionsEl);

  if (appState && appState.mode === 'live') {
    await addSymbolToDashboard(symbol, appState);
  } else {
    console.log(`[Search] Selected: ${symbol}. Detail view coming in Phase 3.`);
  }
}

/**
 * Fetch data for a symbol and add a new card to the dashboard stock grid.
 * @param {string} symbol
 * @param {{ chartReady: boolean }} appState
 */
async function addSymbolToDashboard(symbol, appState) {
  const stockGrid = document.getElementById('stock-grid');
  if (!stockGrid) return;

  try {
    const [quote, candles] = await Promise.all([
      getQuote(symbol),
      getCandles(symbol),
    ]);

    if (!quote) {
      console.warn(`[Search] No data for ${symbol}.`);
      return;
    }

    const stock = {
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
    };

    const prediction = demoPrediction(stock.symbol, stock.quote.current);
    const card = renderStockCard(stock, prediction, appState.chartReady);
    stockGrid.appendChild(card);
    console.log(`[Search] Added ${symbol} to dashboard.`);
  } catch (err) {
    console.error(`[Search] Failed to add ${symbol} to dashboard:`, err.message);
  }
}

/**
 * Hide the suggestions dropdown.
 * @param {HTMLElement} el
 */
function hideSuggestions(el) {
  el.hidden = true;
  el.innerHTML = '';
}

/**
 * Escape HTML special characters.
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
