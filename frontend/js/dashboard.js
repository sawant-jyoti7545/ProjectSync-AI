/* ==========================================================================
   ProjectSync AI - Dashboard logic
   Every number on this page comes from GET /dashboard. On failure, an
   explicit error is shown - this page never falls back to rendering
   zeros for missing data (spec section 16).
   ========================================================================== */

document.addEventListener('DOMContentLoaded', loadDashboard);

async function loadDashboard() {
  const root = document.getElementById('dashboard-root');
  renderLoading(root, 'Loading project data...');

  const result = await callApi('/dashboard');

  if (!result.ok) {
    renderError(root, result.error);
    return;
  }

  const d = result.data;
  const healthBadge = statusBadgeClass(d.project_health);

  root.innerHTML = `
    <div class="section-head">
      <div>
        <h1 style="margin-bottom:4px;">${escapeHtml(d.project_name)}</h1>
        <span class="badge ${healthBadge}">${escapeHtml(d.project_health)}</span>
      </div>
      <a href="data-capture.html" class="btn btn-primary">Upload Site Report</a>
    </div>

    <section class="section grid grid-4">
      <div class="card stat-card">
        <div class="card-title">Total Activities</div>
        <div class="stat-value">${d.total_activities}</div>
      </div>
      <div class="card stat-card">
        <div class="card-title">Completed</div>
        <div class="stat-value green">${d.completed_activities}</div>
      </div>
      <div class="card stat-card">
        <div class="card-title">Delayed</div>
        <div class="stat-value red">${d.delayed_activities}</div>
      </div>
      <div class="card stat-card">
        <div class="card-title">AI Verification</div>
        <div class="stat-value amber">${d.activities_needing_verification}</div>
        <div class="stat-sub">${d.activities_needing_verification > 0 ? 'Pending review' : 'All clear'}</div>
      </div>
    </section>

    <section class="section">
      <div class="section-head"><h2>Overall Execution</h2></div>
      <div class="card">
        ${renderDualProgress(d.planned_pct, d.actual_pct, d.project_health)}
        <div style="display:flex; gap:32px; margin-top:16px; font-size:13px;">
          <div><span class="text-faint">Planned</span> <strong>${d.planned_pct}%</strong></div>
          <div><span class="text-faint">Actual</span> <strong>${d.actual_pct}%</strong></div>
          <div><span class="text-faint">Variance</span> <strong style="color:${d.variance < 0 ? 'var(--red)' : 'var(--green)'}">${d.variance > 0 ? '+' : ''}${d.variance}%</strong></div>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-head"><h2>Recent Site Updates</h2></div>
      <div id="recent-updates-table"></div>
    </section>

    <section class="section">
      <div class="section-head"><h2>AI Insights</h2></div>
      <div class="card">
        <ul style="margin:0; padding-left:20px; color:var(--text-muted); display:flex; flex-direction:column; gap:8px;">
          ${d.ai_insights.map(i => `<li>${escapeHtml(i)}</li>`).join('')}
        </ul>
      </div>
    </section>

    <section class="section">
      <div class="section-head"><h2>Project Operations</h2></div>
      <div class="grid grid-4">
        <a href="data-capture.html" class="card" style="text-decoration:none;"><h3 class="mt-0">Upload Site Report</h3><p style="margin:0;">Analyze a new report</p></a>
        <a href="verification.html" class="card" style="text-decoration:none;"><h3 class="mt-0">Verification Queue</h3><p style="margin:0;">${d.activities_needing_verification} pending</p></a>
        <a href="insights.html" class="card" style="text-decoration:none;"><h3 class="mt-0">AI Insights</h3><p style="margin:0;">Full insight history</p></a>
        <a href="audit.html" class="card" style="text-decoration:none;"><h3 class="mt-0">Audit Trail</h3><p style="margin:0;">System event log</p></a>
      </div>
    </section>
  `;

  renderRecentUpdatesTable(d.recent_site_updates);
}

function renderRecentUpdatesTable(updates) {
  const container = document.getElementById('recent-updates-table');

  if (!updates || updates.length === 0) {
    renderEmpty(container, 'No site updates yet - upload a report to get started.');
    return;
  }

  container.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Activity</th>
            <th>Activity ID</th>
            <th>Progress</th>
            <th>Updated</th>
            <th>AI Confidence</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          ${updates.map(u => `
            <tr onclick="${u.activity_id ? `window.location='activity.html?id=${encodeURIComponent(u.activity_id)}'` : ''}" style="${u.activity_id ? 'cursor:pointer;' : ''}">
              <td>${escapeHtml(u.activity)}</td>
              <td class="activity-id">${u.activity_id ? escapeHtml(u.activity_id) : '—'}</td>
              <td>${u.actual_progress != null ? u.actual_progress + '%' : '—'}</td>
              <td class="text-faint">${u.updated ? new Date(u.updated).toLocaleString() : '—'}</td>
              <td>${u.confidence != null ? (u.confidence * 100).toFixed(0) + '%' : '—'}</td>
              <td><span class="badge ${statusBadgeClass(u.status)}">${escapeHtml(u.status)}</span></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}
