/* ========================================
   GhostRescue Dashboard JavaScript
   ======================================== */

const API_BASE = '/api/v1';
let currentCaseId = null;
let riskChart = null;
let signalsChart = null;
let timeIntervalId = null;
let refreshIntervalId = null;
let dashboardRefreshInFlight = false;
let temporaryAnalysisFiles = [];
let temporaryAnalysisPayload = null;
let temporaryChatMessages = [];
let temporarySessionId = null;
let temporarySessionSensitiveMode = false;

function currentAnalystContext() {
    const analystIdInput = document.getElementById('temp-analyst-id');
    const analystRoleInput = document.getElementById('temp-analyst-role');
    return {
        analystId: ((analystIdInput && analystIdInput.value) || window.currentAnalystId || '').toString().trim(),
        analystRole: ((analystRoleInput && analystRoleInput.value) || window.currentAnalystRole || '').toString().trim(),
    };
}

// ========== Authority Badge Helpers ==========

const _SOURCE_TIER_MAP = [
    { prefix: 'fbi most wanted', tier: 'law_enforcement' },
    { prefix: 'fbi-', tier: 'law_enforcement' },
    { prefix: 'fbi_', tier: 'law_enforcement' },
    { prefix: 'interpol', tier: 'law_enforcement' },
    { prefix: 'law_enforcement', tier: 'law_enforcement' },
    { prefix: 'namus', tier: 'public_dataset' },
    { prefix: 'ncmec', tier: 'public_dataset' },
    { prefix: 'courtlistener', tier: 'public_dataset' },
    { prefix: 'cl-', tier: 'public_dataset' },
    { prefix: 'newsapi', tier: 'osint' },
];

const _TIER_BADGE = {
    law_enforcement: { label: 'Law Enforcement', cls: 'authority-badge badge-law-enforcement' },
    public_dataset:  { label: 'Public Dataset',  cls: 'authority-badge badge-public-dataset' },
    osint:           { label: 'OSINT Signal',     cls: 'authority-badge badge-osint' },
};

function classifySourceTier(sourceName) {
    if (!sourceName) return 'osint';
    const s = sourceName.toLowerCase();
    for (const { prefix, tier } of _SOURCE_TIER_MAP) {
        if (s.startsWith(prefix) || s === prefix) return tier;
    }
    return 'osint';
}

/** Derive authority tier from case_id prefix (fallback when source_name unavailable). */
function tierFromCaseId(caseId) {
    if (!caseId) return null;
    const c = caseId.toUpperCase();
    if (c.startsWith('FBI-')) return 'law_enforcement';
    if (c.startsWith('INTERPOL-')) return 'law_enforcement';
    if (c.startsWith('NAMUS-')) return 'public_dataset';
    if (c.startsWith('CL-')) return 'public_dataset';
    return null;
}

function authorityBadgeHtml(tierOrSource, fromCaseId = false) {
    const tier = fromCaseId ? tierFromCaseId(tierOrSource) : classifySourceTier(tierOrSource);
    if (!tier || !_TIER_BADGE[tier]) return '';
    const { label, cls } = _TIER_BADGE[tier];
    return `<span class="${cls}">${label}</span>`;
}

function escapeHtml(text) {
    return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/** Render source_impact block for the explainability tab. */
function renderSourceImpactHtml(sourceImpact, scoreCalibration = {}) {
    if (!sourceImpact || !sourceImpact.tiers || sourceImpact.tiers.length === 0) return '';
    const badges = (sourceImpact.badges || []).map(b =>
        `<span class="authority-badge ${b.css_class}">${b.label}</span>`
    ).join(' ');
    const boost = sourceImpact.risk_boost_applied > 0
        ? `<span style="color:var(--success);">+${sourceImpact.risk_boost_applied.toFixed(1)} risk pts applied</span>`
        : '';
    const calibrationRows = scoreCalibration && Object.keys(scoreCalibration).length ? `
        <div style="display:grid; grid-template-columns: repeat(2, minmax(180px, 1fr)); gap:10px; margin-top:14px;">
            <div class="calibration-chip"><strong>Raw Score</strong><span>${(scoreCalibration.raw_score_before_calibration || 0).toFixed(1)}</span></div>
            <div class="calibration-chip"><strong>Risk Cap</strong><span>${scoreCalibration.source_class_cap != null ? Number(scoreCalibration.source_class_cap).toFixed(1) : 'N/A'}</span></div>
            <div class="calibration-chip"><strong>Reference Penalty</strong><span>${(scoreCalibration.reference_only_penalty || 0).toFixed(1)}</span></div>
            <div class="calibration-chip"><strong>Corroboration Boost</strong><span>${(scoreCalibration.corroboration_boost || 0).toFixed(1)}</span></div>
            <div class="calibration-chip"><strong>Unlock State</strong><span>${scoreCalibration.cross_source_unlock || 'none'}</span></div>
            <div class="calibration-chip"><strong>Final Score</strong><span>${(scoreCalibration.final_risk_score || 0).toFixed(1)}</span></div>
        </div>
    ` : '';
    return `
        <div style="margin-top:20px; padding:14px; background:var(--bg-tertiary); border-radius:var(--radius-md); border-left:3px solid var(--primary);">
            <h4 style="margin-bottom:10px;">Source Authority</h4>
            <div style="margin-bottom:8px;">${badges} ${boost}</div>
            <p style="font-size:13px; color:var(--text-secondary); margin-bottom:6px;">${sourceImpact.framing}</p>
            <p style="font-size:12px; color:var(--warning);">⚠ ${sourceImpact.guardrail}</p>
            ${calibrationRows}
        </div>
    `;
}

// ========== Initialization ==========

document.addEventListener('DOMContentLoaded', () => {
    if (window.__ghostRescueDashboardInitialized) {
        return;
    }
    window.__ghostRescueDashboardInitialized = true;

    updateTime();
    timeIntervalId = setInterval(updateTime, 1000);
    
    loadDashboardData();
    refreshIntervalId = setInterval(loadDashboardData, 30000); // Refresh every 30 seconds
    initializeTemporaryDropzone();
});

window.addEventListener('beforeunload', () => {
    if (timeIntervalId) {
        clearInterval(timeIntervalId);
    }
        clearTemporaryInvestigationSession();
        if (refreshIntervalId) {
            clearInterval(refreshIntervalId);
        }
});

// ========== UI Navigation ==========

function showSection(sectionId) {
    // Hide all sections
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    // Show selected section
    document.getElementById(sectionId).classList.add('active');
    
    // Update nav items
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelector(`[data-section="${sectionId}"]`).classList.add('active');
    
    // Load section-specific data
    switch(sectionId) {
        case 'overview':
            loadOverviewData();
            break;
        case 'cases':
            loadCasesData();
            break;
        case 'alerts':
            loadAlertsData();
            break;
        case 'entities':
            loadEntitiesData();
            break;
        case 'trust':
            loadTrustData();
            break;
        case 'archive':
            loadArchiveData();
            break;
        case 'staging':
            loadStagingQueue();
            break;
    }
}

function showTrustTab(tabId, btn) {
    document.querySelectorAll('.trust-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.trust-tab-panel').forEach(p => p.classList.remove('active'));
    if (btn) btn.classList.add('active');
    const panel = document.getElementById(`trust-tab-${tabId}`);
    if (panel) panel.classList.add('active');
    if (tabId === 'telemetry') {
        loadDecisionTelemetry();
    }
}

function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('open');
}

function updateTime() {
    const now = new Date();
    const options = { hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true };
    document.getElementById('current-time').textContent = now.toLocaleTimeString('en-US', options);
}

// ========== Dashboard Data Loading ==========

async function loadDashboardData() {
    if (dashboardRefreshInFlight) {
        return;
    }

    dashboardRefreshInFlight = true;
    try {
        const [entities, cases, alerts] = await Promise.all([
            fetch(`${API_BASE}/entities?limit=1`).then(r => r.json()),
            fetch(`${API_BASE}/cases?limit=100`).then(r => r.json()),
            fetch(`${API_BASE}/alerts?limit=100`).then(r => r.json())
        ]);
        
        // Update stats
        document.getElementById('stat-entities').textContent = entities.total || 0;
        document.getElementById('stat-cases').textContent = cases.total || 0;
        const unacknowledged = (alerts.alerts || []).filter(a => !a.acknowledged).length;
        document.getElementById('stat-alerts').textContent = unacknowledged;
        
        // Average confidence
        if (cases.total > 0) {
            const avgConfidence = (cases.cases || []).reduce((sum, c) => sum + (c.system_confidence || 0), 0) / cases.total;
            document.getElementById('stat-confidence').textContent = avgConfidence.toFixed(3);
        } else {
            document.getElementById('stat-confidence').textContent = '0.000';
        }
        
        const activeSection = document.querySelector('.section.active')?.id;
        if (!activeSection || activeSection === 'overview') {
            updateCharts(cases.cases || []);
            updateRecentCases(cases.cases || []);
            await loadCrossSourceLinks();
        }
    } catch (error) {
        console.error('Error loading dashboard data:', error);
    } finally {
        dashboardRefreshInFlight = false;
    }
}

async function loadOverviewData() {
    await loadDashboardData();
    await loadCrossSourceLinks();
}

async function loadCasesData() {
    try {
        const response = await fetch(`${API_BASE}/cases?limit=200`);
        const data = await response.json();
        const cases = data.cases || [];

        let labelsMap = {};
        if (cases.length > 0) {
            const ids = cases.map(c => c.case_id).join(',');
            try {
                const labelsResp = await fetch(`${API_BASE}/feedback/labels?case_ids=${encodeURIComponent(ids)}`);
                if (labelsResp.ok) labelsMap = await labelsResp.json();
            } catch (_) { /* non-critical */ }
        }

        populateCasesTable(cases, labelsMap);
    } catch (error) {
        console.error('Error loading cases:', error);
    }
}

