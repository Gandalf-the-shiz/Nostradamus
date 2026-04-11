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
 */

import * as finnhub   from './finnhub.js';
import * as twelvedata from './twelvedata.js';
import * as polygon   from './polygon.js';
import { getWithTTL, setWithTTL } from '../storage/cache.js';
import { withRetry }  from '../utils/helpers.js';

// ─── Rate Limit Configuration ─────────────────────────────────
const RATE_LIMITS = {
  finnhub:    { callsPerMinute: 60,  callsPerDay: Infinity },
  twelvedata: { callsPerMinute: 8,   callsPerDay: 800 },
  polygon:    { callsPerMinute: Infinity, callsPerDay: Infinity },
};

// ─── Token Bucket State ───────────────────────────────────────
const _buckets = {};
Object.keys(RATE_LIMITS).forEach(provider => {
  _buckets[provider] = {
    tokens: RATE_LIMITS[provider].callsPerMinute,
    lastRefill: Date.now(),
  };
});

/**
 * Try to consume one token from the provider's bucket.
 * Refills tokens every 60 seconds.
 * @param {string} provider
 * @returns {boolean} true if a token was consumed, false if bucket is empty
 */
function consumeToken(provider) {
  const limit = RATE_LIMITS[provider].callsPerMinute;
  if (!isFinite(limit)) return true; // unlimited

  const bucket = _buckets[provider];
  const now = Date.now();
  const elapsed = now - bucket.lastRefill;

  // Refill tokens if a minute has passed
  if (elapsed >= 60_000) {
    bucket.tokens = limit;
    bucket.lastRefill = now;
  }

  if (bucket.tokens > 0) {
    bucket.tokens--;
    return true;
  }
  return false;
}

// ─── Cache TTLs ───────────────────────────────────────────────
const CACHE_TTL = {
  QUOTE:    5  * 60 * 1000,  // 5 minutes (real-time quotes)
  CANDLES:  15 * 60 * 1000,  // 15 minutes (historical data)
  PROFILE:  24 * 60 * 60 * 1000,  // 24 hours (company info)
  SEARCH:   60 * 60 * 1000,  // 1 hour (search results)
};

// ─── Normalisers ──────────────────────────────────────────────

/**
 * Normalise a Finnhub quote response.
 * @param {string} symbol
 * @param {Object} raw
 * @returns {Object}
 */
function normaliseFinnhubQuote(symbol, raw) {
  return {
    symbol,
    current:       raw.c,
    open:          raw.o,
    high:          raw.h,
    low:           raw.l,
    previousClose: raw.pc,
    change:        raw.d,
    changePercent: raw.dp,
    volume:        null,
    timestamp:     raw.t,
  };
}

/**
 * Normalise a Twelve Data quote response.
 * @param {Object} raw
 * @returns {Object}
 */
function normaliseTwelvedataQuote(raw) {
  return {
    symbol:        raw.symbol,
    current:       parseFloat(raw.close),
    open:          parseFloat(raw.open),
    high:          parseFloat(raw.high),
    low:           parseFloat(raw.low),
    previousClose: parseFloat(raw.previous_close),
    change:        parseFloat(raw.change),
    changePercent: parseFloat(raw.percent_change),
    volume:        parseInt(raw.volume, 10) || null,
    timestamp:     raw.datetime ? new Date(raw.datetime).getTime() / 1000 : null,
  };
}

/**
 * Normalise a Polygon previous-close response.
 * @param {string} symbol
 * @param {Object} raw
 * @returns {Object}
 */
function normalisePolygonPrevClose(symbol, raw) {
  const result = (raw.results || [])[0] || {};
  const current = result.c || 0;
  const prevClose = result.o || 0;
  return {
    symbol,
    current,
    open:          result.o || 0,
    high:          result.h || 0,
    low:           result.l || 0,
    previousClose: prevClose,
    change:        current - prevClose,
    changePercent: prevClose ? ((current - prevClose) / prevClose) * 100 : 0,
    volume:        result.v || null,
    timestamp:     result.t ? result.t / 1000 : null,
  };
}

/**
 * Normalise Finnhub candles response to array of OHLCV objects.
 * @param {Object} raw  - Finnhub candles response
 * @returns {Array<{date: string, open: number, high: number, low: number, close: number, volume: number}>}
 */
function normaliseFinnhubCandles(raw) {
  if (!raw || raw.s !== 'ok' || !Array.isArray(raw.t)) return [];
  return raw.t.map((ts, i) => ({
    date:   new Date(ts * 1000).toISOString().slice(0, 10),
    open:   raw.o[i],
    high:   raw.h[i],
    low:    raw.l[i],
    close:  raw.c[i],
    volume: raw.v[i],
  }));
}

/**
 * Normalise Twelve Data time-series response.
 * @param {Object} raw
 * @returns {Array<{date: string, open: number, high: number, low: number, close: number, volume: number}>}
 */
