/* ==========================================================================
   ProjectSync AI - Audit Trail logic
   ========================================================================== */

document.addEventListener('DOMContentLoaded', loadAuditLog);

async function loadAuditLog() {
  const root = document.getElementById('audit-root');
  renderLoading(root, 'Loading audit trail...');

  const result = await callApi('/audit-log');
  if (!result.ok) {
    renderError(root, result.error);
    return;
  }

  const logs = result.data;
  if (!logs || logs.length === 0) {
    renderEmpty(root, 'No events logged yet.');
    return;
  }

  root.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Action</th>
            <th>Activity</th>
            <th>User</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          ${logs.map(log => `
            <tr>
              <td class="text-faint mono" style="font-size:12.5px;">${log.timestamp ? new Date(log.timestamp).toLocaleString() : '—'}</td>
              <td>${escapeHtml(log.action)}</td>
              <td>${log.activity ? escapeHtml(log.activity) : '—'}</td>
              <td><span class="badge badge-neutral">${escapeHtml(log.user)}</span></td>
              <td class="text-muted">${log.details ? escapeHtml(log.details) : '—'}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}
