/* ==========================================================================
   ProjectSync AI - AI Insights logic
   ========================================================================== */

document.addEventListener('DOMContentLoaded', loadInsights);

async function loadInsights() {
  const root = document.getElementById('insights-root');
  renderLoading(root, 'Loading insights...');

  const result = await callApi('/insights');
  if (!result.ok) {
    renderError(root, result.error);
    return;
  }

  const insights = result.data.insights;
  if (!insights || insights.length === 0) {
    renderEmpty(root, 'No insights yet - upload a site report to generate some.');
    return;
  }

  root.innerHTML = `
    <div style="display:flex; flex-direction:column; gap:14px;">
      ${insights.map(text => `
        <div class="card" style="display:flex; gap:14px; align-items:flex-start;">
          <span style="color:var(--cyan); font-family:var(--font-display); font-weight:700; font-size:18px; flex-shrink:0;">AI</span>
          <p style="margin:0; color:var(--text);">${escapeHtml(text)}</p>
        </div>
      `).join('')}
    </div>`;
}
