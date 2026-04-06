/**
 * js/app.js
 * Main application entry point for Nostradamus.
 *
 * Responsibilities:
 *  - Wait for the DOM and CDN libraries (TensorFlow.js, Chart.js) to be ready
 *  - Detect whether API keys are configured in localStorage
 *  - Show/hide the Demo Mode banner accordingly
 *  - Initialize all UI modules (dashboard, search, navigation)
 *  - Bootstrap the ML prediction engine if model weights are available
 *  - Wire up the Settings panel save/clear actions
 *
 * Phase 1: Scaffold — shows welcome screen and loads demo data.
 * Phase 2+: Will load live data via the API manager.
 */

import { getItem, setItem, removeItem, clearAll } from './storage/cache.js';
import { showToast } from './utils/helpers.js';
import { initDashboard } from './ui/dashboard.js';
import { initSearch } from './ui/search.js';
import { initTheme, toggleTheme } from './ui/theme.js';
import { initWatchlist } from './ui/watchlist.js';
import { initAccuracyDashboard } from './ui/accuracy-dashboard.js';
import { trainModel } from './ml/training.js';
import { loadDemoData } from './api/manager.js';
import { clearPredictions } from './ml/tracker.js';

// ─── Constants ────────────────────────────────────────────────
const STORAGE_KEYS = {
  FINNHUB_KEY:    'finnhub_key',
  TWELVEDATA_KEY: 'twelvedata_key',
  POLYGON_KEY:    'polygon_key',
};

// ─── App State ────────────────────────────────────────────────
const appState = {
  /** @type {'demo'|'live'} */
  mode: 'demo',
  /** Whether TensorFlow.js loaded successfully */
  tfReady: false,
  /** Whether Chart.js loaded successfully */
  chartReady: false,
  /** @type {'dashboard'|'watchlist'|'settings'} */
  activeView: 'dashboard',
};

// ─── Initialisation ───────────────────────────────────────────

/**
 * Bootstrap the entire application.
 * Called once the DOM is ready.
 */
async function init() {
  console.log('[Nostradamus] Initializing app…');

  initTheme();
  checkLibraries();
  detectMode();
  initNavigation();
  initDemoBanner();
  initSettingsPanel();
  initThemeToggle();

  // Initialize UI modules
  await initDashboard(appState);
  initSearch(appState);

  console.log(`[Nostradamus] App ready in ${appState.mode} mode.`);
}

/**
 * Check that CDN libraries loaded successfully.
 * Logs warnings but does not crash the app.
 */
function checkLibraries() {
  // TensorFlow.js
  if (typeof tf !== 'undefined') {
    appState.tfReady = true;
    console.log('[Nostradamus] TensorFlow.js ready:', tf.version.tfjs);
  } else {
    console.warn('[Nostradamus] TensorFlow.js not loaded. ML predictions unavailable.');
  }

  // Chart.js
  if (typeof Chart !== 'undefined') {
    appState.chartReady = true;
    console.log('[Nostradamus] Chart.js ready.');
  } else {
    console.warn('[Nostradamus] Chart.js not loaded. Charts unavailable.');
  }
}

/**
 * Determine whether we're running in demo mode (no API keys)
 * or live mode (at least a Finnhub key is configured).
 */
function detectMode() {
  const finnhubKey = getItem(STORAGE_KEYS.FINNHUB_KEY);
  appState.mode = finnhubKey ? 'live' : 'demo';
  console.log(`[Nostradamus] Mode: ${appState.mode}`);
}

// ─── Demo Banner ──────────────────────────────────────────────

function initDemoBanner() {
  const banner  = document.getElementById('demo-banner');
  const closeBtn = document.getElementById('demo-banner-close');
  const settingsBtn = document.getElementById('demo-banner-settings-btn');

  if (!banner) return;

  // Hide banner if we have API keys
  if (appState.mode === 'live') {
    banner.hidden = true;
    return;
  }

  closeBtn?.addEventListener('click', () => {
    banner.hidden = true;
  });

  settingsBtn?.addEventListener('click', () => {
    navigateTo('settings');
  });
}

// ─── Navigation ───────────────────────────────────────────────

function initNavigation() {
  const navDashboard = document.getElementById('nav-dashboard');
  const navWatchlist = document.getElementById('nav-watchlist');
  const navAccuracy  = document.getElementById('nav-accuracy');
  const navSettings  = document.getElementById('nav-settings');

  navDashboard?.addEventListener('click', () => navigateTo('dashboard'));
  navWatchlist?.addEventListener('click', () => navigateTo('watchlist'));
  navAccuracy?.addEventListener('click',  () => navigateTo('accuracy'));
  navSettings?.addEventListener('click',  () => navigateTo('settings'));
}

/**
 * Switch the visible view and update the active nav button.
 * @param {'dashboard'|'watchlist'|'accuracy'|'settings'} viewName
 */
function navigateTo(viewName) {
  const views = ['dashboard', 'watchlist', 'accuracy', 'settings'];
  const navBtns = {
    dashboard: document.getElementById('nav-dashboard'),
    watchlist: document.getElementById('nav-watchlist'),
    accuracy:  document.getElementById('nav-accuracy'),
    settings:  document.getElementById('nav-settings'),
  };

  views.forEach(name => {
    const viewEl = document.getElementById(`view-${name}`);
    if (viewEl) viewEl.hidden = name !== viewName;

    const navBtn = navBtns[name];
    if (navBtn) {
      navBtn.classList.toggle('nav-btn--active', name === viewName);
      navBtn.setAttribute('aria-current', name === viewName ? 'page' : 'false');
    }
  });

  appState.activeView = viewName;

  // Refresh view-specific content on navigation
  if (viewName === 'watchlist') {
    initWatchlist(appState);
  } else if (viewName === 'accuracy') {
    initAccuracyDashboard(appState);
  }
}

