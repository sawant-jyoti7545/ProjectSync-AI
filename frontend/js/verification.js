/* ==========================================================================
   ProjectSync AI - Verification Queue logic
   ========================================================================== */

document.addEventListener('DOMContentLoaded', loadVerificationQueue);

async function loadVerificationQueue() {
  const root = document.getElementById('verification-root');
  renderLoading(root, 'Loading verification queue...');

  const result = await callApi('/verification');
  if (!result.ok) {
    renderError(root, result.error);
    return;
  }

  const items = result.data;
  if (!items || items.length === 0) {
    renderEmpty(root, 'Nothing pending. All matches are either high-confidence or already reviewed.');
    return;
  }

  root.innerHTML = items.map(item => `
    <div class="card" style="margin-bottom:16px;" id="verify-card-${item.match_id}">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:16px;">
        <div>
          <h3 style="margin-bottom:4px;">${escapeHtml(item.site_activity)}</h3>
          <p style="margin-bottom:2px;">
            <span class="text-faint">Possible match:</span>
            ${item.possible_scheduled_activity ? escapeHtml(item.possible_scheduled_activity) : '<span class="text-faint">None found</span>'}
          </p>
          <p style="margin-bottom:0;"><span class="text-faint">Reason:</span> ${escapeHtml(item.reason || 'Low confidence')}</p>
        </div>
        <span class="badge ${statusBadgeClass(item.match_status)}">${escapeHtml(item.match_status)}</span>
      </div>

      <div style="display:flex; gap:24px; margin:16px 0; font-size:13px;">
        <div><span class="text-faint">Confidence</span> <strong>${(item.confidence * 100).toFixed(0)}%</strong></div>
        <div><span class="text-faint">Planned</span> <strong>${item.planned_progress ?? '—'}${item.planned_progress != null ? '%' : ''}</strong></div>
        <div><span class="text-faint">Actual</span> <strong>${item.actual_progress ?? '—'}${item.actual_progress != null ? '%' : ''}</strong></div>
        <div><span class="text-faint">Variance</span> <strong>${item.variance != null ? item.variance + '%' : '—'}</strong></div>
      </div>

      <div style="display:flex; gap:10px;">
        <button class="btn btn-primary" onclick="handleVerificationAction(${item.match_id}, 'confirm')">✓ Confirm Match</button>
        <button class="btn btn-secondary" onclick="handleVerificationAction(${item.match_id}, 'reject')">✕ Reject Match</button>
      </div>
    </div>
  `).join('');
}

async function handleVerificationAction(matchId, action) {
  const card = document.getElementById(`verify-card-${matchId}`);
  const buttons = card.querySelectorAll('button');
  buttons.forEach(b => b.disabled = true);

  const result = await callApi(`/verification/${matchId}/${action}`, { method: 'POST' });

  if (!result.ok) {
    alert(`Failed to ${action}: ${result.error}`);
    buttons.forEach(b => b.disabled = false);
    return;
  }

  card.style.opacity = '0.5';
  card.innerHTML = `<p style="margin:0; color:${action === 'confirm' ? 'var(--green)' : 'var(--red)'};">
    ${action === 'confirm' ? '✓ Confirmed' : '✕ Rejected'}
  </p>`;

  // Refresh the whole queue shortly after so the list stays accurate.
  setTimeout(loadVerificationQueue, 800);
}
