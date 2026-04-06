/**
 * js/ui/charts.js
 * Chart.js integration — price history sparklines and prediction overlays.
 *
 * Phase 1: Renders mini sparkline charts on stock cards.
 * Phase 3+: Full-size price charts in stock detail view.
 * Phase 4+: Prediction overlay showing predicted vs actual prices.
 *
 * Requires Chart.js loaded via CDN (window.Chart).
 */

// Registry of active Chart instances to allow destruction on re-render.
/** @type {Map<string, Chart>} */
const chartRegistry = new Map();

/**
 * Render a compact sparkline chart for a stock card.
 *
 * @param {HTMLElement} container  - The chart container element
 * @param {number[]} prices        - Array of close prices (oldest → newest)
 * @param {boolean} [isUp=true]    - Determines chart color (green/red)
 */
export function renderSparkline(container, prices, isUp = true) {
  if (typeof Chart === 'undefined') {
    console.warn('[Charts] Chart.js not loaded. Skipping sparkline.');
    return;
  }

  // Destroy existing chart if re-rendering
  const existingKey = container.dataset.chartKey;
  if (existingKey && chartRegistry.has(existingKey)) {
    chartRegistry.get(existingKey).destroy();
    chartRegistry.delete(existingKey);
  }

  const canvas = document.createElement('canvas');
  canvas.setAttribute('aria-label', 'Price sparkline chart');
  canvas.setAttribute('role', 'img');
  container.innerHTML = '';
  container.appendChild(canvas);

  const color = isUp ? 'rgba(38, 217, 127, 1)' : 'rgba(240, 92, 110, 1)';
  const fillColor = isUp ? 'rgba(38, 217, 127, 0.1)' : 'rgba(240, 92, 110, 0.1)';

  const chart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: prices.map((_, i) => i),
      datasets: [{
        data: prices,
        borderColor: color,
        backgroundColor: fillColor,
        borderWidth: 1.5,
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        pointHoverRadius: 3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: {
        x: { display: false },
        y: { display: false },
      },
      interaction: { intersect: false },
    },
  });

  const key = `sparkline_${Date.now()}_${Math.random()}`;
  container.dataset.chartKey = key;
  chartRegistry.set(key, chart);
}

/**
 * Render a full-size price history chart with prediction overlay.
 * Used in the stock detail view (Phase 3+).
 *
 * @param {HTMLElement} container
 * @param {Array<{date: string, close: number}>} history
 * @param {import('../ml/prediction.js').Prediction|null} [prediction]
 */
export function renderDetailChart(container, history, prediction = null) {
  // TODO (Phase 3): implement full detail chart
  console.warn('[Charts] renderDetailChart not yet implemented (Phase 3).');
}

/**
 * Destroy all active chart instances (e.g., on route change).
 */
export function destroyAllCharts() {
  chartRegistry.forEach(chart => chart.destroy());
  chartRegistry.clear();
}