async function loadAlertsData() {
    try {
        const response = await fetch(`${API_BASE}/alerts?limit=200`);
        const data = await response.json();
        const alerts = data.alerts || [];
        populateAlertsTable(alerts);

        const pending = alerts.filter(a => !a.acknowledged).length;
        const high = alerts.filter(a => ['critical', 'high'].includes(String(a.severity || '').toLowerCase())).length;
        const elTotal = document.getElementById('alerts-total');
        const elPending = document.getElementById('alerts-pending');
        const elHigh = document.getElementById('alerts-high');
        if (elTotal) elTotal.textContent = String(alerts.length);
        if (elPending) elPending.textContent = String(pending);
        if (elHigh) elHigh.textContent = String(high);
    } catch (error) {
        console.error('Error loading alerts:', error);
    }
}

async function loadEntitiesData() {
    try {
        const referenceOnly = document.getElementById('entity-reference-only')?.checked;
        const referenceSource = document.getElementById('entity-reference-source')?.value;
        const params = new URLSearchParams({ limit: '200' });

        if (referenceOnly) {
            params.set('reference_only', 'true');
            if (referenceSource) {
                params.set('reference_source', referenceSource);
            }
        }

        const query = `?${params.toString()}`;
        const response = await fetch(`${API_BASE}/entities${query}`);
        const data = await response.json();
        const entities = data.entities || [];
        populateEntitiesTable(entities);
        const total = entities.length;
        const avg = total ? (entities.reduce((s, e) => s + (e.confidence || 0), 0) / total) : 0;
        const highConf = entities.filter(e => (e.confidence || 0) >= 0.8).length;
        const elTotal = document.getElementById('entities-total');
        const elAvg = document.getElementById('entities-avg-conf');
        const elHigh = document.getElementById('entities-high-conf');
        if (elTotal) elTotal.textContent = String(total);
        if (elAvg) elAvg.textContent = avg.toFixed(3);
        if (elHigh) elHigh.textContent = String(highConf);
        searchEntities();
    } catch (error) {
        console.error('Error loading entities:', error);
    }
}

async function loadTrustData() {
    try {
        const [config, stats, feedback] = await Promise.all([
            fetch(`${API_BASE}/trust/config`).then(r => r.json()),
            fetch(`${API_BASE}/trust/stats`).then(r => r.json()),
            fetch(`${API_BASE}/trust/feedback?limit=50`).then(r => r.json())
        ]);
        
        // Populate config form
        if (config) {
            document.getElementById('threshold-medium').value = config.risk_medium_threshold || 45;
            document.getElementById('threshold-high').value = config.risk_high_threshold || 65;
            document.getElementById('threshold-critical').value = config.risk_critical_threshold || 80;
            document.getElementById('penalty-fp').value = config.false_positive_penalty || 0.1;
        }
        
        // Update stats
        if (stats) {
            document.getElementById('fb-total').textContent = stats.total_feedback || 0;
            document.getElementById('fb-fp-rate').textContent = ((stats.false_positive_rate || 0) * 100).toFixed(1) + '%';
            document.getElementById('fb-penalty').textContent = (stats.adaptive_penalty || 0).toFixed(3);
        }
        
        // Populate feedback table
        if (feedback.feedback) {
            populateFeedbackTable(feedback.feedback);
        }
    } catch (error) {
        console.error('Error loading trust data:', error);
    }
}

// ========== Table Population ==========

function populateCasesTable(cases, labelsMap = {}) {
    const tbody = document.querySelector('#cases-table tbody');
    if (!cases.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="loading">No cases found</td></tr>';
        return;
    }

    const _LABEL_CFG = {
        confirm_convergence: ['Confirmed', 'badge-confirmed'],
        reject_correlation:  ['Rejected',  'badge-rejected'],
        mark_high_priority:  ['Promoted',  'badge-promoted'],
    };

    tbody.innerHTML = cases.map(c => {
        const labelInfo = labelsMap[c.case_id];
        const analystBadges = labelInfo
            ? labelInfo.labels
                .map(l => {
                    const [text, cls] = _LABEL_CFG[l] || [l, ''];
                    return `<span class="analyst-badge ${cls}" title="${l}">${text}</span>`;
                })
                .join('')
            : '';
        return `
        <tr>
            <td><code>${c.case_id.substring(0, 12)}</code> ${authorityBadgeHtml(c.case_id, true)}${analystBadges}</td>
            <td><span class="status-badge status-${c.status}">${c.status.replace('_', ' ').toUpperCase()}</span></td>
            <td>${c.risk_score?.toFixed(1) || 'N/A'}</td>
            <td>
                ${c.priority_score != null ? c.priority_score.toFixed(1) : 'N/A'}
                ${c.priority_band ? `<div class="table-subtle">${c.priority_band.toUpperCase()}</div>` : ''}
            </td>
            <td>${(c.system_confidence || 0).toFixed(3)}</td>
            <td>${(c.entity_ids || []).length}</td>
            <td>${(c.signal_ids || []).length}</td>
            <td>${new Date(c.created_at).toLocaleDateString()}</td>
            <td>
                <button class="btn btn-secondary btn-small" onclick="viewCaseDetail('${c.case_id}')">View</button>
                <button class="btn btn-secondary btn-small" onclick="openCaseFiles('${c.case_id}')">Files</button>
            </td>
        </tr>
        `;
    }).join('');
}

function populateAlertsTable(alerts) {
    const tbody = document.querySelector('#alerts-table tbody');
    if (!alerts.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">No alerts found</td></tr>';
        return;
    }
    
    tbody.innerHTML = alerts.map(a => `
        <tr>
            <td><code>${a.alert_id.substring(0, 12)}</code></td>
            <td><span class="severity-${a.severity}">${a.severity.toUpperCase()}</span></td>
            <td>${a.message}</td>
            <td>${a.case_id}</td>
            <td>${new Date(a.triggered_at).toLocaleString()}</td>
            <td>${a.acknowledged ? '✓ Acknowledged' : '<span style="color: var(--warning);">Pending</span>'}</td>
            <td>${!a.acknowledged ? `<button class="btn btn-secondary btn-small" onclick="acknowledgeAlert('${a.alert_id}')">Acknowledge</button>` : 'N/A'}</td>
        </tr>
    `).join('');
}

function populateEntitiesTable(entities) {
    const tbody = document.querySelector('#entities-table tbody');
    if (!entities.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">No entities found</td></tr>';
        return;
    }
    
    tbody.innerHTML = entities.map(e => `
        <tr>
            <td><code>${e.entity_id.substring(0, 12)}</code></td>
            <td>
                ${e.display_name || e.canonical_name}
                ${e.record_badge ? `<span class="entity-badge reference">${e.record_badge}</span>` : ''}
                ${authorityBadgeHtml(e.entity_id, true)}
            </td>
            <td>${e.entity_type}</td>
            <td>${(e.confidence || 0).toFixed(3)}</td>
            <td>${e.source_count || 0}</td>
            <td>${new Date(e.created_at).toLocaleDateString()}</td>
            <td><button class="btn btn-secondary btn-small" onclick="viewEntityTimeline('${e.entity_id}')">Timeline</button></td>
        </tr>
    `).join('');
}

function populateFeedbackTable(feedbacks) {
    const tbody = document.querySelector('#feedback-table tbody');
    if (!feedbacks.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="loading">No feedback yet</td></tr>';
        return;
    }
    
    tbody.innerHTML = feedbacks.map(fb => `
        <tr>
            <td><code>${fb.case_id.substring(0, 12)}</code></td>
            <td>${fb.analyst_id}</td>
            <td>${fb.is_false_positive ? '<span style="color: var(--danger);">❌ FP</span>' : '<span style="color: var(--success);">✓ Valid</span>'}</td>
            <td>${fb.corrected_risk_score ? fb.corrected_risk_score.toFixed(1) : 'N/A'}</td>
            <td>${new Date(fb.created_at).toLocaleDateString()}</td>
        </tr>
    `).join('');
}

function updateRecentCases(cases) {
    const criticalCases = cases.filter(c => c.risk_score && c.risk_score > 70).slice(0, 10);
    document.querySelector('#recent-cases-table tbody').innerHTML = criticalCases.map(c => `
        <tr>
            <td><code>${c.case_id.substring(0, 12)}</code> ${authorityBadgeHtml(c.case_id, true)}</td>
            <td><span class="status-badge status-${c.status}">${c.status.replace('_', ' ').toUpperCase()}</span></td>
            <td>${c.risk_score?.toFixed(1) || 'N/A'}</td>
            <td>${(c.system_confidence || 0).toFixed(3)}</td>
            <td>${new Date(c.created_at).toLocaleDateString()}</td>
            <td><button class="btn btn-secondary btn-small" onclick="viewCaseDetail('${c.case_id}')">View</button></td>
        </tr>
    `).join('') || '<tr><td colspan="6" class="loading">No critical cases</td></tr>';
}

