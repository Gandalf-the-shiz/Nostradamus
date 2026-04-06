/**
 * js/ml/preprocessing.js
 * Data preprocessing utilities for the ML pipeline.
 *
 * Converts raw OHLCV data into normalised feature tensors suitable for LSTM training.
 *
 * Feature set (per time step):
 *  0. Normalised close price
 *  1. Normalised volume
 *  2. 5-day SMA (normalised)
 *  3. 20-day SMA (normalised)
 *  4. RSI (14-day)
 *  5. MACD line
 *  6. MACD signal line
 *
 * TODO (Phase 4):
 *  - Implement all functions below
 *  - Add unit tests for normalization
 */

import { sma } from '../utils/helpers.js';

/**
 * @typedef {Object} OHLCV
 * @property {string} date
 * @property {number} open
 * @property {number} high
 * @property {number} low
 * @property {number} close
 * @property {number} volume
 */

/**
 * Normalise an array of values to the [0, 1] range using min-max scaling.
 * @param {number[]} values
 * @returns {{ normalised: number[], min: number, max: number }}
 */
export function minMaxScale(values) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1; // avoid division by zero
  const normalised = values.map(v => (v - min) / range);
  return { normalised, min, max };
}

/**
 * Denormalise a value from [0, 1] back to the original scale.
 * @param {number} value
 * @param {number} min
 * @param {number} max
 * @returns {number}
 */
export function minMaxDescale(value, min, max) {
  return value * (max - min) + min;
}

/**
 * Calculate RSI (Relative Strength Index) for an array of close prices.
 * @param {number[]} closes
 * @param {number} [period=14]
 * @returns {number[]}  Same length as closes; initial values are NaN.
 */
export function calculateRSI(closes, period = 14) {
  const rsi = new Array(closes.length).fill(NaN);

  if (closes.length <= period) return rsi;

  // Calculate initial gains and losses
  let gains = 0;
  let losses = 0;
  for (let i = 1; i <= period; i++) {
    const change = closes[i] - closes[i - 1];
    if (change > 0) gains += change;
    else losses += -change;
  }

  let avgGain = gains / period;
  let avgLoss = losses / period;

  if (avgLoss === 0) {
    rsi[period] = 1.0; // RSI = 100, normalized = 1.0
  } else {
    rsi[period] = (100 - 100 / (1 + avgGain / avgLoss)) / 100;
  }

  for (let i = period + 1; i < closes.length; i++) {
    const change = closes[i] - closes[i - 1];
    const gain = Math.max(change, 0);
    const loss = Math.max(-change, 0);
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;

    if (avgLoss === 0) {
      rsi[i] = 1.0;
    } else {
      rsi[i] = (100 - 100 / (1 + avgGain / avgLoss)) / 100;
    }
  }

  return rsi;
}

/**
 * Calculate MACD (Moving Average Convergence Divergence).
 * @param {number[]} closes
 * @param {number} [fast=12]
 * @param {number} [slow=26]
 * @param {number} [signal=9]
 * @returns {{ macd: number[], signal: number[], histogram: number[] }}
 */
