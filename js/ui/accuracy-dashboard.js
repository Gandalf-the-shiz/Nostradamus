/**
 * js/ui/accuracy-dashboard.js
 * Rolling accuracy dashboard — Phase 5.
 *
 * Renders a dedicated "Accuracy" view showing:
 *   - Summary metric cards (hit rate, MAE, total predictions)
 *   - Rolling accuracy chart (hit rate & MAE over time, Chart.js)
 *   - Recent prediction history log
 *   - Model versions table with A/B champion indicator
 *
 * Called from app.js when the user navigates to the Accuracy view.
 * Requires Chart.js loaded via CDN (window.Chart).
 */

import { getPredictions } from '../ml/tracker.js';
import { getAccuracySummary, getWeeklyMetrics } from '../ml/accuracy.js';
import { getVersions, getChampionVersion } from '../ml/versioning.js';
import { getLastTrainingInfo } from '../ml/retraining.js';
import { formatCurrency } from '../utils/helpers.js';

// Chart instance registry so we can destroy/recreate on refresh
let _accuracyChart = null;

// ─── Main initialiser ────────────────────────────────────────

/**
 * Initialise (or refresh) the Accuracy dashboard view.
 * @param {{ mode: 'demo'|'live', chartReady: boolean }} appState
 */
export function initAccuracyDashboard(appState) {
  const container = document.getElementById('view-accuracy');
  if (!container) return;

  container.innerHTML = '';

  const panel = document.createElement('div');
  panel.className = 'accuracy-panel';

  // Title
  const title = document.createElement('h2');
  title.className = 'accuracy-panel__title';
  title.textContent = '📊 Prediction Accuracy';
  panel.appendChild(title);

  // Demo notice
  if (appState.mode === 'demo') {
    const notice = document.createElement('p');
    notice.className = 'accuracy-panel__demo-notice';
    notice.textContent = 'Demo mode — accuracy data is based on stored predictions. Real accuracy tracking requires live API data.';
    panel.appendChild(notice);
  }

  // Summary metrics
  const metrics = getAccuracySummary();
  panel.appendChild(_renderMetricCards(metrics));

  // Last training info
  panel.appendChild(_renderTrainingInfo());

  // Rolling accuracy chart
  if (appState.chartReady) {
    const chartSection = document.createElement('div');
    chartSection.className = 'accuracy-section';
    const chartTitle = document.createElement('h3');
    chartTitle.className = 'accuracy-section__title';
    chartTitle.textContent = 'Hit Rate Over Time';
    chartSection.appendChild(chartTitle);
    const chartContainer = document.createElement('div');
    chartContainer.id   = 'accuracy-chart-container';
    chartContainer.className = 'accuracy-chart-container';
    chartSection.appendChild(chartContainer);
    panel.appendChild(chartSection);
    // Render chart after the container is added to the live DOM
    requestAnimationFrame(() => {
      if (document.contains(chartContainer)) {
        _renderAccuracyChart(chartContainer);
      }
    });
  }

  // Model versions
  const versions = getVersions();
  if (versions.length > 0) {
    panel.appendChild(_renderVersionsTable(versions));
  }

  // Recent predictions
  const predictions = getPredictions();
  panel.appendChild(_renderPredictionHistory(predictions));

  container.appendChild(panel);
}

// ─── Metric cards ─────────────────────────────────────────────

/**
 * @param {import('../ml/accuracy.js').AccuracyMetrics} metrics
 * @returns {HTMLElement}
 */
function _renderMetricCards(metrics) {
  const grid = document.createElement('div');
  grid.className = 'accuracy-metrics';

  const hitRatePct = isNaN(metrics.hitRate)
    ? '—'
    : `${(metrics.hitRate * 100).toFixed(1)}%`;

  const maeStr = isNaN(metrics.mae)
    ? '—'
    : formatCurrency(metrics.mae);

  const cards = [
    {
      icon:  '🎯',
      label: 'Hit Rate',
      value: hitRatePct,
      sub:   'Direction accuracy',
      good:  !isNaN(metrics.hitRate) && metrics.hitRate >= 0.5,
    },
    {
      icon:  '📏',
      label: 'Avg Price Error',
      value: maeStr,
      sub:   'Mean absolute error',
      good:  null,
    },
    {
      icon:  '✅',
      label: 'Resolved',
      value: String(metrics.resolvedCount),
      sub:   `of ${metrics.totalPredictions} total`,
      good:  null,
    },
    {
      icon:  '⏳',
      label: 'Pending',
      value: String(metrics.pendingCount),
      sub:   'Awaiting actual price',
      good:  null,
    },
  ];

  cards.forEach(c => {
    const card = document.createElement('div');
    card.className = 'accuracy-metric-card';
    if (c.good === true)  card.classList.add('accuracy-metric-card--good');
    if (c.good === false) card.classList.add('accuracy-metric-card--bad');

    card.innerHTML = `
      <span class="accuracy-metric-card__icon">${c.icon}</span>
      <span class="accuracy-metric-card__label">${c.label}</span>
      <span class="accuracy-metric-card__value">${c.value}</span>
      <span class="accuracy-metric-card__sub">${c.sub}</span>
    `;
    grid.appendChild(card);
  });

  return grid;
}

