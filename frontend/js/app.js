/* ==========================================================================
   ProjectSync AI - Shared app utilities
   Loaded on every page. Provides the API client, nav bar, and backend
   health indicator. Every API call goes through callApi() below, which
   ALWAYS returns a consistent {ok, data, error} shape and NEVER silently
   swallows a failure into zeros - this is the direct fix for the
   "dashboard showed 0 activities" problem from earlier attempts.
   ========================================================================== */

const API_BASE = 'http://127.0.0.1:8000';

/**
 * Calls the ProjectSync AI backend and normalizes the result.
 * Every caller gets back { ok: true, data } or { ok: false, error }.
 * Network failures (backend not running) and API-level failures
 * ({success:false}) both flow through this same shape, so page code
 * never has to guess which kind of failure happened.
 */
async function callApi(path, options = {}) {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
      ...options,
    });

    if (!response.ok && response.status >= 500) {
      console.error(`[ProjectSync] Server error on ${path}:`, response.status);
      return { ok: false, error: `Server error (${response.status}). Please try again.` };
    }

    const json = await response.json();

    if (json.success === false) {
      console.error(`[ProjectSync] API error on ${path}:`, json.error);
      return { ok: false, error: json.error || 'Something went wrong.' };
    }

    return { ok: true, data: json.data };

  } catch (err) {
    // This branch fires when the backend is unreachable at all
    // (not running, wrong port, CORS misconfigured, etc.)
    console.error(`[ProjectSync] Network error calling ${path}:`, err);
    return { ok: false, error: 'Backend unavailable. Is the ProjectSync AI server running?' };
  }
}

/**
 * Renders a loading spinner into a container. Call this BEFORE an
 * async fetch starts, so the user never sees a blank/zero state.
 */
function renderLoading(container, message = 'Loading data from ProjectSync AI...') {
  container.innerHTML = `
    <div class="state-message">
      <div class="spinner"></div>
      <span>${escapeHtml(message)}</span>
    </div>`;
}

/**
 * Renders an explicit error state. Never renders zeros/blanks as a
 * substitute for a real error, per spec section 16.
 */
function renderError(container, message = 'Unable to load project data.') {
  container.innerHTML = `
    <div class="state-message is-error">
      <div class="state-title">Unable to load data</div>
      <div>${escapeHtml(message)}</div>
      <div class="text-faint" style="font-size:12px;margin-top:4px;">
        Check the browser console for technical details.
      </div>
    </div>`;
}

/** Renders an empty-but-successful state (0 results is not an error). */
function renderEmpty(container, message = 'Nothing here yet.') {
  container.innerHTML = `
    <div class="state-message">
      <div class="state-title">${escapeHtml(message)}</div>
    </div>`;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

/** Maps a delay/match status string to a badge color class. */
function statusBadgeClass(status) {
  const map = {
    'On Track': 'badge-green',
    'Matched': 'badge-green',
    'At Risk': 'badge-amber',
    'Needs Review': 'badge-amber',
    'Delayed': 'badge-red',
    'New Activity': 'badge-cyan',
    'Not Started': 'badge-neutral',
    'In Progress': 'badge-cyan',
  };
  return map[status] || 'badge-neutral';
}

function statusDotClass(status) {
  if (status === 'On Track' || status === 'Matched') return 'status-ontrack';
  if (status === 'At Risk' || status === 'Needs Review') return 'status-atrisk';
  if (status === 'Delayed') return 'status-delayed';
  return '';
}

/**
 * Builds the dual progress bar HTML (planned marker + actual fill) -
 * the product's core visual: schedule vs. site reality at a glance.
 */
function renderDualProgress(planned, actual, status) {
  const p = Math.max(0, Math.min(100, planned ?? 0));
  const a = Math.max(0, Math.min(100, actual ?? 0));
  const statusClass = statusDotClass(status) === 'status-ontrack' ? 'status-ontrack'
    : statusDotClass(status) === 'status-atrisk' ? 'status-atrisk'
    : statusDotClass(status) === 'status-delayed' ? 'status-delayed' : '';

  return `
    <div class="progress-dual ${statusClass}">
      <div class="actual-fill" style="width:${a}%"></div>
      <div class="planned-marker" style="left:${p}%"></div>
    </div>
    <div class="progress-legend">
      <span>Actual ${a}%</span>
      <span>Planned ${p}%</span>
    </div>`;
}

/* ==========================================================================
   Nav bar - rendered identically on every page, active link highlighted
   ========================================================================== */

const NAV_ITEMS = [
  { href: 'index.html', label: 'Home' },
  { href: 'dashboard.html', label: 'Dashboard' },
  { href: 'data-capture.html', label: 'Data Capture' },
  { href: 'verification.html', label: 'Verification' },
  { href: 'insights.html', label: 'AI Insights' },
  { href: 'audit.html', label: 'Audit Trail' },
];

function renderNavbar() {
  const mount = document.getElementById('navbar-mount');
  if (!mount) return;

  const currentPage = window.location.pathname.split('/').pop() || 'index.html';

  const links = NAV_ITEMS.map(item => {
    const isActive = item.href === currentPage;
    return `<a class="nav-link ${isActive ? 'active' : ''}" href="${item.href}">${item.label}</a>`;
  }).join('');

  mount.innerHTML = `
    <nav class="navbar">
      <div class="navbar-inner">
        <a class="brand" href="index.html">
          <span class="brand-mark">PS</span>
          ProjectSync AI
        </a>
        <div class="nav-links">${links}</div>
        <div class="nav-status" id="backend-status">
          <span class="status-dot" id="status-dot"></span>
          <span id="status-text">Checking...</span>
        </div>
      </div>
    </nav>`;

  checkBackendHealth();
}

async function checkBackendHealth() {
  const dot = document.getElementById('status-dot');
  const text = document.getElementById('status-text');
  if (!dot || !text) return;

  const result = await callApi('/health');
  if (result.ok) {
    dot.classList.add('online');
    text.textContent = `Backend online (${result.data.ai_mode} mode)`;
  } else {
    dot.classList.add('offline');
    text.textContent = 'Backend unavailable';
  }
}

/* ==========================================================================
   Footer - rendered identically on every page
   ========================================================================== */

function renderFooter() {
  const mount = document.getElementById('footer-mount');
  if (!mount) return;
  mount.innerHTML = `
    <footer class="footer">
      <div class="footer-inner">
        <span>ProjectSync AI - Smart India Hackathon Prototype</span>
        <span>Schedule vs. Site Reality, Reconciled by AI</span>
      </div>
    </footer>`;
}

document.addEventListener('DOMContentLoaded', () => {
  renderNavbar();
  renderFooter();
});
