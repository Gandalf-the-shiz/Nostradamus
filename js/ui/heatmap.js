/**
 * js/ui/heatmap.js
 * Market Treemap Heatmap — Phase 7.
 *
 * Renders a Finviz-style squarified treemap on a <canvas> element.
 * Stocks are grouped by sector, sized equally within each sector,
 * and coloured by prediction direction + confidence.
 *
 * Export: renderHeatmap(container, predictionsData, appState)
 *   - container: HTMLElement — will receive a <canvas> and tooltip DOM
 *   - predictionsData: Array of prediction objects from tracker.js or demo
 *   - appState: { mode, chartReady }
 *
 * Lazy-loaded by app.js when the user navigates to the "heatmap" view.
 */

import { getPredictions } from '../ml/tracker.js';
import { demoPrediction }  from '../ml/prediction.js';

// ─── Sector palette ───────────────────────────────────────────

const SECTOR_COLORS = {
  'Technology':             '#7c6fef',
  'Consumer Discretionary': '#f0b429',
  'Financials':             '#26d97f',
  'Healthcare':             '#4dc3ff',
  'Communication Services': '#ff7b54',
  'Energy':                 '#f05c6e',
  'Consumer Staples':       '#a8e6a3',
  'Industrials':            '#c8a2c8',
  'Materials':              '#d4a373',
  'Real Estate':            '#90e0ef',
  'Utilities':              '#b5838d',
  'Other':                  '#8b91a7',
};

const DEMO_SECTORS = {
  AAPL:  'Technology', GOOGL: 'Technology', MSFT: 'Technology',
  AMZN:  'Consumer Discretionary', TSLA: 'Consumer Discretionary',
  META:  'Technology', NVDA: 'Technology', NFLX: 'Communication Services',
  JPM:   'Financials', V: 'Financials', JNJ: 'Healthcare', PFE: 'Healthcare',
  XOM:   'Energy', CVX: 'Energy', GS: 'Financials', BAC: 'Financials',
  WMT:   'Consumer Staples', KO: 'Consumer Staples',
  DIS:   'Communication Services', BA: 'Industrials',
};

// ─── Squarified treemap algorithm ────────────────────────────

/**
 * Squarify layout algorithm.
 * @param {number[]} values   - Non-negative weights (same length as items)
 * @param {number} x
 * @param {number} y
 * @param {number} w
 * @param {number} h
 * @returns {{ x, y, w, h }[]}
 */
function squarify(values, x, y, w, h) {
  if (values.length === 0) return [];
  const total = values.reduce((a, b) => a + b, 0);
  if (total === 0) {
    const n = values.length;
    return values.map((_, i) => ({ x: x + (i * w) / n, y, w: w / n, h }));
  }

  const rects = [];
  _squarifyRow(values, x, y, w, h, total, rects);
  return rects;
}

function _squarifyRow(values, x, y, w, h, total, rects) {
  if (values.length === 0) return;
  if (values.length === 1) {
    rects.push({ x, y, w, h });
    return;
  }

  const horizontal = w >= h;
  const side = horizontal ? h : w;

  let row = [];
  let rowArea = 0;
  let i = 0;

  while (i < values.length) {
    const v = (values[i] / total) * (w * h);
    const candidate = [...row, v];
    const candidateArea = rowArea + v;

    if (row.length === 0 || _worstRatio(candidate, candidateArea, side) <= _worstRatio(row, rowArea, side)) {
      row.push(v);
      rowArea += v;
      i++;
    } else {
      break;
    }
  }

  // Lay out the current row
  const rowFrac = rowArea / (w * h);
  let cursor = horizontal ? x : y;
  for (const rv of row) {
    const frac = rv / rowArea;
    if (horizontal) {
      const rh = rowFrac * h;
      const rw = frac * w;
      rects.push({ x: cursor, y, w: rw, h: rh });
      cursor += rw;
    } else {
      const rw = rowFrac * w;
      const rh = frac * h;
      rects.push({ x, y: cursor, w: rw, h: rh });
      cursor += rh;
    }
  }

  // Recurse on remaining values
  if (i < values.length) {
    if (horizontal) {
      const usedH = rowFrac * h;
      _squarifyRow(values.slice(i), x, y + usedH, w, h - usedH, total - rowArea / (w * h) * total, rects);
    } else {
      const usedW = rowFrac * w;
      _squarifyRow(values.slice(i), x + usedW, y, w - usedW, h, total - rowArea / (w * h) * total, rects);
    }
  }
}

function _worstRatio(row, area, side) {
  if (row.length === 0 || area === 0) return Infinity;
  const maxA = Math.max(...row);
  const minA = Math.min(...row);
  const s2 = side * side;
  const a2 = area * area;
  return Math.max((s2 * maxA) / a2, a2 / (s2 * minA));
}

