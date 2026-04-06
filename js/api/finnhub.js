/**
 * js/api/finnhub.js
 * Finnhub API integration module — primary data source.
 *
 * Docs: https://finnhub.io/docs/api
 * Free tier: 60 API calls/minute, WebSocket support, CORS ✅
 *
 * TODO (Phase 2):
 *  - Implement all functions below
 *  - Integrate with manager.js rate-limit queue
 *  - Add WebSocket connection for real-time quotes
 */

const BASE_URL = 'https://finnhub.io/api/v1';

/**
 * Get the Finnhub API key from localStorage.
 * Uses the cache module's namespace prefix (nostradamus_finnhub_key).
 * @returns {string|null}
 */
function getApiKey() {
  try {
    const raw = localStorage.getItem('nostradamus_finnhub_key');
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * Fetch the real-time quote for a stock symbol.
 * @param {string} symbol  - e.g. "AAPL"
 * @returns {Promise<{c: number, d: number, dp: number, h: number, l: number, o: number, pc: number, t: number}>}
 *   c=current, d=change, dp=change%, h=high, l=low, o=open, pc=prev close, t=timestamp
 */
export async function getQuote(symbol) {
  // TODO (Phase 2): implement
  throw new Error('Finnhub getQuote not yet implemented (Phase 2)');
}

/**
 * Fetch company profile (name, industry, market cap, logo, etc.).
 * @param {string} symbol
 * @returns {Promise<Object>}
 */
export async function getCompanyProfile(symbol) {
  // TODO (Phase 2): implement
  throw new Error('Finnhub getCompanyProfile not yet implemented (Phase 2)');
}

/**
 * Fetch historical OHLCV candlestick data.
 * @param {string} symbol
 * @param {'1'|'5'|'15'|'30'|'60'|'D'|'W'|'M'} resolution  - Candle resolution
 * @param {number} from  - Unix timestamp (seconds), start of range
 * @param {number} to    - Unix timestamp (seconds), end of range
 * @returns {Promise<{c: number[], h: number[], l: number[], o: number[], v: number[], t: number[], s: string}>}
 */
export async function getCandles(symbol, resolution, from, to) {
  // TODO (Phase 2): implement
  throw new Error('Finnhub getCandles not yet implemented (Phase 2)');
}

/**
 * Search for symbols matching a query string.
 * @param {string} query  - e.g. "Apple" or "AAPL"
 * @returns {Promise<Array<{description: string, displaySymbol: string, symbol: string, type: string}>>}
 */
export async function searchSymbols(query) {
  // TODO (Phase 2): implement
  throw new Error('Finnhub searchSymbols not yet implemented (Phase 2)');
}

/**
 * Fetch latest company news.
 * @param {string} symbol
 * @param {string} from  - YYYY-MM-DD
 * @param {string} to    - YYYY-MM-DD
 * @returns {Promise<Array<Object>>}
 */
export async function getCompanyNews(symbol, from, to) {
  // TODO (Phase 6): implement (news sentiment)
  throw new Error('Finnhub getCompanyNews not yet implemented (Phase 6)');
}

/**
 * Open a WebSocket connection for real-time trade data.
 * @param {string[]} symbols  - Array of symbols to subscribe to
 * @param {(trade: Object) => void} onTrade  - Callback for each trade event
 * @returns {{ close: () => void }}  - Object with a close() method to unsubscribe
 */
export function openTradesWebSocket(symbols, onTrade) {
  // TODO (Phase 2): implement WebSocket connection
  console.warn('[Finnhub] WebSocket not yet implemented (Phase 2)');
  return { close: () => {} };
}
