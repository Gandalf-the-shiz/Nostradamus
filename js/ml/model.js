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
  if (typeof tf === 'undefined') {
    throw new Error('TensorFlow.js is not loaded. Cannot build model.');
  }

  const model = tf.sequential();

  // First LSTM layer — returns sequences for stacking
  model.add(tf.layers.lstm({
    units: MODEL_CONFIG.lstmUnits[0],
    inputShape: [MODEL_CONFIG.inputWindowSize, MODEL_CONFIG.featuresPerStep],
    returnSequences: true,
  }));
  model.add(tf.layers.dropout({ rate: MODEL_CONFIG.dropoutRate }));

  // Second LSTM layer — returns only final output
  model.add(tf.layers.lstm({
    units: MODEL_CONFIG.lstmUnits[1],
    returnSequences: false,
  }));
  model.add(tf.layers.dropout({ rate: MODEL_CONFIG.dropoutRate }));

  // Dense hidden layer
  model.add(tf.layers.dense({ units: 16, activation: 'relu' }));

  // Output layer — single neuron for predicted normalized close price
  model.add(tf.layers.dense({ units: 1, activation: 'sigmoid' }));
  // sigmoid because our target is min-max normalized to [0,1]

  model.compile({
    optimizer: tf.train.adam(MODEL_CONFIG.learningRate),
    loss: 'meanSquaredError',
    metrics: ['mae'],
  });

  return model;
}

/**
 * Save model weights to localStorage.
 * @param {tf.LayersModel} model
 * @param {string} [slot='default']
 * @returns {Promise<void>}
 */
export async function saveModel(model, slot = 'default') {
  if (typeof tf === 'undefined') throw new Error('TensorFlow.js not loaded');
  const storageKey = `localstorage://nostradamus-model-${slot}`;
  await model.save(storageKey);
  console.log(`[Model] Saved to ${storageKey}`);
}

/**
 * Load model weights from localStorage.
 * Falls back to starter weights at models/starter/model.json if no saved model.
 *
 * @param {string} [slot='default']
 * @returns {Promise<tf.LayersModel|null>}  null if no model found
 */
export async function loadModel(slot = 'default') {
  if (typeof tf === 'undefined') return null;
  const storageKey = `localstorage://nostradamus-model-${slot}`;
  try {
    const model = await tf.loadLayersModel(storageKey);
    console.log(`[Model] Loaded from ${storageKey}`);
    return model;
  } catch (err) {
    console.warn(`[Model] No saved model found in slot "${slot}":`, err.message);
    return null;
  }
}

/**
 * Load the pre-trained starter model from the repo.
 * @returns {Promise<tf.LayersModel>}
 */
export async function loadStarterModel() {
  if (typeof tf === 'undefined') return null;
  try {
    const model = await tf.loadLayersModel('./models/starter/model.json');
    console.log('[Model] Loaded starter model from repo');
    return model;
  } catch (err) {
    console.warn('[Model] Failed to load starter model:', err.message);
    return null;
  }
}
