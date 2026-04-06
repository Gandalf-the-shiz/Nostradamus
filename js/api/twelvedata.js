/**
 * js/api/twelvedata.js
 * Twelve Data API integration module — secondary fallback.
 *
 * Docs: https://twelvedata.com/docs
 * Free tier: 800 calls/day, 8 calls/minute, CORS ✅
 *
 * TODO (Phase 2):
 *  - Implement all functions below
 *  - Integrate with manager.js rate-limit queue
 */

const BASE_URL = 'https://api.twelvedata.com';

/**
 * Get the Twelve Data API key from localStorage.
 * Uses the cache module's namespace prefix (nostradamus_twelvedata_key).
 * @returns {string|null}
 */
function getApiKey() {
  try {
    const raw = localStorage.getItem('nostradamus_twelvedata_key');
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * Fetch a real-time price quote.
 * @param {string} symbol
 * @returns {Promise<{symbol: string, name: string, exchange: string, currency: string, datetime: string, open: string, high: string, low: string, close: string, volume: string, previous_close: string, change: string, percent_change: string}>}
 */
export async function getQuote(symbol) {
  // TODO (Phase 2): implement
  throw new Error('TwelveData getQuote not yet implemented (Phase 2)');
}

/**
 * Fetch time series (OHLCV) data.
 * @param {string} symbol
 * @param {'1min'|'5min'|'15min'|'30min'|'1h'|'1day'|'1week'|'1month'} interval
 * @param {number} [outputsize=30]  - Number of data points to return
 * @returns {Promise<{values: Array<{datetime: string, open: string, high: string, low: string, close: string, volume: string}>}>}
 */
export async function getTimeSeries(symbol, interval = '1day', outputsize = 30) {
  // TODO (Phase 2): implement
  throw new Error('TwelveData getTimeSeries not yet implemented (Phase 2)');
}

/**
 * Search for symbols.
 * @param {string} query
 * @returns {Promise<Array<{symbol: string, instrument_name: string, exchange: string, mic_code: string, exchange_timezone: string, instrument_type: string, country: string, currency: string}>>}
 */
export async function searchSymbols(query) {
  // TODO (Phase 2): implement
  throw new Error('TwelveData searchSymbols not yet implemented (Phase 2)');
}

/**
 * Fetch technical indicators (RSI, MACD, etc.) — used by the ML preprocessing pipeline.
 * @param {string} symbol
 * @param {string} indicator  - e.g. "rsi", "macd"
 * @param {Object} [params={}]  - Additional indicator parameters
 * @returns {Promise<Object>}
 */
export async function getIndicator(symbol, indicator, params = {}) {
  // TODO (Phase 4): implement (used by ML preprocessing)
  throw new Error('TwelveData getIndicator not yet implemented (Phase 4)');
}
