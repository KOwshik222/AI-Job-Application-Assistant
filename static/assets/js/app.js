/**
 * AI Job Application Assistant — Modern Frontend Orchestrator
 * High-performance state management, real-time polling, and glassmorphism UI updates.
 */

const API = '/api/v1';

const state = {
  userId: null,
  resumeId: null,
  runId: null,
  fileHash: null,
  pollTimer: null,
  currentStep: 1,
};

// --- Stepper Navigation Manager ---
function setStep(stepNum) {
  state.currentStep = stepNum;
  for (let i = 1; i <= 4; i++) {
    const indicator = document.getElementById(`indicatorStep${i}`);
    const line = document.getElementById(`line${i - 1}`);
    
    if (indicator) {
      indicator.classList.remove('active', 'done');
      if (i < stepNum) {
        indicator.classList.add('done');
      } else if (i === stepNum) {
        indicator.classList.add('active');
      }
    }
    
    if (line) {
      line.classList.remove('active', 'done');
      if (i <= stepNum) {
        line.classList.add(i < stepNum ? 'done' : 'active');
      }
    }
  }
}

// --- Notifications ---
function toast(msg, type = 'success') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  
  setTimeout(() => {
    el.classList.add('hide');
    setTimeout(() => el.remove(), 320);
  }, 4200);
}

function show(id) { 
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('hidden');
  el.classList.remove('fade-in');
  void el.offsetWidth;
  el.classList.add('fade-in');
}

function hide(id) { 
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden'); 
}

function setLoading(btnId, spinnerId, loading) {
  const btn = document.getElementById(btnId);
  const spinner = document.getElementById(spinnerId);
  if (btn) btn.disabled = loading;
  if (spinner) spinner.classList.toggle('hidden', !loading);
}

function parseList(val) {
  return (val || '').split(',').map(s => s.trim()).filter(Boolean);
}

function statusBadge(status) {
  const map = {
    SUCCESS: 'badge-success',
    ELIGIBLE: 'badge-success',
    QUEUED: 'badge-info',
    PENDING_MANUAL: 'badge-warning',
    MANUAL_ACTION_REQUIRED: 'badge-warning',
    NOT_MATCHED: 'badge-secondary',
    FAILED: 'badge-danger',
  };
  let label = status;
  if (status === 'SUCCESS') label = 'VERIFIED SUBMITTED';
  else if (status === 'ELIGIBLE') label = 'ELIGIBLE';
  else if (status === 'QUEUED') label = 'QUEUED';
  else if (status === 'MANUAL_ACTION_REQUIRED' || status === 'PENDING_MANUAL') label = 'MANUAL ACTION';
  else if (status === 'NOT_MATCHED') label = 'NOT MATCHED';
  
  return `<span class="badge ${map[status] || 'badge-secondary'}">${label}</span>`;
}

/**
 * Safely extract error message from response without consuming the body stream twice.
 */
async function extractErrorMessage(res, defaultMsg) {
  try {
    const text = await res.text();
    if (!text) return defaultMsg;
    try {
      const json = JSON.parse(text);
      if (typeof json.detail === 'string') return json.detail;
      if (Array.isArray(json.detail)) {
        return json.detail.map(d => (d.msg ? `${d.loc ? d.loc.slice(-1) + ': ' : ''}${d.msg}` : JSON.stringify(d))).join(', ');
      }
      if (json.error) return json.error;
      if (json.message) return json.message;
      if (json.reason) return json.reason;
    } catch {
      if (!text.trim().startsWith('<') && text.length < 250) {
        return text.trim();
      }
    }
  } catch {}
  return defaultMsg;
}

// --- Init & System Health Status ---
async function init() {
  setStep(1);
  try {
    const res = await fetch(`${API}/config`);
    if (!res.ok) throw new Error('API Offline');
    const cfg = await res.json();
    const badge = document.getElementById('modeBadge');
    
    if (cfg.demo_mode) {
      badge.textContent = 'DEMO MODE (Keyword Matcher)';
      badge.className = 'header-badge demo';
      badge.title = 'Demo mode active. Using keyword matching.';
    } else {
      const providerName = (cfg.llm_provider || 'AI').toUpperCase();
      badge.textContent = `LIVE PRODUCTION (${providerName})`;
      badge.className = 'header-badge live';
      badge.title = `Active LLM: ${providerName} · Tavily: ${cfg.tavily_configured ? 'Configured' : 'Missing'} · SMTP: ${cfg.smtp_configured ? 'Configured' : 'Local Log'}`;
    }
  } catch (err) {
    const badge = document.getElementById('modeBadge');
    if (badge) {
      badge.textContent = 'API OFFLINE';
      badge.className = 'header-badge demo';
    }
    toast('Cannot connect to backend API', 'error');
  }
}

