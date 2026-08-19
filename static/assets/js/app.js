const API = '/api/v1';

const state = {
  userId: null,
  resumeId: null,
  runId: null,
  fileHash: null,
  pollTimer: null,
};

// --- Utils ---
function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toastContainer').appendChild(el);
  setTimeout(() => {
    el.classList.add('hide');
    setTimeout(() => el.remove(), 300);
  }, 4000);
}

function show(id) { 
  const el = document.getElementById(id);
  el.classList.remove('hidden');
  // Re-trigger animation
  el.classList.remove('fade-in');
  void el.offsetWidth;
  el.classList.add('fade-in');
}
function hide(id) { document.getElementById(id).classList.add('hidden'); }

function setLoading(btnId, spinnerId, loading) {
  const btn = document.getElementById(btnId);
  const spinner = document.getElementById(spinnerId);
  btn.disabled = loading;
  spinner.classList.toggle('hidden', !loading);
}

function parseList(val) {
  return val.split(',').map(s => s.trim()).filter(Boolean);
}

function statusBadge(status) {
  const map = {
    SUCCESS: 'badge-success',
    PENDING_MANUAL: 'badge-warning',
    FAILED: 'badge-danger',
  };
  return `<span class="badge ${map[status] || ''}">${status}</span>`;
}

// --- Init ---
async function init() {
  try {
    const res = await fetch(`${API}/config`);
    if (!res.ok) throw new Error('API Offline');
    const cfg = await res.json();
    const badge = document.getElementById('modeBadge');
    if (!cfg.demo_mode) {
      badge.textContent = 'Live Mode';
      badge.classList.add('live');
    } else if (cfg.tavily_configured || cfg.smtp_configured) {
      badge.textContent = `Live Search + Email`;
      badge.classList.add('live');
    } else {
      badge.textContent = 'Demo Mode (no API keys)';
      badge.classList.add('demo');
    }
  } catch (err) {
    document.getElementById('modeBadge').textContent = 'API Offline';
    toast('Cannot connect to backend API', 'error');
  }
}

// --- File handling ---
const fileInput = document.getElementById('resumeFile');
const fileDrop = document.getElementById('fileDrop');

fileInput.addEventListener('change', () => {
  const f = fileInput.files[0];
  document.getElementById('fileName').textContent = f ? f.name : 'No file selected';
});

fileDrop.addEventListener('dragover', e => { e.preventDefault(); fileDrop.classList.add('dragover'); });
fileDrop.addEventListener('dragleave', () => fileDrop.classList.remove('dragover'));
fileDrop.addEventListener('drop', e => {
  e.preventDefault();
  fileDrop.classList.remove('dragover');
  if (e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    document.getElementById('fileName').textContent = e.dataTransfer.files[0].name;
  }
});

document.getElementById('useSampleBtn').addEventListener('click', async () => {
  try {
    const res = await fetch('/assets/sample_resume.pdf');
    if (!res.ok) throw new Error('Not found');
    const blob = await res.blob();
    const file = new File([blob], 'sample_resume.pdf', { type: 'application/pdf' });
    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;
    document.getElementById('fileName').textContent = 'sample_resume.pdf';
    toast('Sample resume loaded');
  } catch {
    toast('Sample resume not found', 'error');
  }
});

// --- Upload ---
document.getElementById('profileForm').addEventListener('submit', async e => {
  e.preventDefault();
  const file = fileInput.files[0];
  if (!file) { toast('Please select a resume PDF', 'error'); return; }

  setLoading('uploadBtn', 'uploadSpinner', true);
  const formData = new FormData();
  formData.append('file', file);
  formData.append('email', document.getElementById('email').value);

  try {
    const res = await fetch(`${API}/upload-resume`, { method: 'POST', body: formData });
    if (!res.ok) {
      let errMsg = `Upload failed (${res.status})`;
      try { const err = await res.json(); errMsg = err.detail || errMsg; } catch { errMsg = await res.text() || errMsg; }
      throw new Error(errMsg);
    }
    const data = await res.json();
    state.userId = data.user_id;
    state.resumeId = data.resume_id;
    state.fileHash = data.file_hash;

    document.getElementById('resumeInfo').innerHTML =
      `Resume uploaded: <strong>${file.name}</strong> · ${data.chunks_indexed} chunks indexed · Hash: <code>${data.file_hash.slice(0, 12)}…</code>`;

    hide('stepProfile');
    show('stepSearch');
    toast(`Resume indexed (${data.chunks_indexed} chunks)`);
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    setLoading('uploadBtn', 'uploadSpinner', false);
  }
});