async function loadCrossSourceLinks() {
    const tbody = document.querySelector('#cross-source-links-table tbody');
    if (!tbody) return;

    try {
        const response = await fetch(`${API_BASE}/links/cross-source?days=90&max_candidates=8`);
        const data = await response.json();
        const candidates = data.candidates || [];

        if (!candidates.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="loading">No cross-source candidates in the current window</td></tr>';
            return;
        }

        tbody.innerHTML = candidates.map(link => `
            <tr>
                <td>
                    <div>${link.anchor.entity_name || link.anchor.label}</div>
                    <div class="table-subtle">${authorityBadgeHtml(link.anchor.source_name)} ${link.anchor.source_name || 'unknown'}</div>
                </td>
                <td>
                    <div>${link.target.entity_name || link.target.label}</div>
                    <div class="table-subtle">${authorityBadgeHtml(link.target.source_name)} ${link.target.source_name || 'unknown'}</div>
                </td>
                <td>${(link.link_reasons || []).slice(0, 2).join(', ')}</td>
                <td><strong>${(link.score || 0).toFixed(3)}</strong></td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('Error loading cross-source links:', error);
        tbody.innerHTML = '<tr><td colspan="4" class="loading">Unable to load cross-source candidates</td></tr>';
    }
}

// ========== Charts ==========

function updateCharts(cases) {
    // Risk distribution chart
    const riskBands = {
        'Low (0-45)': cases.filter(c => c.risk_score < 45).length,
        'Medium (45-65)': cases.filter(c => c.risk_score >= 45 && c.risk_score < 65).length,
        'High (65-80)': cases.filter(c => c.risk_score >= 65 && c.risk_score < 80).length,
        'Critical (80+)': cases.filter(c => c.risk_score >= 80).length
    };
    
    const riskCtx = document.getElementById('risk-chart');
    if (!riskChart) {
        riskChart = new Chart(riskCtx, {
            type: 'doughnut',
            data: {
                labels: Object.keys(riskBands),
                datasets: [{
                    data: Object.values(riskBands),
                    backgroundColor: [
                        'rgba(16, 185, 129, 0.8)',
                        'rgba(245, 158, 11, 0.8)',
                        'rgba(239, 68, 68, 0.8)',
                        'rgba(220, 38, 38, 0.8)'
                    ],
                    borderColor: '#1e293b',
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#cbd5e1', font: { size: 12 } }
                    }
                }
            }
        });
    } else {
        riskChart.data.labels = Object.keys(riskBands);
        riskChart.data.datasets[0].data = Object.values(riskBands);
        riskChart.update();
    }
    
    // Signal types chart
    const signalCounts = {};
    cases.forEach(c => {
        (c.signal_ids || []).forEach(sid => {
            signalCounts[sid] = (signalCounts[sid] || 0) + 1;
        });
    });

    const sortedSignals = Object.entries(signalCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10);
    
    const signalsCtx = document.getElementById('signals-chart');
    const topLabels = sortedSignals.map(item => item[0]);
    const topData = sortedSignals.map(item => item[1]);
    const labels = topLabels.length ? topLabels : ['No data'];
    const data = topData.length ? topData : [0];

    if (!signalsChart) {
        signalsChart = new Chart(signalsCtx, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: 'Detected',
                    data,
                    backgroundColor: 'rgba(37, 99, 235, 0.8)',
                    borderColor: 'rgba(37, 99, 235, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                indexAxis: 'y',
                plugins: {
                    legend: { labels: { color: '#cbd5e1', font: { size: 12 } } }
                },
                scales: {
                    x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                    y: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } }
                }
            }
        });
    } else {
        signalsChart.data.labels = labels;
        signalsChart.data.datasets[0].data = data;
        signalsChart.update();
    }
}

// ========== Case Management ==========

async function viewCaseDetail(caseId) {
    currentCaseId = caseId;
    try {
        const [caseData, summary, explainability] = await Promise.all([
            fetch(`${API_BASE}/cases/${caseId}`).then(r => r.json()),
            fetch(`${API_BASE}/cases/${caseId}/summary`).then(r => r.json()),
            fetch(`${API_BASE}/cases/${caseId}/explainability`).then(r => r.json())
        ]);
        
        // Populate case detail
        const detailHtml = `
            <h2>Case: ${caseData.case_id}</h2>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 16px 0;">
                <div><strong>Status:</strong> <span class="status-badge status-${caseData.status}">${caseData.status}</span></div>
                <div><strong>Risk Score:</strong> ${caseData.risk_score?.toFixed(1)}</div>
                <div><strong>Priority:</strong> ${caseData.priority_score != null ? caseData.priority_score.toFixed(1) : 'N/A'} ${caseData.priority_band ? `(${caseData.priority_band.toUpperCase()})` : ''}</div>
                <div><strong>Confidence:</strong> ${(caseData.system_confidence || 0).toFixed(3)}</div>
                <div><strong>Created:</strong> ${new Date(caseData.created_at).toLocaleString()}</div>
                <div><strong>Entities:</strong> ${(caseData.entity_ids || []).length}</div>
                <div><strong>Signals:</strong> ${(caseData.signal_ids || []).length}</div>
            </div>
            <div>${authorityBadgeHtml(caseData.case_id, true)}</div>
        `;
        document.getElementById('case-detail-content').innerHTML = detailHtml;
        
        // Summary tab
        document.getElementById('case-summary-tab').innerHTML = `
            <div>
                <h3>Summary</h3>
                <p>${summary.summary || 'No summary available'}</p>
                <p style="font-size: 12px; color: var(--text-tertiary); margin-top: 8px;">
                    Potential correlation only. This output is an investigative triage aid and not a legal determination.
                </p>
                <div style="margin-top: 16px;">
                    <h4>Signals Detected</h4>
                    <ul style="list-style-position: inside; color: var(--text-secondary);">
                        ${(summary.signal_summary || []).map(s => `<li>${s}</li>`).join('')}
                    </ul>
                </div>
            </div>
        `;
        
        // Explainability tab
        if (explainability.signal_contributions) {
            const sigHtml = explainability.signal_contributions.map(sig => `
                <div style="padding: 12px; background: var(--bg-tertiary); border-radius: var(--radius-md); margin: 8px 0;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <strong>${sig.signal_type}</strong>
                        <span>${sig.weight_pct.toFixed(1)}%</span>
                    </div>
                    <div style="background: var(--bg-secondary); height: 8px; border-radius: 4px; overflow: hidden;">
                        <div style="width: ${sig.weight_pct}%; height: 100%; background: var(--primary);"></div>
                    </div>
                    <small style="color: var(--text-tertiary);">${sig.confidence.toFixed(3)} confidence · ${sig.source_name || 'unknown source'}</small>
                </div>
            `).join('');
            
            document.getElementById('case-explainability-tab').innerHTML = `
                <div>
                    <h3>Signal Contributions</h3>
                    ${sigHtml}
                    <div style="margin-top: 24px; padding: 16px; background: var(--bg-tertiary); border-radius: var(--radius-md);">
                        <h4>Confidence Breakdown</h4>
                        <p style="font-size: 13px; color: var(--text-secondary);">
                            Final confidence: <strong>${explainability.confidence_breakdown.final_system_confidence.toFixed(3)}</strong>
                        </p>
                    </div>
                    <div style="margin-top: 12px; padding: 16px; background: var(--bg-tertiary); border-radius: var(--radius-md);">
                        <h4>Priority Ranking</h4>
                        <p style="font-size: 13px; color: var(--text-secondary);">
                            Score: <strong>${(explainability.priority?.priority_score || 0).toFixed(1)}</strong>
                            (${(explainability.priority?.priority_band || 'routine').toUpperCase()})
                        </p>
                        <p style="font-size: 12px; color: var(--text-secondary); margin-top: 6px;">
                            Corroboration tier: <strong>${(explainability.priority?.corroboration_tier || 'tier_0_single_source').replaceAll('_', ' ')}</strong>
                        </p>
                        <p style="font-size: 12px; color: var(--text-secondary); margin-top: 6px;">
                            Independent corroboration: 
                            <strong>${explainability.priority?.independent_corroboration?.linked_cases || 0}</strong> linked cases,
                            <strong>${explainability.priority?.independent_corroboration?.source_families || 0}</strong> source families,
                            <strong>${explainability.priority?.independent_corroboration?.strong_matches || 0}</strong> strong matches,
                            confidence <strong>${(explainability.priority?.independent_corroboration?.confidence || 0).toFixed(2)}</strong>
                        </p>
                        <p style="font-size: 12px; color: var(--text-tertiary); margin-top: 8px;">
                            ${explainability.priority?.priority_explanation || 'Priority explanation unavailable.'}
                        </p>
                    </div>
                    ${renderSourceImpactHtml(explainability.source_impact, explainability.score_calibration)}
                </div>
            `;
        }
        
        // Feedback tab
        if (explainability.feedback_summary) {
            const decisionCounts = explainability.feedback_summary.decision_counts || {};
            const fbHtml = explainability.feedback_summary.recent_feedback.map(fb => `
                <div style="padding: 12px; background: var(--bg-tertiary); border-radius: var(--radius-md); margin: 8px 0;">
                    <div style="display: flex; justify-content: space-between;">
                        <div>
                            <strong>${fb.analyst_id}</strong>
                            <span style="margin-left: 8px; color: ${fb.is_false_positive ? 'var(--danger)' : 'var(--success)'};">
                                ${fb.is_false_positive ? '❌ False Positive' : '✓ Confirmed'}
                            </span>
                        </div>
                        <span style="color: var(--text-tertiary);">${new Date(fb.created_at).toLocaleDateString()}</span>
                    </div>
                    <p style="margin-top: 6px; font-size: 12px; color: var(--text-tertiary);">
                        Decision: <strong>${(fb.decision_type || 'unlabeled').replaceAll('_', ' ')}</strong>
                    </p>
                    <p style="margin-top: 8px; font-size: 13px; color: var(--text-secondary);">${fb.notes || 'No notes'}</p>
                </div>
            `).join('');
            
            document.getElementById('case-feedback-tab').innerHTML = `
                <div>
                    <h3>Analyst Feedback</h3>
                    <p style="font-size: 13px; color: var(--text-secondary);">
                        Total feedback: ${explainability.feedback_summary.feedback_count} | 
                        False positives: ${explainability.feedback_summary.false_positive_count} (${(explainability.feedback_summary.false_positive_rate * 100).toFixed(1)}%)
                    </p>
                    <p style="font-size: 12px; color: var(--text-secondary); margin-top: 6px;">
                        Decisions: confirm ${decisionCounts.confirm_convergence || 0}, reject ${decisionCounts.reject_correlation || 0}, high priority ${decisionCounts.mark_high_priority || 0}
                    </p>

                    <div style="margin-top: 14px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px;">
                        <button class="btn btn-secondary" onclick="submitCaseDecision('confirm_convergence')">Confirm Convergence</button>
                        <button class="btn btn-secondary" onclick="submitCaseDecision('reject_correlation')">Reject Correlation</button>
                        <button class="btn btn-primary" onclick="submitCaseDecision('mark_high_priority')">Mark High Priority</button>
                    </div>
                    ${fbHtml || '<p style="color: var(--text-tertiary);">No feedback yet</p>'}
                </div>
            `;
        }

        await renderCaseFilesTab(caseData.case_id);
        
        showCaseTab('summary');
        document.getElementById('case-modal').classList.add('active');
    } catch (error) {
        console.error('Error loading case detail:', error);
        document.getElementById('case-detail-content').innerHTML = '<p style="color: var(--danger);">Error loading case details</p>';
    }
}

function openCaseFiles(caseId) {
    viewCaseDetail(caseId).then(() => showCaseTab('files'));
}

async function renderCaseFilesTab(caseId) {
    const tab = document.getElementById('case-files-tab');
    if (!tab) return;

    let docRows = [];
    try {
        const resp = await fetch(`${API_BASE}/ingest/documents?case_id=${encodeURIComponent(caseId)}&limit=50`);
        if (resp.ok) {
            const payload = await resp.json();
            docRows = payload.documents || [];
        }
    } catch (_) {
        // Non-critical; file links below still render.
    }

    const docHtml = docRows.length
        ? docRows.map(d => `
            <tr>
                <td>${d.file_name || 'document'}</td>
                <td>${d.imported_at ? new Date(d.imported_at).toLocaleString() : 'n/a'}</td>
                <td>${d.size_bytes || 0}</td>
                <td><button class="btn btn-secondary btn-small" onclick="window.open('${API_BASE}/ingest/documents/${d.doc_id}/download','_blank')">Open</button></td>
            </tr>
          `).join('')
        : '<tr><td colspan="4" class="loading">No linked documents yet</td></tr>';

    tab.innerHTML = `
        <div>
            <h3>Case Files</h3>
            <div style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0 14px;">
                <button class="btn btn-secondary" onclick="window.open('${API_BASE}/cases/${caseId}/explainability/html','_blank')">Open Explainability Report</button>
                <button class="btn btn-secondary" onclick="window.open('${API_BASE}/system/tier4-proof/report.pdf?case_id=${encodeURIComponent(caseId)}','_blank')">Open Tier 4 PDF</button>
                <button class="btn btn-secondary" onclick="verifyArchiveCase('${caseId}')">Verify Integrity</button>
            </div>
            <div class="table-container">
                <table>
                    <thead><tr><th>Document</th><th>Imported At</th><th>Bytes</th><th>Action</th></tr></thead>
                    <tbody>${docHtml}</tbody>
                </table>
            </div>
        </div>
    `;
}

function closeCaseModal() {
    document.getElementById('case-modal').classList.remove('active');
}

function showCaseTab(tabName, triggerButton = null) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));
    document.getElementById(`case-${tabName}-tab`).classList.add('active');

    const targetButton = triggerButton || document.querySelector(`.tab-button[data-tab="${tabName}"]`);
    if (targetButton) {
        targetButton.classList.add('active');
    }
}

async function submitCaseDecision(decisionType) {
    if (!currentCaseId) return;
    const analystId = prompt('Analyst ID:');
    if (!analystId) return;
    const analystRole = (prompt('Analyst role (junior_analyst | senior_analyst | trusted_operator):', 'junior_analyst') || 'junior_analyst').trim();
    const notes = prompt('Optional notes:') || null;

    try {
        const response = await fetch(`${API_BASE}/cases/${currentCaseId}/feedback/decision`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                analyst_id: analystId,
                analyst_role: analystRole,
                decision_type: decisionType,
                notes,
            }),
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || 'Failed to submit analyst decision');
        }
        await viewCaseDetail(currentCaseId);
        await loadTrustData();
        alert(`Decision recorded: ${(payload.decision_type || decisionType).replaceAll('_', ' ')}`);
    } catch (error) {
        console.error('Error submitting analyst decision:', error);
        alert('Failed to submit analyst decision');
    }
}

// ========== Filtering ==========

function filterCases() {
    const searchTerm = document.getElementById('case-search').value.toLowerCase();
    const status = document.getElementById('case-status-filter').value;
    
    const rows = document.querySelectorAll('#cases-table tbody tr:not(.loading)');
    rows.forEach(row => {
        const caseId = row.cells[0].textContent.toLowerCase();
        const rowStatus = row.cells[1].textContent.toLowerCase();
        const matchSearch = caseId.includes(searchTerm);
        const matchStatus = !status || rowStatus.includes(status);
        row.style.display = matchSearch && matchStatus ? '' : 'none';
    });
}

function filterAlerts() {
    const severity = document.getElementById('alert-severity-filter').value;
    const unacknowledgedOnly = document.getElementById('alert-unacknowledged-only').checked;
    
    const rows = document.querySelectorAll('#alerts-table tbody tr:not(.loading)');
    rows.forEach(row => {
        const rowSeverity = row.cells[1].textContent.toLowerCase();
        const rowStatus = row.cells[5].textContent;
        const matchSeverity = !severity || rowSeverity.includes(severity);
        const matchAcknowledged = !unacknowledgedOnly || !rowStatus.includes('Acknowledged');
        row.style.display = matchSeverity && matchAcknowledged ? '' : 'none';
    });
}

function searchEntities() {
    const term = document.getElementById('entity-search').value.toLowerCase();
    const rows = document.querySelectorAll('#entities-table tbody tr:not(.loading)');
    rows.forEach(row => {
        const name = row.cells[1].textContent.toLowerCase();
        row.style.display = name.includes(term) ? '' : 'none';
    });
}

// ========== Actions ==========

async function acknowledgeAlert(alertId) {
    try {
        await fetch(`${API_BASE}/alerts/${alertId}/acknowledge`, { method: 'PATCH' });
        loadAlertsData();
        alert('Alert acknowledged');
    } catch (error) {
        console.error('Error acknowledging alert:', error);
    }
}

async function viewEntityTimeline(entityId) {
    try {
        const response = await fetch(`${API_BASE}/entities/${entityId}/timeline`);
        const data = await response.json();
        alert(`Timeline for ${entityId}\n\nEvents: ${data.events.length}\n\nRecent:\n${data.events.slice(0, 3).map(e => `• ${e.event_type}: ${e.summary}`).join('\n')}`);
    } catch (error) {
        console.error('Error loading timeline:', error);
    }
}

async function saveTrustConfig() {
    try {
        const config = {
            risk_medium_threshold: parseFloat(document.getElementById('threshold-medium').value),
            risk_high_threshold: parseFloat(document.getElementById('threshold-high').value),
            risk_critical_threshold: parseFloat(document.getElementById('threshold-critical').value),
            false_positive_penalty: parseFloat(document.getElementById('penalty-fp').value)
        };
        
        await fetch(`${API_BASE}/trust/config`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        
        alert('Configuration saved successfully');
        loadTrustData();
    } catch (error) {
        console.error('Error saving config:', error);
        alert('Error saving configuration');
    }
}

async function importNamUsLeads() {
    const button = document.getElementById('namus-import-btn');
    const status = document.getElementById('namus-import-status');
    if (!button || !status) {
        return;
    }

    const caseSet = document.getElementById('namus-case-set')?.value || 'MissingPersons';
    const lastName = document.getElementById('namus-last-name')?.value.trim() || null;
    const firstName = document.getElementById('namus-first-name')?.value.trim() || null;
    const state = document.getElementById('namus-state')?.value.trim() || null;
    const caseNumber = document.getElementById('namus-case-number')?.value.trim() || null;

    try {
        button.disabled = true;
        const previousLabel = button.textContent;
        button.textContent = 'Importing...';
        status.textContent = 'Running';
        status.className = 'import-status running';

        const body = {
            live: true,
            pages: 1,
            per_page: 25,
            fetch_details: true,
            case_set: caseSet,
            last_name: lastName,
            first_name: firstName,
            state: state,
            case_number: caseNumber,
        };

        const response = await fetch(`${API_BASE}/ingest/namus`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        const payload = await response.json();
        if (!response.ok || payload.status === 'rejected') {
            throw new Error(payload.reason || 'NamUs import failed');
        }

        const result = payload.result || {};
        if (payload.status === 'skipped') {
            status.textContent = 'Skipped';
            status.className = 'import-status warning';
            alert(`NamUs import skipped: ${result.reason || 'No data processed'}`);
        } else {
            const loaded = result.records_loaded ?? 0;
            const created = result.cases_created ?? 0;
            const label = { MissingPersons: 'Missing', UnidentifiedPersons: 'Unidentified', UnclaimedPersons: 'Unclaimed' }[caseSet] || caseSet;
            status.textContent = `Imported ${created}`;
            status.className = 'import-status success';
            alert(`NamUs ${label} import complete. Loaded ${loaded} records and created ${created} cases.`);
        }

        await loadDashboardData();
        await loadCasesData();
        await loadEntitiesData();
    } catch (error) {
        console.error('Error importing NamUs leads:', error);
        status.textContent = 'Error';
        status.className = 'import-status error';
        alert(`NamUs import failed: ${error.message || 'Unknown error'}`);
    } finally {
        button.disabled = false;
        button.textContent = 'Import NamUs';
    }
}

async function importInterpolLeads() {
    const button = document.getElementById('interpol-import-btn');
    const status = document.getElementById('interpol-import-status');
    if (!button || !status) return;

    try {
        button.disabled = true;
        button.textContent = 'Importing...';
        status.textContent = 'Running';
        status.className = 'import-status running';

        const response = await fetch(`${API_BASE}/ingest/interpol`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ live: true, pages: 1, fetch_details: true }),
        });

        const payload = await response.json();
        if (!response.ok || payload.status === 'rejected') {
            throw new Error(payload.reason || 'Interpol import failed');
        }

        const result = payload.result || {};
        if (payload.status === 'skipped') {
            status.textContent = 'Skipped';
            status.className = 'import-status warning';
            alert(`Interpol import skipped: ${result.reason || 'No data processed'}`);
        } else {
            const loaded = result.records_loaded ?? 0;
            const created = result.cases_created ?? 0;
            status.textContent = `Imported ${created}`;
            status.className = 'import-status success';
            alert(`Interpol import complete. Loaded ${loaded} notices and created ${created} cases.`);
        }

        await loadDashboardData();
        await loadCasesData();
        await loadEntitiesData();
    } catch (error) {
        console.error('Error importing Interpol notices:', error);
        status.textContent = 'Error';
        status.className = 'import-status error';
        alert(`Interpol import failed: ${error.message || 'Unknown error'}`);
    } finally {
        button.disabled = false;
        button.textContent = 'Import Interpol Notices';
    }
}

async function importNewsApiLeads() {
    const button = document.getElementById('newsapi-import-btn');
    const status = document.getElementById('newsapi-import-status');
    if (!button || !status) return;

    try {
        button.disabled = true;
        button.textContent = 'Importing...';
        status.textContent = 'Running';
        status.className = 'import-status running';

        const response = await fetch(`${API_BASE}/ingest/newsapi`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });

        const payload = await response.json();
        if (!response.ok || payload.status === 'rejected') {
            throw new Error(payload.reason || 'NewsAPI import failed');
        }

        const result = payload.result || {};
        if (payload.status === 'skipped') {
            status.textContent = 'Skipped';
            status.className = 'import-status warning';
            alert(`NewsAPI import skipped: ${result.reason || 'No data processed'}`);
        } else {
            const articles = result.articles_found ?? 0;
            const signals = result.signals_created ?? result.imported_count ?? 0;
            status.textContent = `Imported ${signals}`;
            status.className = 'import-status success';
            alert(`NewsAPI import complete. Found ${articles} articles and created ${signals} signals.`);
        }

        await loadDashboardData();
        await loadCasesData();
        await loadEntitiesData();
    } catch (error) {
        console.error('Error importing NewsAPI signals:', error);
        status.textContent = 'Error';
        status.className = 'import-status error';
        alert(`NewsAPI import failed: ${error.message || 'Unknown error'}`);
    } finally {
        button.disabled = false;
        button.textContent = 'Import News Signals';
    }
}

async function importCourtListenerLeads() {
    const button = document.getElementById('courtlistener-import-btn');
    const status = document.getElementById('courtlistener-import-status');
    if (!button || !status) return;

    try {
        button.disabled = true;
        button.textContent = 'Importing...';
        status.textContent = 'Running';
        status.className = 'import-status running';

        const response = await fetch(`${API_BASE}/ingest/courtlistener`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pages_per_query: 2,
                page_size: 20,
                ai_enrich: true,
                ai_max_records: 20,
            }),
        });

        const payload = await response.json();
        if (!response.ok || payload.status === 'rejected') {
            throw new Error(payload.reason || payload.result?.reason || 'CourtListener import failed');
        }

        const result = payload.result || {};
        if (payload.status === 'skipped') {
            status.textContent = 'Skipped';
            status.className = 'import-status warning';
            alert(`CourtListener import skipped: ${result.reason || 'No data processed'}`);
        } else {
            const seen = result.results_seen ?? 0;
            const created = result.cases_created ?? result.imported_count ?? 0;
            const aiCount = result.ai_enriched_count ?? 0;
            const aiProvider = result.ai_provider || 'none';
            status.textContent = `Imported ${created}`;
            status.className = 'import-status success';
            alert(
                `CourtListener import complete. Processed ${seen} legal results and created ${created} cases.\n` +
                `AI enrichment: ${aiCount} record(s) via ${aiProvider}.`
            );
        }

        await loadDashboardData();
        await loadCasesData();
        await loadEntitiesData();
    } catch (error) {
        console.error('Error importing CourtListener records:', error);
        status.textContent = 'Error';
        status.className = 'import-status error';
        alert(`CourtListener import failed: ${error.message || 'Unknown error'}`);
    } finally {
        button.disabled = false;
        button.textContent = 'Import CourtListener';
    }
}

async function recomputeAuthorityScores() {
    const button = document.getElementById('recompute-authority-btn');
    const status = document.getElementById('recompute-authority-status');
    if (!button || !status) return;

    try {
        button.disabled = true;
        button.textContent = 'Normalizing...';
        status.textContent = 'Running';
        status.className = 'import-status running';

        const response = await fetch(`${API_BASE}/cases/recompute-authority?limit=500`, {
            method: 'POST',
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || payload.reason || 'Normalization failed');
        }

        const result = payload.result || {};
        status.textContent = `Updated ${result.updated || 0}`;
        status.className = 'import-status success';

        alert(
            `Case scoring normalization complete. Processed ${result.processed || 0} cases and updated ${result.updated || 0}.`
        );

        await loadDashboardData();
        await loadCasesData();
    } catch (error) {
        console.error('Error normalizing case scoring:', error);
        status.textContent = 'Error';
        status.className = 'import-status error';
        alert(`Case scoring normalization failed: ${error.message || 'Unknown error'}`);
    } finally {
        button.disabled = false;
        button.textContent = 'Normalize Case Scoring';
    }
}

async function importFBILeads() {
    const button = document.getElementById('fbi-import-btn');
    const status = document.getElementById('fbi-import-status');
    if (!button || !status) return;

    try {
        button.disabled = true;
        button.textContent = 'Importing...';
        status.textContent = 'Running';
        status.className = 'import-status running';

        const response = await fetch(`${API_BASE}/ingest/fbi`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pages: 10, per_page: 50 }),
        });

        const payload = await response.json();
        if (!response.ok || payload.status === 'rejected') {
            throw new Error(payload.reason || payload.result?.reason || 'FBI import failed');
        }

        const result = payload.result || {};
        if (payload.status === 'skipped') {
            status.textContent = 'Skipped';
            status.className = 'import-status warning';
            alert(`FBI import skipped: ${result.reason || 'No data processed'}`);
        } else {
            const fetched = result.records_fetched ?? 0;
            const matched = result.records_matched ?? 0;
            const created = result.cases_created ?? result.imported_count ?? 0;
            status.textContent = `Imported ${created}`;
            status.className = 'import-status success';
            alert(
                `FBI Most Wanted import complete.\n` +
                `Fetched: ${fetched} records | Matched: ${matched} | Cases created: ${created}\n` +
                `Lists: ${(result.lists || []).join(', ')}`
            );
        }

        await loadDashboardData();
        await loadCasesData();
        await loadEntitiesData();
    } catch (error) {
        console.error('Error importing FBI records:', error);
        status.textContent = 'Error';
        status.className = 'import-status error';
        alert(`FBI import failed: ${error.message || 'Unknown error'}`);
    } finally {
        button.disabled = false;
        button.textContent = 'Import FBI Wanted';
    }
}

async function importDocuments() {
    const fileInput = document.getElementById('doc-import-files');
    const caseInput = document.getElementById('doc-import-case-id');
    const button = document.getElementById('doc-import-btn');
    const status = document.getElementById('doc-import-status');
    if (!fileInput || !button || !status) return;
    const files = fileInput.files;
    if (!files || files.length === 0) {
        alert('Select one or more documents first.');
        return;
    }

    try {
        button.disabled = true;
        status.textContent = 'Uploading';
        status.className = 'import-status running';

        const form = new FormData();
        for (const f of files) form.append('files', f);
        const caseId = (caseInput?.value || '').trim();
        if (caseId) form.append('case_id', caseId);
        form.append('source_name', 'analyst_upload');

        const resp = await fetch(`${API_BASE}/ingest/documents`, {
            method: 'POST',
            body: form,
        });
        const payload = await resp.json();
        if (!resp.ok) {
            throw new Error(payload.detail || payload.reason || 'Document import failed');
        }

        status.textContent = `Imported ${payload.imported_count || 0}`;
        status.className = 'import-status success';
        fileInput.value = '';
        alert(`Imported ${payload.imported_count || 0} document(s).`);

        if (caseId && currentCaseId === caseId) {
            await renderCaseFilesTab(caseId);
        }
        if (document.querySelector('.section.active')?.id === 'archive') {
            await loadArchiveData();
        }
    } catch (error) {
        console.error('Error importing documents:', error);
        status.textContent = 'Error';
        status.className = 'import-status error';
        alert(`Document import failed: ${error.message || 'Unknown error'}`);
    } finally {
        button.disabled = false;
    }
}

function initializeTemporaryDropzone() {
    const zone = document.getElementById('temp-dropzone');
    const picker = document.getElementById('temp-doc-files');
    if (!zone || !picker) return;

    ['dragenter', 'dragover'].forEach(evt => {
        zone.addEventListener(evt, e => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.add('dragover');
        });
    });
    ['dragleave', 'drop'].forEach(evt => {
        zone.addEventListener(evt, e => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.remove('dragover');
        });
    });
    zone.addEventListener('drop', e => {
        const files = Array.from(e.dataTransfer?.files || []);
        setTemporaryAnalysisFiles(files);
    });
}

function triggerTempFilePicker() {
    const picker = document.getElementById('temp-doc-files');
    if (picker) picker.click();
}

function handleTempFilesSelected(event) {
    const files = Array.from(event?.target?.files || []);
    setTemporaryAnalysisFiles(files);
}

function setTemporaryAnalysisFiles(files) {
    temporaryAnalysisFiles = files || [];
    temporaryAnalysisPayload = null;
    temporaryChatMessages = [];
    temporarySessionId = null;
    renderTemporaryChatTranscript();
    const list = document.getElementById('temp-doc-list');
    if (!list) return;
    if (!temporaryAnalysisFiles.length) {
        list.innerHTML = '<em>No files selected.</em>';
        return;
    }
    list.innerHTML = temporaryAnalysisFiles
        .map(f => `<div>• ${f.name} (${(f.size || 0).toLocaleString()} bytes)</div>`)
        .join('');
}

async function analyzeTempDocuments() {
    const button = document.getElementById('temp-doc-analyze-btn');
    const status = document.getElementById('temp-doc-status');
    const context = document.getElementById('temp-doc-context')?.value || '';
    const reportEl = document.getElementById('temp-doc-report');
    const keyInput = document.getElementById('temp-chat-access-key');
    const sensitiveMode = !!document.getElementById('temp-sensitive-mode')?.checked;

    if (!temporaryAnalysisFiles.length) {
        alert('Drop or select documents first.');
        return;
    }

    try {
        if (button) button.disabled = true;
        if (status) {
            status.textContent = 'Analyzing';
            status.className = 'import-status running';
        }
        if (reportEl) reportEl.innerHTML = '<div class="telemetry-empty">Analyzing temporary documents...</div>';

        const form = new FormData();
        for (const f of temporaryAnalysisFiles) form.append('files', f);
        if (context.trim()) form.append('analyst_context', context.trim());
        if (sensitiveMode) form.append('sensitive_mode', 'true');
        const analyst = currentAnalystContext();
        if (analyst.analystId) form.append('analyst_id', analyst.analystId);
        if (analyst.analystRole) form.append('analyst_role', analyst.analystRole);

        const headers = {};
        const key = (keyInput?.value || '').trim();
        if (key) headers['X-Investigation-Key'] = key;

        const resp = await fetch(`${API_BASE}/analyze/documents-temporary`, {
            method: 'POST',
            headers,
            body: form,
        });
        const payload = await resp.json();
        if (!resp.ok) {
            throw new Error(payload.detail || payload.reason || 'Temporary analysis failed');
        }

        if (status) {
            status.textContent = 'Analyzed';
            status.className = 'import-status success';
        }

        temporaryAnalysisPayload = payload;
        temporarySessionId = payload.session_id || null;
        temporarySessionSensitiveMode = !!payload.sensitive_mode;
        temporaryChatMessages = [];
        renderTemporaryChatTranscript();
        renderTemporaryReport(payload);

        const metaEl = document.getElementById('temp-session-meta');
        if (metaEl) {
            metaEl.innerHTML = payload.session_id
                ? `Session: <strong>${payload.session_id}</strong> | Expires: ${new Date(payload.session_expires_at).toLocaleString()} | Sensitive mode: ${temporarySessionSensitiveMode ? 'ON' : 'OFF'}`
                : '';
        }
    } catch (error) {
        console.error('Temporary analysis error:', error);
        if (status) {
            status.textContent = 'Error';
            status.className = 'import-status error';
        }
        if (reportEl) {
            reportEl.innerHTML = `<div style="color: var(--danger);">${error.message || 'Analysis failed'}</div>`;
        }
    } finally {
        if (button) button.disabled = false;
    }
}

function renderTemporaryReport(payload) {
    const reportEl = document.getElementById('temp-doc-report');
    if (!reportEl) return;
    const report = payload.report || {};
    const signals = report.signals || [];
    const docs = payload.documents || [];
    const overlap = payload.document_correlation || {};
    const suggestions = payload.case_suggestions || [];

    reportEl.innerHTML = `
        <h4>Temporary Investigation Report</h4>
        <div class="temp-disclaimer">${payload.temporary_disclaimer || 'Temporary analysis only: this output is not stored as verified system evidence.'}</div>
        <p style="font-size:13px;color:var(--text-secondary);">${report.summary || 'No summary generated.'}</p>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:10px 0;">
            <div class="stat-mini"><div class="label">Risk Score</div><div class="value">${Number(report.risk_score || 0).toFixed(1)}</div></div>
            <div class="stat-mini"><div class="label">Confidence</div><div class="value">${Number(report.system_confidence || 0).toFixed(3)}</div></div>
            <div class="stat-mini"><div class="label">Detected Signals</div><div class="value">${signals.length}</div></div>
            <div class="stat-mini"><div class="label">Strong Signals (>=0.7)</div><div class="value">${Number(report.strong_signal_count || 0)}</div></div>
        </div>
        <p style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">Doc overlap score: <strong>${Number(overlap.overlap_score || 0).toFixed(3)}</strong> | Shared terms: ${(overlap.shared_terms || []).slice(0, 8).join(', ') || 'none'}</p>
        <div class="table-container">
            <table>
                <thead><tr><th>Signal</th><th>Confidence</th><th>Evidence</th><th>Action</th></tr></thead>
                <tbody>
                    ${signals.length ? signals.map(s => `
                        <tr>
                            <td>${s.signal_type || 'n/a'}</td>
                            <td><span class="temp-signal-confidence ${Number(s.confidence || 0) >= 0.7 ? 'strong' : Number(s.confidence || 0) >= 0.45 ? 'medium' : 'weak'}">${Number(s.confidence || 0).toFixed(3)}</span></td>
                            <td>${(s.evidence || '').slice(0, 120)}</td>
                            <td><button class="btn btn-secondary btn-small" onclick="askAboutSpecificSignal('${escapeHtml(s.signal_type || 'signal')}', '${escapeHtml((s.evidence || '').slice(0, 180))}')">Explain this signal</button></td>
                        </tr>
                    `).join('') : '<tr><td colspan="4" class="loading">No signals detected.</td></tr>'}
                </tbody>
            </table>
        </div>
        <div style="margin-top:10px;">
            <h4 style="margin-bottom:6px;">Suggested Case Matches</h4>
            <div class="table-container">
                <table>
                    <thead><tr><th>Case ID</th><th>Status</th><th>Risk</th><th>Match</th><th>Action</th></tr></thead>
                    <tbody>
                        ${suggestions.length ? suggestions.map(s => `
                            <tr>
                                <td><code>${s.case_id}</code></td>
                                <td>${(s.status || '').toUpperCase()}</td>
                                <td>${Number(s.risk_score || 0).toFixed(1)}</td>
                                <td>${Number(s.match_score || 0).toFixed(3)}</td>
                                <td><button class="btn btn-secondary btn-small" onclick="viewCaseDetail('${s.case_id}')">Open</button></td>
                            </tr>
                        `).join('') : '<tr><td colspan="5" class="loading">No close case matches found.</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
        <p style="font-size:12px;color:var(--text-tertiary);margin-top:8px;">${payload.disclaimer || ''}</p>
        <p style="font-size:12px;color:var(--text-tertiary);margin-top:4px;">Temporary mode: files are not stored. Processed ${docs.length} document(s).</p>
    `;
}

function askAboutSpecificSignal(signalType, evidenceSnippet) {
    const input = document.getElementById('temp-chat-input');
    if (!input) return;
    input.value = `Explain why signal "${signalType}" was flagged. Evidence: ${evidenceSnippet}`;
    sendTemporaryChatMessage();
}

function _temporaryChatContext() {
    const payload = temporaryAnalysisPayload || {};
    const report = payload.report || {};
    const contextText = (document.getElementById('temp-doc-context')?.value || '').trim();
    const docs = (payload.documents || []).map(d => ({
        file_name: d.file_name,
        extractable: d.extractable,
        extracted_chars: d.extracted_chars,
    }));
    return JSON.stringify({
        context_notes: contextText,
        report_summary: report.summary,
        risk_score: report.risk_score,
        confidence_score: report.system_confidence,
        signals: report.signals || [],
        document_correlation: payload.document_correlation || {},
        case_suggestions: payload.case_suggestions || [],
        documents: docs,
        temporary: true,
        stored: false,
    });
}

function renderTemporaryChatTranscript() {
    const el = document.getElementById('temp-chat-transcript');
    if (!el) return;
    if (!temporaryChatMessages.length) {
        el.innerHTML = '<div class="temp-chat-msg"><strong>System:</strong> No conversation yet. Analyze temporary documents first, then ask questions.</div>';
        return;
    }
    el.innerHTML = temporaryChatMessages
        .map(m => `<div class="temp-chat-msg"><strong>${m.role === 'assistant' ? 'Assistant' : 'You'}:</strong> ${escapeHtml(m.content)}</div>`)
        .join('');
    el.scrollTop = el.scrollHeight;
}

async function sendTemporaryChatMessage() {
    const input = document.getElementById('temp-chat-input');
    const button = document.getElementById('temp-chat-send-btn');
    const keyInput = document.getElementById('temp-chat-access-key');
    const text = (input?.value || '').trim();

    if (!temporaryAnalysisPayload) {
        alert('Run temporary analysis before starting secure chat.');
        return;
    }
    if (!text) {
        return;
    }

    temporaryChatMessages.push({ role: 'user', content: text });
    renderTemporaryChatTranscript();
    if (input) input.value = '';

    try {
        if (button) button.disabled = true;
        const form = new FormData();
        if (temporarySessionId) {
            form.append('session_id', temporarySessionId);
            form.append('user_message', text);
        } else {
            form.append('document_context', _temporaryChatContext());
            form.append('messages_json', JSON.stringify(temporaryChatMessages));
        }
        const analyst = currentAnalystContext();
        if (analyst.analystId) form.append('analyst_id', analyst.analystId);
        if (analyst.analystRole) form.append('analyst_role', analyst.analystRole);

        const headers = {};
        const key = (keyInput?.value || '').trim();
        if (key) headers['X-Investigation-Key'] = key;

        const resp = await fetch(`${API_BASE}/analyze/documents-temporary/chat`, {
            method: 'POST',
            headers,
            body: form,
        });
        const payload = await resp.json();
        if (!resp.ok) {
            throw new Error(payload.detail || payload.reason || 'Secure chat request failed');
        }
        const reply = (payload.reply || '').trim() || 'No response generated.';
        temporaryChatMessages.push({ role: 'assistant', content: reply });
        renderTemporaryChatTranscript();
    } catch (error) {
        temporaryChatMessages.push({ role: 'assistant', content: `Secure chat error: ${error.message || 'unknown error'}` });
        renderTemporaryChatTranscript();
    } finally {
        if (button) button.disabled = false;
    }
}

async function convertTempDocumentsToCase() {
    const button = document.getElementById('temp-doc-convert-btn');
    const status = document.getElementById('temp-doc-status');
    const context = document.getElementById('temp-doc-context')?.value || '';
    const entityId = (document.getElementById('temp-doc-entity-id')?.value || '').trim();

    if (!temporaryAnalysisFiles.length) {
        alert('Analyze or select files first.');
        return;
    }
    if (!entityId) {
        alert('Entity ID is required to convert temporary analysis into a case.');
        return;
    }

    try {
        if (button) button.disabled = true;
        if (status) {
            status.textContent = 'Converting';
            status.className = 'import-status running';
        }

        const form = new FormData();
        if (temporarySessionId) {
            form.append('session_id', temporarySessionId);
        } else {
            for (const f of temporaryAnalysisFiles) form.append('files', f);
        }
        form.append('entity_id', entityId);
        if (context.trim()) form.append('analyst_context', context.trim());
        form.append('persist_documents', 'true');
        const analyst = currentAnalystContext();
        if (analyst.analystId) form.append('analyst_id', analyst.analystId);
        if (analyst.analystRole) form.append('analyst_role', analyst.analystRole);

        const headers = {};
        const key = (document.getElementById('temp-chat-access-key')?.value || '').trim();
        if (key) headers['X-Investigation-Key'] = key;

        const resp = await fetch(`${API_BASE}/analyze/documents-temporary/convert`, {
            method: 'POST',
            headers,
            body: form,
        });
        const payload = await resp.json();
        if (!resp.ok) {
            throw new Error(payload.detail || payload.reason || 'Conversion failed');
        }

        if (status) {
            status.textContent = 'Converted';
            status.className = 'import-status success';
        }
        alert(`Converted to case ${payload.case_id}. Persisted documents: ${payload.persisted_documents}.`);
        await loadDashboardData();
        await loadCasesData();
    } catch (error) {
        console.error('Convert temporary analysis error:', error);
        if (status) {
            status.textContent = 'Error';
            status.className = 'import-status error';
        }
        alert(`Conversion failed: ${error.message || 'Unknown error'}`);
    } finally {
        if (button) button.disabled = false;
    }
}

async function clearTemporaryInvestigationSession() {
    if (!temporarySessionId) return;
    const key = (document.getElementById('temp-chat-access-key')?.value || '').trim();
    const headers = {};
    const analyst = currentAnalystContext();
    if (analyst.analystId) headers['X-Analyst-Id'] = analyst.analystId;
    if (analyst.analystRole) headers['X-Analyst-Role'] = analyst.analystRole;
    if (key) headers['X-Investigation-Key'] = key;
    try {
        await fetch(`${API_BASE}/analyze/documents-temporary/session/${encodeURIComponent(temporarySessionId)}`, {
            method: 'DELETE',
            headers,
            keepalive: true,
        });
    } catch (_) {
        // Ignore during unload.
    }
}

// Close modal on Escape
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeCaseModal();
});

// Close modal on outside click
document.getElementById('case-modal')?.addEventListener('click', e => {
    if (e.target.id === 'case-modal') closeCaseModal();
});

// ---------------------------------------------------------------------------
// Staging Queue — Source Validation Gate
// ---------------------------------------------------------------------------

const TRUST_LEVEL_COLORS = {
    law_enforcement_direct: '#3b82f6',
    validated_public:       '#10b981',
    validated_osint:        '#f59e0b',
    unvalidated_osint:      '#ef4444',
    staged_pending:         '#6b7280',
};

const TRUST_LEVEL_LABELS = {
    law_enforcement_direct: 'Law Enforcement',
    validated_public:       'Validated Public',
    validated_osint:        'Validated OSINT',
    unvalidated_osint:      'Unvalidated',
    staged_pending:         'Pending',
};

function trustBadge(level) {
    const color = TRUST_LEVEL_COLORS[level] || '#6b7280';
    const label = TRUST_LEVEL_LABELS[level] || level;
    return `<span style="background:${color}22;color:${color};border:1px solid ${color}44;
                         border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600;">${label}</span>`;
}

async function loadStagingQueue() {
    const status = document.getElementById('staging-status-filter')?.value || 'pending';
    const tbody = document.getElementById('staging-table-body');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="9">Loading...</td></tr>';

    try {
        const [resp, pendingResp, approvedResp, rejectedResp] = await Promise.all([
            fetch(`/api/v1/staging/queue?status=${status}&limit=100`),
            fetch('/api/v1/staging/queue?status=pending&limit=1'),
            fetch('/api/v1/staging/queue?status=approved&limit=1'),
            fetch('/api/v1/staging/queue?status=rejected&limit=1'),
        ]);
        const data = await resp.json();
        const pendingData = pendingResp.ok ? await pendingResp.json() : { total: 0 };
        const approvedData = approvedResp.ok ? await approvedResp.json() : { total: 0 };
        const rejectedData = rejectedResp.ok ? await rejectedResp.json() : { total: 0 };

        const pendingEl = document.getElementById('staging-pending-count');
        const approvedEl = document.getElementById('staging-approved-count');
        const rejectedEl = document.getElementById('staging-rejected-count');
        if (pendingEl) pendingEl.textContent = String(pendingData.total || 0);
        if (approvedEl) approvedEl.textContent = String(approvedData.total || 0);
        if (rejectedEl) rejectedEl.textContent = String(rejectedData.total || 0);

        // Summary bar
        const sumEl = document.getElementById('staging-summary');
        if (sumEl) {
            sumEl.innerHTML = `<strong>${data.total}</strong> items with status <em>${status}</em>.`;
        }

        if (!data.items || data.items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" style="color:#94a3b8;">No items with status "${status}".</td></tr>`;
            return;
        }

        tbody.innerHTML = data.items.map(item => `
            <tr>
                <td><code style="font-size:11px;">${item.staged_id}</code></td>
                <td>${item.source_name}</td>
                <td>${trustBadge(item.trust_level)}</td>
                <td>${item.canonical_name || '<em style="color:#64748b">—</em>'}</td>
                <td>${item.entity_type || '—'}</td>
                <td>${(item.confidence_baseline || 0).toFixed(2)}</td>
                <td><span class="status-badge status-${item.status}">${item.status}</span></td>
                <td>${item.submitted_at ? new Date(item.submitted_at).toLocaleString() : '—'}</td>
                <td>${stagingActionButtons(item)}</td>
            </tr>
        `).join('');
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="9" style="color:#ef4444;">Error loading staging queue: ${err.message}</td></tr>`;
    }
}

function stagingActionButtons(item) {
    if (item.status !== 'pending') {
        const note = item.reviewed_by ? `Reviewed by ${item.reviewed_by}` : '';
        return `<span style="color:#64748b;font-size:12px;">${note}</span>`;
    }
    return `
        <button class="btn btn-sm btn-success" onclick="stagingApprove('${item.staged_id}')">Approve</button>
        <button class="btn btn-sm btn-danger" onclick="stagingReject('${item.staged_id}')">Reject</button>
    `;
}

async function stagingApprove(stagedId) {
    const analyst = prompt('Analyst ID approving this signal:', 'ops_analyst_1');
    if (!analyst) return;
    const notes = prompt('Approval notes (optional):', '') || undefined;

    try {
        const resp = await fetch(`/api/v1/staging/${stagedId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reviewed_by: analyst, notes }),
        });
        const data = await resp.json();
        if (resp.ok) {
            alert(`✅ ${data.message || 'Approved.'}`);
        } else {
            alert(`Error: ${data.detail || JSON.stringify(data)}`);
        }
    } catch (err) {
        alert(`Request failed: ${err.message}`);
    }
    loadStagingQueue();
}

