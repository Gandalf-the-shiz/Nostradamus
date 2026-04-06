/**
 * js/api/manager.js
 * API Manager — orchestrates fallback chain, rate limiting, and request batching.
 *
 * Fallback order:
 *   1. Finnhub (primary)    — 60 calls/min
 *   2. Twelve Data          — 800 calls/day, 8 calls/min
 *   3. Polygon.io           — unlimited (prev-day only on free tier)
 *   4. localStorage cache   — any age
 *   5. Demo data (sample.json)
 *
 * TODO (Phase 2):
 *  - Implement rate-limit token bucket per provider
 *  - Implement request batching queue
 *  - Wire up all fallback logic
 *  - Integrate TTL cache checks before every network call
 */

import * as finnhub   from './finnhub.js';
import * as twelvdata from './twelvedata.js';
import * as polygon   from './polygon.js';
import { getWithTTL, setWithTTL } from '../storage/cache.js';
import { withRetry }  from '../utils/helpers.js';

// ─── Rate Limit Configuration ─────────────────────────────────
const RATE_LIMITS = {
  finnhub:    { callsPerMinute: 60,  callsPerDay: Infinity },
  twelvedata: { callsPerMinute: 8,   callsPerDay: 800 },
  polygon:    { callsPerMinute: Infinity, callsPerDay: Infinity },
};

// ─── Cache TTLs ───────────────────────────────────────────────
const CACHE_TTL = {
  QUOTE:    5  * 60 * 1000,  // 5 minutes (real-time quotes)
  CANDLES:  15 * 60 * 1000,  // 15 minutes (historical data)
  PROFILE:  24 * 60 * 60 * 1000,  // 24 hours (company info)
  SEARCH:   60 * 60 * 1000,  // 1 hour (search results)
};

/**
 * Get a real-time stock quote with fallback chain + caching.
 * @param {string} symbol
 * @returns {Promise<Object>}  Normalised quote object.
 */
export async function getQuote(symbol) {
  const cacheKey = `quote_${symbol}`;
  const cached = getWithTTL(cacheKey);
  if (cached) {
    console.log(`[APIManager] Cache hit for quote: ${symbol}`);
    return cached;
  }

  // TODO (Phase 2): attempt finnhub → twelvedata → polygon → demo data
  console.warn(`[APIManager] getQuote not yet fully implemented (Phase 2). Symbol: ${symbol}`);
  return null;
}

/**
 * Get historical OHLCV candles with fallback chain + caching.
 * @param {string} symbol
 * @param {number} [days=30]  - How many days of history to fetch
 * @returns {Promise<Array<{date: string, open: number, high: number, low: number, close: number, volume: number}>>}
 */
export async function getCandles(symbol, days = 30) {
  const cacheKey = `candles_${symbol}_${days}d`;
  const cached = getWithTTL(cacheKey);
  if (cached) {
    console.log(`[APIManager] Cache hit for candles: ${symbol}`);
    return cached;
  }

  // TODO (Phase 2): attempt finnhub → twelvedata → polygon → demo data
  console.warn(`[APIManager] getCandles not yet fully implemented (Phase 2). Symbol: ${symbol}`);
  return null;
}

/**
 * Get company profile with fallback chain + caching.
 * @param {string} symbol
 * @returns {Promise<Object>}
 */
export async function getCompanyProfile(symbol) {
  const cacheKey = `profile_${symbol}`;
  const cached = getWithTTL(cacheKey);
  if (cached) return cached;

  // TODO (Phase 2): implement
  console.warn(`[APIManager] getCompanyProfile not yet implemented (Phase 2). Symbol: ${symbol}`);
  return null;
}

/**
 * Search for stock symbols/companies.
 * @param {string} query
 * @returns {Promise<Array<{symbol: string, name: string}>>}
 */
export async function searchSymbols(query) {
  const cacheKey = `search_${query.toLowerCase()}`;
  const cached = getWithTTL(cacheKey);
  if (cached) return cached;

  // TODO (Phase 2): implement fallback search
  console.warn(`[APIManager] searchSymbols not yet implemented (Phase 2). Query: ${query}`);
  return [];
}

/**
 * Load the demo data from data/sample.json.
 * Used as the last fallback, and always used in Demo Mode.
 * @returns {Promise<Object>}
 */
export async function loadDemoData() {
  try {
    const res = await fetch('./data/sample.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error('[APIManager] Failed to load demo data:', err);
    return { stocks: [] };
  }
}
