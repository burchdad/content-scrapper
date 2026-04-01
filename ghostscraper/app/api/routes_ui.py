from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"])


@router.get("/ui/agent", response_class=HTMLResponse)
async def agent_console() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GhostScraper Agent Console</title>
  <style>
    :root {
      --bg: #f2eee7;
      --panel: #fffdf8;
      --ink: #151310;
      --muted: #6f665d;
      --accent: #1f7a6f;
      --accent2: #c14f2d;
      --line: rgba(21, 19, 16, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      color: var(--ink);
      background: linear-gradient(145deg, #efe9df, #f7f2ea);
      min-height: 100vh;
    }
    .shell {
      display: grid;
      grid-template-columns: 340px 1fr;
      gap: 16px;
      max-width: 1500px;
      margin: 0 auto;
      padding: 20px;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--panel);
      overflow: hidden;
    }
    .head {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }
    .head h2 { margin: 0; font-size: 0.95rem; letter-spacing: 0.08em; text-transform: uppercase; }
    .body { padding: 14px; display: grid; gap: 10px; }
    .stack { display: grid; gap: 8px; }
    .history-list {
      max-height: 420px;
      overflow: auto;
      padding-right: 4px;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px;
      background: #fff;
    }
    input, textarea, select, button {
      width: 100%;
      font: inherit;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      background: #fff;
      color: var(--ink);
    }
    textarea { min-height: 100px; resize: vertical; }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .row { display: flex; gap: 8px; align-items: center; }
    .row input[type="checkbox"] { width: auto; }
    button { cursor: pointer; }
    .primary { background: var(--accent); color: #fff; border-color: transparent; }
    .secondary { background: var(--accent2); color: #fff; border-color: transparent; }
    .muted { color: var(--muted); font-size: 0.9rem; }
    .export-links a, .case-links a {
      color: var(--accent);
      text-decoration: none;
      display: block;
      margin: 6px 0;
      word-break: break-word;
    }
    .pill {
      display: inline-block;
      border-radius: 999px;
      padding: 2px 8px;
      border: 1px solid var(--line);
      font-size: 0.8rem;
      color: var(--muted);
      margin-left: 6px;
    }
    .badge {
      display: inline-block;
      border-radius: 999px;
      padding: 2px 8px;
      border: 1px solid var(--line);
      font-size: 0.75rem;
      margin-right: 6px;
    }
    .badge.ok {
      background: rgba(31, 122, 111, 0.12);
      border-color: rgba(31, 122, 111, 0.35);
      color: #16534c;
    }
    .badge.warn {
      background: rgba(193, 79, 45, 0.12);
      border-color: rgba(193, 79, 45, 0.35);
      color: #8e381f;
    }
    @media (max-width: 980px) {
      .shell { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="panel">
      <div class="head"><h2>Presets & History</h2></div>
      <div class="body">
        <div class="stack">
          <label>User</label>
          <input id="userId" value="default" />
          <button id="loadBtn">Load</button>
        </div>
        <div class="stack">
          <h3 style="margin:0;font-size:0.95rem;">Saved Presets</h3>
          <div id="presetList" class="stack"></div>
        </div>
        <div class="stack">
          <h3 style="margin:0;font-size:0.95rem;">Request History</h3>
          <div id="historyList" class="stack history-list"></div>
          <button id="historyMoreBtn" type="button">Load More</button>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="head"><h2>Agent Console</h2></div>
      <div class="body">
        <label>Label</label>
        <input id="labelInput" placeholder="Campaign scrape" />
        <label>Query</label>
        <textarea id="queryInput" placeholder="Describe your request"></textarea>
        <label>Desired Fields (comma separated)</label>
        <input id="fieldsInput" placeholder="title,image_urls,video_urls,social_links" />
        <label>Source Packs</label>
        <select id="sourcePackSelect" multiple size="10"></select>
        <div class="muted" id="sourcePackMeta">Loading curated public-source packs...</div>
        <div class="grid2">
          <div>
            <label>Mode</label>
            <select id="modeSelect">
              <option value="auto">auto</option>
              <option value="static">static</option>
              <option value="dynamic">dynamic</option>
            </select>
          </div>
          <div>
            <label>Max Pages</label>
            <input id="maxPagesInput" type="number" min="1" max="100" value="10" />
          </div>
        </div>
        <div class="row"><input id="matureToggle" type="checkbox" /><label for="matureToggle">Include mature-content discovery</label></div>
        <div class="row"><input id="asyncToggle" type="checkbox" checked /><label for="asyncToggle">Run async</label></div>
        <div class="grid2">
          <button class="primary" id="runBtn">Run Request</button>
          <button id="savePresetBtn">Save Preset</button>
        </div>
        <button class="secondary" id="saveSafetyPresetBtn">Save Safety Preset</button>
        <div class="muted" id="statusMsg"></div>

        <div class="card">
          <h3 style="margin-top:0;">Safety Persona</h3>
          <div id="personaPane" class="stack muted">Loading safety persona...</div>
        </div>

        <div class="card">
          <h3 style="margin-top:0;">Case Board</h3>
          <div class="grid2">
            <select id="caseApprovalFilter">
              <option value="all">all approvals</option>
              <option value="approved">approved only</option>
              <option value="pending">pending only</option>
            </select>
            <input id="caseChannelFilter" placeholder="channel filter (optional)" />
          </div>
          <div class="grid2">
            <button id="applyCaseFiltersBtn">Apply Case Filters</button>
            <button id="downloadCaseCsvBtn">Download Case CSV</button>
          </div>
          <div class="grid2">
            <button id="bulkReviewBtn">Bulk Mark Human Review</button>
            <button class="secondary" id="bulkApproveBtn">Bulk Approve</button>
          </div>
          <div id="caseList" class="case-links"></div>
        </div>

        <div class="card">
          <h3 style="margin-top:0;">Export Center</h3>
          <div id="exportLinks" class="export-links"></div>
        </div>

        <div class="card">
          <h3 style="margin-top:0;">Result Preview</h3>
          <div id="previewPane" class="stack muted">Run or load a completed job to preview extracted images and videos.</div>
        </div>
      </div>
    </section>
  </div>

  <script>
    const ui = {
      userId: document.getElementById('userId'),
      loadBtn: document.getElementById('loadBtn'),
      presetList: document.getElementById('presetList'),
      historyList: document.getElementById('historyList'),
      historyMoreBtn: document.getElementById('historyMoreBtn'),
      labelInput: document.getElementById('labelInput'),
      queryInput: document.getElementById('queryInput'),
      fieldsInput: document.getElementById('fieldsInput'),
      sourcePackSelect: document.getElementById('sourcePackSelect'),
      sourcePackMeta: document.getElementById('sourcePackMeta'),
      modeSelect: document.getElementById('modeSelect'),
      maxPagesInput: document.getElementById('maxPagesInput'),
      matureToggle: document.getElementById('matureToggle'),
      asyncToggle: document.getElementById('asyncToggle'),
      runBtn: document.getElementById('runBtn'),
      savePresetBtn: document.getElementById('savePresetBtn'),
      saveSafetyPresetBtn: document.getElementById('saveSafetyPresetBtn'),
      statusMsg: document.getElementById('statusMsg'),
      personaPane: document.getElementById('personaPane'),
      caseApprovalFilter: document.getElementById('caseApprovalFilter'),
      caseChannelFilter: document.getElementById('caseChannelFilter'),
      applyCaseFiltersBtn: document.getElementById('applyCaseFiltersBtn'),
      downloadCaseCsvBtn: document.getElementById('downloadCaseCsvBtn'),
      bulkReviewBtn: document.getElementById('bulkReviewBtn'),
      bulkApproveBtn: document.getElementById('bulkApproveBtn'),
      caseList: document.getElementById('caseList'),
      exportLinks: document.getElementById('exportLinks'),
      previewPane: document.getElementById('previewPane'),
    };

    let lastJobId = null;
    let lastJobStatus = null;
    let sourcePacks = [];
    let historyOffset = 0;
    const historyPageSize = 10;
    const selectedCaseIds = new Set();

    function parseFields(raw) {
      return raw.split(',').map(v => v.trim()).filter(Boolean);
    }

    function buildRequest() {
      return {
        query: ui.queryInput.value.trim(),
        mode: ui.modeSelect.value,
        max_pages: Number(ui.maxPagesInput.value || 10),
        include_images: true,
        include_videos: true,
        include_mature_content: ui.matureToggle.checked,
        use_search_discovery: true,
        desired_fields: parseFields(ui.fieldsInput.value),
        source_pack_ids: getSelectedPackIds(),
      };
    }

    function getSelectedPackIds() {
      return Array.from(ui.sourcePackSelect.selectedOptions).map(option => option.value);
    }

    async function loadSourcePacks() {
      sourcePacks = await api('/api/v1/source-packs');
      ui.sourcePackSelect.innerHTML = sourcePacks.map(pack => (
        `<option value="${escapeHtml(pack.pack_id)}">${escapeHtml(pack.name)} · ${escapeHtml(pack.category)}</option>`
      )).join('');
      ui.sourcePackMeta.textContent = `${sourcePacks.length} curated packs available. Selected packs feed search scoping and curated fallback URLs.`;
      return sourcePacks;
    }

    function setSelectedPackIds(packIds) {
      const selected = new Set(packIds || []);
      Array.from(ui.sourcePackSelect.options).forEach(option => {
        option.selected = selected.has(option.value);
      });
    }

    async function api(path, options = {}) {
      const res = await fetch(path, {
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
      return body;
    }

    async function loadPresets() {
      const user = encodeURIComponent(ui.userId.value.trim() || 'default');
      const presets = await api(`/api/v1/agent/presets?user_id=${user}`);
      ui.presetList.innerHTML = presets.length ? '' : '<div class="muted">No presets yet.</div>';
      presets.forEach(p => {
        const el = document.createElement('div');
        el.className = 'card';
        el.innerHTML = `<strong>${escapeHtml(p.name)}</strong><div class="muted">${escapeHtml(p.request.query)}</div>`;
        const row = document.createElement('div');
        row.className = 'row';
        const useBtn = document.createElement('button');
        useBtn.textContent = 'Use';
        useBtn.onclick = () => hydrateFromRequest(p.request, p.name);
        const delBtn = document.createElement('button');
        delBtn.textContent = 'Delete';
        delBtn.onclick = async () => {
          await api(`/api/v1/agent/presets/${p.preset_id}?user_id=${user}`, { method: 'DELETE' });
          await loadPresets();
        };
        row.appendChild(useBtn);
        row.appendChild(delBtn);
        el.appendChild(row);
        ui.presetList.appendChild(el);
      });
      return presets;
    }

    async function loadHistory(reset = true) {
      const user = encodeURIComponent(ui.userId.value.trim() || 'default');
      if (reset) {
        historyOffset = 0;
        ui.historyList.innerHTML = '';
      }
      const history = await api(`/api/v1/agent/history?user_id=${user}&limit=${historyPageSize}&offset=${historyOffset}`);

      if (reset && !history.length) {
        ui.historyList.innerHTML = '<div class="muted">No history yet.</div>';
      }

      history.forEach(item => {
        const el = document.createElement('div');
        el.className = 'card';
        el.innerHTML = `<strong>${escapeHtml(item.label)}</strong><div class="muted">job: ${escapeHtml(item.job_id || '-')}</div>`;
        const row = document.createElement('div');
        row.className = 'row';
        const rerunBtn = document.createElement('button');
        rerunBtn.textContent = 'Rerun';
        rerunBtn.onclick = async () => {
          const body = await api(`/api/v1/agent/history/${item.history_id}/rerun?user_id=${user}&run_async=${ui.asyncToggle.checked}`, { method: 'POST' });
          onJobCreated(body.job_id, 'rerun submitted');
          await loadHistory();
        };
        const useBtn = document.createElement('button');
        useBtn.textContent = 'Load';
        useBtn.onclick = async () => {
          hydrateFromRequest(item.request, item.label);
          if (item.job_id) {
            onJobCreated(item.job_id, 'history loaded');
            await syncJobStatus(item.job_id, false);
            ui.statusMsg.textContent = `Loaded history request and bound exports to ${item.job_id} (${lastJobStatus || 'unknown'})`;
          } else {
            renderPreviewPlaceholder('Loaded request has no linked job yet.');
            ui.statusMsg.textContent = 'Loaded history request (no linked job ID).';
          }
        };
        const delBtn = document.createElement('button');
        delBtn.textContent = 'Delete';
        delBtn.style.cssText = 'background:#c0392b;border-color:#c0392b;';
        delBtn.onclick = async () => {
          if (!confirm('Delete this history entry?')) return;
          await api(`/api/v1/agent/history/${encodeURIComponent(item.history_id)}?user_id=${user}`, { method: 'DELETE' });
          await loadHistory();
        };
        row.appendChild(rerunBtn);
        row.appendChild(useBtn);
        row.appendChild(delBtn);
        el.appendChild(row);
        ui.historyList.appendChild(el);
      });

      historyOffset += history.length;
      ui.historyMoreBtn.disabled = history.length < historyPageSize;
      ui.historyMoreBtn.style.display = history.length || historyOffset ? 'block' : 'none';
      return history;
    }

    function caseFilterParams() {
      const params = new URLSearchParams({ limit: '20' });
      const approval = ui.caseApprovalFilter.value;
      const channel = ui.caseChannelFilter.value.trim();
      if (approval === 'approved') params.set('signoff_approved', 'true');
      if (approval === 'pending') params.set('signoff_approved', 'false');
      if (channel) params.set('destination_channel', channel);
      return params;
    }

    async function loadCases() {
      const params = caseFilterParams();
      const cases = await api(`/api/v1/safety/cases?${params.toString()}`);
      const availableIds = new Set(cases.map(c => c.case_id));
      Array.from(selectedCaseIds).forEach(caseId => {
        if (!availableIds.has(caseId)) {
          selectedCaseIds.delete(caseId);
        }
      });
      ui.caseList.innerHTML = cases.length ? '' : '<div class="muted">No safety cases yet.</div>';
      cases.forEach(c => {
        const wrap = document.createElement('div');
        wrap.className = 'card';
        const selectRow = document.createElement('div');
        selectRow.className = 'row';
        const select = document.createElement('input');
        select.type = 'checkbox';
        select.checked = selectedCaseIds.has(c.case_id);
        select.onchange = () => {
          if (select.checked) {
            selectedCaseIds.add(c.case_id);
          } else {
            selectedCaseIds.delete(c.case_id);
          }
        };
        const selectLabel = document.createElement('label');
        selectLabel.textContent = 'Select for bulk actions';
        selectLabel.style.width = 'auto';
        selectRow.appendChild(select);
        selectRow.appendChild(selectLabel);

        const detail = document.createElement('a');
        detail.href = `/api/v1/safety/cases/${encodeURIComponent(c.case_id)}`;
        detail.target = '_blank';
        detail.rel = 'noreferrer';
        detail.textContent = `${c.case_id} (${c.flagged_records_count} flagged, avg ${c.average_risk_score}, ${c.highest_risk_band})`;
        const workflowMeta = document.createElement('div');
        workflowMeta.className = 'muted';
        const checklistProgress = `${c.checklist_completed_count || 0}/${c.checklist_total_count || 0}`;
        const approvalBadge = c.signoff_approved
          ? '<span class="badge ok">approved</span>'
          : '<span class="badge warn">pending</span>';
        const reviewer = c.signoff_reviewer_id || 'unassigned';
        const destination = c.destination_channel || 'not set';
        workflowMeta.innerHTML = `${approvalBadge}<span class="badge">checklist ${escapeHtml(checklistProgress)}</span> reviewer: ${escapeHtml(reviewer)} · channel: ${escapeHtml(destination)}`;
        const report = document.createElement('a');
        report.href = `/api/v1/safety/cases/${encodeURIComponent(c.case_id)}/report.json`;
        report.target = '_blank';
        report.rel = 'noreferrer';
        report.textContent = 'Download evidence report';
        const actions = document.createElement('div');
        actions.className = 'row';
        const reviewBtn = document.createElement('button');
        reviewBtn.textContent = 'Mark Human Review Done';
        reviewBtn.onclick = async () => {
          await patchCaseWorkflow(c.case_id, {
            checklist_updates: [
              {
                item_id: 'human-review',
                completed: true,
                notes: 'Marked complete from Agent Console Case Board.',
              },
            ],
          }, 'Human review marked complete');
        };

        const approveBtn = document.createElement('button');
        approveBtn.textContent = 'Approve + Sign Off';
        approveBtn.onclick = async () => {
          const reviewer = prompt('Reviewer ID', ui.userId.value.trim() || 'default');
          if (reviewer === null) return;
          const destination = prompt('Destination channel', 'platform-trust-safety');
          if (destination === null) return;
          await patchCaseWorkflow(c.case_id, {
            checklist_updates: [
              { item_id: 'submission-channel', completed: true, notes: destination || null },
              { item_id: 'second-review', completed: true, notes: 'Confirmed in Agent Console.' },
            ],
            signoff: {
              reviewer_id: reviewer || null,
              approved: true,
              destination_channel: destination || null,
            },
          }, 'Case signed off');
        };

        actions.appendChild(reviewBtn);
        actions.appendChild(approveBtn);
        wrap.appendChild(selectRow);
        wrap.appendChild(detail);
        wrap.appendChild(workflowMeta);
        wrap.appendChild(report);
        wrap.appendChild(actions);
        ui.caseList.appendChild(wrap);
      });
      return cases;
    }

    async function patchCaseWorkflow(caseId, payload, successText) {
      try {
        const workflow = await api(`/api/v1/safety/cases/${encodeURIComponent(caseId)}/report/workflow`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
        const signoff = workflow.signoff || {};
        const approvalState = signoff.approved ? 'approved' : 'pending';
        ui.statusMsg.textContent = `${successText}: ${caseId} (${approvalState})`;
        await loadCases();
      } catch (err) {
        ui.statusMsg.textContent = `Case workflow update failed: ${err.message}`;
      }
    }

    async function patchCasesWorkflowBulk(caseIds, payload, successText) {
      if (!caseIds.length) {
        ui.statusMsg.textContent = 'Select at least one case for bulk action.';
        return;
      }
      try {
        const result = await api('/api/v1/safety/cases/report/workflow/bulk', {
          method: 'PATCH',
          body: JSON.stringify({ case_ids: caseIds, workflow: payload }),
        });
        ui.statusMsg.textContent = `${successText}: updated ${result.updated_case_ids.length}, missing ${result.missing_case_ids.length}.`;
        await loadCases();
      } catch (err) {
        ui.statusMsg.textContent = `Bulk workflow update failed: ${err.message}`;
      }
    }

    function copyToClipboard(value) {
      return navigator.clipboard.writeText(value);
    }

    async function loadSafetyPersona() {
      const persona = await api('/api/v1/safety/persona');
      const templates = (persona.first_message_templates || []).map((tpl) => {
        const safeMessage = escapeHtml(tpl.message || '');
        return `
          <div class="card" style="padding:8px;">
            <div><strong>${escapeHtml(tpl.purpose || tpl.template_id)}</strong></div>
            <div class="muted" style="margin:6px 0;">${safeMessage}</div>
            <button data-copy-template="${escapeHtml(tpl.template_id)}">Copy Template</button>
          </div>
        `;
      }).join('');

      ui.personaPane.innerHTML = `
        <div><strong>${escapeHtml(persona.display_name)}</strong><span class="pill">${escapeHtml(persona.persona_id)}</span></div>
        <div class="muted">${escapeHtml(persona.profile_bio)}</div>
        <div class="muted">${escapeHtml(persona.disclosure)}</div>
        <div class="muted"><strong>Hard Stops:</strong> ${(persona.hard_stop_rules || []).map(escapeHtml).join(' | ')}</div>
        <div class="stack">${templates}</div>
      `;

      Array.from(ui.personaPane.querySelectorAll('button[data-copy-template]')).forEach(btn => {
        btn.onclick = async () => {
          const templateId = btn.getAttribute('data-copy-template');
          const template = (persona.first_message_templates || []).find(item => item.template_id === templateId);
          if (!template) return;
          try {
            await copyToClipboard(template.message || '');
            ui.statusMsg.textContent = `Copied template: ${template.template_id}`;
          } catch (err) {
            ui.statusMsg.textContent = `Copy failed: ${err.message}`;
          }
        };
      });
      return persona;
    }

    function hydrateFromRequest(request, label) {
      ui.labelInput.value = label || '';
      ui.queryInput.value = request.query || '';
      ui.modeSelect.value = request.mode || 'auto';
      ui.maxPagesInput.value = request.max_pages || 10;
      ui.matureToggle.checked = !!request.include_mature_content;
      ui.fieldsInput.value = (request.desired_fields || []).join(',');
      setSelectedPackIds(request.source_pack_ids || []);
    }

    function onJobCreated(jobId, prefix) {
      lastJobId = jobId;
      lastJobStatus = null;
      ui.statusMsg.textContent = `${prefix}: ${jobId}`;
      renderExportLinks();
      renderPreviewPlaceholder('Waiting for completed job data...');
    }

    async function syncJobStatus(jobId, showErrors = true) {
      try {
        const job = await api(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
        lastJobStatus = job.status || null;
        renderExportLinks();
        if (job.status === 'completed') {
          await loadRecordPreview(jobId);
        }
        if (job.diagnostics && job.diagnostics.recommendation) {
          ui.statusMsg.textContent = `Job ${jobId}: ${job.status}. ${job.diagnostics.recommendation}`;
        }
        return job.status || null;
      } catch (err) {
        if (showErrors) {
          ui.statusMsg.textContent = `Status check failed: ${err.message}`;
        }
        return null;
      }
    }

    async function watchJobUntilTerminal(jobId) {
      for (let i = 0; i < 60; i++) {
        const status = await syncJobStatus(jobId, false);
        if (status === 'completed' || status === 'failed') {
          ui.statusMsg.textContent = `Job ${jobId} is ${status}.`;
          await loadHistory();
          return;
        }
        if (status) {
          ui.statusMsg.textContent = `Job ${jobId} is ${status}...`;
        }
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
      ui.statusMsg.textContent = `Job ${jobId} is still running. You can reopen JSON status any time.`;
    }

    function renderExportLinks() {
      if (!lastJobId) {
        ui.exportLinks.innerHTML = '<div class="muted">Run a request to populate exports.</div>';
        renderPreviewPlaceholder('Run or load a completed job to preview extracted images and videos.');
        return;
      }
      const json = `/api/v1/jobs/${encodeURIComponent(lastJobId)}`;
      const summary = `/api/v1/jobs/${encodeURIComponent(lastJobId)}/summary`;
      const csv = `/api/v1/jobs/${encodeURIComponent(lastJobId)}/export.csv`;
      const statusText = lastJobStatus ? `Current job status: ${escapeHtml(lastJobStatus)}` : 'Current job status: unknown';
      const jsonLabel = lastJobStatus && lastJobStatus !== 'completed' ? 'Open JSON status (job still processing)' : 'Download JSON result';
      const csvLink = lastJobStatus === 'completed'
        ? `<a href="${csv}" target="_blank" rel="noreferrer">Download CSV bundle</a>`
        : '<div class="muted">CSV export is enabled when job status is completed.</div>';
      ui.exportLinks.innerHTML = `
        <div class="muted">${statusText}</div>
        <a href="${summary}" target="_blank" rel="noreferrer">Open concise run summary</a>
        <a href="${json}" target="_blank" rel="noreferrer">${jsonLabel}</a>
        ${csvLink}
      `;
    }

    function renderPreviewPlaceholder(text) {
      ui.previewPane.innerHTML = `<div class="muted">${escapeHtml(text)}</div>`;
    }

    async function loadRecordPreview(jobId) {
      try {
        const payload = await api(`/api/v1/jobs/${encodeURIComponent(jobId)}/records?limit=6&offset=0`);
        const items = payload.items || [];
        if (!items.length) {
          renderPreviewPlaceholder('No preview records available for this job.');
          return;
        }

        ui.previewPane.innerHTML = items.map((item, idx) => {
          const title = escapeHtml(item.title || `Record ${idx + 1}`);
          const sourceUrl = escapeHtml(item.source_url || '');
          const images = (item.images || []).slice(0, 6).map((url) => (
            `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer"><img src="${escapeHtml(url)}" alt="preview" style="width:72px;height:72px;object-fit:cover;border:1px solid var(--line);border-radius:8px;" /></a>`
          )).join('');
          const videos = (item.videos || []).slice(0, 3).map((url) => (
            `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">video</a>`
          )).join(' · ');

          return `
            <div class="card" style="padding:8px;">
              <div><strong>${title}</strong></div>
              <div class="muted" style="word-break:break-word;">${sourceUrl}</div>
              <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:6px;">${images || '<span class="muted">no images</span>'}</div>
              <div class="muted" style="margin-top:6px;">${videos || 'no videos'}</div>
            </div>
          `;
        }).join('');
      } catch (err) {
        renderPreviewPlaceholder(`Preview load failed: ${err.message}`);
      }
    }

    ui.loadBtn.onclick = async () => {
      try {
        const [packs, presets, history, cases, persona] = await Promise.all([loadSourcePacks(), loadPresets(), loadHistory(true), loadCases(), loadSafetyPersona()]);
        ui.statusMsg.textContent = `Console loaded (${packs.length} packs, ${presets.length} presets, ${history.length} history items, ${cases.length} cases, persona ${persona.persona_id}).`;
      } catch (err) {
        ui.statusMsg.textContent = `Load failed: ${err.message}`;
      }
    };

    ui.historyMoreBtn.onclick = async () => {
      try {
        const chunk = await loadHistory(false);
        if (!chunk.length) {
          ui.statusMsg.textContent = 'No more history entries.';
        }
      } catch (err) {
        ui.statusMsg.textContent = `History load failed: ${err.message}`;
      }
    };

    ui.applyCaseFiltersBtn.onclick = async () => {
      try {
        selectedCaseIds.clear();
        await loadCases();
        ui.statusMsg.textContent = 'Case filters applied.';
      } catch (err) {
        ui.statusMsg.textContent = `Case filter failed: ${err.message}`;
      }
    };

    ui.downloadCaseCsvBtn.onclick = () => {
      const params = caseFilterParams();
      window.open(`/api/v1/safety/cases/export.csv?${params.toString()}`, '_blank');
    };

    ui.bulkReviewBtn.onclick = async () => {
      await patchCasesWorkflowBulk(Array.from(selectedCaseIds), {
        checklist_updates: [
          {
            item_id: 'human-review',
            completed: true,
            notes: 'Bulk marked from Agent Console Case Board.',
          },
        ],
      }, 'Bulk human-review update complete');
    };

    ui.bulkApproveBtn.onclick = async () => {
      const reviewer = prompt('Reviewer ID for bulk signoff', ui.userId.value.trim() || 'default');
      if (reviewer === null) return;
      const destination = prompt('Destination channel for bulk signoff', 'platform-trust-safety');
      if (destination === null) return;
      await patchCasesWorkflowBulk(Array.from(selectedCaseIds), {
        checklist_updates: [
          { item_id: 'second-review', completed: true, notes: 'Bulk confirmed in Agent Console.' },
          { item_id: 'submission-channel', completed: true, notes: destination || null },
        ],
        signoff: {
          reviewer_id: reviewer || null,
          approved: true,
          destination_channel: destination || null,
        },
      }, 'Bulk signoff complete');
    };

    ui.savePresetBtn.onclick = async () => {
      try {
        const payload = {
          user_id: ui.userId.value.trim() || 'default',
          name: ui.labelInput.value.trim() || 'Saved preset',
          request: buildRequest(),
        };
        await api('/api/v1/agent/presets', { method: 'POST', body: JSON.stringify(payload) });
        ui.statusMsg.textContent = 'Preset saved.';
        await loadPresets();
      } catch (err) {
        ui.statusMsg.textContent = `Preset save failed: ${err.message}`;
      }
    };

    ui.saveSafetyPresetBtn.onclick = async () => {
      try {
        const payload = {
          user_id: ui.userId.value.trim() || 'default',
          query: ui.queryInput.value.trim() || undefined,
          include_mature_content: ui.matureToggle.checked,
        };
        const preset = await api('/api/v1/agent/presets/safety-default', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        ui.statusMsg.textContent = `Safety preset saved: ${preset.name}`;
        await loadPresets();
      } catch (err) {
        ui.statusMsg.textContent = `Safety preset failed: ${err.message}`;
      }
    };

    ui.runBtn.onclick = async () => {
      try {
        const payload = {
          user_id: ui.userId.value.trim() || 'default',
          label: ui.labelInput.value.trim() || undefined,
          request: buildRequest(),
          run_async: ui.asyncToggle.checked,
        };
        const body = await api('/api/v1/agent/history/submit', { method: 'POST', body: JSON.stringify(payload) });
        onJobCreated(body.job_id, 'request submitted');
        await loadHistory();
        watchJobUntilTerminal(body.job_id);
      } catch (err) {
        ui.statusMsg.textContent = `Run failed: ${err.message}`;
      }
    };

    function escapeHtml(value) {
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;');
    }

    renderExportLinks();
    ui.loadBtn.click();
  </script>
</body>
</html>
    """


@router.get("/ui/jobs", response_class=HTMLResponse)
async def jobs_browser() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GhostScraper Jobs</title>
  <style>
    :root {
      --bg: #f4efe6;
      --panel: rgba(255, 251, 245, 0.92);
      --ink: #1d1a17;
      --muted: #6a6158;
      --accent: #b64d2d;
      --accent-2: #235a52;
      --line: rgba(29, 26, 23, 0.12);
      --shadow: 0 18px 45px rgba(50, 31, 17, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(182, 77, 45, 0.12), transparent 30%),
        radial-gradient(circle at bottom right, rgba(35, 90, 82, 0.12), transparent 28%),
        linear-gradient(135deg, #efe6d8, #f7f2ea 45%, #ece2d1);
      min-height: 100vh;
    }
    .shell {
      max-width: 1400px;
      margin: 0 auto;
      padding: 32px 20px 40px;
    }
    .hero {
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: end;
      margin-bottom: 24px;
    }
    .hero h1 {
      margin: 0;
      font-size: clamp(2.2rem, 4vw, 4.4rem);
      line-height: 0.95;
      letter-spacing: -0.04em;
    }
    .hero p {
      max-width: 620px;
      margin: 10px 0 0;
      color: var(--muted);
      font-size: 1rem;
    }
    .layout {
      display: grid;
      grid-template-columns: 360px 1fr;
      gap: 18px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
      overflow: hidden;
      backdrop-filter: blur(8px);
    }
    .panel-head {
      padding: 18px 20px;
      border-bottom: 1px solid var(--line);
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
    }
    .panel-head h2 {
      margin: 0;
      font-size: 1rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }
    .controls, .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    select, input, button {
      font: inherit;
      border-radius: 999px;
      border: 1px solid var(--line);
      padding: 10px 14px;
      background: #fffdf9;
      color: var(--ink);
    }
    button {
      cursor: pointer;
      transition: transform 120ms ease, background 120ms ease;
    }
    button:hover { transform: translateY(-1px); }
    .accent { background: var(--accent); color: white; border-color: transparent; }
    .accent-2 { background: var(--accent-2); color: white; border-color: transparent; }
    .job-list {
      max-height: 70vh;
      overflow: auto;
      padding: 10px;
    }
    .composer {
      margin-bottom: 18px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.72);
      display: grid;
      gap: 10px;
    }
    .composer textarea {
      width: 100%;
      min-height: 92px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      font: inherit;
      background: #fffdf9;
      color: var(--ink);
    }
    .composer-options {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      color: var(--muted);
      font-size: 0.9rem;
    }
    .pack-select {
      width: 100%;
      min-height: 140px;
      border-radius: 18px;
      padding: 10px 12px;
    }
    .composer-status {
      color: var(--muted);
      font-size: 0.9rem;
      min-height: 1.2em;
    }
    .job-card {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      margin-bottom: 10px;
      background: rgba(255,255,255,0.75);
      cursor: pointer;
      transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
    }
    .job-card:hover, .job-card.active {
      transform: translateX(3px);
      border-color: rgba(182, 77, 45, 0.35);
      background: rgba(255,255,255,0.96);
    }
    .job-meta {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      font-size: 0.9rem;
      color: var(--muted);
      margin-top: 8px;
    }
    .status {
      display: inline-block;
      padding: 4px 9px;
      border-radius: 999px;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      background: rgba(29, 26, 23, 0.08);
    }
    .records {
      padding: 18px;
      display: grid;
      gap: 14px;
      min-height: 500px;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      background: rgba(255,255,255,0.6);
    }
    .metric strong {
      display: block;
      font-size: 1.3rem;
      margin-bottom: 4px;
    }
    .record-card {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      background: rgba(255,255,255,0.72);
    }
    .record-card h3 {
      margin: 0 0 8px;
      font-size: 1.15rem;
    }
    .record-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
      margin-bottom: 10px;
    }
    .record-url {
      color: var(--muted);
      word-break: break-word;
      font-size: 0.92rem;
    }
    .thumbnail-strip {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
      gap: 10px;
      margin: 14px 0 4px;
    }
    .thumbnail {
      position: relative;
      border-radius: 14px;
      overflow: hidden;
      aspect-ratio: 1 / 1;
      border: 1px solid var(--line);
      background: linear-gradient(135deg, rgba(182, 77, 45, 0.08), rgba(35, 90, 82, 0.08));
    }
    .thumbnail img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .thumbnail-count {
      display: inline-block;
      margin-top: 10px;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 0.8rem;
      color: var(--muted);
      background: rgba(29, 26, 23, 0.06);
    }
    .video-strip {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
      gap: 10px;
      margin: 14px 0 4px;
    }
    .video-card {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      background: rgba(255, 255, 255, 0.82);
      min-height: 74px;
      display: grid;
      align-content: center;
      gap: 8px;
    }
    .video-card a {
      color: var(--accent-2);
      text-decoration: none;
      font-weight: 600;
      font-size: 0.92rem;
      word-break: break-word;
    }
    .video-card small {
      color: var(--muted);
    }
    .embed-list {
      margin-top: 12px;
      display: grid;
      gap: 8px;
    }
    .embed-list a {
      color: var(--accent-2);
      text-decoration: none;
      font-size: 0.92rem;
      word-break: break-word;
    }
    .kv {
      display: grid;
      grid-template-columns: 160px 1fr;
      gap: 8px 14px;
      font-size: 0.96rem;
      margin-top: 12px;
    }
    .kv div:nth-child(odd) {
      color: var(--muted);
    }
    .empty {
      padding: 28px;
      text-align: center;
      color: var(--muted);
    }
    @media (max-width: 980px) {
      .layout, .summary { grid-template-columns: 1fr; }
      .hero { display: block; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="hero">
      <div>
        <h1>GhostScraper Jobs Browser</h1>
        <p>Browse recent scrape jobs, preview extracted records, filter fields for faster review, and download CSV outputs directly from the API.</p>
      </div>
      <div class="toolbar">
        <button id="trendPresetBtn">Trend Pull Preset</button>
        <button class="accent-2" id="refreshBtn">Refresh Jobs</button>
      </div>
    </div>

    <section class="composer">
      <textarea id="queryInput" placeholder="Describe what to scrape..."></textarea>
      <select id="sourcePackSelect" class="pack-select" multiple size="8"></select>
      <div class="composer-options">
        <label><input type="checkbox" id="matureToggle" /> include mature-content discovery</label>
        <label><input type="checkbox" id="asyncToggle" checked /> queue async job</label>
      </div>
      <div class="composer-status" id="sourcePackStatus">Loading curated source packs...</div>
      <div class="toolbar">
        <button class="accent" id="runJobBtn">Run Job</button>
      </div>
      <div class="composer-status" id="composerStatus"></div>
    </section>

    <div class="layout">
      <section class="panel">
        <div class="panel-head">
          <h2>Jobs</h2>
          <div class="controls">
            <select id="statusFilter">
              <option value="">All</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
            </select>
            <button id="moreJobsBtn">More</button>
          </div>
        </div>
        <div class="job-list" id="jobList"></div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2>Records</h2>
          <div class="controls">
            <input id="fieldInput" placeholder="Fields e.g. title,price,address" />
            <button id="applyFieldsBtn">Apply</button>
            <button id="caseBtn">Create Safety Case</button>
            <button class="accent" id="csvBtn">Download CSV</button>
          </div>
        </div>
        <div class="records" id="recordsPane">
          <div class="empty">Select a job to view extracted content.</div>
        </div>
      </section>
    </div>
  </div>

  <script>
    const state = {
      jobs: [],
      cursor: null,
      activeJobId: null,
      fields: "",
      offset: 0,
      limit: 10,
    };

    const jobList = document.getElementById("jobList");
    const recordsPane = document.getElementById("recordsPane");
    const statusFilter = document.getElementById("statusFilter");
    const moreJobsBtn = document.getElementById("moreJobsBtn");
    const fieldInput = document.getElementById("fieldInput");
    const queryInput = document.getElementById("queryInput");
    const matureToggle = document.getElementById("matureToggle");
    const asyncToggle = document.getElementById("asyncToggle");
    const sourcePackSelect = document.getElementById("sourcePackSelect");
    const sourcePackStatus = document.getElementById("sourcePackStatus");
    const composerStatus = document.getElementById("composerStatus");
    const caseBtn = document.getElementById("caseBtn");
    let sourcePacks = [];

    const TREND_PRESET = {
      query: "Pull the top 10 memes, gifs, shorts, and tiktok videos with current trends",
      mode: "auto",
      use_search_discovery: true,
      include_images: true,
      include_videos: true,
      include_mature_content: true,
      max_pages: 10,
      source_pack_ids: [
        "short-video-viral",
        "meme-gif-culture",
        "social-discussion",
        "livestream-clips",
        "music-scenes",
        "gaming-culture",
      ],
      desired_fields: ["title", "image_urls", "video_urls", "embed_urls", "social_links", "hashtags"],
    };

    document.getElementById("refreshBtn").addEventListener("click", () => loadJobs(true));
    document.getElementById("trendPresetBtn").addEventListener("click", () => {
      queryInput.value = TREND_PRESET.query;
      matureToggle.checked = true;
      setSelectedPackIds(TREND_PRESET.source_pack_ids);
      composerStatus.textContent = "Trend Pull preset applied.";
    });
    document.getElementById("applyFieldsBtn").addEventListener("click", () => {
      state.fields = fieldInput.value.trim();
      state.offset = 0;
      if (state.activeJobId) {
        loadRecords(state.activeJobId);
      }
    });
    document.getElementById("runJobBtn").addEventListener("click", runJobFromComposer);
    caseBtn.addEventListener("click", createSafetyCaseFromSelectedJob);
    document.getElementById("csvBtn").addEventListener("click", () => {
      if (!state.activeJobId) {
        return;
      }
      const params = new URLSearchParams();
      if (state.fields) params.set("fields", state.fields);
      window.open(`/api/v1/jobs/${state.activeJobId}/export.csv?${params.toString()}`, "_blank");
    });
    statusFilter.addEventListener("change", () => loadJobs(true));
    moreJobsBtn.addEventListener("click", () => loadJobs(false));

    async function createSafetyCaseFromSelectedJob() {
      if (!state.activeJobId) {
        composerStatus.textContent = "Select a job before creating a safety case.";
        return;
      }
      composerStatus.textContent = "Creating safety case...";
      try {
        const response = await fetch("/api/v1/safety/cases/from-job", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_id: state.activeJobId,
            title: `Safety case for ${state.activeJobId}`,
            min_risk_score: 0.45,
            record_limit: 100,
          }),
        });
        const body = await response.json();
        if (!response.ok) {
          composerStatus.textContent = `Safety case failed: ${body.detail || response.status}`;
          return;
        }
        composerStatus.textContent = `Safety case created: ${body.case_id} (${body.flagged_records_count} flagged, band ${body.highest_risk_band || 'low'})`;
      } catch (error) {
        composerStatus.textContent = "Safety case failed due to network error.";
      }
    }

    async function runJobFromComposer() {
      const query = queryInput.value.trim();
      if (!query) {
        composerStatus.textContent = "Add a query before running a job.";
        return;
      }

      const payload = {
        ...TREND_PRESET,
        query,
        include_mature_content: matureToggle.checked,
        source_pack_ids: getSelectedPackIds(),
      };

      const useAsync = asyncToggle.checked;
      const endpoint = useAsync ? "/api/v1/jobs/scrape/async" : "/api/v1/jobs/scrape";
      composerStatus.textContent = "Submitting job...";

      try {
        const response = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const body = await response.json();
        if (!response.ok) {
          composerStatus.textContent = `Request failed: ${body.detail || response.status}`;
          return;
        }

        if (useAsync) {
          composerStatus.textContent = `Queued job ${body.job_id}`;
          await loadJobs(true);
          if (body.job_id) {
            await selectJob(body.job_id);
          }
        } else {
          composerStatus.textContent = `Completed job ${body.job_id}`;
          await loadJobs(true);
          if (body.job_id) {
            await selectJob(body.job_id);
          }
        }
      } catch (error) {
        composerStatus.textContent = "Request failed due to network error.";
      }
    }

    async function loadJobs(reset) {
      if (reset) {
        state.jobs = [];
        state.cursor = null;
      }
      const params = new URLSearchParams({ limit: "20" });
      if (statusFilter.value) params.set("status", statusFilter.value);
      if (state.cursor) params.set("cursor", state.cursor);
      const response = await fetch(`/api/v1/jobs?${params.toString()}`);
      const payload = await response.json();
      state.jobs = reset ? payload.items : state.jobs.concat(payload.items);
      state.cursor = payload.next_cursor;
      renderJobs();
      if (!state.activeJobId && state.jobs.length) {
        selectJob(state.jobs[0].job_id);
      }
    }

    async function loadSourcePacks() {
      const response = await fetch("/api/v1/source-packs");
      sourcePacks = await response.json();
      sourcePackSelect.innerHTML = sourcePacks.map(pack => `
        <option value="${escapeHtml(pack.pack_id)}">${escapeHtml(pack.name)} · ${escapeHtml(pack.category)}</option>
      `).join("");
      sourcePackStatus.textContent = `${sourcePacks.length} curated packs loaded. Selected packs add source-scoped discovery and curated fallback URLs.`;
      setSelectedPackIds(TREND_PRESET.source_pack_ids);
    }

    function getSelectedPackIds() {
      return Array.from(sourcePackSelect.selectedOptions).map(option => option.value);
    }

    function setSelectedPackIds(packIds) {
      const selected = new Set(packIds || []);
      Array.from(sourcePackSelect.options).forEach(option => {
        option.selected = selected.has(option.value);
      });
    }

    function renderJobs() {
      if (!state.jobs.length) {
        jobList.innerHTML = `<div class="empty">No jobs found for this filter.</div>`;
        moreJobsBtn.disabled = true;
        return;
      }
      moreJobsBtn.disabled = !state.cursor;
      jobList.innerHTML = state.jobs.map(job => `
        <article class="job-card ${job.job_id === state.activeJobId ? "active" : ""}" data-job-id="${job.job_id}">
          <div><span class="status">${job.status}</span></div>
          <h3>${job.job_id}</h3>
          <div class="job-meta"><span>${job.records_extracted} records</span><span>${job.pages_processed} pages</span></div>
          <div class="job-meta"><span>${job.failures} failures</span><span>${new Date(job.updated_at).toLocaleString()}</span></div>
        </article>
      `).join("");
      jobList.querySelectorAll(".job-card").forEach(card => {
        card.addEventListener("click", () => selectJob(card.dataset.jobId));
      });
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;');
    }

    async function selectJob(jobId) {
      state.activeJobId = jobId;
      state.offset = 0;
      renderJobs();
      await loadRecords(jobId);
    }

    async function loadRecords(jobId) {
      const params = new URLSearchParams({ limit: String(state.limit), offset: String(state.offset) });
      if (state.fields) params.set("fields", state.fields);
      const response = await fetch(`/api/v1/jobs/${jobId}/records?${params.toString()}`);
      const payload = await response.json();
      renderRecords(payload, jobId);
    }

    function renderRecords(payload, jobId) {
      const items = payload.items || [];
      const fieldLabel = payload.requested_fields?.length ? payload.requested_fields.join(", ") : "all fields";
      const metrics = `
        <div class="summary">
          <div class="metric"><strong>${jobId}</strong>Active job</div>
          <div class="metric"><strong>${payload.total}</strong>Total records</div>
          <div class="metric"><strong>${payload.offset}</strong>Current offset</div>
          <div class="metric"><strong>${fieldLabel}</strong>Field view</div>
        </div>
      `;
      if (!items.length) {
        recordsPane.innerHTML = metrics + `<div class="empty">No records available for this page.</div>`;
        return;
      }

      const cards = items.map(record => {
        const dataEntries = Object.entries(record.data || {});
        const thumbnails = renderThumbnails(record.images || []);
        const videos = renderVideos(record.videos || []);
        const embeds = renderEmbeds(record.data?.embed_urls || []);
        const body = dataEntries.length
          ? `<div class="kv">${dataEntries.map(([key, value]) => `<div>${key}</div><div>${formatValue(value)}</div>`).join("")}</div>`
          : `<div class="empty" style="padding:12px 0 0;text-align:left;">No matching data fields in this view.</div>`;
        return `
          <article class="record-card">
            <div class="record-head">
              <div>
                <h3>${escapeHtml(record.title || record.record_type || "Record")}</h3>
                <div class="record-url">${escapeHtml(record.source_url)}</div>
              </div>
              <span class="status">${escapeHtml(record.record_type)}</span>
            </div>
            ${thumbnails}
            ${videos}
            ${embeds}
            ${body}
          </article>
        `;
      }).join("");

      const pager = `
        <div class="toolbar">
          <button ${payload.offset === 0 ? "disabled" : ""} id="prevPageBtn">Previous</button>
          <button class="accent-2" ${payload.has_more ? "" : "disabled"} id="nextPageBtn">Next</button>
        </div>
      `;
      recordsPane.innerHTML = metrics + cards + pager;
      const prev = document.getElementById("prevPageBtn");
      const next = document.getElementById("nextPageBtn");
      if (prev) prev.addEventListener("click", async () => {
        state.offset = Math.max(0, state.offset - state.limit);
        await loadRecords(jobId);
      });
      if (next) next.addEventListener("click", async () => {
        state.offset = state.offset + state.limit;
        await loadRecords(jobId);
      });
    }

    function formatValue(value) {
      if (value === null || value === undefined) return "-";
      if (Array.isArray(value)) return escapeHtml(value.join(", "));
      if (typeof value === "object") return escapeHtml(JSON.stringify(value));
      return escapeHtml(String(value));
    }

    function renderThumbnails(images) {
      if (!images.length) return "";
      const preview = images.slice(0, 6).map((src, index) => `
        <a class="thumbnail" href="${escapeAttribute(src)}" target="_blank" rel="noreferrer">
          <img src="${escapeAttribute(src)}" alt="Scraped image ${index + 1}" loading="lazy" />
        </a>
      `).join("");
      const count = `<div class="thumbnail-count">${images.length} image${images.length === 1 ? "" : "s"}</div>`;
      return `<div class="thumbnail-strip">${preview}</div>${count}`;
    }

    function renderVideos(videos) {
      if (!videos.length) return "";
      const preview = videos.slice(0, 6).map((src, index) => `
        <div class="video-card">
          <small>Video ${index + 1}</small>
          <a href="${escapeAttribute(src)}" target="_blank" rel="noreferrer">${escapeHtml(shortenUrl(src))}</a>
        </div>
      `).join("");
      const count = `<div class="thumbnail-count">${videos.length} video${videos.length === 1 ? "" : "s"}</div>`;
      return `<div class="video-strip">${preview}</div>${count}`;
    }

    function renderEmbeds(embedUrls) {
      if (!embedUrls.length) return "";
      const links = embedUrls.slice(0, 5).map((src, index) =>
        `<a href="${escapeAttribute(src)}" target="_blank" rel="noreferrer">Embed ${index + 1}: ${escapeHtml(shortenUrl(src))}</a>`
      ).join("");
      return `<div class="embed-list">${links}</div>`;
    }

    function shortenUrl(value) {
      try {
        const url = new URL(value);
        const compact = `${url.hostname}${url.pathname}`;
        return compact.length > 64 ? `${compact.slice(0, 61)}...` : compact;
      } catch {
        return value.length > 64 ? `${value.slice(0, 61)}...` : value;
      }
    }

    function escapeHtml(value) {
      return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function escapeAttribute(value) {
      return escapeHtml(value).replaceAll("'", "&#39;");
    }

    Promise.all([loadSourcePacks(), loadJobs(true)]).catch(() => {
      sourcePackStatus.textContent = "Failed to load source packs.";
    });
  </script>
</body>
</html>
    """