// ─── Theme Toggle ─────────────────────────────────────────────

function initThemeToggle() {
  const btn = document.getElementById('theme-toggle');
  btn?.addEventListener('click', toggleTheme);
}

// ─── Settings Panel ───────────────────────────────────────────

function initSettingsPanel() {
  const saveBtn       = document.getElementById('setting-save-btn');
  const clearBtn      = document.getElementById('setting-clear-btn');
  const clearCacheBtn = document.getElementById('setting-clear-cache-btn');
  const trainBtn      = document.getElementById('setting-train-btn');
  const clearModelBtn = document.getElementById('setting-clear-model-btn');
  const clearPredsBtn = document.getElementById('setting-clear-predictions-btn');

  // Populate existing keys (masked)
  populateSettingsInputs();

  saveBtn?.addEventListener('click', saveApiKeys);
  clearBtn?.addEventListener('click', clearApiKeys);
  clearCacheBtn?.addEventListener('click', clearCache);

  trainBtn?.addEventListener('click', async () => {
    trainBtn.disabled = true;
    trainBtn.textContent = 'Training…';
    const progressEl = document.getElementById('training-progress');
    if (progressEl) progressEl.hidden = false;

    try {
      const demoData = await loadDemoData();
      const allCandles = [];
      for (const stock of (demoData.stocks || [])) {
        if (stock.candles && stock.candles.length > 0) {
          allCandles.push(...stock.candles);
        }
      }
      // Note: candles from different stocks are combined into one dataset.
      // All close prices and volumes are min-max normalized within buildFeatureMatrix,
      // so relative scale differences between stocks are removed during preprocessing.

      await trainModel(allCandles, (progress) => {
        const epochEl = document.getElementById('training-epoch');
        const lossEl  = document.getElementById('training-loss');
        const barEl   = document.getElementById('training-progress-bar');
        if (epochEl) epochEl.textContent = `Epoch ${progress.epoch}/${progress.totalEpochs}`;
        if (lossEl)  lossEl.textContent  = `Loss: ${progress.loss.toFixed(6)}`;
        if (barEl)   barEl.style.width   = `${(progress.epoch / progress.totalEpochs) * 100}%`;
      });

      showToast('Model training complete! 🧠', 'success');
    } catch (err) {
      console.error('[App] Training failed:', err);
      showToast(`Training failed: ${err.message}`, 'error');
    } finally {
      trainBtn.disabled = false;
      trainBtn.textContent = '🧠 Train Model';
    }
  });

  clearModelBtn?.addEventListener('click', () => {
    const keysToRemove = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && (key.includes('nostradamus-model') || key === 'nostradamus_scaling_params')) {
        keysToRemove.push(key);
      }
    }
    keysToRemove.forEach(k => localStorage.removeItem(k));
    showToast('Saved model deleted.', 'info');
  });

  clearPredsBtn?.addEventListener('click', () => {
    clearPredictions();
    showToast('Prediction history cleared.', 'info');
  });

  document.getElementById('settings-goto-accuracy')?.addEventListener('click', () => {
    navigateTo('accuracy');
  });
}

function populateSettingsInputs() {
  const fields = [
    { id: 'setting-finnhub-key',    key: STORAGE_KEYS.FINNHUB_KEY },
    { id: 'setting-twelvedata-key', key: STORAGE_KEYS.TWELVEDATA_KEY },
    { id: 'setting-polygon-key',    key: STORAGE_KEYS.POLYGON_KEY },
  ];

  fields.forEach(({ id, key }) => {
    const input = document.getElementById(id);
    const value = getItem(key);
    if (input && value) {
      // Show masked value so user knows a key exists
      input.placeholder = '••••••••••••••••••••';
    }
  });
}

function saveApiKeys() {
  const fields = [
    { id: 'setting-finnhub-key',    key: STORAGE_KEYS.FINNHUB_KEY },
    { id: 'setting-twelvedata-key', key: STORAGE_KEYS.TWELVEDATA_KEY },
    { id: 'setting-polygon-key',    key: STORAGE_KEYS.POLYGON_KEY },
  ];

  let saved = 0;
  fields.forEach(({ id, key }) => {
    const input = document.getElementById(id);
    if (input?.value.trim()) {
      setItem(key, input.value.trim());
      input.value = '';
      input.placeholder = '••••••••••••••••••••';
      saved++;
    }
  });

  if (saved > 0) {
    showToast(`${saved} API key(s) saved.`, 'success');
    detectMode();
    const banner = document.getElementById('demo-banner');
    if (appState.mode === 'live' && banner) banner.hidden = true;
  } else {
    showToast('No keys entered.', 'info');
  }
}

function clearApiKeys() {
  Object.values(STORAGE_KEYS).forEach(key => removeItem(key));
  showToast('API keys cleared. Demo mode active.', 'info');
  detectMode();
  const banner = document.getElementById('demo-banner');
  if (banner) banner.hidden = false;
  populateSettingsInputs();
}

function clearCache() {
  const count = clearAll(false);
  showToast(`Cache cleared (${count} entr${count === 1 ? 'y' : 'ies'} removed).`, 'success');
}

// ─── DOM Ready ────────────────────────────────────────────────
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