export function calculateMACD(closes, fast = 12, slow = 26, signal = 9) {
  const len = closes.length;
  const macdLine = new Array(len).fill(NaN);
  const signalLine = new Array(len).fill(NaN);
  const histogram = new Array(len).fill(NaN);

  if (len < slow) return { macd: macdLine, signal: signalLine, histogram };

  // Calculate EMAs
  const fastMultiplier = 2 / (fast + 1);
  const slowMultiplier = 2 / (slow + 1);
  const signalMultiplier = 2 / (signal + 1);

  const emaFast = new Array(len).fill(NaN);
  const emaSlow = new Array(len).fill(NaN);

  // Seed EMA with SMA for first period values
  let fastSum = 0;
  for (let i = 0; i < fast; i++) fastSum += closes[i];
  emaFast[fast - 1] = fastSum / fast;

  let slowSum = 0;
  for (let i = 0; i < slow; i++) slowSum += closes[i];
  emaSlow[slow - 1] = slowSum / slow;

  // Fill fast EMA from index fast onward
  for (let i = fast; i < len; i++) {
    emaFast[i] = closes[i] * fastMultiplier + emaFast[i - 1] * (1 - fastMultiplier);
  }

  // Fill slow EMA from index slow onward
  for (let i = slow; i < len; i++) {
    emaSlow[i] = closes[i] * slowMultiplier + emaSlow[i - 1] * (1 - slowMultiplier);
  }

  // MACD line = fast EMA - slow EMA (only where both are valid)
  for (let i = slow - 1; i < len; i++) {
    if (!isNaN(emaFast[i]) && !isNaN(emaSlow[i])) {
      // Normalize by dividing by price to make comparable across stocks
      macdLine[i] = (emaFast[i] - emaSlow[i]) / closes[i];
    }
  }

  // Signal line = EMA(signal) of MACD line
  // Find first valid MACD value to seed signal EMA
  let firstMacdIdx = -1;
  for (let i = 0; i < len; i++) {
    if (!isNaN(macdLine[i])) { firstMacdIdx = i; break; }
  }

  if (firstMacdIdx >= 0 && firstMacdIdx + signal - 1 < len) {
    let signalSeedSum = 0;
    let validCount = 0;
    for (let i = firstMacdIdx; validCount < signal && i < len; i++) {
      if (!isNaN(macdLine[i])) {
        signalSeedSum += macdLine[i];
        validCount++;
        if (validCount === signal) {
          signalLine[i] = signalSeedSum / signal;
          // Continue from here
          for (let j = i + 1; j < len; j++) {
            if (!isNaN(macdLine[j])) {
              signalLine[j] = macdLine[j] * signalMultiplier + signalLine[j - 1] * (1 - signalMultiplier);
            } else {
              signalLine[j] = signalLine[j - 1];
            }
            histogram[j] = isNaN(macdLine[j]) ? NaN : macdLine[j] - signalLine[j];
          }
          histogram[i] = macdLine[i] - signalLine[i];
        }
      }
    }
  }

  return { macd: macdLine, signal: signalLine, histogram };
}

/**
 * Convert an array of OHLCV objects into a 2D feature matrix.
 * Each row is one time step with MODEL_CONFIG.featuresPerStep features.
 *
 * @param {OHLCV[]} candles  - Sorted oldest → newest
 * @returns {{ features: number[][], priceMin: number, priceMax: number, volumeMin: number, volumeMax: number }}
 */
export function buildFeatureMatrix(candles) {
  const closes  = candles.map(c => c.close);
  const volumes = candles.map(c => c.volume);

  // Calculate indicators
  const sma5  = sma(closes, 5);
  const sma20 = sma(closes, 20);
  const rsi14 = calculateRSI(closes, 14);
  const { macd: macdLine, signal: macdSignal } = calculateMACD(closes);

  // Normalize close prices and volumes
  const { normalised: normClose, min: priceMin, max: priceMax } = minMaxScale(closes);
  const { normalised: normVolume, min: volumeMin, max: volumeMax } = minMaxScale(volumes);

  const priceRange = priceMax - priceMin || 1;

  const features = [];

  for (let i = 0; i < candles.length; i++) {
    // Skip rows where any indicator is NaN
    if (
      isNaN(sma5[i])      ||
      isNaN(sma20[i])     ||
      isNaN(rsi14[i])     ||
      isNaN(macdLine[i])  ||
      isNaN(macdSignal[i])
    ) continue;

    const normSMA5  = (sma5[i]  - priceMin) / priceRange;
    const normSMA20 = (sma20[i] - priceMin) / priceRange;

    features.push([
      normClose[i],
      normVolume[i],
      normSMA5,
      normSMA20,
      rsi14[i],       // already normalized to [0,1] by calculateRSI
      macdLine[i],
      macdSignal[i],
    ]);
  }

  return { features, priceMin, priceMax, volumeMin, volumeMax };
}

/**
 * Slice the feature matrix into overlapping windows for sequence modeling.
 * @param {number[][]} features
 * @param {number} windowSize
 * @returns {{ X: number[][][], y: number[] }}
 *   X[i] = window of windowSize rows, y[i] = next day's normalised close
 */
export function createWindows(features, windowSize) {
  const X = [];
  const y = [];

  for (let i = 0; i + windowSize < features.length; i++) {
    X.push(features.slice(i, i + windowSize));
    y.push(features[i + windowSize][0]); // next day's normalised close
  }

  return { X, y };
}