// --- Start workflow ---
document.getElementById('startSearchBtn').addEventListener('click', async () => {
  setLoading('startSearchBtn', 'searchSpinner', true);
  hide('stepSearch');
  show('stepProgress');
  setPipelineStep('job_search');

  const body = {
    user_id: state.userId,
    resume_id: state.resumeId,
    full_name: document.getElementById('fullName').value,
    phone: document.getElementById('phone').value,
    role: document.getElementById('role').value,
    skills: parseList(document.getElementById('skills').value),
    experience: parseInt(document.getElementById('experience').value, 10),
    locations: parseList(document.getElementById('locations').value),
    email: document.getElementById('email').value,
  };

  try {
    const res = await fetch(`${API}/start-job-search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let errMsg = `Failed to start workflow (${res.status})`;
      try { const err = await res.json(); errMsg = err.detail || errMsg; } catch { errMsg = await res.text() || errMsg; }
      throw new Error(errMsg);
    }
    const data = await res.json();
    state.runId = data.run_id;
    document.getElementById('statusText').textContent = 'Supervisor agent routing to job search…';
    pollStatus();
  } catch (err) {
    toast(err.message, 'error');
    show('stepSearch');
    hide('stepProgress');
    setLoading('startSearchBtn', 'searchSpinner', false);
  }
});

// --- Poll workflow status ---
function setPipelineStep(agent) {
  const steps = ['job_search', 'resume_match', 'application', 'notification'];
  const idx = steps.indexOf(agent);
  document.querySelectorAll('.pipeline-step').forEach(el => {
    const a = el.dataset.agent;
    const i = steps.indexOf(a);
    el.classList.remove('active', 'done');
    if (i < idx) el.classList.add('done');
    if (i === idx) el.classList.add('active');
  });
  const pct = ((idx + 1) / steps.length) * 100;
  document.getElementById('progressFill').style.width = `${pct}%`;
}

const statusMessages = {
  RUNNING: 'Agents working…',
  COMPLETED: 'Workflow complete!',
  FAILED: 'Workflow failed',
};

function pollStatus() {
  if (state.pollTimer) clearInterval(state.pollTimer);

  state.pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`${API}/application-summary?run_id=${state.runId}`);
      if (!res.ok) return;
      const data = await res.json();

      if (data.jobs_found > 0) setPipelineStep('resume_match');
      if (data.matched_jobs > 0) setPipelineStep('application');
      if (data.applied_successfully > 0 || data.manual_action_required > 0) setPipelineStep('notification');

      document.getElementById('statusText').textContent =
        `${statusMessages[data.status] || data.status} · ${data.jobs_found} jobs found · ${data.matched_jobs} matched`;

      if (data.status === 'COMPLETED' || data.status === 'FAILED') {
        clearInterval(state.pollTimer);
        await loadResults(data);
        hide('stepProgress');
        show('stepResults');
        setLoading('startSearchBtn', 'searchSpinner', false);
        if (data.status === 'FAILED') toast(data.errors?.[0] || 'Workflow failed', 'error');
        else toast('Workflow completed!');
      }
    } catch { /* retry */ }
  }, 2000);
}

// --- Results ---
async function loadResults(summary) {
  document.getElementById('statApplied').textContent = summary.applied_successfully;
  document.getElementById('statManual').textContent = summary.manual_action_required;
  document.getElementById('statFailed').textContent = summary.failed;
  document.getElementById('statMatched').textContent = summary.matched_jobs;

  const banner = document.getElementById('emailBanner');
  banner.classList.remove('hidden', 'success', 'warning', 'error');
  if (summary.email_sent) {
    banner.classList.add('success');
    banner.innerHTML = `✅ Email summary sent to your inbox.`;
  } else if (summary.email_status === 'NOT_CONFIGURED') {
    banner.classList.add('warning');
    banner.innerHTML = `
      ⚠️ <strong>Email not sent</strong> — SMTP is not configured.
      ${summary.email_log_url ? ` <a href="${summary.email_log_url}" target="_blank">View summary in browser</a>` : ''}
      <br><small>To receive real emails, add SMTP settings to <code>.env</code> (see README).</small>
    `;
  } else if (summary.email_status === 'FAILED') {
    banner.classList.add('error');
    banner.innerHTML = `
      ❌ <strong>Email failed:</strong> ${summary.email_note || 'Unknown error'}
      ${summary.email_log_url ? ` · <a href="${summary.email_log_url}" target="_blank">View saved summary</a>` : ''}
    `;
  } else {
    banner.classList.add('warning');
    banner.innerHTML = summary.email_note || 'Email status unknown.';
  }

  // Applications table
  try {
    const res = await fetch(`${API}/applications?user_id=${state.userId}`);
    const data = await res.json();
    const tbody = document.getElementById('applicationsTable');
    if (data.applications.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">No applications yet</td></tr>';
    } else {
      tbody.innerHTML = data.applications.map(a => `
        <tr>
          <td>${a.company}</td>
          <td>${a.job_title}</td>
          <td>
            ${statusBadge(a.status)}
            ${a.error ? `<br><small class="text-danger" style="margin-top:4px;display:inline-block;">${a.error}</small>` : ''}
          </td>
          <td>${a.match_score ?? '—'}</td>
          <td>${a.applied_at ? new Date(a.applied_at).toLocaleString() : '—'}</td>
        </tr>
      `).join('');
    }
  } catch (err) { 
    toast('Could not load applications list', 'error');
  }

  // Manual actions
  const manualList = document.getElementById('manualList');
  if (summary.pending_manual_jobs.length === 0) {
    manualList.innerHTML = '<p class="empty">No manual actions required</p>';
  } else {
    manualList.innerHTML = summary.pending_manual_jobs.map(j => `
      <div class="manual-item">
        <h4>${j.company}</h4>
        <p>Reason: ${j.reason}</p>
        <a href="${j.job_url}" target="_blank" rel="noopener">${j.job_url}</a>
      </div>
    `).join('');
  }
}

// --- Tabs ---
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`tab${tab.dataset.tab.charAt(0).toUpperCase() + tab.dataset.tab.slice(1)}`).classList.add('active');
  });
});

// --- New run ---
document.getElementById('newRunBtn').addEventListener('click', () => {
  hide('stepResults');
  show('stepSearch');
  state.runId = null;
});

init();
