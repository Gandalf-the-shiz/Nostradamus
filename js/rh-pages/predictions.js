import { api } from '../rh-api.js';

function metric(label, value, tone = '') {
  return `<div class="rh-metric">
    <div class="rh-metric__label">${label}</div>
    <div class="rh-metric__value ${tone}">${value}</div>
  </div>`;
}

function tone(n) {
  if (n == null || Number.isNaN(Number(n))) return '';
  return Number(n) > 0 ? 'rh-metric__value--green' : (Number(n) < 0 ? 'rh-metric__value--red' : '');
}

export async function renderPredictions(main) {
  main.innerHTML = '<div class="rh-loading">Loading prediction-market sleeve…</div>';
  let pm;
  try {
    pm = await api.predictionMarkets();
  } catch (e) {
    main.innerHTML = `<section class="rh-card"><h2 class="rh-card__title">Prediction markets</h2>
      <p class="rh-muted">Could not reach the server endpoint (${e.message}).</p></section>`;
    return;
  }

  const banner = pm.available
    ? (pm.hasActivity
        ? '<span class="rh-pill rh-pill--green">Active sleeve</span>'
        : '<span class="rh-pill">Installed · idle</span>')
    : '<span class="rh-pill rh-pill--red">Not installed</span>';

  const metrics = pm.hasActivity ? `
    <div class="rh-metrics">
      ${metric('Open bets', pm.openBets)}
      ${metric('Resolved', pm.resolvedBets)}
      ${metric('Realized edge / $1', pm.realizedEdgePerDollar, tone(pm.realizedEdgePerDollar))}
      ${metric('Win rate', pm.winRatePct == null ? '—' : pm.winRatePct + '%')}
      ${metric('Brier score', pm.brierScore == null ? '—' : pm.brierScore)}
      ${metric('Alert rules', pm.nAlertRules)}
    </div>` : '';

  const triggers = (pm.recentTriggers || []).length
    ? `<h3 class="rh-card__subtitle">Recent alert triggers</h3><ul class="rh-list">${
        pm.recentTriggers.map((t) => `<li>${t.question} — <strong>${t.side}</strong>
          (${((t.edge || 0) * 100).toFixed(1)}% edge)</li>`).join('')}</ul>` : '';

  main.innerHTML = `
    <section class="rh-card">
      <div class="rh-card__head">
        <h2 class="rh-card__title">Prediction markets ${banner}</h2>
      </div>
      <p class="rh-muted">A separate strategy and bankroll from the stock book (Kalshi / Polymarket),
        shown here for one combined view. ${pm.note}</p>
      ${metrics}
      ${triggers}
      <p class="rh-muted" style="margin-top:14px;font-size:12px">
        The Prediction Market Predictor runs as its own service. To analyze contracts, scan for
        mispricings, and record paper bets, launch it (<code>run.ps1</code>) and add an LLM key.
        Resolved paper bets here feed its execution gate — real money stays locked until forward edge is proven.
      </p>
    </section>`;
}
