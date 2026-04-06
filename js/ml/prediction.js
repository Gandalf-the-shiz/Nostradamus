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

import { loadModel, loadStarterModel, MODEL_CONFIG } from './model.js';
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
  if (typeof tf === 'undefined') {
    console.warn('[Prediction] TensorFlow.js not loaded. Returning demo prediction.');
    const currentPrice = candles.length > 0 ? candles[candles.length - 1].close : 100;
    return demoPrediction(symbol, currentPrice);
  }

  const currentPrice = candles[candles.length - 1].close;

  // 1. Try to load model: saved → starter → fall back to demo
  let model = await loadModel('best');
  if (!model) model = await loadModel('default');
  if (!model) {
    try {
      model = await loadStarterModel();
    } catch (e) {
      // starter model not available
    }
  }

  if (!model) {
    console.warn('[Prediction] No model available. Returning demo prediction.');
    return demoPrediction(symbol, currentPrice);
  }

  // 2. Build feature matrix from candles
  const { features, priceMin, priceMax } = buildFeatureMatrix(candles);

  if (features.length < MODEL_CONFIG.inputWindowSize) {
    console.warn('[Prediction] Not enough feature data. Returning demo prediction.');
    return demoPrediction(symbol, currentPrice);
  }

  // 3. Take the last inputWindowSize rows as the input window
  const window = features.slice(features.length - MODEL_CONFIG.inputWindowSize);

  // 4. Create tensor and run prediction
  const inputTensor = tf.tensor3d([window]); // shape [1, 30, 7]
  const outputTensor = model.predict(inputTensor);
  const normalizedPrediction = (await outputTensor.data())[0];

  // Cleanup tensors
  inputTensor.dispose();
  outputTensor.dispose();

  // 5. Descale: convert normalized [0,1] back to dollar price
  // Try to load scaling params from training; fall back to current data's range
  let scalePriceMin = priceMin;
  let scalePriceMax = priceMax;
  try {
    const saved = JSON.parse(localStorage.getItem('nostradamus_scaling_params') || 'null');
    if (saved && saved.priceMin !== undefined) {
      scalePriceMin = saved.priceMin;
      scalePriceMax = saved.priceMax;
    }
  } catch (e) { /* use data range */ }

  const predictedPrice = parseFloat(minMaxDescale(normalizedPrediction, scalePriceMin, scalePriceMax).toFixed(2));

  // 6. Direction and delta
  const delta     = parseFloat(Math.abs(predictedPrice - currentPrice).toFixed(2));
  const direction = predictedPrice >= currentPrice ? 'UP' : 'DOWN';

  // Confidence estimation: scale the distance between the normalized prediction
  // and the current normalized price. The multiplier of 5 maps a typical
  // ~0.02–0.05 normalized delta to a visible confidence spread within [0.5, 0.95].
  const currentNormalized = (currentPrice - scalePriceMin) / (scalePriceMax - scalePriceMin || 1);
  const rawConfidence = Math.abs(normalizedPrediction - currentNormalized) * 5;
  const confidence = parseFloat(Math.min(0.95, Math.max(0.5, 0.5 + rawConfidence)).toFixed(2));

  return {
    symbol,
    direction,
    delta,
    confidence,
    predictedPrice,
    currentPrice,
    generatedAt: Date.now(),
    isDemo: false,
  };
}

/**
 * Run predictions for multiple symbols in sequence.
 * Avoids running all in parallel to prevent OOM on low-end devices.
 *
 * @param {Array<{symbol: string, candles: import('./preprocessing.js').OHLCV[]}>} items
 * @returns {Promise<Prediction[]>}
 */
export async function batchPredict(items) {
  const predictions = [];
  for (const item of items) {
    try {
      const pred = await runPrediction(item.symbol, item.candles);
      predictions.push(pred);
    } catch (err) {
      console.error(`[Prediction] Failed for ${item.symbol}:`, err.message);
      const currentPrice = item.candles.length > 0 ? item.candles[item.candles.length - 1].close : 100;
      predictions.push(demoPrediction(item.symbol, currentPrice));
    }
  }
  return predictions;
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
