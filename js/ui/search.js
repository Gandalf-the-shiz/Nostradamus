/**
 * js/ui/search.js
 * Stock search bar with autocomplete suggestions.
 *
 * Phase 1: Wires up the search input with a no-op handler.
 * Phase 2+: Calls api/manager.js searchSymbols for live autocomplete.
 * Phase 3+: Clicking a suggestion opens the stock detail view.
 */

import { searchSymbols } from '../api/manager.js';

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
    // TODO (Phase 2): use live API search. For now, filter demo data.
    const results = await getDemoSearchResults(query);

    if (results.length === 0) {
      suggestions.innerHTML = `<div class="search-suggestion-item" style="color:var(--color-text-muted)">No results for "${escapeHtml(query)}"</div>`;
      return;
    }

    renderSuggestions(suggestions, results);
  } catch (err) {
    console.error('[Search] Error:', err);
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
 */
function renderSuggestions(container, results) {
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
      onSelectSymbol(item.symbol, container);
    });

    el.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onSelectSymbol(item.symbol, container);
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
 * @param {string} symbol
 * @param {HTMLElement} suggestionsEl
 */
function onSelectSymbol(symbol, suggestionsEl) {
  console.log(`[Search] Selected: ${symbol}. Detail view coming in Phase 3.`);
  const input = document.getElementById('stock-search');
  if (input) input.value = symbol;
  hideSuggestions(suggestionsEl);
  // TODO (Phase 3): navigate to stock detail view
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