// ─── Training info ────────────────────────────────────────────

function _renderTrainingInfo() {
  const info = getLastTrainingInfo();
  const champion = getChampionVersion();

  const wrap = document.createElement('div');
  wrap.className = 'accuracy-training-info';

  const lastTrainStr = info.lastTrainedAt
    ? new Date(info.lastTrainedAt).toLocaleString()
    : 'Never';

  const championStr = champion
    ? `v${champion.versionNumber} (hit rate: ${
        isNaN(champion.accuracy.hitRate)
          ? '—'
          : `${(champion.accuracy.hitRate * 100).toFixed(1)}%`
      })`
    : 'None';

  wrap.innerHTML = `
    <div class="accuracy-training-info__row">
      <span class="accuracy-training-info__label">Last trained</span>
      <span class="accuracy-training-info__value">${lastTrainStr}</span>
    </div>
    <div class="accuracy-training-info__row">
      <span class="accuracy-training-info__label">Champion model</span>
      <span class="accuracy-training-info__value">${championStr}</span>
    </div>
  `;

  return wrap;
}

// ─── Rolling accuracy chart ───────────────────────────────────

/**
 * @param {HTMLElement} container
 */
function _renderAccuracyChart(container) {
  if (typeof Chart === 'undefined') return;

  const weekly = getWeeklyMetrics(undefined, 12);

  if (weekly.length === 0) {
    container.innerHTML = '<p class="accuracy-empty-note">No resolved predictions yet. Accuracy trends will appear here after predictions are evaluated.</p>';
    return;
  }

  // Destroy previous instance
  if (_accuracyChart) {
    _accuracyChart.destroy();
    _accuracyChart = null;
  }

  const canvas = document.createElement('canvas');
  canvas.setAttribute('aria-label', 'Weekly prediction accuracy chart');
  canvas.setAttribute('role', 'img');
  container.innerHTML = '';
  container.appendChild(canvas);

  const labels   = weekly.map(w => w.label);
  const hitRates = weekly.map(w => isNaN(w.hitRate) ? null : parseFloat((w.hitRate * 100).toFixed(1)));
  const maes     = weekly.map(w => isNaN(w.mae) ? null : parseFloat(w.mae.toFixed(2)));

  const C_ACCENT = 'rgba(124, 111, 239, 1)';
  const C_ACCENT_FILL = 'rgba(124, 111, 239, 0.15)';
  const C_DOWN   = 'rgba(240, 92, 110, 0.8)';
  const C_GRID   = 'rgba(255,255,255,0.06)';
  const C_TICK   = 'rgba(255,255,255,0.35)';

  _accuracyChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label:           'Hit Rate %',
          data:            hitRates,
          borderColor:     C_ACCENT,
          backgroundColor: C_ACCENT_FILL,
          borderWidth:     2,
          fill:            true,
          tension:         0.3,
          pointRadius:     4,
          pointBackgroundColor: C_ACCENT,
          yAxisID:         'yHit',
        },
        {
          label:           'Avg Price Error ($)',
          data:            maes,
          borderColor:     C_DOWN,
          backgroundColor: 'transparent',
          borderWidth:     2,
          borderDash:      [5, 4],
          fill:            false,
          tension:         0.3,
          pointRadius:     3,
          pointBackgroundColor: C_DOWN,
          yAxisID:         'yMAE',
        },
      ],
    },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      animation:           { duration: 400 },
      interaction:         { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: { color: C_TICK, font: { size: 11 }, boxWidth: 16 },
        },
        tooltip: {
          backgroundColor: 'rgba(26,29,39,0.95)',
          titleColor:      'rgba(255,255,255,0.6)',
          bodyColor:       '#e8eaf0',
          borderColor:     'rgba(255,255,255,0.1)',
          borderWidth:     1,
          padding:         10,
        },
      },
      scales: {
        x: {
          ticks:  { color: C_TICK, font: { size: 11 }, maxRotation: 0 },
          grid:   { color: C_GRID },
          border: { color: C_GRID },
        },
        yHit: {
          position: 'left',
          min: 0,
          max: 100,
          ticks:  { color: C_TICK, font: { size: 11 }, callback: v => `${v}%` },
          grid:   { color: C_GRID },
          border: { color: C_GRID },
          title:  { display: false },
        },
        yMAE: {
          position: 'right',
          min: 0,
          ticks:  { color: C_TICK, font: { size: 11 }, callback: v => `$${v}` },
          grid:   { display: false },
          border: { color: C_GRID },
        },
      },
    },
  });
}

