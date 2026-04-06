/**
 * js/ml/tracker.js
 * Prediction tracking system — Phase 5.
 *
 * Stores every prediction the model makes with timestamps, symbol,
 * direction (UP/DOWN), dollar delta, predicted price, and actual price
 * at prediction time. Predictions are persisted in localStorage.
 *
 * When actual next-day prices become available, predictions can be
 * "resolved" by supplying the real close price, which computes whether
 * the direction call was correct and the absolute price error.
 *
 * localStorage key (via cache.js): 'predictions' → 'nostradamus_predictions'
 */

import { getItem, setItem } from '../storage/cache.js';

const PREDICTIONS_KEY = 'predictions';
const MAX_STORED = 500; // keep last N predictions to avoid unbounded growth

/**
 * @typedef {Object} TrackedPrediction
 * @property {string}  id             - Unique identifier
 * @property {string}  symbol
 * @property {'UP'|'DOWN'} direction
 * @property {number}  delta          - Predicted dollar change magnitude
 * @property {number}  predictedPrice
 * @property {number}  currentPrice   - Price at the time of prediction
 * @property {number}  confidence     - 0..1
 * @property {number}  generatedAt    - Unix ms timestamp
 * @property {boolean} isDemo         - Was this a demo (no real model)?
 * @property {number|null}  actualPrice    - Filled when resolved
 * @property {'UP'|'DOWN'|null} actualDirection - UP/DOWN relative to currentPrice
 * @property {boolean|null} isCorrect  - Was the direction call correct?
 * @property {number|null}  priceError - |predictedPrice - actualPrice|
 * @property {number|null}  resolvedAt - Unix ms timestamp when resolved
 */

/**
 * Load all tracked predictions from localStorage.
 * @returns {TrackedPrediction[]}
 */
function _load() {
  const stored = getItem(PREDICTIONS_KEY);
  return Array.isArray(stored) ? stored : [];
}

/**
 * Persist predictions array to localStorage.
 * Trims to MAX_STORED (most recent first) to avoid quota exhaustion.
 * @param {TrackedPrediction[]} predictions
 */
function _save(predictions) {
  const trimmed = predictions.slice(-MAX_STORED);
  setItem(PREDICTIONS_KEY, trimmed);
}

/**
 * Store a new prediction.
 * Returns the assigned unique ID.
 *
 * @param {import('./prediction.js').Prediction} prediction
 * @returns {string}  The ID of the stored prediction
 */
export function storePrediction(prediction) {
  const predictions = _load();

  const id = `pred_${prediction.generatedAt}_${Math.random().toString(36).slice(2, 7)}`;

  const entry = {
    id,
    symbol:         prediction.symbol,
    direction:      prediction.direction,
    delta:          prediction.delta,
    predictedPrice: prediction.predictedPrice,
    currentPrice:   prediction.currentPrice,
    confidence:     prediction.confidence ?? null,
    generatedAt:    prediction.generatedAt,
    isDemo:         prediction.isDemo ?? false,
    // resolved fields — null until actual prices arrive
    actualPrice:    null,
    actualDirection: null,
    isCorrect:      null,
    priceError:     null,
    resolvedAt:     null,
  };

  predictions.push(entry);
  _save(predictions);
  return id;
}

/**
 * Return all tracked predictions, optionally filtered by symbol.
 * @param {string} [symbol]
 * @returns {TrackedPrediction[]}
 */
export function getPredictions(symbol) {
  const all = _load();
  if (!symbol) return all;
  return all.filter(p => p.symbol === symbol.toUpperCase());
}

/**
 * Return only predictions that have not yet been resolved
 * (i.e., actualPrice is still null).
 * @param {string} [symbol]
 * @returns {TrackedPrediction[]}
 */
export function getPendingPredictions(symbol) {
  return getPredictions(symbol).filter(p => p.resolvedAt === null);
}

/**
 * Resolve a single prediction by its ID.
 * Fills in actualPrice, actualDirection, isCorrect, priceError, resolvedAt.
 *
 * @param {string} id
 * @param {number} actualPrice  - Actual next-day close price
 * @returns {boolean}  true if found and updated, false otherwise
 */
export function resolvePrediction(id, actualPrice) {
  const predictions = _load();
  const idx = predictions.findIndex(p => p.id === id);
  if (idx === -1) return false;

  const p = predictions[idx];
  const actualDirection = actualPrice >= p.currentPrice ? 'UP' : 'DOWN';

  predictions[idx] = {
    ...p,
    actualPrice:      parseFloat(actualPrice.toFixed(2)),
    actualDirection,
    isCorrect:        p.direction === actualDirection,
    priceError:       parseFloat(Math.abs(p.predictedPrice - actualPrice).toFixed(2)),
    resolvedAt:       Date.now(),
  };

  _save(predictions);
  return true;
}

/**
 * Resolve all pending predictions for symbols present in the given price map.
 * Call this whenever fresh price data arrives.
 *
 * @param {Object.<string, number>} symbolPriceMap  - e.g. { AAPL: 182.50, TSLA: 245.10 }
 * @returns {number}  Count of predictions resolved
 */
export function resolveAll(symbolPriceMap) {
  const predictions = _load();
  let resolvedCount = 0;

  const updated = predictions.map(p => {
    if (p.resolvedAt !== null) return p;          // already resolved
    const actualPrice = symbolPriceMap[p.symbol];
    if (actualPrice == null) return p;            // no price for this symbol

    const actualDirection = actualPrice >= p.currentPrice ? 'UP' : 'DOWN';
    resolvedCount++;
    return {
      ...p,
      actualPrice:      parseFloat(actualPrice.toFixed(2)),
      actualDirection,
      isCorrect:        p.direction === actualDirection,
      priceError:       parseFloat(Math.abs(p.predictedPrice - actualPrice).toFixed(2)),
      resolvedAt:       Date.now(),
    };
  });

  if (resolvedCount > 0) _save(updated);
  return resolvedCount;
}

/**
 * Remove all stored predictions (e.g., from the Settings clear action).
 */
export function clearPredictions() {
  setItem(PREDICTIONS_KEY, []);
}
