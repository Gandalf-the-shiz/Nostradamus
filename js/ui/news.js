/**
 * js/ui/news.js
 * News sentiment display component — Phase 6.
 *
 * Fetches recent company news from Finnhub and renders it with a
 * simple keyword-based sentiment score (positive / neutral / negative).
 * Falls back to demo news articles when no API key is configured.
 *
 * Dependencies: js/api/finnhub.js, js/utils/helpers.js
 */

import { getNews } from '../api/manager.js';
import { daysAgoISO, todayISO, escapeHtml } from '../utils/helpers.js';

// ─── Sentiment keywords ───────────────────────────────────────

/** Words that shift sentiment score positively. */
const POSITIVE_WORDS = [
  'surge', 'surges', 'soar', 'soars', 'beat', 'beats', 'record', 'growth',
  'gain', 'gains', 'profit', 'profits', 'upgrade', 'buy', 'outperform',
  'strong', 'rally', 'boost', 'win', 'wins', 'up', 'rise', 'rises',
  'bullish', 'positive', 'exceeds', 'exceed', 'innovative', 'breakthrough',
  'partnership', 'deal', 'acquire', 'launch', 'expand', 'expansion',
];

/** Words that shift sentiment score negatively. */
const NEGATIVE_WORDS = [
  'fall', 'falls', 'drop', 'drops', 'miss', 'misses', 'loss', 'losses',
  'decline', 'declines', 'cut', 'downgrade', 'sell', 'underperform',
  'weak', 'down', 'crash', 'concern', 'risk', 'risks', 'warning',
  'bearish', 'negative', 'lawsuit', 'fine', 'probe', 'investigation',
  'layoff', 'layoffs', 'recall', 'fraud', 'scandal', 'default',
];

// ─── Demo news data ───────────────────────────────────────────

/**
 * @type {Object.<string, Array<{headline: string, summary: string, url: string, datetime: number, source: string}>>}
 */
const DEMO_NEWS = {
  AAPL: [
    { headline: 'Apple beats Q2 estimates with record iPhone sales', summary: 'Apple Inc. surpassed analyst expectations in Q2, driven by record iPhone sales in emerging markets.', url: '#', datetime: Date.now() / 1000 - 3600, source: 'Demo News' },
    { headline: 'Apple expands Vision Pro lineup with new models', summary: 'Analysts upgrade Apple stock citing strong demand for spatial computing products.', url: '#', datetime: Date.now() / 1000 - 86400, source: 'Demo News' },
    { headline: 'EU investigation into Apple App Store practices', summary: 'Regulators continue probe into App Store fees; Apple faces potential fines.', url: '#', datetime: Date.now() / 1000 - 172800, source: 'Demo News' },
  ],
  GOOGL: [
    { headline: 'Google Cloud revenue surges 28% year-over-year', summary: 'Alphabet reports strong quarterly results, led by a surge in Google Cloud growth.', url: '#', datetime: Date.now() / 1000 - 7200, source: 'Demo News' },
    { headline: 'Google launches next-generation Gemini AI model', summary: 'The new Gemini model outperforms competitors in key benchmarks.', url: '#', datetime: Date.now() / 1000 - 90000, source: 'Demo News' },
  ],
  MSFT: [
    { headline: 'Microsoft Azure growth accelerates on AI demand', summary: 'Microsoft beats estimates; Azure revenue up 31% driven by AI services.', url: '#', datetime: Date.now() / 1000 - 5400, source: 'Demo News' },
    { headline: 'Microsoft Copilot expansion drives enterprise upgrades', summary: 'Analysts raise price targets as Copilot adoption grows across Fortune 500.', url: '#', datetime: Date.now() / 1000 - 108000, source: 'Demo News' },
  ],
  AMZN: [
    { headline: 'Amazon AWS posts record quarter; retail margins improve', summary: 'Amazon profits surge as AWS growth rebounds and retail business shows margin expansion.', url: '#', datetime: Date.now() / 1000 - 10800, source: 'Demo News' },
    { headline: 'Amazon layoffs continue in some divisions despite growth', summary: 'Despite strong overall results, Amazon cuts roles in some underperforming units.', url: '#', datetime: Date.now() / 1000 - 180000, source: 'Demo News' },
  ],
  TSLA: [
    { headline: 'Tesla delivers record number of vehicles in Q1', summary: 'Tesla beat delivery estimates for the quarter, pushing stock higher in after-hours trading.', url: '#', datetime: Date.now() / 1000 - 14400, source: 'Demo News' },
    { headline: 'Tesla faces recall on Autopilot software concerns', summary: 'NHTSA investigation prompts Tesla to issue software update; analysts remain cautious.', url: '#', datetime: Date.now() / 1000 - 200000, source: 'Demo News' },
  ],
};

