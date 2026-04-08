/**
 * js/ml/model.js
 * TensorFlow.js model definition for stock price direction prediction.
 *
 * Model overview:
 *  - Input: Sliding window of 30 days × 32 features
 *  - Architecture: Bidirectional LSTM (128) → Dropout(0.3) → LSTM(64) →
 *                  Dropout(0.2) → Dense(32, relu) → Dropout(0.2) → Dense(1, sigmoid)
 *  - Output: P(price UP tomorrow) ∈ [0, 1]  (binary classification)
 *  - Matches server-side train-model.py architecture exactly
 */

// ─── Hyperparameters ──────────────────────────────────────────
export const MODEL_CONFIG = {
  inputWindowSize: 30,      // Number of days of history fed as input
  featuresPerStep:  32,     // Features per time step — must match build-features.py FEATURE_COUNT
  lstmUnits:       [128, 64], // BiLSTM then LSTM layer sizes
  dropoutRate:     0.2,
  learningRate:    0.001,
  batchSize:       32,
  epochs:          50,
  earlyStoppingPatience: 5,  // stop if val_loss doesn't improve for this many epochs
};

/**
 * Build and return an untrained Bidirectional LSTM model matching the
 * server-side architecture in train-model.py.
 * Requires TensorFlow.js to be loaded (window.tf).
 *
 * @returns {tf.Sequential}
 */
export function buildModel() {
  if (typeof tf === 'undefined') {
    throw new Error('TensorFlow.js is not loaded. Cannot build model.');
  }

  const model = tf.sequential();

  // Bidirectional LSTM layer — returns sequences for stacking
  model.add(tf.layers.bidirectional({
    layer: tf.layers.lstm({
      units: MODEL_CONFIG.lstmUnits[0],
      returnSequences: true,
    }),
    inputShape: [MODEL_CONFIG.inputWindowSize, MODEL_CONFIG.featuresPerStep],
  }));
  model.add(tf.layers.dropout({ rate: 0.3 }));

  // Second LSTM layer — returns only final output
  model.add(tf.layers.lstm({
    units: MODEL_CONFIG.lstmUnits[1],
    returnSequences: false,
  }));
  model.add(tf.layers.dropout({ rate: MODEL_CONFIG.dropoutRate }));

  // Dense hidden layer
  model.add(tf.layers.dense({ units: 32, activation: 'relu' }));
  model.add(tf.layers.dropout({ rate: MODEL_CONFIG.dropoutRate }));

  // Output layer — sigmoid for binary classification P(UP)
  model.add(tf.layers.dense({ units: 1, activation: 'sigmoid' }));

  model.compile({
    optimizer: tf.train.adam(MODEL_CONFIG.learningRate),
    loss: 'binaryCrossentropy',
    metrics: ['accuracy'],
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
 * Load the pre-trained V2 model from the repo (primary model).
 * @returns {Promise<tf.LayersModel|null>}
 */
export async function loadV2Model() {
  if (typeof tf === 'undefined') return null;
  try {
    const model = await tf.loadLayersModel('./models/v2/model.json');
    console.log('[Model] Loaded V2 model from repo');
    return model;
  } catch (err) {
    console.warn('[Model] Failed to load V2 model:', err.message);
    return null;
  }
}

/**
 * Load model weights.
 * Fallback chain: localStorage → V2 pre-trained → null (demo mode)
 *
 * @param {string} [slot='default']
 * @returns {Promise<tf.LayersModel|null>}  null if no model found anywhere
 */
export async function loadModel(slot = 'default') {
  if (typeof tf === 'undefined') return null;

  // 1. Try localStorage (user-trained model)
  const storageKey = `localstorage://nostradamus-model-${slot}`;
  try {
    const model = await tf.loadLayersModel(storageKey);
    console.log(`[Model] Loaded from ${storageKey}`);
    return model;
  } catch (err) {
    console.warn(`[Model] No saved model found in slot "${slot}":`, err.message);
  }

  // 2. Try V2 pre-trained model
  const v2 = await loadV2Model();
  if (v2) return v2;

  // 3. No model available — caller should fall back to demo mode
  console.warn('[Model] No model available. App will run in demo mode.');
  return null;
}
