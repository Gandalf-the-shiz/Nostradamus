#!/usr/bin/env node
/**
 * scripts/fetch-historical.js
 * Fetches the last 30 days of daily OHLCV data from Finnhub for tracked symbols
 * and writes the results to data/historical/{SYMBOL}.json.
 *
 * Usage:
 *   FINNHUB_API_KEY=<your_key> node scripts/fetch-historical.js
 *
 * Runs in GitHub Actions via .github/workflows/fetch-data.yml
 * Uses only built-in Node.js modules (no npm dependencies).
 */

'use strict';

const fs   = require('fs');
const path = require('path');

const REPO_ROOT  = path.resolve(__dirname, '..');
const OUTPUT_DIR = path.resolve(REPO_ROOT, 'data', 'historical');

const SYMBOLS  = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA'];
const DAYS     = 30;
const DELAY_MS = 1000; // 1 second between API calls to respect rate limits

const API_KEY = process.env.FINNHUB_API_KEY;

if (!API_KEY) {
  console.error('[fetch-historical] ERROR: FINNHUB_API_KEY environment variable is not set.');
  process.exit(1);
}

/**
 * Fetch JSON from a URL using the built-in fetch (Node 20+).
 * @param {string} url
 * @returns {Promise<Object>}
 */
async function fetchJSON(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Sleep for a given number of milliseconds.
 * @param {number} ms
 * @returns {Promise<void>}
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Fetch 30 days of daily candles from Finnhub for a symbol.
 * @param {string} symbol
 * @returns {Promise<Array<{date: string, open: number, high: number, low: number, close: number, volume: number}>>}
 */
async function fetchCandles(symbol) {
  const nowSec  = Math.floor(Date.now() / 1000);
  const fromSec = nowSec - DAYS * 86400;
  const url = `https://finnhub.io/api/v1/stock/candle?symbol=${encodeURIComponent(symbol)}&resolution=D&from=${fromSec}&to=${nowSec}&token=${API_KEY}`;

  const data = await fetchJSON(url);

  if (!data || data.s !== 'ok' || !Array.isArray(data.t)) {
    throw new Error(`Finnhub returned status "${data?.s || 'unknown'}" for ${symbol}`);
  }

  return data.t.map((ts, i) => ({
    date:   new Date(ts * 1000).toISOString().slice(0, 10),
    open:   data.o[i],
    high:   data.h[i],
    low:    data.l[i],
    close:  data.c[i],
    volume: data.v[i],
  }));
}

/**
 * Write or update the historical JSON file for a symbol.
 * @param {string} symbol
 * @param {Array} candles
 */
function writeHistoricalFile(symbol, candles) {
  const filePath = path.resolve(OUTPUT_DIR, `${symbol}.json`);
  const payload = {
    symbol,
    lastUpdated: new Date().toISOString(),
    candles,
  };
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2) + '\n', 'utf8');
  console.log(`[fetch-historical] ✅ Wrote ${candles.length} candles for ${symbol} → ${filePath}`);
}

async function main() {
  // Ensure output directory exists
  if (!fs.existsSync(OUTPUT_DIR)) {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    console.log(`[fetch-historical] Created directory: ${OUTPUT_DIR}`);
  }

  console.log(`[fetch-historical] Fetching ${DAYS} days of data for: ${SYMBOLS.join(', ')}`);
  console.log(`[fetch-historical] Started at: ${new Date().toISOString()}`);

  for (const symbol of SYMBOLS) {
    try {
      console.log(`[fetch-historical] Fetching ${symbol}…`);
      const candles = await fetchCandles(symbol);
      writeHistoricalFile(symbol, candles);
    } catch (err) {
      console.error(`[fetch-historical] ❌ Failed to fetch ${symbol}: ${err.message}`);
    }

    // Respect rate limits — wait between requests (skip delay after last symbol)
    if (SYMBOLS.indexOf(symbol) < SYMBOLS.length - 1) {
      await sleep(DELAY_MS);
    }
  }

  console.log(`[fetch-historical] Done at: ${new Date().toISOString()}`);
}

main().catch(err => {
  console.error('[fetch-historical] Fatal error:', err);
  process.exit(1);
});
