/* ==========================================================================
   ProjectSync AI - Activity Details logic
   Reads the activity_id from the URL query string (?id=L5-EXC-001) and
   fetches full detail from GET /activities/{activity_id}.
   ========================================================================== */

document.addEventListener('DOMContentLoaded', loadActivityDetail);

async function loadActivityDetail() {
  const root = document.getElementById('activity-root');
  const params = new URLSearchParams(window.location.search);
  const activityId = params.get('id');

  if (!activityId) {
    renderError(root, 'No activity specified. Go back to the dashboard and click an activity row.');
    return;
  }

  renderLoading(root, `Loading ${activityId}...`);

  const result = await callApi(`/activities/${encodeURIComponent(activityId)}`);
  if (!result.ok) {
    renderError(root, result.error);
    return;
  }

  const a = result.data;

  root.innerHTML = `
    <div class="section-head">
      <div>
        <h1 style="margin-bottom:4px;">${escapeHtml(a.activity_name)}</h1>
        <span class="activity-id">${escapeHtml(a.activity_id)}</span>
      </div>
      <span class="badge ${statusBadgeClass(a.status)}">${escapeHtml(a.status)}</span>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <h3>Progress</h3>
        ${renderDualProgress(a.planned_progress, a.actual_progress, a.status)}
        <div style="display:flex; gap:24px; margin-top:12px; font-size:13px;">
          <div><span class="text-faint">Variance</span> <strong style="color:${a.variance < 0 ? 'var(--red)' : 'var(--green)'}">${a.variance > 0 ? '+' : ''}${a.variance}%</strong></div>
          <div><span class="text-faint">AI Confidence</span> <strong>${a.ai_confidence != null ? (a.ai_confidence * 100).toFixed(0) + '%' : 'N/A'}</strong></div>
        </div>
      </div>

      <div class="card">
        <h3>Schedule</h3>
        <div style="display:flex; flex-direction:column; gap:8px; font-size:14px;">
          <div><span class="text-faint">Location:</span> ${escapeHtml(a.location || '—')}</div>
          <div><span class="text-faint">Planned Start:</span> ${a.planned_start ? new Date(a.planned_start).toLocaleDateString() : '—'}</div>
          <div><span class="text-faint">Planned End:</span> ${a.planned_end ? new Date(a.planned_end).toLocaleDateString() : '—'}</div>
          <div><span class="text-faint">Dependencies:</span> <span class="mono">${escapeHtml(a.dependencies || 'None')}</span></div>
        </div>
      </div>
    </div>

    <div class="section" style="margin-top:24px;">
      <div class="card">
        <h3>AI Explanation</h3>
        <p style="color:var(--text);">${escapeHtml(a.ai_explanation)}</p>
        ${a.issues ? `<p><span class="text-faint">Reported issue:</span> ${escapeHtml(a.issues)}</p>` : ''}
      </div>
    </div>

    <div class="section">
      <div class="card" style="border-color:var(--cyan);">
        <h3 style="color:var(--cyan);">Recommended Action</h3>
        <p style="color:var(--text); margin:0;">${escapeHtml(a.recommended_action)}</p>
      </div>
    </div>
  `;
}