function normaliseTwelvedataCandles(raw) {
  if (!raw || !Array.isArray(raw.values)) return [];
  return raw.values
    .map(v => ({
      date:   v.datetime ? v.datetime.slice(0, 10) : '',
      open:   parseFloat(v.open),
      high:   parseFloat(v.high),
      low:    parseFloat(v.low),
      close:  parseFloat(v.close),
      volume: parseInt(v.volume, 10) || 0,
    }))
    .reverse(); // Twelve Data returns newest first
}

/**
 * Normalise Polygon aggregates response.
 * @param {Object} raw
 * @returns {Array<{date: string, open: number, high: number, low: number, close: number, volume: number}>}
 */
function normalisePolygonCandles(raw) {
  if (!raw || !Array.isArray(raw.results)) return [];
  return raw.results.map(r => ({
    date:   new Date(r.t).toISOString().slice(0, 10),
    open:   r.o,
    high:   r.h,
    low:    r.l,
    close:  r.c,
    volume: r.v,
  }));
}

/**
 * Normalise Finnhub company profile response.
 * @param {string} symbol
 * @param {Object} raw
 * @returns {Object}
 */
function normaliseFinnhubProfile(symbol, raw) {
  return {
    symbol,
    name:      raw.name || symbol,
    industry:  raw.finnhubIndustry || null,
    marketCap: raw.marketCapitalization ? raw.marketCapitalization * 1e6 : null,
    logo:      raw.logo || null,
    exchange:  raw.exchange || null,
    country:   raw.country || null,
    currency:  raw.currency || null,
  };
}

/**
 * Normalise Polygon ticker details response.
 * @param {string} symbol
 * @param {Object} raw
 * @returns {Object}
 */
function normalisePolygonProfile(symbol, raw) {
  return {
    symbol,
    name:      raw.name || symbol,
    industry:  raw.sic_description || null,
    marketCap: raw.market_cap || null,
    logo:      raw.branding?.icon_url || null,
    exchange:  raw.primary_exchange || null,
    country:   raw.locale || null,
    currency:  raw.currency_name || null,
  };
}