async function stagingReject(stagedId) {
    const analyst = prompt('Analyst ID rejecting this signal:', 'ops_analyst_1');
    if (!analyst) return;
    const reason = prompt('Rejection reason (required):');
    if (!reason || reason.trim().length < 3) {
        alert('A reason of at least 3 characters is required.');
        return;
    }

    try {
        const resp = await fetch(`/api/v1/staging/${stagedId}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reviewed_by: analyst, reason }),
        });
        const data = await resp.json();
        if (resp.ok) {
            alert(`🚫 Rejected: ${data.reason}`);
        } else {
            alert(`Error: ${data.detail || JSON.stringify(data)}`);
        }
    } catch (err) {
        alert(`Request failed: ${err.message}`);
    }
    loadStagingQueue();
}

async function loadSourceRegistry() {
    const panel = document.getElementById('source-registry-panel');
    const content = document.getElementById('source-registry-content');
    if (!panel || !content) return;

    try {
        const resp = await fetch('/api/v1/staging/sources');
        const data = await resp.json();

        const caps = data.trust_level_influence_caps || {};
        const byTrust = data.by_trust_level || {};

        let html = `<div style="font-size:12px;color:#94a3b8;margin-bottom:12px;">${data.architecture_note || ''}</div>`;
        html += '<div style="display:grid;gap:12px;">';

        for (const [level, sources] of Object.entries(byTrust)) {
            const color = TRUST_LEVEL_COLORS[level] || '#6b7280';
            const cap = caps[level] ?? '?';
            html += `
                <div style="border:1px solid ${color}33;border-radius:8px;padding:12px;">
                    <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                        ${trustBadge(level)}
                        <span style="color:#64748b;font-size:12px;">Influence cap: <strong style="color:#e2e8f0;">${(cap * 100).toFixed(0)}%</strong></span>
                    </div>
                    <div style="display:flex;flex-wrap:wrap;gap:6px;">
                        ${sources.map(s => `
                            <span title="${s.notes || ''}" style="background:#1e293b;border-radius:4px;padding:3px 8px;font-size:11px;color:#cbd5e1;">
                                ${s.display_name}
                                ${s.direct_ingest ? '' : ' <em style="color:#f59e0b;">(staging)</em>'}
                            </span>
                        `).join('')}
                    </div>
                </div>
            `;
        }
        html += '</div>';
        content.innerHTML = html;
        panel.style.display = 'block';
    } catch (err) {
        content.innerHTML = `<p style="color:#ef4444;">Error: ${err.message}</p>`;
        panel.style.display = 'block';
    }
}

// Auto-load staging queue when section is shown
const _origShowSection = typeof showSection !== 'undefined' ? showSection : null;

async function loadDecisionTelemetry() {
    const el = document.getElementById('decision-telemetry-content');
    if (!el) return;
    el.innerHTML = '<div class="telemetry-empty">Loading telemetry...</div>';
    try {
        const resp = await fetch('/api/v1/system/performance');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        const t = data.feedback_telemetry || {};
        const counts7 = t.decision_counts?.['7_days'] || {};
        const counts30 = t.decision_counts?.['30_days'] || {};
        const lift = t.avg_priority_lift_per_decision || {};
        const byRole = t.decisions_by_role || {};
        const roleLift = t.avg_priority_lift_by_role || {};
        const roleInfluence = t.top_queue_influence_by_role || {};
        const roleFalseCorr = t.false_correlation_rate_by_role || {};
        const dtLabels = {
            confirm_convergence: ['Analyst Confirmed', 'badge-confirmed'],
            mark_high_priority:  ['Analyst Promoted',  'badge-promoted'],
            reject_correlation:  ['Analyst Rejected',  'badge-rejected'],
            other:               ['Other',             ''],
        };
        const roleLabels = {
            junior_analyst: 'Junior Analyst',
            senior_analyst: 'Senior Analyst',
            trusted_operator: 'Trusted Operator',
        };
        el.innerHTML = `
            <div class="telemetry-kpi-grid">
                <div class="stat-mini"><div class="label">Total Decisions (30d)</div><div class="value">${t.total_decisions_30d ?? 0}</div></div>
                <div class="stat-mini"><div class="label">Top-Queue Influence</div><div class="value">${((t.top_queue_influence_pct ?? 0) * 100).toFixed(0)}%</div></div>
                <div class="stat-mini"><div class="label">False Correlation Rate</div><div class="value">${((t.false_correlation_rate ?? 0) * 100).toFixed(1)}%</div></div>
            </div>

            <div class="table-container telemetry-table-wrap">
            <table class="telemetry-table">
                <thead><tr><th>Decision Type</th><th>7d</th><th>30d</th><th>Avg \u0394</th></tr></thead>
                <tbody>
                    ${Object.entries(dtLabels).map(([dt, [label, cls]]) => `
                    <tr>
                        <td><span class="analyst-badge ${cls}">${label}</span></td>
                        <td>${counts7[dt] ?? 0}</td>
                        <td>${counts30[dt] ?? 0}</td>
                        <td>${lift[dt] != null ? (lift[dt] >= 0 ? '+' : '') + lift[dt].toFixed(1) : '\u2014'}</td>
                    </tr>`).join('')}
                </tbody>
            </table>
            </div>

            <div class="table-container telemetry-table-wrap" style="margin-top:10px;">
            <table class="telemetry-table">
                <thead><tr><th>Role</th><th>Decisions</th><th>Avg Lift</th><th>Queue Influence</th><th>False Corr.</th></tr></thead>
                <tbody>
                    ${Object.keys(roleLabels).map(role => `
                    <tr>
                        <td>${roleLabels[role]}</td>
                        <td>${byRole[role] ?? 0}</td>
                        <td>${roleLift[role] != null ? (roleLift[role] >= 0 ? '+' : '') + Number(roleLift[role]).toFixed(2) : '\u2014'}</td>
                        <td>${(((roleInfluence[role] ?? 0) * 100)).toFixed(1)}%</td>
                        <td>${(((roleFalseCorr[role] ?? 0) * 100)).toFixed(1)}%</td>
                    </tr>`).join('')}
                </tbody>
            </table>
            </div>

            <div class="telemetry-footnote">
                Guardrail: max 3 decisions of same type per analyst per case \u2014 HTTP 409 returned on excess.
            </div>`;
    } catch (err) {
        el.innerHTML = `<div class="telemetry-empty" style="color:var(--danger);">Failed to load: ${err.message}</div>`;
    }
}

async function loadArchiveData() {
    const tbody = document.querySelector('#archive-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr class="loading"><td colspan="5">Loading archive...</td></tr>';

    const date = document.getElementById('archive-date-filter')?.value;
    const caseId = (document.getElementById('archive-case-filter')?.value || '').trim();
    const qs = new URLSearchParams();
    if (date) qs.set('date', date);
    if (caseId) qs.set('case_id', caseId);

    try {
        const resp = await fetch(`/api/v1/system/tier4-proof/archive${qs.toString() ? `?${qs.toString()}` : ''}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        const rows = data.results || [];

        document.getElementById('archive-total').textContent = rows.length;
        document.getElementById('archive-valid').textContent = '0';
        document.getElementById('archive-last-case').textContent = rows[0]?.case_id || '-';

        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="loading">No archived records for this filter</td></tr>';
            return;
        }

        tbody.innerHTML = rows.map(row => `
            <tr>
                <td><code>${(row.case_id || '').substring(0, 24)}</code></td>
                <td>${row.date || '-'}</td>
                <td>${row.archived_at ? new Date(row.archived_at).toLocaleString() : '-'}</td>
                <td><span class="status-badge status-under_review">Pending Verify</span></td>
                <td><button class="btn btn-secondary btn-small" onclick="verifyArchiveCase('${row.case_id}')">Verify</button></td>
            </tr>
        `).join('');
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="5" class="loading" style="color: var(--danger);">Failed to load archive: ${err.message}</td></tr>`;
    }
}

async function verifyArchiveCase(caseId) {
    const totalEl = document.getElementById('archive-valid');
    try {
        const resp = await fetch(`/api/v1/system/tier4-proof/verify?case_id=${encodeURIComponent(caseId)}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        const rows = Array.from(document.querySelectorAll('#archive-table tbody tr'));
        for (const tr of rows) {
            const code = tr.querySelector('code');
            if (code && code.textContent === caseId.substring(0, 24)) {
                const statusCell = tr.children[3];
                statusCell.innerHTML = data.match
                    ? '<span class="status-badge status-open">Verified</span>'
                    : '<span class="status-badge status-closed">Mismatch</span>';
                break;
            }
        }

        if (data.match && totalEl) {
            totalEl.textContent = String((parseInt(totalEl.textContent || '0', 10) || 0) + 1);
        }
    } catch (err) {
        alert(`Verification failed: ${err.message}`);
    }
}

// Hook into section navigation to load staging/trust data on demand
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-section="staging"]').forEach(el => {
        el.addEventListener('click', () => { setTimeout(loadStagingQueue, 100); });
    });
    document.querySelectorAll('[data-section="trust"]').forEach(el => {
        el.addEventListener('click', () => { setTimeout(loadDecisionTelemetry, 150); });
    });
    document.querySelectorAll('[data-section="archive"]').forEach(el => {
        el.addEventListener('click', () => { setTimeout(loadArchiveData, 120); });
    });
});