// ─── Model versions table ─────────────────────────────────────

/**
 * @param {import('../ml/versioning.js').ModelVersion[]} versions
 * @returns {HTMLElement}
 */
function _renderVersionsTable(versions) {
  const section = document.createElement('div');
  section.className = 'accuracy-section';

  const title = document.createElement('h3');
  title.className = 'accuracy-section__title';
  title.textContent = '🏆 Model Versions';
  section.appendChild(title);

  const table = document.createElement('table');
  table.className = 'accuracy-table';
  table.setAttribute('role', 'table');

  table.innerHTML = `
    <thead>
      <tr>
        <th>Version</th>
        <th>Trained</th>
        <th>Val Loss</th>
        <th>Hit Rate</th>
        <th>MAE</th>
        <th>Status</th>
      </tr>
    </thead>
  `;

  const tbody = document.createElement('tbody');
  // Show at most 10 most recent
  versions.slice(0, 10).forEach(v => {
    const tr = document.createElement('tr');
    if (v.isChampion) tr.classList.add('accuracy-table__row--champion');

    const trainedDate = new Date(v.trainedAt).toLocaleDateString('en-US', {
      month: 'short',
      day:   'numeric',
    });

    const hitRateStr = isNaN(v.accuracy.hitRate)
      ? '—'
      : `${(v.accuracy.hitRate * 100).toFixed(1)}%`;

    const maeStr = isNaN(v.accuracy.mae)
      ? '—'
      : `$${v.accuracy.mae.toFixed(2)}`;

    tr.innerHTML = `
      <td><strong>v${v.versionNumber}</strong></td>
      <td>${trainedDate}</td>
      <td>${v.valLoss.toFixed(4)}</td>
      <td>${hitRateStr}</td>
      <td>${maeStr}</td>
      <td>${v.isChampion ? '<span class="accuracy-champion-badge">👑 Champion</span>' : '<span class="accuracy-version-badge">—</span>'}</td>
    `;
    tbody.appendChild(tr);
  });

  table.appendChild(tbody);
  section.appendChild(table);
  return section;
}

// ─── Prediction history ───────────────────────────────────────

/**
 * @param {import('../ml/tracker.js').TrackedPrediction[]} predictions
 * @returns {HTMLElement}
 */
function _renderPredictionHistory(predictions) {
  const section = document.createElement('div');
  section.className = 'accuracy-section';

  const header = document.createElement('div');
  header.className = 'accuracy-section__header';
  const title = document.createElement('h3');
  title.className = 'accuracy-section__title';
  title.textContent = '📋 Recent Predictions';
  header.appendChild(title);
  const countBadge = document.createElement('span');
  countBadge.className = 'accuracy-count-badge';
  countBadge.textContent = `${predictions.length} stored`;
  header.appendChild(countBadge);
  section.appendChild(header);

  if (predictions.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'accuracy-empty-note';
    empty.textContent = 'No predictions stored yet. Predictions are recorded automatically each time the model runs.';
    section.appendChild(empty);
    return section;
  }

  const table = document.createElement('table');
  table.className = 'accuracy-table';

  table.innerHTML = `
    <thead>
      <tr>
        <th>Symbol</th>
        <th>Date</th>
        <th>Prediction</th>
        <th>Actual</th>
        <th>Result</th>
      </tr>
    </thead>
  `;

  const tbody = document.createElement('tbody');
  // Show most recent 20 predictions
  const recent = predictions.slice().reverse().slice(0, 20);

  recent.forEach(p => {
    const tr = document.createElement('tr');

    const date = new Date(p.generatedAt).toLocaleDateString('en-US', {
      month: 'short', day: 'numeric',
    });

    const dirIcon = p.direction === 'UP' ? '▲' : '▼';
    const dirClass = p.direction === 'UP' ? 'accuracy-up' : 'accuracy-down';
    const predStr = `<span class="${dirClass}">${dirIcon} ${p.direction} ${formatCurrency(p.delta)}</span>`;

    let actualStr = '—';
    let resultStr = '<span class="accuracy-pending">Pending</span>';

    if (p.resolvedAt !== null) {
      actualStr = formatCurrency(p.actualPrice ?? 0);
      if (p.isCorrect) {
        resultStr = '<span class="accuracy-correct">✓ Correct</span>';
      } else {
        resultStr = '<span class="accuracy-incorrect">✗ Wrong</span>';
      }
    }

    tr.innerHTML = `
      <td><strong>${p.symbol}</strong>${p.isDemo ? ' <span class="accuracy-demo-tag">demo</span>' : ''}</td>
      <td>${date}</td>
      <td>${predStr}</td>
      <td>${actualStr}</td>
      <td>${resultStr}</td>
    `;
    tbody.appendChild(tr);
  });

  table.appendChild(tbody);
  section.appendChild(table);
  return section;
}
