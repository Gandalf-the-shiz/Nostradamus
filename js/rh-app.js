/**
 * Nostradamus Robinhood-style SPA router.
 */
import { openPageHelp } from './rh-help.js';
import { renderHome } from './rh-pages/home.js';
import { renderMarkets } from './rh-pages/markets.js';
import { renderInvestorPage } from './rh-pages/investor-page.js';
import { renderTrade } from './rh-pages/trade.js';
import { renderChat } from './rh-pages/chat.js';
import { renderStock } from './rh-pages/stock.js';
import { renderArchitecture } from './rh-pages/architecture.js';
import { renderPredictions } from './rh-pages/predictions.js';

const TITLES = {
  home: 'Command Center',
  markets: 'Markets',
  investor: 'Investor',
  trade: 'Trade',
  chat: 'ML Chat',
  predictions: 'Prediction Markets',
  stock: 'Stock',
  architecture: 'How It Works',
};

let currentPage = 'home';

function parseRoute() {
  const hash = (location.hash || '#/home').replace(/^#\/?/, '');
  const parts = hash.split('/').filter(Boolean);
  if (parts[0] === 'stock' && parts[1]) {
    return { page: 'stock', symbol: parts[1].toUpperCase() };
  }
  if (parts[0] === 'architecture') return { page: 'architecture' };
  const page = ['home', 'markets', 'investor', 'trade', 'chat', 'predictions'].includes(parts[0]) ? parts[0] : 'home';
  return { page };
}

function setActiveTab(page) {
  document.querySelectorAll('.rh-tab').forEach((tab) => {
    const r = tab.dataset.route;
    const active = r === page || (page === 'stock' && r === 'markets') || page === 'architecture';
    tab.classList.toggle('rh-tab--active', active && ['home', 'markets', 'investor', 'trade', 'chat', 'predictions'].includes(r));
    tab.toggleAttribute('aria-current', active && tab.classList.contains('rh-tab--active') ? 'page' : false);
  });
}

function navigate(page, symbol) {
  if (page === 'stock' && symbol) {
    location.hash = `#/stock/${symbol}`;
  } else if (page === 'architecture') {
    location.hash = '#/architecture';
  } else {
    location.hash = `#/${page}`;
  }
}

async function render() {
  const route = parseRoute();
  const main = document.getElementById('rh-main');
  const titleEl = document.getElementById('rh-page-title');
  if (!main) return;

  currentPage = route.page === 'stock' ? 'stock' : route.page;
  const helpPage = route.page === 'stock' ? 'stock' : route.page;
  titleEl.textContent = route.page === 'stock' ? route.symbol : (TITLES[route.page] || 'Nostradamus');
  setActiveTab(route.page === 'architecture' ? 'home' : route.page);

  if (route.page === 'home') await renderHome(main);
  else if (route.page === 'markets') await renderMarkets(main, { navigate });
  else if (route.page === 'investor') await renderInvestorPage(main);
  else if (route.page === 'trade') await renderTrade(main);
  else if (route.page === 'chat') await renderChat(main);
  else if (route.page === 'predictions') await renderPredictions(main);
  else if (route.page === 'stock') await renderStock(main, route.symbol);
  else if (route.page === 'architecture') await renderArchitecture(main);
  else await renderHome(main);
}

function init() {
  document.querySelectorAll('.rh-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      navigate(tab.dataset.route);
    });
  });

  document.getElementById('rh-help-btn')?.addEventListener('click', () => {
    const route = parseRoute();
    const pid = route.page === 'stock' ? 'stock' : route.page;
    openPageHelp(pid);
  });

  document.getElementById('rh-arch-btn')?.addEventListener('click', () => {
    location.hash = '#/architecture';
  });

  window.addEventListener('hashchange', () => render());
  if (!location.hash) location.hash = '#/home';
  render();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