// ─── Colour helpers ───────────────────────────────────────────

/**
 * Map a prediction to a canvas fill colour.
 * UP → green gradient by confidence; DOWN → red gradient; neutral → gray.
 */
function _predictionColor(pred) {
  if (!pred) return 'rgba(139,145,167,0.5)';
  const c = pred.confidence ?? 0.5;
  const alpha = 0.4 + c * 0.55; // 0.4 – 0.95

  if (pred.direction === 'UP') {
    // green family
    const g = Math.round(180 + c * 75);
    return `rgba(38,${g},127,${alpha.toFixed(2)})`;
  }
  // DOWN → red family
  const r = Math.round(200 + c * 55);
  return `rgba(${r},60,90,${alpha.toFixed(2)})`;
}

// ─── Public API ───────────────────────────────────────────────

/**
 * Render (or refresh) the heatmap into the given container.
 *
 * @param {HTMLElement} container
 * @param {Object[]|null} predictionsData  - Optional override; uses tracker if null
 * @param {{ mode: 'demo'|'live' }} appState
 */
export function renderHeatmap(container, predictionsData, appState) {
  container.innerHTML = '';

  // ── Build prediction lookup
  let predictions = predictionsData;
  if (!predictions || predictions.length === 0) {
    predictions = getPredictions();
  }

  // Fall back to demo predictions for the default watchlist
  if (predictions.length === 0) {
    const DEMO_SYMBOLS = ['AAPL','GOOGL','MSFT','AMZN','TSLA','META','NVDA','NFLX',
                          'JPM','V','JNJ','PFE','XOM','CVX','GS','BAC','WMT','KO','DIS','BA'];
    const BASE_PRICES  = { AAPL:185,GOOGL:140,MSFT:380,AMZN:178,TSLA:245,META:490,NVDA:800,
                           NFLX:600,JPM:195,V:270,JNJ:160,PFE:28,XOM:110,CVX:155,GS:400,
                           BAC:38,WMT:175,KO:61,DIS:95,BA:215 };
    predictions = DEMO_SYMBOLS.map(s => demoPrediction(s, BASE_PRICES[s] ?? 100));
  }

  // Latest per symbol
  const latestMap = new Map();
  for (const p of predictions) {
    const ex = latestMap.get(p.symbol);
    if (!ex || p.generatedAt > ex.generatedAt) latestMap.set(p.symbol, p);
  }

  // Group by sector
  const sectorGroups = new Map();
  for (const [symbol, pred] of latestMap) {
    const sector = DEMO_SECTORS[symbol] ?? 'Other';
    if (!sectorGroups.has(sector)) sectorGroups.set(sector, []);
    sectorGroups.get(sector).push({ symbol, pred });
  }

  // ── Title
  const titleEl = document.createElement('h2');
  titleEl.className = 'heatmap-title';
  titleEl.textContent = '🌡️ Market Heatmap';
  container.appendChild(titleEl);

  const subtitleEl = document.createElement('p');
  subtitleEl.className = 'heatmap-subtitle';
  subtitleEl.textContent =
    'Colour = prediction direction (green ▲ / red ▼). Intensity = confidence. Click a cell to view details.';
  container.appendChild(subtitleEl);

  // ── Legend
  const legend = document.createElement('div');
  legend.className = 'heatmap-legend';
  legend.innerHTML = `
    <span class="heatmap-legend__item heatmap-legend__item--up">▲ Bullish</span>
    <span class="heatmap-legend__item heatmap-legend__item--neutral">◼ No data</span>
    <span class="heatmap-legend__item heatmap-legend__item--down">▼ Bearish</span>
  `;
  container.appendChild(legend);

  if (appState.mode === 'demo') {
    const note = document.createElement('p');
    note.className = 'heatmap-demo-note';
    note.textContent = 'Demo mode — showing sample predictions for illustration.';
    container.appendChild(note);
  }

  // ── Canvas
  const canvasWrap = document.createElement('div');
  canvasWrap.className = 'heatmap-canvas-wrap';
  const canvas = document.createElement('canvas');
  canvas.className = 'heatmap-canvas';
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', 'Market heatmap treemap');
  canvasWrap.appendChild(canvas);
  container.appendChild(canvasWrap);

  // ── Tooltip
  const tooltip = document.createElement('div');
  tooltip.className = 'heatmap-tooltip';
  tooltip.hidden = true;
  container.appendChild(tooltip);

  // Draw after layout (so offsetWidth is known)
  requestAnimationFrame(() => {
    _drawHeatmap(canvas, tooltip, sectorGroups, latestMap);
    // Redraw on window resize
    const observer = new ResizeObserver(() => {
      _drawHeatmap(canvas, tooltip, sectorGroups, latestMap);
    });
    observer.observe(canvasWrap);
    canvas._resizeObserver = observer;
  });
}

