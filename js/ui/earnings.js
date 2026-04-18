import { getEarningsCalendar } from '../api/manager.js';
import { getWatchlist } from './watchlist.js';

export async function renderEarningsView(container, appState) {
  container.innerHTML = '';

  const title = document.createElement('h2');
  title.className = 'backtest-title';
  title.textContent = '📅 Upcoming Earnings';
  container.appendChild(title);

  const watchlist = getWatchlist();
  if (!watchlist.length) {
    container.innerHTML += '<p class="accuracy-empty-note">Add symbols to your watchlist to see upcoming earnings.</p>';
    return;
  }

  let rows = [];
  if (appState.mode === 'demo') {
    try {
      const res = await fetch('./data/sample-earnings.json');
      const data = await res.json();
      rows = (data.earningsCalendar || []).filter(e => watchlist.includes(e.symbol));
    } catch {
      rows = [];
    }
  } else {
    const from = new Date().toISOString().slice(0, 10);
    const toD = new Date();
    toD.setDate(toD.getDate() + 30);
    const to = toD.toISOString().slice(0, 10);
    const all = await getEarningsCalendar(from, to);
    rows = (all || []).filter(e => watchlist.includes(e.symbol));
  }

  if (!rows.length) {
    const noKey = appState.mode !== 'demo'
      ? 'No Finnhub key configured or no upcoming earnings for your watchlist.'
      : 'Demo earnings sample is empty for the current watchlist.';
    container.innerHTML += `<p class="accuracy-empty-note">${noKey}</p>`;
    return;
  }

  const table = document.createElement('table');
  table.className = 'accuracy-table';
  table.innerHTML = `
    <thead>
      <tr>
        <th>Symbol</th>
        <th>Date</th>
        <th>Session</th>
        <th>EPS Est.</th>
      </tr>
    </thead>
    <tbody>
      ${rows.slice(0, 100).map(e => `
        <tr>
          <td><strong>${_esc(e.symbol || '')}</strong></td>
          <td>${_esc(e.date || '—')}</td>
          <td>${_esc((e.hour || '').toUpperCase() || '—')}</td>
          <td>${e.epsEstimate != null ? Number(e.epsEstimate).toFixed(2) : '—'}</td>
        </tr>
      `).join('')}
    </tbody>
  `;
  container.appendChild(table);
}

function _esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
