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
  // TODO (Phase 4): implement
  throw new Error('minMaxScale not yet implemented (Phase 4)');
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
  // TODO (Phase 4): implement
  throw new Error('calculateRSI not yet implemented (Phase 4)');
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
  // TODO (Phase 4): implement
  throw new Error('calculateMACD not yet implemented (Phase 4)');
}

/**
 * Convert an array of OHLCV objects into a 2D feature matrix.
 * Each row is one time step with MODEL_CONFIG.featuresPerStep features.
 *
 * @param {OHLCV[]} candles  - Sorted oldest → newest
 * @returns {{ features: number[][], priceMin: number, priceMax: number, volumeMin: number, volumeMax: number }}
 */
export function buildFeatureMatrix(candles) {
  // TODO (Phase 4): implement
  throw new Error('buildFeatureMatrix not yet implemented (Phase 4)');
}

/**
 * Slice the feature matrix into overlapping windows for sequence modeling.
 * @param {number[][]} features
 * @param {number} windowSize
 * @returns {{ X: number[][][], y: number[] }}
 *   X[i] = window of windowSize rows, y[i] = next day's normalised close
 */
export function createWindows(features, windowSize) {
  // TODO (Phase 4): implement
  throw new Error('createWindows not yet implemented (Phase 4)');
}