const DEFAULT_DEMO = [
  { headline: 'Market rally continues as inflation data cools', summary: 'Broad market indices posted gains after a favorable CPI print.', url: '#', datetime: Date.now() / 1000 - 3600, source: 'Demo News' },
  { headline: 'Fed signals potential rate cuts later this year', summary: 'Federal Reserve meeting minutes hint at two possible rate reductions in H2.', url: '#', datetime: Date.now() / 1000 - 86400, source: 'Demo News' },
];

// ─── Public API ───────────────────────────────────────────────

/**
 * Fetch and render news for a symbol into the given container.
 * Falls back to demo news when the API key is absent.
 *
 * @param {HTMLElement} container
 * @param {string}      symbol
 * @param {{ mode: 'demo'|'live' }} appState
 * @returns {Promise<void>}
 */
export async function renderNewsPanel(container, symbol, appState) {
  container.innerHTML = '<div class="news-loading">Loading news…</div>';

  let articles = [];

  try {
    const from = daysAgoISO(7);
    const to   = todayISO();
    articles = await getNews(symbol, from, to);
  } catch (err) {
    console.warn('[News] API fetch failed, falling back to demo news:', err.message);
  }

  if (!articles || articles.length === 0) {
    articles = _getDemoNews(symbol);
  }

  container.innerHTML = '';
  _renderArticles(container, articles, symbol);
}

/**
 * Score a text snippet and return a sentiment label.
 *
 * @param {string} text
 * @returns {'positive'|'negative'|'neutral'}
 */
export function scoreSentiment(text) {
  if (!text) return 'neutral';
  const lower = text.toLowerCase();
  const words = lower.split(/\W+/);
  let score = 0;
  for (const word of words) {
    if (POSITIVE_WORDS.includes(word)) score++;
    if (NEGATIVE_WORDS.includes(word)) score--;
  }
  if (score > 0) return 'positive';
  if (score < 0) return 'negative';
  return 'neutral';
}

/**
 * Fetch news headlines for a symbol as plain strings (for sentiment scoring).
 * Returns up to 5 headlines. Gracefully falls back to demo data.
 *
 * @param {string} symbol
 * @param {{ mode: 'demo'|'live' }} appState
 * @returns {Promise<string[]>}
 */
export async function fetchNewsHeadlines(symbol, appState) {
  let articles = [];
  try {
    const from = daysAgoISO(7);
    const to   = todayISO();
    articles = await getNews(symbol, from, to);
  } catch {
    // ignore — fall through to demo
  }
  if (!articles || articles.length === 0) {
    articles = _getDemoNews(symbol);
  }
  return articles.map(a => a.headline || a.summary || '').filter(Boolean);
}

// ─── Private helpers ──────────────────────────────────────────

/**
 * Return demo news articles for a symbol.
 * @param {string} symbol
 * @returns {Array}
 */
function _getDemoNews(symbol) {
  return DEMO_NEWS[symbol.toUpperCase()] || DEFAULT_DEMO;
}

/**
 * Render a list of articles into the container.
 * @param {HTMLElement} container
 * @param {Array}       articles
 * @param {string}      symbol
 */
function _renderArticles(container, articles, symbol) {
  if (!articles || articles.length === 0) {
    container.innerHTML = '<p class="news-empty">No recent news found.</p>';
    return;
  }

  const list = document.createElement('div');
  list.className = 'news-list';

  for (const article of articles) {
    const sentiment = scoreSentiment(`${article.headline} ${article.summary}`);
    const sentimentLabel = { positive: '😊 Positive', negative: '😟 Negative', neutral: '😐 Neutral' }[sentiment];
    const date = article.datetime
      ? new Date(article.datetime * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      : '';

    const item = document.createElement('div');
    item.className = `news-item news-item--${sentiment}`;
    item.innerHTML = `
      <div class="news-item__meta">
        <span class="news-item__sentiment news-item__sentiment--${sentiment}">${sentimentLabel}</span>
        <span class="news-item__date">${_escapeHtml(date)}</span>
        <span class="news-item__source">${_escapeHtml(article.source || '')}</span>
      </div>
      <a class="news-item__headline" href="${_escapeHtml(article.url || '#')}" target="_blank" rel="noopener noreferrer">
        ${_escapeHtml(article.headline || 'No headline')}
      </a>
      ${article.summary ? `<p class="news-item__summary">${_escapeHtml(article.summary)}</p>` : ''}
    `;
    list.appendChild(item);
  }

  container.appendChild(list);

  // Append demo mode badge if applicable
  if (articles[0]?.source === 'Demo News') {
    const badge = document.createElement('p');
    badge.className = 'news-demo-badge';
    badge.textContent = 'Showing demo news — add a Finnhub API key for live news.';
    container.appendChild(badge);
  }
}

