/**
 * js/ml/model.js
 * TensorFlow.js LSTM model definition for stock price prediction.
 *
 * Model overview:
 *  - Input: Sliding window of N days of features (price, volume, indicators)
 *  - Architecture: LSTM → Dense → Output
 *  - Output: Predicted next-day close price (regression)
 *  - Post-processing: Compare to current price → UP/DOWN + dollar delta
 *
 * TODO (Phase 4):
 *  - Define the full LSTM model architecture
 *  - Implement model serialisation/deserialisation to localStorage
 *  - Load starter model weights from models/starter/model.json
 */

// ─── Hyperparameters ──────────────────────────────────────────
export const MODEL_CONFIG = {
  inputWindowSize: 30,      // Number of days of history fed as input
  featuresPerStep:  7,      // Features per time step (see preprocessing.js)
  lstmUnits:       [64, 32], // LSTM layer unit sizes
  dropoutRate:     0.2,
  learningRate:    0.001,
  batchSize:       32,
  epochs:          50,
};

/**
 * Build and return an untrained LSTM model.
 * Requires TensorFlow.js to be loaded (window.tf).
 *
 * @returns {tf.Sequential}
 */
export function buildModel() {
  // TODO (Phase 4): implement
  if (typeof tf === 'undefined') {
    throw new Error('TensorFlow.js is not loaded. Cannot build model.');
  }
  throw new Error('buildModel not yet implemented (Phase 4)');
}

/**
 * Save model weights to localStorage.
 * @param {tf.LayersModel} model
 * @param {string} [slot='default']
 * @returns {Promise<void>}
 */
export async function saveModel(model, slot = 'default') {
  // TODO (Phase 4): implement using tf.io.browserLocalStorage
  throw new Error('saveModel not yet implemented (Phase 4)');
}

/**
 * Load model weights from localStorage.
 * Falls back to starter weights at models/starter/model.json if no saved model.
 *
 * @param {string} [slot='default']
 * @returns {Promise<tf.LayersModel|null>}  null if no model found
 */
export async function loadModel(slot = 'default') {
  // TODO (Phase 4): implement using tf.loadLayersModel
  throw new Error('loadModel not yet implemented (Phase 4)');
}

/**
 * Load the pre-trained starter model from the repo.
 * @returns {Promise<tf.LayersModel>}
 */
export async function loadStarterModel() {
  // TODO (Phase 4): implement
  // await tf.loadLayersModel('./models/starter/model.json')
  throw new Error('loadStarterModel not yet implemented (Phase 4)');
}