// ─── Public API ───────────────────────────────────────────────

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

  // 1. Try Finnhub
  if (consumeToken('finnhub')) {
    try {
      const raw = await withRetry(() => finnhub.getQuote(symbol));
      if (raw && raw.c) {
        const result = normaliseFinnhubQuote(symbol, raw);
        setWithTTL(cacheKey, result, CACHE_TTL.QUOTE);
        return result;
      }
    } catch (err) {
      console.warn(`[APIManager] Finnhub getQuote failed for ${symbol}:`, err.message);
    }
  } else {
    console.warn('[APIManager] Finnhub rate limit reached, skipping.');
  }

  // 2. Try Twelve Data
  if (consumeToken('twelvedata')) {
    try {
      const raw = await withRetry(() => twelvedata.getQuote(symbol));
      if (raw && raw.close) {
        const result = normaliseTwelvedataQuote(raw);
        setWithTTL(cacheKey, result, CACHE_TTL.QUOTE);
        return result;
      }
    } catch (err) {
      console.warn(`[APIManager] Twelve Data getQuote failed for ${symbol}:`, err.message);
    }
  } else {
    console.warn('[APIManager] Twelve Data rate limit reached, skipping.');
  }

  // 3. Try Polygon
  if (consumeToken('polygon')) {
    try {
      const raw = await withRetry(() => polygon.getPreviousClose(symbol));
      if (raw && raw.results && raw.results.length > 0) {
        const result = normalisePolygonPrevClose(symbol, raw);
        setWithTTL(cacheKey, result, CACHE_TTL.QUOTE);
        return result;
      }
    } catch (err) {
      console.warn(`[APIManager] Polygon getPreviousClose failed for ${symbol}:`, err.message);
    }
  }

  // 4. Demo fallback
  console.warn(`[APIManager] All APIs failed for ${symbol}. Falling back to demo data.`);
  const demo = await loadDemoData();
  const demoStock = (demo.stocks || []).find(s => s.symbol === symbol);
  if (demoStock) return { symbol, ...demoStock.quote };

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

  const nowSec  = Math.floor(Date.now() / 1000);
  const fromSec = nowSec - days * 86400;

  // 1. Try Finnhub
  if (consumeToken('finnhub')) {
    try {
      const raw = await withRetry(() => finnhub.getCandles(symbol, 'D', fromSec, nowSec));
      const candles = normaliseFinnhubCandles(raw);
      if (candles.length > 0) {
        setWithTTL(cacheKey, candles, CACHE_TTL.CANDLES);
        return candles;
      }
    } catch (err) {
      console.warn(`[APIManager] Finnhub getCandles failed for ${symbol}:`, err.message);
    }
  }

  // 2. Try Twelve Data
  if (consumeToken('twelvedata')) {
    try {
      const raw = await withRetry(() => twelvedata.getTimeSeries(symbol, '1day', days));
      const candles = normaliseTwelvedataCandles(raw);
      if (candles.length > 0) {
        setWithTTL(cacheKey, candles, CACHE_TTL.CANDLES);
        return candles;
      }
    } catch (err) {
      console.warn(`[APIManager] Twelve Data getTimeSeries failed for ${symbol}:`, err.message);
    }
  }

  // 3. Try Polygon
  if (consumeToken('polygon')) {
    try {
      const fromISO = new Date(fromSec * 1000).toISOString().slice(0, 10);
      const toISO   = new Date(nowSec  * 1000).toISOString().slice(0, 10);
      const raw = await withRetry(() => polygon.getAggregates(symbol, 1, 'day', fromISO, toISO));
      const candles = normalisePolygonCandles(raw);
      if (candles.length > 0) {
        setWithTTL(cacheKey, candles, CACHE_TTL.CANDLES);
        return candles;
      }
    } catch (err) {
      console.warn(`[APIManager] Polygon getAggregates failed for ${symbol}:`, err.message);
    }
  }

  // 4. Demo fallback
  console.warn(`[APIManager] All APIs failed for candles ${symbol}. Falling back to demo data.`);
  const demo = await loadDemoData();
  const demoStock = (demo.stocks || []).find(s => s.symbol === symbol);
  return demoStock ? (demoStock.candles || []) : [];
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

  // 1. Try Finnhub
  if (consumeToken('finnhub')) {
    try {
      const raw = await withRetry(() => finnhub.getCompanyProfile(symbol));
      if (raw && raw.name) {
        const result = normaliseFinnhubProfile(symbol, raw);
        setWithTTL(cacheKey, result, CACHE_TTL.PROFILE);
        return result;
      }
    } catch (err) {
      console.warn(`[APIManager] Finnhub getCompanyProfile failed for ${symbol}:`, err.message);
    }
  }

  // 2. Try Polygon
  if (consumeToken('polygon')) {
    try {
      const raw = await withRetry(() => polygon.getTickerDetails(symbol));
      if (raw && raw.name) {
        const result = normalisePolygonProfile(symbol, raw);
        setWithTTL(cacheKey, result, CACHE_TTL.PROFILE);
        return result;
      }
    } catch (err) {
      console.warn(`[APIManager] Polygon getTickerDetails failed for ${symbol}:`, err.message);
    }
  }

  // 3. Demo fallback
  const demo = await loadDemoData();
  const demoStock = (demo.stocks || []).find(s => s.symbol === symbol);
  if (demoStock) {
    return {
      symbol,
      name:      demoStock.name,
      industry:  demoStock.industry || null,
      marketCap: demoStock.marketCap || null,
      logo:      null,
      exchange:  demoStock.exchange || null,
      country:   null,
      currency:  null,
    };
  }
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

  // 1. Try Finnhub
  if (consumeToken('finnhub')) {
    try {
      const raw = await withRetry(() => finnhub.searchSymbols(query));
      if (raw && Array.isArray(raw.result) && raw.result.length > 0) {
        const results = raw.result.map(r => ({ symbol: r.symbol, name: r.description }));
        setWithTTL(cacheKey, results, CACHE_TTL.SEARCH);
        return results;
      }
    } catch (err) {
      console.warn(`[APIManager] Finnhub searchSymbols failed for "${query}":`, err.message);
    }
  }

  // 2. Try Twelve Data
  if (consumeToken('twelvedata')) {
    try {
      const raw = await withRetry(() => twelvedata.searchSymbols(query));
      if (Array.isArray(raw) && raw.length > 0) {
        const results = raw.map(r => ({ symbol: r.symbol, name: r.instrument_name }));
        setWithTTL(cacheKey, results, CACHE_TTL.SEARCH);
        return results;
      }
    } catch (err) {
      console.warn(`[APIManager] Twelve Data searchSymbols failed for "${query}":`, err.message);
    }
  }

  // 3. Try Polygon
  if (consumeToken('polygon')) {
    try {
      const raw = await withRetry(() => polygon.searchTickers(query));
      if (Array.isArray(raw) && raw.length > 0) {
        const results = raw.map(r => ({ symbol: r.ticker, name: r.name }));
        setWithTTL(cacheKey, results, CACHE_TTL.SEARCH);
        return results;
      }
    } catch (err) {
      console.warn(`[APIManager] Polygon searchTickers failed for "${query}":`, err.message);
    }
  }

  // 4. Return empty array as final fallback
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

