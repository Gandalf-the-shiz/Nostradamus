/**
 * js/ml/prediction.js
 * Prediction engine — generates UP/DOWN predictions with dollar amounts.
 *
 * Output format:
 *  {
 *    symbol:      'AAPL',
 *    direction:   'UP' | 'DOWN',
 *    delta:       2.15,    // predicted dollar change
 *    confidence:  0.73,    // 0..1
 *    predictedPrice: 187.30,
 *    currentPrice:   185.15,
 *    generatedAt:    1712345678000,
 *  }
 *
 * TODO (Phase 4):
 *  - Implement runPrediction using the loaded model + preprocessing pipeline
 *  - Implement confidence estimation
 *  - Store predictions in localStorage for accuracy tracking (Phase 5)
 */

import { loadModel, loadStarterModel } from './model.js';
import { buildFeatureMatrix, minMaxDescale } from './preprocessing.js';

/**
 * @typedef {Object} Prediction
 * @property {string} symbol
 * @property {'UP'|'DOWN'} direction
 * @property {number} delta          - Predicted dollar change
 * @property {number} confidence     - 0..1
 * @property {number} predictedPrice
 * @property {number} currentPrice
 * @property {number} generatedAt    - Unix ms timestamp
 */

/**
 * Run a next-day price prediction for a given symbol.
 *
 * @param {string} symbol
 * @param {import('./preprocessing.js').OHLCV[]} candles  - Last 30+ days of OHLCV data
 * @returns {Promise<Prediction>}
 */
export async function runPrediction(symbol, candles) {
  // TODO (Phase 4): implement
  // 1. Load model (saved → starter → null)
  // 2. Build feature matrix from candles
  // 3. Take last MODEL_CONFIG.inputWindowSize rows as the input window
  // 4. Run model.predict()
  // 5. Descale output → dollar price
  // 6. Compute direction & delta vs current price
  // 7. Return Prediction object
  throw new Error('runPrediction not yet implemented (Phase 4)');
}

/**
 * Run predictions for multiple symbols in sequence.
 * Avoids running all in parallel to prevent OOM on low-end devices.
 *
 * @param {Array<{symbol: string, candles: import('./preprocessing.js').OHLCV[]}>} items
 * @returns {Promise<Prediction[]>}
 */
export async function batchPredict(items) {
  // TODO (Phase 4): implement
  throw new Error('batchPredict not yet implemented (Phase 4)');
}

/**
 * Return a placeholder/demo prediction for use in Demo Mode
 * (no model loaded, just illustrates the UI).
 *
 * @param {string} symbol
 * @param {number} currentPrice
 * @returns {Prediction}
 */
export function demoPrediction(symbol, currentPrice) {
  const seed = symbol.charCodeAt(0) + symbol.charCodeAt(symbol.length - 1);
  const direction = seed % 2 === 0 ? 'UP' : 'DOWN';
  const delta = parseFloat((((seed % 500) / 100) + 0.5).toFixed(2));
  return {
    symbol,
    direction,
    delta,
    confidence: 0.5 + (seed % 30) / 100,
    predictedPrice: parseFloat((currentPrice + (direction === 'UP' ? delta : -delta)).toFixed(2)),
    currentPrice,
    generatedAt: Date.now(),
    isDemo: true,
  };
}