// --- File Handling & Drag Drop ---
const fileInput = document.getElementById('resumeFile');
const fileDrop = document.getElementById('fileDrop');

if (fileInput) {
  fileInput.addEventListener('change', () => {
    const f = fileInput.files[0];
    const chip = document.getElementById('fileName');
    if (chip) {
      chip.innerHTML = f 
        ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path></svg> <span>${f.name}</span>`
        : '<span>No file selected</span>';
    }
  });
}

if (fileDrop) {
  ['dragenter', 'dragover'].forEach(eventName => {
    fileDrop.addEventListener(eventName, e => {
      e.preventDefault();
      e.stopPropagation();
      fileDrop.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach(eventName => {
    fileDrop.addEventListener(eventName, e => {
      e.preventDefault();
      e.stopPropagation();
      fileDrop.classList.remove('dragover');
    });
  });

  fileDrop.addEventListener('drop', e => {
    if (e.dataTransfer.files.length) {
      fileInput.files = e.dataTransfer.files;
      const f = e.dataTransfer.files[0];
      const chip = document.getElementById('fileName');
      if (chip) {
        chip.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path></svg> <span>${f.name}</span>`;
      }
    }
  });
}

const useSampleBtn = document.getElementById('useSampleBtn');
if (useSampleBtn) {
  useSampleBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/assets/sample_resume.pdf');
      if (!res.ok) throw new Error('Sample resume not found');
      const blob = await res.blob();
      const file = new File([blob], 'sample_resume.pdf', { type: 'application/pdf' });
      const dt = new DataTransfer();
      dt.items.add(file);
      fileInput.files = dt.files;
      
      const chip = document.getElementById('fileName');
      if (chip) {
        chip.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path></svg> <span>sample_resume.pdf</span>`;
      }
      toast('Sample resume loaded');
    } catch {
      toast('Sample resume not found', 'error');
    }
  });
}

// --- Upload Resume ---
const profileForm = document.getElementById('profileForm');
if (profileForm) {
  profileForm.addEventListener('submit', async e => {
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
        const errMsg = await extractErrorMessage(res, `Upload failed (${res.status})`);
        throw new Error(errMsg);
      }
      const data = await res.json();
      state.userId = data.user_id;
      state.resumeId = data.resume_id;
      state.fileHash = data.file_hash;

      const resumeInfoEl = document.getElementById('resumeInfo');
      if (resumeInfoEl) {
        resumeInfoEl.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
            <div>
              <span style="font-weight:700; color:#ffffff;">📄 ${file.name}</span>
              <span style="color:#94a3b8; font-size:0.85rem; margin-left:0.5rem;">(${data.chunks_indexed} vector chunks indexed)</span>
            </div>
            <span class="field-badge secure">Verified SHA-256</span>
          </div>
          <div style="margin-top:0.4rem;">
            <span style="font-size:0.78rem; color:#64748b;">ORIGINAL HASH:</span>
            <code>${data.file_hash || ''}</code>
          </div>
        `;
      }

      setStep(2);
      hide('stepProfile');
      show('stepSearch');
      toast(`Original Resume Indexed & Hash Verified (${data.chunks_indexed} chunks)`);
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setLoading('uploadBtn', 'uploadSpinner', false);
    }
  });
}

// --- Start Workflow ---
const startSearchBtn = document.getElementById('startSearchBtn');
if (startSearchBtn) {
  startSearchBtn.addEventListener('click', async () => {
    setLoading('startSearchBtn', 'searchSpinner', true);
    setStep(3);
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
        const errMsg = await extractErrorMessage(res, `Failed to start workflow (${res.status})`);
        throw new Error(errMsg);
      }
      const data = await res.json();
      state.runId = data.run_id;
      
      const statusEl = document.getElementById('statusText');
      if (statusEl) statusEl.textContent = 'Supervisor Agent coordinating targeted ATS discovery…';
      pollStatus();
    } catch (err) {
      toast(err.message, 'error');
      setStep(2);
      show('stepSearch');
      hide('stepProgress');
      setLoading('startSearchBtn', 'searchSpinner', false);
    }
  });
}

