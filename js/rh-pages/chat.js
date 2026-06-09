import { api } from '../rh-api.js';

const HISTORY = [];

export async function renderChat(container) {
  const SUGGESTIONS = [
    'How accurate is Predictor v3?',
    'Why is the investor return negative?',
    "What's on the watchlist today?",
    'Explain the daytrade strategy',
  ];

  container.innerHTML = `
    <div class="rh-chat">
      <div class="rh-chat__messages" id="rh-chat-msgs">
        <div class="rh-chat__bubble rh-chat__bubble--bot">
          I'm your Nostradamus ML analyst, running locally (on the NPU when available, otherwise CPU). Ask me about Predictor accuracy, the Investor backtest, the reasoning watchlist, or pipeline health.
        </div>
      </div>
      <div class="rh-chat__suggest" id="rh-chat-suggest">
        ${SUGGESTIONS.map((s) => `<button type="button" class="rh-btn-secondary" data-q="${s.replace(/"/g, '&quot;')}">${s}</button>`).join('')}
      </div>
      <div class="rh-chat__input-row">
        <input type="text" class="rh-chat__input" id="rh-chat-input" placeholder="Ask about ML findings…" />
        <button type="button" class="rh-btn-primary" id="rh-chat-send">Send</button>
      </div>
      <p class="rh-sub" id="rh-chat-backend" style="margin-top:8px"></p>
    </div>`;

  const msgs = container.querySelector('#rh-chat-msgs');
  const input = container.querySelector('#rh-chat-input');
  const sendBtn = container.querySelector('#rh-chat-send');
  const backendEl = container.querySelector('#rh-chat-backend');

  container.querySelectorAll('#rh-chat-suggest [data-q]').forEach((btn) => {
    btn.addEventListener('click', () => {
      input.value = btn.dataset.q;
      send();
    });
  });

  function addBubble(text, role) {
    const b = document.createElement('div');
    b.className = `rh-chat__bubble rh-chat__bubble--${role === 'user' ? 'user' : 'bot'}`;
    b.textContent = text;
    msgs.appendChild(b);
    msgs.scrollTop = msgs.scrollHeight;
  }

  async function send() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    sendBtn.disabled = true;
    addBubble(text, 'user');
    HISTORY.push({ role: 'user', content: text });
    try {
      const res = await api.chat(text, HISTORY);
      addBubble(res.reply.replace(/\*\*/g, ''), 'bot');
      HISTORY.push({ role: 'assistant', content: res.reply });
      const backendHint = {
        gemini: 'Google Gemini (live)',
        genai: 'Local NPU/CPU model',
        template: 'Structured local answers (no LLM weights)',
      }[res.backend] || res.backend;
      backendEl.textContent = `Backend: ${backendHint}`;
    } catch (err) {
      addBubble(`Error: ${err.message}. Is serve.py running?`, 'bot');
    }
    sendBtn.disabled = false;
    input.focus();
  }

  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
}