/**
 * Load the latest V2 pipeline predictions from data/predictions/YYYY-MM-DD.json.
 * Tries today's date first, then scans back up to 7 days to find the most recent file.
 *
 * The file is produced by scripts/generate-predictions.py and has the shape:
 *   { date, predictionFor, generatedAt, modelVersion, predictions: { SYMBOL: { probability, direction, confidence, predictedReturn? } } }
 *
 * Returns an object: { date, generatedAt, items: Prediction[] }
 * where each Prediction has: { symbol, direction, probability, confidence, currentPrice, predictedPrice, delta, generatedAt }
 *
 * Returns null if no prediction file can be found.
 *
 * @returns {Promise<{ date: string, generatedAt: string, items: Array } | null>}
 */
export async function loadLatestPredictions() {
  const MAX_LOOKBACK_DAYS = 7;
  const now = new Date();

  for (let i = 0; i < MAX_LOOKBACK_DAYS; i++) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const dateStr = d.toISOString().slice(0, 10);

    try {
      const res = await fetch(`./data/predictions/${dateStr}.json`);
      if (!res.ok) continue;

      const data = await res.json();
      if (!data || typeof data.predictions !== 'object') continue;

      // Convert dict { SYMBOL: { probability, direction, confidence, predictedReturn? } }
      // into a flat array of Prediction objects.
      const generatedAt = data.generatedAt || new Date().toISOString();
      const items = Object.entries(data.predictions).map(([symbol, pred]) => {
        const probability     = pred.probability ?? 0.5;
        const direction       = pred.direction   ?? (probability > 0.5 ? 'UP' : 'DOWN');
        const confidence      = pred.confidence  ?? Math.abs(probability - 0.5) * 2;
        // Without live prices, currentPrice is 0. predictedPrice and delta are 0 as well,
        // and will be enriched by the live API once a user adds API keys.
        const currentPrice    = 0;
        const predictedPrice  = 0;
        const delta           = 0;

        return {
          symbol,
          direction,
          probability,
          confidence,
          currentPrice,
          predictedPrice,
          delta,
          predictedReturn: pred.predictedReturn ?? null,
          generatedAt,
          isDemo: false,
        };
      });

      console.log(`[APIManager] Loaded V2 predictions for ${dateStr}: ${items.length} tickers`);
      return { date: dateStr, generatedAt, items };
    } catch (_err) {
      // Network or parse error — try the previous day
    }
  }

  console.warn('[APIManager] No V2 prediction files found in the last 7 days.');
  return null;
}

// ─── Ticker Registry ──────────────────────────────────────────
let _tickerRegistryCache = null;

/**
 * Load the ticker registry from data/tickers/us_tickers.json.
 * Returns a Map of symbol → { name, sector, exchange }.
 * Caches the result after the first successful load.
 *
 * @returns {Promise<Map<string, { name: string, sector: string, exchange: string }>>}
 */
export async function loadTickerRegistry() {
  if (_tickerRegistryCache) return _tickerRegistryCache;
  try {
    const res = await fetch('./data/tickers/us_tickers.json');
    if (!res.ok) return new Map();
    const data = await res.json();
    const map = new Map();
    for (const t of (data.tickers || [])) {
      map.set(t.symbol, { name: t.name, sector: t.sector, exchange: t.exchange });
    }
    _tickerRegistryCache = map;
    console.log(`[APIManager] Ticker registry loaded: ${map.size.toLocaleString()} entries`);
    return map;
  } catch (err) {
    console.warn('[APIManager] Failed to load ticker registry:', err);
    return new Map();
  }
}

/**
 * Start a round-robin quote rotation for a list of symbols.
 * Fetches one quote per second (≤60/min) to respect Finnhub's free-tier rate limit.
 * Cycles through all symbols indefinitely until stopped.
 *
 * @param {string[]} symbols          - Ticker symbols to rotate through
 * @param {(symbol: string, quote: Object) => void} onQuoteUpdate  - Called with each fresh quote
 * @returns {{ stop: () => void }}    - Handle to stop the rotation
 *
 * @example
 * const rotation = startQuoteRotation(['AAPL', 'MSFT', 'TSLA'], (sym, q) => {
 *   console.log(`${sym}: $${q.current}`);
 * });
 * // Later:
 * rotation.stop();
 */
export function startQuoteRotation(symbols, onQuoteUpdate) {
  if (!Array.isArray(symbols) || symbols.length === 0) {
    return { stop: () => {} };
  }

  let index = 0;
  const intervalId = setInterval(async () => {
    const symbol = symbols[index % symbols.length];
    index++;
    try {
      const quote = await getQuote(symbol);
      if (quote) {
        onQuoteUpdate(symbol, quote);
      }
    } catch (err) {
      console.warn(`[APIManager] startQuoteRotation: failed to fetch ${symbol}:`, err.message);
    }
  }, 1000); // one call per second ≈ 60 calls/min

  return {
    stop() {
      clearInterval(intervalId);
    },
  };
}