// --- Poll Workflow Status ---
function setPipelineStep(agent) {
  const steps = ['job_search', 'resume_match', 'application', 'notification'];
  const idx = steps.indexOf(agent);
  
  document.querySelectorAll('.pipeline-node').forEach(el => {
    const a = el.dataset.agent;
    const i = steps.indexOf(a);
    el.classList.remove('active', 'done');
    if (i < idx) el.classList.add('done');
    if (i === idx) el.classList.add('active');
  });
  
  const pct = Math.min(100, Math.max(15, ((idx + 1) / steps.length) * 100));
  const trackFill = document.getElementById('trackFill');
  if (trackFill) trackFill.style.width = `${pct}%`;
}

const statusMessages = {
  RUNNING: 'Autonomous AI Agents Active',
  COMPLETED: 'Workflow Completed Successfully',
  FAILED: 'Workflow Execution Stopped',
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
      if (data.applied_successfully > 0 || data.manual_action_required > 0 || data.failed > 0) setPipelineStep('notification');

      const statusEl = document.getElementById('statusText');
      if (statusEl) {
        statusEl.textContent = `${statusMessages[data.status] || data.status} · ${data.jobs_found} individual postings discovered · ${data.matched_jobs} passed match threshold (>= 75%)`;
      }

      if (data.status === 'COMPLETED' || data.status === 'FAILED') {
        clearInterval(state.pollTimer);
        await loadResults(data);
        setStep(4);
        hide('stepProgress');
        show('stepResults');
        setLoading('startSearchBtn', 'searchSpinner', false);
        if (data.status === 'FAILED') toast(data.errors?.[0] || 'Workflow failed', 'error');
        else toast('Workflow successfully completed!');
      }
    } catch { /* retry */ }
  }, 2000);
}

