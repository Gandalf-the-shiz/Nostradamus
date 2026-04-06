/**
 * js/ml/training.js
 * In-browser training pipeline for the LSTM prediction model.
 *
 * Runs entirely in the browser using TensorFlow.js.
 * Training is triggered when fresh historical data is available and
 * when the user's device is idle (requestIdleCallback).
 *
 * TODO (Phase 4):
 *  - Implement the training loop
 *  - Emit progress events (loss, epoch, ETA)
 *  - Save model after each epoch to avoid losing progress
 *  - Implement early stopping
 */

import { buildModel, saveModel, loadModel, MODEL_CONFIG } from './model.js';
import { buildFeatureMatrix, createWindows } from './preprocessing.js';

/**
 * @typedef {Object} TrainingProgress
 * @property {number} epoch
 * @property {number} totalEpochs
 * @property {number} loss
 * @property {number} valLoss
 */

/**
 * Train (or fine-tune) the model on a set of historical OHLCV candles.
 *
 * @param {import('./preprocessing.js').OHLCV[]} candles  - Historical data, oldest → newest
 * @param {(progress: TrainingProgress) => void} [onProgress]  - Progress callback
 * @returns {Promise<tf.LayersModel>}  The trained model
 */
export async function trainModel(candles, onProgress) {
  // TODO (Phase 4): implement
  throw new Error('trainModel not yet implemented (Phase 4)');
}

/**
 * Trigger a training run in the background using requestIdleCallback (if available).
 * Falls back to setTimeout on unsupported browsers.
 *
 * @param {import('./preprocessing.js').OHLCV[]} candles
 * @param {(progress: TrainingProgress) => void} [onProgress]
 * @returns {void}
 */
export function scheduledTrain(candles, onProgress) {
  const run = () => trainModel(candles, onProgress).catch(err => {
    console.error('[Training] Background training failed:', err);
  });

  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(run, { timeout: 30000 });
  } else {
    setTimeout(run, 1000);
  }
}