// ─── Drawing ──────────────────────────────────────────────────

function _drawHeatmap(canvas, tooltip, sectorGroups, latestMap) {
  const wrap = canvas.parentElement;
  const W = wrap.clientWidth  || 600;
  const H = Math.max(400, Math.round(W * 0.55));

  canvas.width  = W;
  canvas.height = H;

  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, W, H);

  // Gather all stocks in sector order
  const stocks = [];
  const sortedSectors = Array.from(sectorGroups.keys()).sort();
  for (const sector of sortedSectors) {
    for (const item of sectorGroups.get(sector)) {
      stocks.push({ ...item, sector });
    }
  }

  if (stocks.length === 0) return;

  // Equal weights
  const values = stocks.map(() => 1);
  const rects  = squarify(values, 0, 0, W, H);

  // Store rect data for hit-testing
  canvas._cells = [];

  for (let i = 0; i < stocks.length; i++) {
    const { symbol, pred, sector } = stocks[i];
    const { x, y, w, h } = rects[i];
    if (w < 1 || h < 1) continue;

    const color = _predictionColor(pred);
    ctx.fillStyle = color;
    ctx.fillRect(x, y, w, h);

    // Border
    ctx.strokeStyle = 'rgba(15,17,23,0.8)';
    ctx.lineWidth   = 1.5;
    ctx.strokeRect(x + 0.75, y + 0.75, w - 1.5, h - 1.5);

    // Label (only if cell is large enough)
    if (w > 36 && h > 20) {
      ctx.save();
      ctx.fillStyle = 'rgba(255,255,255,0.92)';
      const fontSize = Math.min(13, Math.max(9, Math.floor(Math.min(w, h) / 5)));
      ctx.font       = `700 ${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;
      ctx.textAlign  = 'center';
      ctx.textBaseline = 'middle';
      // Clip to cell
      ctx.beginPath();
      ctx.rect(x + 2, y + 2, w - 4, h - 4);
      ctx.clip();
      ctx.fillText(symbol, x + w / 2, y + h / 2);
      ctx.restore();
    }

    canvas._cells.push({ x, y, w, h, symbol, pred, sector });
  }

  // Wire up pointer events (attach only once)
  if (!canvas._eventsWired) {
    canvas._eventsWired = true;
    _wireCanvasEvents(canvas, tooltip, latestMap);
  }
}

function _wireCanvasEvents(canvas, tooltip, latestMap) {
  canvas.style.cursor = 'pointer';

  canvas.addEventListener('pointermove', e => {
    const cell = _hitTest(canvas, e);
    if (!cell) {
      tooltip.hidden = true;
      return;
    }

    const pred = cell.pred;
    const dir  = pred ? (pred.direction === 'UP' ? '▲ UP' : '▼ DOWN') : '—';
    const conf = pred ? `${Math.round((pred.confidence ?? 0) * 100)}%` : '—';
    const prob = pred ? `${Math.round((pred.probability ?? 0.5) * 100)}%` : '—';

    tooltip.innerHTML = `
      <strong>${_escHtml(cell.symbol)}</strong>
      <span class="heatmap-tooltip__sector">${_escHtml(cell.sector)}</span>
      <span class="heatmap-tooltip__dir heatmap-tooltip__dir--${pred?.direction?.toLowerCase() ?? 'neutral'}">${dir}</span>
      <span>Confidence: ${conf}</span>
      <span>Probability: ${prob}</span>
    `;
    tooltip.hidden = false;

    const rect = canvas.getBoundingClientRect();
    const tx = e.clientX - rect.left;
    const ty = e.clientY - rect.top;
    tooltip.style.left = `${Math.min(tx + 12, canvas.width - tooltip.offsetWidth - 8)}px`;
    tooltip.style.top  = `${Math.max(ty - tooltip.offsetHeight - 8, 8)}px`;
  });

  canvas.addEventListener('pointerleave', () => {
    tooltip.hidden = true;
  });

  canvas.addEventListener('click', e => {
    const cell = _hitTest(canvas, e);
    if (!cell) return;
    // Dispatch event so app.js / dashboard can open detail modal
    canvas.dispatchEvent(new CustomEvent('heatmap-cell-click', {
      bubbles:   true,
      composed:  true,
      detail:    { symbol: cell.symbol, pred: cell.pred },
    }));
  });
}

function _hitTest(canvas, e) {
  if (!canvas._cells) return null;
  const rect = canvas.getBoundingClientRect();
  const mx   = e.clientX - rect.left;
  const my   = e.clientY - rect.top;
  for (const cell of canvas._cells) {
    if (mx >= cell.x && mx <= cell.x + cell.w && my >= cell.y && my <= cell.y + cell.h) {
      return cell;
    }
  }
  return null;
}

function _escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
