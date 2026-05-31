/**
 * Local Nostradamus server API client (serve.py).
 */

const BASE = '';

export async function apiGet(path) {
  const r = await fetch(`${BASE}${path}`, { cache: 'no-cache' });
  if (!r.ok) {
    const err = new Error(`HTTP ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

export async function apiPost(path, body) {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = new Error(`HTTP ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

export function isServerMode() {
  return apiGet('/api/health').then(() => true).catch(() => false);
}

export const api = {
  health: () => apiGet('/api/health'),
  overview: () => apiGet('/api/models/overview'),
  commandCenter: () => apiGet('/api/command-center'),
  pipelineHealth: () => apiGet('/api/pipeline/health'),
  livePredictions: (limit = 50) => apiGet(`/api/predictions/live?limit=${limit}`),
  decisions: () => apiGet('/api/decisions'),
  quote: (symbol) => apiGet(`/api/quote?symbol=${encodeURIComponent(symbol)}`),
  news: (symbol, max = 8) => apiGet(`/api/news?symbol=${encodeURIComponent(symbol)}&max_headlines=${max}`),
  bars: (symbol, limit = 90) => apiGet(`/api/bars?symbol=${encodeURIComponent(symbol)}&limit=${limit}`),
  reasoningStrategy: () => apiGet('/api/reasoning/strategy'),
  reasoningJournal: (limit = 20) => apiGet(`/api/reasoning/journal?limit=${limit}`),
  swingManifest: () => apiGet('/api/trading/manifest'),
  daytradeManifest: () => apiGet('/api/daytrade/manifest'),
  brainSchedule: () => apiGet('/api/brain/schedule'),
  congressNotable: () => apiGet('/api/congress/notable'),
  predictionMarkets: () => apiGet('/api/prediction-markets'),
  chat: (message, history) => apiPost('/api/chat', { message, history }),
  retrain: () => apiPost('/api/retrain', {}),
  retrainStatus: () => apiGet('/api/retrain/status'),
};