// --- Continue Paused Session ---
window.continueSession = async function(sessionId) {
  try {
    toast('Resuming application session in browser...');
    const res = await fetch(`${API}/applications/continue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ browser_session_id: sessionId }),
    });
    if (!res.ok) {
      const err = await extractErrorMessage(res, 'Failed to resume session');
      throw new Error(err);
    }
    const data = await res.json();
    if (data.status === 'SUCCESS') {
      toast(`Application verified and submitted for ${data.company || 'job'}!`);
    } else if (data.status === 'MANUAL_ACTION_REQUIRED') {
      toast(`Action still required: ${data.reason}`, 'warning');
    } else {
      toast(`Application could not be completed: ${data.reason}`, 'error');
    }
    
    // Refresh results
    if (state.runId) {
      const summaryRes = await fetch(`${API}/application-summary?run_id=${state.runId}`);
      if (summaryRes.ok) {
        const summaryData = await summaryRes.json();
        await loadResults(summaryData);
      }
    }
  } catch (err) {
    toast(err.message, 'error');
  }
};

// --- Load Results & Update Executive Dashboard ---
async function loadResults(summary) {
  const statApplied = document.getElementById('statApplied');
  const statManual = document.getElementById('statManual');
  const statFailed = document.getElementById('statFailed');
  const statMatched = document.getElementById('statMatched');

  if (statApplied) statApplied.textContent = summary.applied_successfully || 0;
  if (statManual) statManual.textContent = summary.manual_action_required || 0;
  if (statFailed) statFailed.textContent = summary.failed || 0;
  if (statMatched) statMatched.textContent = summary.matched_jobs || 0;

  const banner = document.getElementById('emailBanner');
  if (banner) {
    banner.classList.remove('hidden', 'success', 'warning', 'error');
    if (summary.email_sent) {
      banner.classList.add('success');
      banner.innerHTML = `✅ Full application summary email dispatched to <strong>${document.getElementById('email').value}</strong>.`;
    } else if (summary.email_status === 'NOT_CONFIGURED') {
      banner.classList.add('warning');
      banner.innerHTML = `
        ⚠️ <strong>Email saved locally</strong> — SMTP credentials not configured in .env.
        ${summary.email_log_url ? ` <a href="${summary.email_log_url}" target="_blank" style="color:#a5b4fc;text-decoration:underline;margin-left:8px;font-weight:600;">Open Saved HTML Report ↗</a>` : ''}
      `;
    } else if (summary.email_status === 'FAILED') {
      banner.classList.add('error');
      banner.innerHTML = `
        ❌ <strong>Email dispatch issue:</strong> ${summary.email_note || 'Unknown error'}
        ${summary.email_log_url ? ` · <a href="${summary.email_log_url}" target="_blank" style="color:#fca5a5;text-decoration:underline;">View saved report ↗</a>` : ''}
      `;
    } else {
      banner.classList.add('warning');
      banner.innerHTML = summary.email_note || 'Summary ready.';
    }
  }

  // Applications table
  try {
    const res = await fetch(`${API}/applications?user_id=${state.userId}`);
    if (res.ok) {
      const data = await res.json();
      const tbody = document.getElementById('applicationsTable');
      if (tbody) {
        if (!data.applications || data.applications.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No applications processed in this batch</td></tr>';
        } else {
          tbody.innerHTML = data.applications.map(a => {
            const scoreClass = (a.match_score >= 75) ? 'high' : 'mid';
            return `
              <tr>
                <td><strong style="color:#ffffff; font-weight:700;">${a.company}</strong></td>
                <td>
                  <span style="font-weight:600; color:#f1f5f9;">${a.job_title}</span>
                  ${a.error ? `<br><span style="color:#f87171; font-size:0.75rem; margin-top:4px; display:inline-block;">⚠️ ${a.error}</span>` : ''}
                </td>
                <td>${statusBadge(a.status)}</td>
                <td><span class="score-pill ${scoreClass}">${a.match_score ?? '—'}%</span></td>
                <td>
                  ${a.job_url 
                    ? `<a href="${a.job_url}" target="_blank" rel="noopener" class="btn-ghost-sm" style="font-size:0.75rem; padding:0.25rem 0.6rem;">Visit ATS ↗</a>` 
                    : '—'}
                </td>
                <td style="color:#94a3b8; font-size:0.8rem; font-family:'JetBrains Mono', monospace;">
                  ${a.applied_at ? new Date(a.applied_at).toLocaleTimeString() : '—'}
                </td>
              </tr>
            `;
          }).join('');
        }
      }
    }
  } catch (err) { 
    toast('Could not load applications list', 'error');
  }

  // Manual actions container
  const manualList = document.getElementById('manualList');
  if (manualList) {
    if (!summary.pending_manual_jobs || summary.pending_manual_jobs.length === 0) {
      manualList.innerHTML = `
        <div class="empty-state-card">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
          <p>No human intervention required. All qualifying applications processed autonomously.</p>
        </div>
      `;
    } else {
      manualList.innerHTML = summary.pending_manual_jobs.map(j => `
        <div class="manual-item-card">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <h4>${j.company}</h4>
            <span class="badge badge-warning">Action Required</span>
          </div>
          <p class="manual-reason"><strong>Reason:</strong> ${j.reason}</p>
          <div class="manual-action-btns">
            <a href="${j.job_url}" target="_blank" rel="noopener" class="btn btn-secondary" style="font-size:0.82rem; padding:0.45rem 0.95rem;">
              Open ATS Directly ↗
            </a>
            ${j.browser_session_id ? `
              <button class="btn btn-primary" onclick="continueSession('${j.browser_session_id}')" style="font-size:0.82rem; padding:0.45rem 0.95rem;">
                ⚡ Resume Application Session
              </button>
            ` : ''}
          </div>
        </div>
      `).join('');
    }
  }
}

// --- Tab Controller ---
document.querySelectorAll('.tab-btn').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content-panel').forEach(p => p.classList.remove('active'));
    
    tab.classList.add('active');
    const panelId = `tab${tab.dataset.tab.charAt(0).toUpperCase() + tab.dataset.tab.slice(1)}`;
    const panel = document.getElementById(panelId);
    if (panel) panel.classList.add('active');
  });
});

// --- Start New Run ---
const newRunBtn = document.getElementById('newRunBtn');
if (newRunBtn) {
  newRunBtn.addEventListener('click', () => {
    setStep(2);
    hide('stepResults');
    show('stepSearch');
    state.runId = null;
  });
}

// Initialize on page load
init();
