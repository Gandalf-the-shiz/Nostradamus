/**
 * js/ml/prediction.js
 * Prediction engine — generates UP/DOWN predictions with confidence scores.
 *
 * The V2 model outputs P(UP) via sigmoid (binary classification).
 *  - direction:  probability > 0.5 → 'UP', else 'DOWN'
 *  - confidence: Monte Carlo Dropout — run N forward passes with dropout active,
 *                average the outputs, compute std dev as uncertainty measure.
 *                confidence = 1 − (2 × stddev), clamped to [0.3, 0.99].
 *
 * Output format:
 *  {
 *    symbol:         'AAPL',
 *    direction:      'UP' | 'DOWN',
 *    probability:    0.72,   // raw sigmoid output (mean of MC passes)
 *    delta:          null,   // V2 is direction-only; estimated from ATR if available
 *    confidence:     0.73,   // 0..1, derived from MC dropout uncertainty
 *    predictedPrice: 187.30, // currentPrice × (1 + estimatedDelta) for UI compat
 *    currentPrice:   185.15,
 *    generatedAt:    1712345678000,
 *    isDemo:         false,
 *  }
 */

import { loadModel, MODEL_CONFIG } from './model.js';
import { buildFeatureMatrix } from './preprocessing.js';

// Number of Monte Carlo Dropout forward passes for uncertainty estimation
const MC_PASSES = 20;

/**
 * @typedef {Object} Prediction
 * @property {string} symbol
 * @property {'UP'|'DOWN'} direction
 * @property {number} probability      - Raw P(UP) from model, mean of MC passes
 * @property {number|null} delta       - Estimated dollar change (null for V2 direction-only)
 * @property {number} confidence       - 0..1, from MC dropout uncertainty
 * @property {number} predictedPrice
 * @property {number} currentPrice
 * @property {number} generatedAt      - Unix ms timestamp
 */

/**
 * Run N Monte Carlo Dropout forward passes and return mean + stddev.
 * Dropout layers must stay active during inference.
 *
 * In TF.js, `model.predict()` always runs in inference mode (dropout disabled).
 * To keep dropout active, use `model.call(inputs, { training: true })` which
 * passes the training flag through to each layer.
 *
 * @param {tf.LayersModel} model
 * @param {tf.Tensor} inputTensor  - Shape [1, windowSize, features]
 * @returns {{ mean: number, stddev: number }}
 */
async function mcDropoutPredict(model, inputTensor) {
  const results = [];
  for (let i = 0; i < MC_PASSES; i++) {
    // model.call() with training=true keeps dropout active during inference
    const rawOut = model.call(inputTensor, { training: true });
    // call() may return a Tensor directly or an array of Tensors
    const out = Array.isArray(rawOut) ? rawOut[0] : rawOut;
    const val = (await out.data())[0];
    out.dispose();
    results.push(val);
  }

  const mean   = results.reduce((s, v) => s + v, 0) / MC_PASSES;
  const variance = results.reduce((s, v) => s + (v - mean) ** 2, 0) / MC_PASSES;
  const stddev = Math.sqrt(variance);
  return { mean, stddev };
}

/**
 * Compute confidence from MC dropout uncertainty.
 * confidence = clamp(1 − 2 × stddev, 0.3, 0.99)
 *
 * @param {number} stddev
 * @returns {number}
 */
function computeConfidence(stddev) {
  const raw = 1 - 2 * stddev;
  return parseFloat(Math.min(0.99, Math.max(0.3, raw)).toFixed(2));
}

/**
 * Estimate a dollar delta from historical volatility (ATR proxy).
 * Used only for UI display — V2 model does not predict magnitude.
 *
 * @param {import('./preprocessing.js').OHLCV[]} candles
 * @returns {number}  Estimated typical move in dollars
 */
function estimateDelta(candles) {
  const lookback = Math.min(14, candles.length - 1);
  if (lookback <= 0) return 0;
  let atrSum = 0;
  for (let i = candles.length - lookback; i < candles.length; i++) {
    const high = candles[i].high ?? candles[i].close;
    const low  = candles[i].low  ?? candles[i].close;
    atrSum += high - low;
  }
  return parseFloat((atrSum / lookback).toFixed(2));
}

/**
 * Run a next-day direction prediction for a given symbol.
 *
 * @param {string} symbol
 * @param {import('./preprocessing.js').OHLCV[]} candles  - Last 60+ days of OHLCV data
 * @returns {Promise<Prediction>}
 */
export async function runPrediction(symbol, candles) {
  if (typeof tf === 'undefined') {
    console.warn('[Prediction] TensorFlow.js not loaded. Returning demo prediction.');
    const currentPrice = candles.length > 0 ? candles[candles.length - 1].close : 100;
    return demoPrediction(symbol, currentPrice);
  }

  const currentPrice = candles[candles.length - 1].close;

  // 1. Try to load model: localStorage 'best' → 'default' → V2 → null (demo mode)
  const model = await loadModel('best');

  if (!model) {
    console.warn('[Prediction] No model available. Returning demo prediction.');
    return demoPrediction(symbol, currentPrice);
  }

  // 2. Build 32-feature matrix from candles
  const { features } = buildFeatureMatrix(candles);

  if (features.length < MODEL_CONFIG.inputWindowSize) {
    console.warn('[Prediction] Not enough feature data. Returning demo prediction.');
    return demoPrediction(symbol, currentPrice);
  }

  // 3. Take the last inputWindowSize rows as the input window
  const window = features.slice(features.length - MODEL_CONFIG.inputWindowSize);

  // 4. Create tensor and run MC Dropout passes
  const inputTensor = tf.tensor3d([window]); // shape [1, 30, 32]
  let probability, confidence;
  try {
    const { mean, stddev } = await mcDropoutPredict(model, inputTensor);
    probability = parseFloat(mean.toFixed(4));
    confidence  = computeConfidence(stddev);
  } finally {
    inputTensor.dispose();
  }

  // 5. Interpret binary classification output
  const direction = probability > 0.5 ? 'UP' : 'DOWN';

  // 6. Estimate delta for UI display (model predicts direction only)
  const delta = estimateDelta(candles);
  const predictedPrice = parseFloat(
    (currentPrice + (direction === 'UP' ? delta : -delta)).toFixed(2)
  );

  return {
    symbol,
    direction,
    probability,
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
  // Demo probability is synthetic, centered around 0.5
  const probability = parseFloat((0.5 + (seed % 30) / 100 * (direction === 'UP' ? 1 : -1)).toFixed(2));
  return {
    symbol,
    direction,
    probability,
    delta,
    confidence: 0.5 + (seed % 30) / 100,
    predictedPrice: parseFloat((currentPrice + (direction === 'UP' ? delta : -delta)).toFixed(2)),
    currentPrice,
    generatedAt: Date.now(),
    isDemo: true,
  };
}
