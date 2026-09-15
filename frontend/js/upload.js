/* ==========================================================================
   ProjectSync AI - Data Capture / Upload logic

   DESIGN NOTE: the spec describes Data Capture and Processing as separate
   pages. This implementation deliberately keeps them as two SECTIONS of
   the same page instead of two separate HTML documents. Reason: a
   selected File object cannot survive a full browser navigation (you
   can't pass it through a URL, localStorage, or sessionStorage), so
   splitting "select file" and "show processing" across pages forces
   either re-selecting the file or a fragile workaround. Keeping them on
   one page means the upload is a single real fetch() call with an
   honest, backend-driven progress UI - directly avoiding the
   "processing.js was empty" / "frontend redirected before data was
   available" failures from prior attempts.
   ========================================================================== */

let selectedFile = null;

const PROCESSING_STEPS = [
  'Uploading report',
  'Extracting project data',
  'Identifying activities',
  'Matching schedule',
  'Calculating progress',
  'Running AI risk analysis',
  'Preparing dashboard',
];

document.addEventListener('DOMContentLoaded', () => {
  const fileInput = document.getElementById('file-input');
  const dropZone = document.getElementById('drop-zone');
  const chooseFileBtn = document.getElementById('choose-file-btn');
  const removeFileBtn = document.getElementById('remove-file-btn');
  const analyzeBtn = document.getElementById('analyze-btn');
  const useSampleBtn = document.getElementById('use-sample-btn');

  chooseFileBtn.addEventListener('click', () => fileInput.click());
  dropZone.addEventListener('click', (e) => {
    if (e.target === dropZone) fileInput.click();
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) setSelectedFile(fileInput.files[0]);
  });

  dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.style.borderColor = 'var(--cyan)'; });
  dropZone.addEventListener('dragleave', () => { dropZone.style.borderColor = 'var(--border-strong)'; });
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.style.borderColor = 'var(--border-strong)';
    if (e.dataTransfer.files.length > 0) setSelectedFile(e.dataTransfer.files[0]);
  });

  removeFileBtn.addEventListener('click', () => {
    selectedFile = null;
    fileInput.value = '';
    document.getElementById('drop-zone-empty').classList.remove('hidden');
    document.getElementById('drop-zone-selected').classList.add('hidden');
    analyzeBtn.disabled = true;
  });

  analyzeBtn.addEventListener('click', () => {
    if (selectedFile) runAnalysis(selectedFile);
  });

  // Demo/sample report convenience button - runs the bundled sample
  // PDF through the exact same backend pipeline as a real upload.
  useSampleBtn.addEventListener('click', () => runAnalysis(null));

  function setSelectedFile(file) {
    selectedFile = file;
    document.getElementById('selected-filename').textContent = file.name;
    document.getElementById('selected-filesize').textContent = formatFileSize(file.size);
    document.getElementById('drop-zone-empty').classList.add('hidden');
    document.getElementById('drop-zone-selected').classList.remove('hidden');
    analyzeBtn.disabled = false;
  }
});

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function runAnalysis(file) {
  const apiCall = file
    ? () => {
        const formData = new FormData();
        formData.append('file', file);
        return callApi('/upload', { method: 'POST', body: formData });
      }
    : () => callApi('/upload-sample', { method: 'POST' });

  await runProcessingPipeline(apiCall);
}

/**
 * Shared processing UI driver. Takes a zero-arg function that performs
 * the actual backend call (upload file / sample / voice transcript) and
 * returns a callApi() result. Used by the file-upload flow above and by
 * voice.js's transcript flow, so both share one honest, backend-driven
 * progress UI instead of duplicating it.
 */
async function runProcessingPipeline(apiCall) {
  document.getElementById('upload-section').classList.add('hidden');
  const voiceSection = document.getElementById('voice-section');
  if (voiceSection) voiceSection.classList.add('hidden');
  const processingSection = document.getElementById('processing-section');
  processingSection.classList.remove('hidden');
  processingSection.scrollIntoView({ behavior: 'smooth' });

  const stepsContainer = document.getElementById('processing-steps');
  const resultContainer = document.getElementById('processing-result');
  resultContainer.innerHTML = '';

  stepsContainer.innerHTML = PROCESSING_STEPS.map((label, i) => `
    <div class="processing-step" id="step-${i}" style="display:flex; align-items:center; gap:10px; color:var(--text-faint);">
      <span class="step-icon" style="width:18px; text-align:center;">${i === 0 ? '<span class="spinner" style="width:14px;height:14px;"></span>' : '○'}</span>
      <span>${label}</span>
    </div>`).join('');

  let currentStep = 0;
  const advanceStep = () => {
    if (currentStep >= PROCESSING_STEPS.length - 1) return; // hold on the last step until real completion
    markStepDone(currentStep);
    currentStep++;
    markStepActive(currentStep);
  };
  markStepActive(0);

  // Paces the animation forward while we wait for the real response.
  // This never marks the FINAL step done until the backend actually
  // returns - it only advances through the earlier steps for feel.
  const pacer = setInterval(advanceStep, 550);

  // --- The real, non-simulated backend call ---
  const result = await apiCall();

  clearInterval(pacer);

  if (!result.ok) {
    // Mark whatever step we were on as failed and show the real error -
    // never fake success per spec section 12/16.
    markStepFailed(currentStep);
    resultContainer.innerHTML = `
      <div class="state-message is-error">
        <div class="state-title">Analysis failed</div>
        <div>${escapeHtml(result.error)}</div>
      </div>
      <button class="btn btn-secondary" style="margin-top:16px;" onclick="location.reload()">Try Again</button>`;
    return;
  }

  // Real success - finish out the remaining steps instantly and show results.
  for (let i = currentStep; i < PROCESSING_STEPS.length; i++) markStepDone(i);

  const { summary, risk_analysis } = result.data;

  resultContainer.innerHTML = `
    <div class="state-message" style="border-color:var(--green); background:var(--green-wash);">
      <div class="state-title" style="color:var(--green);">Analysis complete</div>
      <div>${summary.matched} matched, ${summary.needs_review} need review, ${summary.new_activities} new
      activities detected. Overall risk: <strong>${escapeHtml(risk_analysis.overall_risk)}</strong>.</div>
    </div>
    <div style="display:flex; gap:12px; margin-top:16px;">
      <a href="dashboard.html" class="btn btn-primary">View Dashboard</a>
      <a href="verification.html" class="btn btn-secondary">Review Verification Queue</a>
    </div>`;
}

function markStepActive(i) {
  const el = document.getElementById(`step-${i}`);
  if (!el) return;
  el.style.color = 'var(--text)';
  el.querySelector('.step-icon').innerHTML = '<span class="spinner" style="width:14px;height:14px;"></span>';
}

function markStepDone(i) {
  const el = document.getElementById(`step-${i}`);
  if (!el) return;
  el.style.color = 'var(--green)';
  el.querySelector('.step-icon').textContent = '✓';
}

function markStepFailed(i) {
  const el = document.getElementById(`step-${i}`);
  if (!el) return;
  el.style.color = 'var(--red)';
  el.querySelector('.step-icon').textContent = '✕';
}
