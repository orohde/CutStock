'use strict';

// ===========================================================================
// 1. STATE
// ===========================================================================

const State = {
    settings: { language: 'de', unit: 'mm', theme: 'system', hotkeys: {} },
    translations: {},
    materials: [],
    stock: [],
    blades: [],
    projects: [],
    parts: [],
    selectedMaterialId: null,
    selectedProjectId: null,
    selectedStockId: null,
    selectedPartId: null,
    selectedBladeId: null,
    optimizationResult: null,
};

// ===========================================================================
// 2. CONSTANTS
// ===========================================================================

const API_BASE = '';

const PART_COLORS = [
    'hsl(210, 70%, 50%)', 'hsl(150, 60%, 40%)', 'hsl(30, 80%, 50%)',
    'hsl(340, 65%, 50%)', 'hsl(260, 55%, 55%)', 'hsl(180, 60%, 40%)',
    'hsl(45, 75%, 48%)', 'hsl(0, 65%, 50%)', 'hsl(120, 50%, 40%)',
    'hsl(285, 55%, 50%)', 'hsl(195, 70%, 45%)', 'hsl(15, 70%, 50%)',
    'hsl(75, 55%, 42%)', 'hsl(315, 50%, 48%)',
];

const THEME_ICONS = { system: '☾', light: '☀', dark: '☾' };
const THEME_CYCLE = { system: 'light', light: 'dark', dark: 'system' };

// Konfigurierbare Tastenkuerzel (Aktion -> Standard-Taste)
const DEFAULT_HOTKEYS = {
    new: 'n',
    edit: 'e',
    delete: 'Delete',
    stock: 's',
    optimize: 'r',
};
// Fuer Umbelegung gesperrt (fest vergeben)
const RESERVED_KEYS = ['1', '2', '3', '4', 'enter', 'escape'];

const hotkey = (action) =>
    (State.settings.hotkeys || {})[action] || DEFAULT_HOTKEYS[action];

const hotkeyMatches = (action, e) => {
    const bound = hotkey(action).toLowerCase();
    const key = e.key.toLowerCase();
    if (key === bound) return true;
    // Backspace als Alias, solange Loeschen auf Standard (Delete) steht
    return action === 'delete' && bound === 'delete' && key === 'backspace';
};

const TYP_KEY = { 'Platte': 'mat.plate', 'Stange': 'mat.bar' };
const GRAIN_KEY = {
    'keine': 'mat.grain.none', 'längs': 'mat.grain.long',
    'quer': 'mat.grain.cross', 'egal': 'part.grain.any',
};

// ===========================================================================
// 3. TRANSLATION (i18n)
// ===========================================================================

const t = (key, params) => {
    let text = State.translations[key] ?? key;
    if (params) {
        for (const [k, v] of Object.entries(params)) {
            text = text.replaceAll(`{${k}}`, v);
        }
    }
    // Qt-Mnemonic-Escape aus der Desktop-i18n: "&&" = literales "&"
    return text.replaceAll('&&', '&');
};

const applyTranslations = () => {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        el.textContent = t(key);
    });
    if (typeof renderHotkeyTable === 'function') renderHotkeyTable();
};

// ===========================================================================
// 4. UNIT HELPERS
// ===========================================================================

const toDisplay = (mm) => {
    if (mm == null || mm === '') return '';
    const v = parseFloat(mm);
    if (isNaN(v)) return '';
    switch (State.settings.unit) {
        case 'cm': return +(v / 10).toFixed(2);
        case 'in': return +(v / 25.4).toFixed(3);
        default: return +v.toFixed(1);
    }
};

const toMm = (displayVal) => {
    const v = parseFloat(displayVal);
    if (isNaN(v)) return 0;
    switch (State.settings.unit) {
        case 'cm': return +(v * 10).toFixed(2);
        case 'in': return +(v * 25.4).toFixed(2);
        default: return +v.toFixed(2);
    }
};

const unitLabel = () => State.settings.unit || 'mm';

const formatDim = (mm) => {
    if (mm == null) return '';
    return `${toDisplay(mm)} ${unitLabel()}`;
};

// ===========================================================================
// 5. API FUNCTIONS
// ===========================================================================

async function fetchJSON(url, method = 'GET', body = null) {
    const opts = {
        method,
        headers: {},
    };
    if (body !== null) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    const resp = await fetch(API_BASE + url, opts);
    if (resp.status === 204) return null;
    if (!resp.ok) {
        let msg = `HTTP ${resp.status}`;
        try {
            const err = await resp.json();
            msg = err.detail || err.message || msg;
        } catch { /* ignore parse error */ }
        showToast(msg, 'error');
        throw new Error(msg);
    }
    return resp.json();
}

const Api = {
    getMaterials: () => fetchJSON('/api/materials'),
    createMaterial: (data) => fetchJSON('/api/materials', 'POST', data),
    updateMaterial: (id, data) => fetchJSON(`/api/materials/${id}`, 'PUT', data),
    deleteMaterial: (id) => fetchJSON(`/api/materials/${id}`, 'DELETE'),

    getStock: (materialId) => fetchJSON(`/api/stock?material_id=${materialId}`),
    createStock: (data) => fetchJSON('/api/stock', 'POST', data),
    updateStock: (id, data) => fetchJSON(`/api/stock/${id}`, 'PUT', data),
    deleteStock: (id) => fetchJSON(`/api/stock/${id}`, 'DELETE'),

    getBlades: () => fetchJSON('/api/blades'),
    createBlade: (data) => fetchJSON('/api/blades', 'POST', data),
    updateBlade: (id, data) => fetchJSON(`/api/blades/${id}`, 'PUT', data),
    deleteBlade: (id) => fetchJSON(`/api/blades/${id}`, 'DELETE'),

    getProjects: () => fetchJSON('/api/projects'),
    getProject: (id) => fetchJSON(`/api/projects/${id}`),
    createProject: (data) => fetchJSON('/api/projects', 'POST', data),
    updateProject: (id, data) => fetchJSON(`/api/projects/${id}`, 'PUT', data),
    deleteProject: (id) => fetchJSON(`/api/projects/${id}`, 'DELETE'),

    getParts: (projectId) => fetchJSON(`/api/projects/${projectId}/parts`),
    createPart: (projectId, data) => fetchJSON(`/api/projects/${projectId}/parts`, 'POST', data),
    updatePart: (id, data) => fetchJSON(`/api/parts/${id}`, 'PUT', data),
    deletePart: (id) => fetchJSON(`/api/parts/${id}`, 'DELETE'),

    optimize: (data) => fetchJSON('/api/optimize', 'POST', data),
    confirmOptimization: (data) => fetchJSON('/api/optimize/confirm', 'POST', data),
    markPlan: (data) => fetchJSON('/api/optimize/mark-plan', 'POST', data),

    async downloadPdf(data) {
        const resp = await fetch(API_BASE + '/api/pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) {
            showToast(t('error.pdf_failed'), 'error');
            return;
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `CutStock-${data.projekt_name || 'Schnittplan'}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    },

    async downloadLabels(data) {
        const resp = await fetch(API_BASE + '/api/labels', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) {
            showToast(t('error.pdf_failed'), 'error');
            return;
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `CutStock-${data.filename || 'Etiketten'}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    },

    getSettings: () => fetchJSON('/api/settings'),
    updateSettings: (data) => fetchJSON('/api/settings', 'PUT', data),
    getTranslations: (lang) => fetchJSON(`/api/i18n/${lang}`),
    getVersion: () => fetchJSON('/api/version'),

    async downloadBackup() {
        const resp = await fetch(API_BASE + '/api/backup');
        if (!resp.ok) { showToast('HTTP ' + resp.status, 'error'); return; }
        const blob = await resp.blob();
        const cd = resp.headers.get('Content-Disposition') || '';
        const m = cd.match(/filename="?([^"]+)"?/);
        const name = m ? m[1] : 'cutstock_backup.zip';
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    },

    async restoreBackup(file) {
        const fd = new FormData();
        fd.append('file', file);
        const resp = await fetch(API_BASE + '/api/restore', { method: 'POST', body: fd });
        if (!resp.ok) {
            let detail = 'HTTP ' + resp.status;
            try { detail = (await resp.json()).detail || detail; } catch { /* ignore */ }
            throw new Error(detail);
        }
        return resp.json();
    },
};

// ===========================================================================
// TOAST NOTIFICATIONS
// ===========================================================================

function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        Object.assign(container.style, {
            position: 'fixed', bottom: '24px', left: '50%', transform: 'translateX(-50%)',
            zIndex: '2000', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px',
        });
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = 'fd-message-toast';
    toast.textContent = message;
    Object.assign(toast.style, {
        opacity: '0',
        transition: 'opacity 0.3s ease',
        maxWidth: '360px',
        wordWrap: 'break-word',
    });
    if (type === 'error') {
        toast.style.background = 'var(--sapErrorBackground, #ffeaf4)';
        toast.style.color = 'var(--sapNegativeTextColor, #d20a0a)';
    }
    container.appendChild(toast);
    requestAnimationFrame(() => { toast.style.opacity = '1'; });
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// ===========================================================================
// 6. RENDERING FUNCTIONS
// ===========================================================================

// ---------------------------------------------------------------------------
// Material Tab
// ---------------------------------------------------------------------------

async function renderMaterials() {
    try {
        State.materials = await Api.getMaterials();
    } catch { return; }

    const tbody = document.querySelector('#material-table tbody');
    if (!tbody) return;

    if (State.materials.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="empty-state">${t('mat.empty')}</td></tr>`;
        State.selectedMaterialId = null;
        renderStock();
        return;
    }

    // Automatisch das erste Material auswählen, falls noch keins gewählt ist
    if (!State.materials.some(m => m.id === State.selectedMaterialId)) {
        State.selectedMaterialId = State.materials[0].id;
    }

    tbody.innerHTML = State.materials.map(m => {
        const selected = m.id === State.selectedMaterialId ? ' selected' : '';
        const typLabel = t(TYP_KEY[m.typ] || m.typ);
        let dims;
        if (m.typ === 'Platte') {
            dims = formatDim(m.dicke);
        } else {
            dims = `${formatDim(m.querschnitt_breite)} x ${formatDim(m.querschnitt_tiefe)}`;
        }
        const grain = m.typ === 'Platte' ? t(GRAIN_KEY[m.maserung] || m.maserung) : '';
        return `<tr class="fd-table__row ${selected}" data-id="${m.id}">
            <td class="fd-table__cell">${escHtml(m.name)}</td>
            <td class="fd-table__cell">${typLabel}</td>
            <td class="fd-table__cell num">${dims}</td>
            <td class="fd-table__cell">${grain}</td>
        </tr>`;
    }).join('');

    tbody.querySelectorAll('tr[data-id]').forEach(row => {
        row.addEventListener('click', () => selectMaterialRow(parseInt(row.dataset.id)));
        row.addEventListener('dblclick', () => {
            selectMaterialRow(parseInt(row.dataset.id));
            openMaterialDialog(getSelectedMaterial());
        });
    });

    renderStock();
}

function selectMaterialRow(id) {
    State.selectedMaterialId = id;
    document.querySelectorAll('#material-table tbody tr').forEach(r => {
        r.classList.toggle('selected', parseInt(r.dataset.id) === id);
    });
    renderStock();
}

function getSelectedMaterial() {
    return State.materials.find(m => m.id === State.selectedMaterialId) ?? null;
}

async function renderStock() {
    const tbody = document.querySelector('#stock-table tbody');
    if (!tbody) return;

    const mat = getSelectedMaterial();

    // Show/hide width column based on material type
    const isPlatte = mat?.typ === 'Platte';
    document.querySelectorAll('#stock-table th:nth-child(2), #stock-table td:nth-child(2)').forEach(el => {
        el.style.display = isPlatte ? '' : 'none';
    });

    if (!mat) {
        tbody.innerHTML = `<tr><td colspan="3" class="empty-state">${t('dlg.select_material')}</td></tr>`;
        State.stock = [];
        State.selectedStockId = null;
        return;
    }

    try {
        State.stock = await Api.getStock(mat.id);
    } catch { return; }

    if (State.stock.length === 0) {
        tbody.innerHTML = `<tr><td colspan="3" class="empty-state">${t('stock.empty')}</td></tr>`;
        State.selectedStockId = null;
        return;
    }

    tbody.innerHTML = State.stock.map(s => {
        const selected = s.id === State.selectedStockId ? ' selected' : '';
        return `<tr class="fd-table__row ${selected}" data-id="${s.id}">
            <td class="fd-table__cell num">${formatDim(s.laenge)}</td>
            <td class="fd-table__cell num" style="${isPlatte ? '' : 'display:none'}">${formatDim(s.breite)}</td>
            <td class="fd-table__cell num">${s.stueckzahl}</td>
        </tr>`;
    }).join('');

    tbody.querySelectorAll('tr[data-id]').forEach(row => {
        row.addEventListener('click', () => selectStockRow(parseInt(row.dataset.id)));
        row.addEventListener('dblclick', () => {
            selectStockRow(parseInt(row.dataset.id));
            openStockDialog(State.stock.find(s => s.id === State.selectedStockId));
        });
    });
}

function selectStockRow(id) {
    State.selectedStockId = id;
    document.querySelectorAll('#stock-table tbody tr').forEach(r => {
        r.classList.toggle('selected', parseInt(r.dataset.id) === id);
    });
}

// ---------------------------------------------------------------------------
// Project Tab
// ---------------------------------------------------------------------------

async function renderProjects() {
    try {
        State.projects = await Api.getProjects();
    } catch { return; }

    const tbody = document.querySelector('#project-list tbody');
    if (!tbody) return;

    if (State.projects.length === 0) {
        tbody.innerHTML = `<tr><td class="empty-state">${t('proj.empty')}</td></tr>`;
        State.selectedProjectId = null;
        renderParts();
        return;
    }

    tbody.innerHTML = State.projects.map(p => {
        const selected = p.id === State.selectedProjectId ? ' selected' : '';
        return `<tr class="fd-table__row ${selected}" data-id="${p.id}"><td class="fd-table__cell">${escHtml(p.name)}</td></tr>`;
    }).join('');

    tbody.querySelectorAll('tr[data-id]').forEach(row => {
        row.addEventListener('click', () => selectProjectRow(parseInt(row.dataset.id)));
        row.addEventListener('dblclick', () => {
            selectProjectRow(parseInt(row.dataset.id));
            const proj = State.projects.find(p => p.id === State.selectedProjectId);
            if (proj) openProjectDialog(proj);
        });
    });

    renderParts();
}

function selectProjectRow(id) {
    State.selectedProjectId = id;
    document.querySelectorAll('#project-list tbody tr').forEach(r => {
        r.classList.toggle('selected', parseInt(r.dataset.id) === id);
    });
    renderParts();
}

async function renderParts() {
    const tbody = document.querySelector('#parts-table tbody');
    if (!tbody) return;

    if (!State.selectedProjectId) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty-state">${t('dlg.select_project')}</td></tr>`;
        State.parts = [];
        State.selectedPartId = null;
        return;
    }

    try {
        State.parts = await Api.getParts(State.selectedProjectId);
    } catch { return; }

    if (State.parts.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty-state">${t('parts.empty')}</td></tr>`;
        State.selectedPartId = null;
        return;
    }

    tbody.innerHTML = State.parts.map(p => {
        const selected = p.id === State.selectedPartId ? ' selected' : '';
        const mat = State.materials.find(m => m.id === p.material_id);
        const matName = mat ? mat.name : `#${p.material_id}`;
        const isPlatte = p.typ === 'Platte';
        const grain = isPlatte ? t(GRAIN_KEY[p.maserung] || p.maserung) : '';
        const pct = p.stueckzahl > 0 ? Math.round((p.gesaegt_anzahl / p.stueckzahl) * 100) : 0;
        const statusText = `${p.gesaegt_anzahl}/${p.stueckzahl}`;
        const statusClass = p.gesaegt_anzahl >= p.stueckzahl ? 'status-cut' : 'status-open';
        return `<tr class="fd-table__row ${selected}" data-id="${p.id}">
            <td class="fd-table__cell">${escHtml(p.label)}</td>
            <td class="fd-table__cell">${t(TYP_KEY[p.typ] || p.typ)}</td>
            <td class="fd-table__cell">${escHtml(matName)}</td>
            <td class="fd-table__cell">${grain}</td>
            <td class="fd-table__cell num">${formatDim(p.laenge)}</td>
            <td class="fd-table__cell num">${isPlatte ? formatDim(p.breite) : ''}</td>
            <td class="fd-table__cell num">${p.stueckzahl}</td>
            <td class="fd-table__cell">
                <div style="display:flex;align-items:center;gap:8px">
                    <div class="progress-bar" style="flex:1;min-width:60px">
                        <div class="progress-fill" style="width:${pct}%"></div>
                    </div>
                    <span class="status-badge ${statusClass}">${statusText}</span>
                </div>
            </td>
        </tr>`;
    }).join('');

    tbody.querySelectorAll('tr[data-id]').forEach(row => {
        row.addEventListener('click', () => selectPartRow(parseInt(row.dataset.id)));
        row.addEventListener('dblclick', () => {
            selectPartRow(parseInt(row.dataset.id));
            const part = State.parts.find(p => p.id === State.selectedPartId);
            if (part) openPartDialog(part);
        });
    });
}

function selectPartRow(id) {
    State.selectedPartId = id;
    document.querySelectorAll('#parts-table tbody tr').forEach(r => {
        r.classList.toggle('selected', parseInt(r.dataset.id) === id);
    });
}

// ---------------------------------------------------------------------------
// Optimization Tab
// ---------------------------------------------------------------------------

function renderOptDropdowns() {
    const projSel = document.getElementById('opt-project');
    const matSel = document.getElementById('opt-material');
    const bladeSel = document.getElementById('opt-blade');
    const algoSel = document.getElementById('opt-algorithm');

    // Bisherige Auswahl merken, damit sie beim Neuaufbau (z.B. Tab-Wechsel)
    // erhalten bleibt und nicht auf das erste Projekt zurückspringt.
    const prevProj = projSel?.value;
    const prevMat = matSel?.value;
    const prevBlade = bladeSel?.value;
    const prevAlgo = algoSel?.value;

    if (projSel) {
        projSel.innerHTML = State.projects.map(p =>
            `<option value="${p.id}">${escHtml(p.name)}</option>`
        ).join('');
        if (prevProj && projSel.querySelector(`option[value="${prevProj}"]`)) {
            projSel.value = prevProj;
        }
    }

    updateOptMaterialDropdown();
    if (prevMat && matSel?.querySelector(`option[value="${prevMat}"]`)) {
        matSel.value = prevMat;
    }

    if (bladeSel) {
        bladeSel.innerHTML = State.blades.map(b =>
            `<option value="${b.id}">${escHtml(b.name)} (${formatDim(b.schnittbreite)})</option>`
        ).join('');
        if (prevBlade && bladeSel.querySelector(`option[value="${prevBlade}"]`)) {
            bladeSel.value = prevBlade;
        }
    }

    if (algoSel) {
        algoSel.innerHTML = [
            { value: 'greedy', key: 'opt.algo_greedy' },
            { value: 'nested', key: 'opt.algo_nested' },
            { value: 'ga', key: 'opt.algo_ga' },
        ].map(a => `<option value="${a.value}">${t(a.key)}</option>`).join('');
        // Standard: Nested Guillotine (dreht Teile, packt dichter als Greedy)
        algoSel.value = prevAlgo || 'nested';
    }

    // Passt der angezeigte Schnittplan nicht mehr zur (wieder­hergestellten)
    // Auswahl – etwa weil das Projekt gelöscht wurde – verwerfen.
    if (State.optimizationResult &&
        (!projSel?.value || projSel.value !== String(State.optimizationResult._projId))) {
        clearOptResult();
    }
}

// Angezeigten Schnittplan verwerfen (Auswahl passt nicht mehr dazu).
function clearOptResult() {
    if (!State.optimizationResult) return;
    State.optimizationResult = null;
    renderOptResults();
}

function updateOptMaterialDropdown() {
    const projSel = document.getElementById('opt-project');
    const matSel = document.getElementById('opt-material');
    if (!projSel || !matSel) return;

    const projectId = parseInt(projSel.value);
    const project = State.projects.find(p => p.id === projectId);
    const materialIds = new Set();

    if (project?.teile) {
        project.teile.forEach(t => {
            if (t.offen_anzahl > 0) materialIds.add(t.material_id);
        });
    }

    const filtered = materialIds.size > 0
        ? State.materials.filter(m => materialIds.has(m.id))
        : State.materials;

    matSel.innerHTML = filtered.map(m =>
        `<option value="${m.id}">${escHtml(m.name)}</option>`
    ).join('');
}

function renderOptResults() {
    const container = document.getElementById('opt-results');
    const statsEl = document.getElementById('opt-stats');
    const plansEl = document.getElementById('cut-plans');
    const actionsEl = document.querySelector('.opt-actions');

    if (!State.optimizationResult) {
        if (container) container.classList.add('hidden');
        if (statsEl) statsEl.innerHTML = '';
        if (plansEl) plansEl.innerHTML = '';
        if (actionsEl) actionsEl.style.display = 'none';
        return;
    }

    if (container) container.classList.remove('hidden');

    const result = State.optimizationResult;
    const plans = result.schnittplaene || [];
    const missing = result.fehlende_teile || [];
    const totalParts = plans.reduce((sum, p) => sum + p.platzierungen.length, 0);
    const waste = result.gesamt_verschnitt_prozent ?? 0;
    const wasteAbs = plans.reduce((sum, p) => sum + (p.verschnitt_mm || 0), 0);
    const utilization = 100 - waste;

    const optMat = State.materials.find(
        m => m.id === parseInt(document.getElementById('opt-material')?.value));
    const is1D = optMat?.typ === 'Stange';
    const wasteUnit = is1D ? 'mm' : 'mm²';

    // Nutzbares Restmaterial: Reste, die die Mindest-Restmaße erreichen, sind
    // kein echter Verschnitt. Anteil an der gesamten Brettfläche berechnen.
    const minL = optMat?.rest_min_laenge ?? 0;
    const minB = optMat?.rest_min_breite ?? 0;
    let usableRemnant = 0, totalBoard = 0;
    plans.forEach(sp => {
        if (is1D) {
            totalBoard += sp.lager_laenge;
            (sp.reste || []).forEach(r => { if (r[0] >= minL) usableRemnant += r[0]; });
        } else {
            totalBoard += sp.lager_laenge * (sp.lager_breite || 0);
            (sp.reste || []).forEach(r => {
                if (r.length >= 2 && r[0] >= minL && r[1] >= minB) usableRemnant += r[0] * r[1];
            });
        }
    });
    const usablePct = totalBoard > 0 ? (usableRemnant / totalBoard * 100) : 0;
    const realWaste = Math.max(0, waste - usablePct);

    if (statsEl) {
        const missingCard = missing.length > 0
            ? `<div class="stat-card">
                <div class="stat-icon">&#9888;</div>
                <div><div class="stat-value stat-danger">${missing.length}</div>
                <div class="stat-label">${t('stat.parts_missing')}</div>
                <div class="stat-sub stat-danger">${escHtml(missing.join(', '))}</div></div>
            </div>`
            : `<div class="stat-card">
                <div class="stat-icon">&#9888;</div>
                <div><div class="stat-value">0</div>
                <div class="stat-label">${t('stat.parts_missing')}</div></div>
            </div>`;

        statsEl.innerHTML = `
            <div class="stat-card">
                <div class="stat-icon">&#128196;</div>
                <div><div class="stat-value">${plans.length}</div>
                <div class="stat-label">${t('stat.stock_used')}</div></div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">&#9998;</div>
                <div><div class="stat-value">${totalParts}</div>
                <div class="stat-label">${t('stat.parts_placed')}</div></div>
            </div>
            ${missingCard}
            <div class="stat-card">
                <div class="stat-icon">&#9989;</div>
                <div><div class="stat-value">${utilization.toFixed(1)}%</div>
                <div class="stat-label">${t('stat.utilization')}</div></div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">&#128230;</div>
                <div><div class="stat-value">${usablePct.toFixed(1)}%</div>
                <div class="stat-label">${t('stat.usable_remnant')}</div></div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">&#9851;</div>
                <div><div class="stat-value">${waste.toFixed(1)}%</div>
                <div class="stat-label">${t('stat.total_waste')}</div>
                <div class="stat-sub">${t('stat.real_waste')}: ${realWaste.toFixed(1)}%</div></div>
            </div>
        `;
        statsEl.className = 'opt-stats';
    }

    if (plansEl) {
        const matId = parseInt(document.getElementById('opt-material')?.value);
        const mat = State.materials.find(m => m.id === matId);

        const kerf = currentKerf();
        const hint = `<p class="saw-hint">${t('opt.saw_hint')}</p>`;
        plansEl.innerHTML = hint + plans.map((plan, i) => {
            const canvasHeight = is1D ? 100 : 400;
            const seq = buildCutSequence(plan, is1D, kerf);
            const seqHtml = seq.length ? `<details class="cut-seq">
                <summary>${t('seq.title')} (${seq.length})</summary>
                <ol class="cut-seq-list">${seq.map(s =>
                    `<li data-plan-index="${i}"${s.cutIndex != null ? ` data-cut-index="${s.cutIndex}"` : ''}${s.pieceIndex != null ? ` data-piece-index="${s.pieceIndex}"` : ''}>${s.html}</li>`
                ).join('')}</ol>
            </details>` : '';
            return `<div class="cut-plan-card">
                <div class="plan-header">
                    <strong>${t('opt.preview')} ${i + 1}</strong>
                    <span>${formatDim(plan.lager_laenge)}${plan.lager_breite ? ' x ' + formatDim(plan.lager_breite) : ''}</span>
                    <span>${plan.platzierungen.length} ${t('proj.parts')}</span>
                    <span>${t('stat.utilization')}: ${(100 - plan.verschnitt_prozent).toFixed(1)}%</span>
                    <span class="waste">${t('stat.total_waste')}: ${plan.verschnitt_prozent.toFixed(1)}%</span>
                    <button class="fd-button btn-zoom" data-plan-index="${i}" type="button" title="${escAttr(t('opt.zoom'))}" aria-label="${escAttr(t('opt.zoom'))}">&#128269;</button>
                </div>
                <canvas class="cut-plan-canvas" data-plan-index="${i}"
                    style="width:100%;height:${canvasHeight}px"></canvas>
                ${seqHtml}
            </div>`;
        }).join('');
        plansEl.className = 'cut-plans';

        requestAnimationFrame(() => {
            plansEl.querySelectorAll('canvas').forEach(canvas => {
                const idx = parseInt(canvas.dataset.planIndex);
                drawCutPlan(canvas, plans[idx], mat);
            });
        });

        setupSeqHover(plansEl);
    }

    if (actionsEl) actionsEl.style.display = '';

    if (missing.length > 0) {
        showToast(`${t('opt.missing')}: ${missing.join(', ')}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Settings Tab
// ---------------------------------------------------------------------------

// Verfügbare Etikettenformate (Auswahltexte kommen aus der i18n)
const LABEL_FORMATS = [
    { value: 'a4_3x8', key: 'labels.fmt_a4_3x8' },
    { value: 'a4_3x7', key: 'labels.fmt_a4_3x7' },
    { value: 'roll_89x36', key: 'labels.fmt_roll_89x36' },
    { value: 'roll_62x29', key: 'labels.fmt_roll_62x29' },
    { value: 'custom', key: 'labels.fmt_custom' },
];

function renderSettings() {
    const langSel = document.getElementById('settings-lang');
    const unitSel = document.getElementById('settings-unit');
    const themeSel = document.getElementById('settings-theme');

    if (langSel) langSel.value = State.settings.language;
    if (unitSel) unitSel.value = State.settings.unit;
    if (themeSel) themeSel.value = State.settings.theme;

    const fmtSel = document.getElementById('settings-label-format');
    if (fmtSel) {
        fmtSel.innerHTML = LABEL_FORMATS.map(f =>
            `<option value="${f.value}">${escHtml(t(f.key))}</option>`).join('');
        fmtSel.value = State.settings.label_format || 'a4_3x8';
        if (!fmtSel.value) fmtSel.value = 'a4_3x8';
    }
    const wInp = document.getElementById('settings-label-w');
    const hInp = document.getElementById('settings-label-h');
    if (wInp) wInp.value = State.settings.label_custom_w ?? 89;
    if (hInp) hInp.value = State.settings.label_custom_h ?? 36;
    updateLabelCustomVisibility();

    const vEl = document.getElementById('app-version');
    if (vEl) {
        Api.getVersion()
            .then(v => { vEl.textContent = v.version; State.versionInfo = v; })
            .catch(() => { vEl.textContent = '—'; });
    }
}

// Breite/Höhe-Felder nur beim benutzerdefinierten Etikettenformat zeigen
function updateLabelCustomVisibility() {
    const isCustom = document.getElementById('settings-label-format')?.value === 'custom';
    document.querySelectorAll('.label-custom-field').forEach(el => {
        el.style.display = isCustom ? '' : 'none';
    });
}

// Versionsstrings JJJJ.MM.NN numerisch vergleichen (-1/0/1)
function compareVersions(a, b) {
    const pa = String(a).split('.').map(n => parseInt(n) || 0);
    const pb = String(b).split('.').map(n => parseInt(n) || 0);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
        const d = (pa[i] || 0) - (pb[i] || 0);
        if (d !== 0) return d < 0 ? -1 : 1;
    }
    return 0;
}

// Externe URL im System-Browser öffnen (Desktop) bzw. neuem Tab (Web)
function openExternal(url) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_external) {
        window.pywebview.api.open_external(url);
    } else {
        window.open(url, '_blank', 'noopener');
    }
}

async function checkForUpdate() {
    showToast(t('set.checking_update'), 'info');
    try {
        const info = State.versionInfo || await Api.getVersion();
        const resp = await fetch(info.releases_api, {
            headers: { 'Accept': 'application/vnd.github+json' },
        });
        if (!resp.ok) throw new Error('github');
        const rel = await resp.json();
        const latest = (rel.tag_name || '').trim();
        if (latest && compareVersions(latest, info.version) > 0) {
            showToast(t('set.update_available', { version: latest }), 'info');
        } else {
            showToast(t('set.up_to_date', { version: info.version }), 'info');
        }
    } catch {
        showToast(t('set.update_failed'), 'error');
    }
}

async function renderBlades() {
    try {
        State.blades = await Api.getBlades();
    } catch { return; }

    const tbody = document.querySelector('#blade-table tbody');
    if (!tbody) return;

    if (State.blades.length === 0) {
        tbody.innerHTML = `<tr><td colspan="2" class="empty-state">${t('blade.empty')}</td></tr>`;
        State.selectedBladeId = null;
        return;
    }

    tbody.innerHTML = State.blades.map(b => {
        const selected = b.id === State.selectedBladeId ? ' selected' : '';
        return `<tr class="fd-table__row ${selected}" data-id="${b.id}">
            <td class="fd-table__cell">${escHtml(b.name)}</td>
            <td class="fd-table__cell num">${formatDim(b.schnittbreite)}</td>
        </tr>`;
    }).join('');

    tbody.querySelectorAll('tr[data-id]').forEach(row => {
        row.addEventListener('click', () => {
            State.selectedBladeId = parseInt(row.dataset.id);
            document.querySelectorAll('#blade-table tbody tr').forEach(r => {
                r.classList.toggle('selected', parseInt(r.dataset.id) === State.selectedBladeId);
            });
        });
        row.addEventListener('dblclick', () => {
            State.selectedBladeId = parseInt(row.dataset.id);
            const blade = State.blades.find(b => b.id === State.selectedBladeId);
            if (blade) openBladeDialog(blade);
        });
    });
}

// ===========================================================================
// 7. CUT PLAN VISUALIZATION (Canvas)
// ===========================================================================

// Konsistente Label→Farbe-Zuordnung über alle Schnittpläne des Ergebnisses.
function buildColorMap() {
    const map = {};
    const labels = new Set();
    (State.optimizationResult?.schnittplaene || []).forEach(sp =>
        sp.platzierungen.forEach(p => labels.add(p.teil_label)));
    [...labels].sort().forEach((label, i) => {
        map[label] = PART_COLORS[i % PART_COLORS.length];
    });
    return map;
}

function drawCutPlan(canvas, plan, material) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const canvasW = rect.width;
    const canvasH = rect.height;

    canvas.width = canvasW * dpr;
    canvas.height = canvasH * dpr;

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const is1D = material?.typ === 'Stange';

    // Farbzuordnung global über ALLE Pläne, damit dasselbe Teil überall die
    // gleiche Farbe hat (auch wenn es über mehrere Platten verteilt ist).
    const colorMap = buildColorMap();

    // Trefferflächen der einzelnen Stücke für Klick-zum-Abhaken sammeln
    const hits = [];
    if (is1D) {
        draw1D(ctx, canvasW, canvasH, plan, colorMap, hits);
    } else {
        draw2D(ctx, canvasW, canvasH, plan, colorMap, hits);
    }
    canvas._hits = hits;

    if (!canvas._cutHandler) {
        canvas._cutHandler = (e) => {
            const r = canvas.getBoundingClientRect();
            const mx = e.clientX - r.left;
            const my = e.clientY - r.top;
            const hit = (canvas._hits || []).find(h =>
                mx >= h.x && mx <= h.x + h.w && my >= h.y && my <= h.y + h.h);
            if (hit) togglePieceSawn(canvas, hit.p);
        };
        canvas.addEventListener('click', canvas._cutHandler);
        canvas.style.cursor = 'pointer';
    }
}

// Ein Stück im Schnittplan als gesägt markieren/zurücknehmen: Fortschritt des
// Teils anpassen UND den Lagerbestand live führen (wie Desktop _on_teil_cut).
async function togglePieceSawn(canvas, placement) {
    const result = State.optimizationResult;
    if (!result) return;
    const idx = parseInt(canvas.dataset.planIndex);
    const plan = result.schnittplaene[idx];
    const proj = State.projects.find(p => String(p.id) === result._projId);
    const teil = proj?.teile?.find(t => t.label === placement.teil_label);

    const willBeDone = !placement._done;
    placement._done = willBeDone;
    redrawPlanForCanvas(canvas);

    // 1) Fortschritt des Teils
    if (teil) {
        const delta = willBeDone ? +1 : -1;
        const next = Math.max(0, Math.min(teil.stueckzahl, teil.gesaegt_anzahl + delta));
        if (next !== teil.gesaegt_anzahl) {
            try {
                await Api.updatePart(teil.id, { ...teil, gesaegt_anzahl: next });
                teil.gesaegt_anzahl = next;
                if (State.selectedProjectId === proj.id) renderParts();
            } catch {
                placement._done = !willBeDone;
                redrawPlanForCanvas(canvas);
                return;
            }
        }
    }

    // 2) Lagerbestand live anpassen
    await reconcilePlanStock(plan);
    await refreshStockAfterMark();

    // Rebuild the workshop-mode view (if open) with the new state
    if (sawModeActive()) renderSawMode();
}

// Lagerbestand für einen Schnittplan mit dem Backend abgleichen und den
// Verbrauchszustand am Plan-Objekt mitführen.
async function reconcilePlanStock(plan) {
    const optMat = State.materials.find(
        m => m.id === parseInt(document.getElementById('opt-material')?.value));
    if (!optMat) return;
    const is1D = optMat.typ === 'Stange';
    const blade = State.blades.find(
        b => b.id === parseInt(document.getElementById('opt-blade')?.value));
    const kerf = blade?.schnittbreite || 0;
    const markedLaengen = plan.platzierungen.filter(p => p._done).map(p => p.laenge);

    try {
        const res = await Api.markPlan({
            material_id: optMat.id,
            lagerstueck_id: plan.lagerstueck_id,
            is_1d: is1D,
            lager_laenge: plan.lager_laenge,
            lager_breite: plan.lager_breite || 0,
            kerf,
            marked_laengen: markedLaengen,
            total_pieces: plan.platzierungen.length,
            reste: plan.reste || [],
            prev_consumed: plan._consumed || false,
            prev_rest_ids: plan._restIds || [],
        });
        plan._consumed = res.consumed;
        plan._restIds = res.rest_ids || [];
    } catch { /* nicht kritisch */ }
}

// Lagerbestand-Tabelle auffrischen, falls das betroffene Material dort offen ist.
async function refreshStockAfterMark() {
    const matId = parseInt(document.getElementById('opt-material')?.value);
    if (State.selectedMaterialId === matId) {
        try { State.stock = await Api.getStock(matId); renderStock(); } catch { /* ignore */ }
    }
}

// „Bestätigen": alle noch nicht markierten Stücke auf einmal als gesägt
// markieren – nutzt denselben Pfad wie das Einzel-Abhaken (kein Doppelzählen).
async function confirmAllPieces() {
    const result = State.optimizationResult;
    if (!result) return;
    const proj = State.projects.find(p => String(p.id) === result._projId);

    // Pro Label die noch nicht markierten Platzierungen zählen und markieren
    const addByLabel = {};
    (result.schnittplaene || []).forEach(plan => {
        plan.platzierungen.forEach(p => {
            if (!p._done) {
                addByLabel[p.teil_label] = (addByLabel[p.teil_label] || 0) + 1;
                p._done = true;
            }
        });
    });

    // Fortschritt je Teil setzen
    for (const [label, add] of Object.entries(addByLabel)) {
        const teil = proj?.teile?.find(t => t.label === label);
        if (!teil) continue;
        const next = Math.min(teil.stueckzahl, teil.gesaegt_anzahl + add);
        if (next !== teil.gesaegt_anzahl) {
            try {
                await Api.updatePart(teil.id, { ...teil, gesaegt_anzahl: next });
                teil.gesaegt_anzahl = next;
            } catch { /* handled */ }
        }
    }

    // Lager pro Plan abgleichen (jetzt sind alle Stücke markiert)
    for (const plan of (result.schnittplaene || [])) {
        await reconcilePlanStock(plan);
    }

    document.querySelectorAll('.cut-plan-canvas').forEach(c => redrawPlanForCanvas(c));
    State.projects = await Api.getProjects();
    if (proj && State.selectedProjectId === proj.id) renderParts();
    await refreshStockAfterMark();
    showToast(t('opt.done'), 'info');
}

function redrawPlanForCanvas(canvas) {
    const idx = parseInt(canvas.dataset.planIndex);
    const plan = State.optimizationResult?.schnittplaene?.[idx];
    if (!plan) return;
    const matId = parseInt(document.getElementById('opt-material')?.value);
    const mat = State.materials.find(m => m.id === matId);
    drawCutPlan(canvas, plan, mat);
}

// Einen Schnittplan groß in einem Popup anzeigen
function openPlanZoom(idx) {
    const plan = State.optimizationResult?.schnittplaene?.[idx];
    if (!plan) return;
    const mat = State.materials.find(
        m => m.id === parseInt(document.getElementById('opt-material')?.value));
    const is1D = mat?.typ === 'Stange';

    const maxW = window.innerWidth * 0.9;
    const maxH = window.innerHeight * 0.8;
    let cw, ch;
    if (is1D) {
        cw = maxW;
        ch = Math.min(maxH, 220);
    } else {
        const ar = plan.lager_laenge / (plan.lager_breite || 1);
        cw = maxW;
        ch = cw / ar;
        if (ch > maxH) { ch = maxH; cw = ch * ar; }
    }

    const canvas = document.getElementById('zoom-canvas');
    canvas.dataset.planIndex = idx;
    canvas.style.width = Math.round(cw) + 'px';
    canvas.style.height = Math.round(ch) + 'px';

    document.getElementById('zoom-overlay').classList.add('active');
    requestAnimationFrame(() => drawCutPlan(canvas, plan, mat));
}

function closePlanZoom() {
    document.getElementById('zoom-overlay').classList.remove('active');
    // Inline-Pläne auffrischen, falls im Zoom etwas markiert wurde
    document.querySelectorAll('.cut-plan-canvas').forEach(c => redrawPlanForCanvas(c));
}

// ---------------------------------------------------------------------------
// Labels: printable stickers for sawn parts (from the optimization result)
// and for stock pieces/remnants. The #ID gets written onto the physical
// piece, linking the remnant shelf to the digital stock list.
// ---------------------------------------------------------------------------

function dimText(laenge, breite) {
    return breite > 0
        ? `${toDisplay(laenge)} × ${toDisplay(breite)} ${unitLabel()}`
        : formatDim(laenge);
}

// One label per placed part; the ID references the panel/bar in the plan
function printPartLabels() {
    const result = State.optimizationResult;
    if (!result?.schnittplaene?.length) return;
    const projName = document.getElementById('opt-project')?.selectedOptions[0]?.text || '';
    const matName = document.getElementById('opt-material')?.selectedOptions[0]?.text || '';

    const labels = [];
    result.schnittplaene.forEach((plan, i) => {
        plan.platzierungen.forEach(p => {
            labels.push({
                title: p.teil_label,
                line1: dimText(p.laenge, p.breite) + (p.gedreht ? '  (R)' : ''),
                line2: [projName, matName].filter(Boolean).join(' · '),
                id_text: `P${i + 1}`,
            });
        });
    });
    Api.downloadLabels({ labels, filename: `${t('labels.button')}-${projName || 'Teile'}` });
}

// One label per physical stock piece (quantity > 1 → several labels);
// the #ID is written onto the wood and uniquely identifies the remnant.
function printStockLabels() {
    const mat = getSelectedMaterial();
    if (!mat) { showToast(t('dlg.select_material'), 'error'); return; }
    if (!State.stock.length) { showToast(t('stock.empty'), 'error'); return; }

    const labels = [];
    State.stock.forEach(s => {
        for (let n = 0; n < Math.min(s.stueckzahl, 200); n++) {
            labels.push({
                title: mat.name,
                line1: dimText(s.laenge, s.breite),
                line2: t('labels.stock'),
                id_text: `#${s.id}`,
            });
        }
    });
    Api.downloadLabels({ labels, filename: `${t('labels.button')}-${mat.name}` });
}

// ---------------------------------------------------------------------------
// Workshop mode: full-screen view for a tablet at the saw.
// One panel/bar per page, large touch targets; marking pieces uses the same
// code path as the normal view (togglePieceSawn → mark-plan), so stock is
// kept in sync live.
// ---------------------------------------------------------------------------

let sawPlanIdx = 0;

function openSawMode() {
    if (!State.optimizationResult?.schnittplaene?.length) return;
    sawPlanIdx = 0;
    document.getElementById('saw-overlay').classList.add('active');
    renderSawMode();
}

function closeSawMode() {
    document.getElementById('saw-overlay').classList.remove('active');
    // Refresh the inline plans in case pieces were marked in workshop mode
    document.querySelectorAll('.cut-plan-canvas').forEach(c => redrawPlanForCanvas(c));
}

function sawModeActive() {
    return document.getElementById('saw-overlay')?.classList.contains('active');
}

function renderSawMode() {
    const plans = State.optimizationResult?.schnittplaene || [];
    if (!plans.length) { closeSawMode(); return; }
    sawPlanIdx = Math.max(0, Math.min(plans.length - 1, sawPlanIdx));
    const plan = plans[sawPlanIdx];
    const mat = State.materials.find(
        m => m.id === parseInt(document.getElementById('opt-material')?.value));
    const is1D = mat?.typ === 'Stange';

    // Header + overall progress across all plans
    const total = plans.reduce((s, p) => s + p.platzierungen.length, 0);
    const done = plans.reduce((s, p) => s + p.platzierungen.filter(x => x._done).length, 0);
    document.getElementById('saw-plan-label').textContent =
        `${t('opt.preview')} ${sawPlanIdx + 1} / ${plans.length}`;
    document.getElementById('saw-progress-text').textContent =
        done >= total ? t('saw.done') : `${done} / ${total}`;
    document.getElementById('saw-progress-fill').style.width =
        total > 0 ? `${(done / total) * 100}%` : '0';
    document.getElementById('saw-prev').disabled = sawPlanIdx === 0;
    document.getElementById('saw-next').disabled = sawPlanIdx >= plans.length - 1;

    // Plan drawing (reuses the existing canvas logic incl. click-to-mark)
    const canvas = document.getElementById('saw-canvas');
    canvas.dataset.planIndex = sawPlanIdx;
    const bodyW = document.querySelector('.saw-body').clientWidth - 4;
    let ch;
    if (is1D) {
        ch = 120;
    } else {
        const ar = plan.lager_laenge / (plan.lager_breite || 1);
        ch = Math.min(window.innerHeight * 0.45, bodyW / ar + 60);
    }
    canvas.style.width = '100%';
    canvas.style.height = Math.round(ch) + 'px';
    drawCutPlan(canvas, plan, mat);

    renderSawPieceList(plan, canvas);
}

function renderSawPieceList(plan, canvas) {
    const list = document.getElementById('saw-piece-list');
    // Reading order: 2D row by row (top→bottom, left→right), 1D from left
    const order = [...plan.platzierungen].sort((a, b) => (a.y - b.y) || (a.x - b.x));
    const nextPiece = order.find(p => !p._done);
    const colorMap = buildColorMap();
    list.innerHTML = order.map(p => {
        const idx = plan.platzierungen.indexOf(p);
        const dims = p.breite > 0
            ? `${toDisplay(p.laenge)}×${toDisplay(p.breite)} ${unitLabel()}`
            : formatDim(p.laenge);
        const cls = ['saw-piece', p._done ? 'done' : '', p === nextPiece ? 'saw-next' : '']
            .filter(Boolean).join(' ');
        const badge = p === nextPiece ? `<span class="saw-next-badge">${t('saw.next_piece')}</span>` : '';
        return `<li class="${cls}" data-piece-index="${idx}">
            <span class="saw-dot" style="background:${colorMap[p.teil_label] || '#888'}"></span>
            <span class="saw-piece-label">${escHtml(p.teil_label)}${p.gedreht ? ' <small>(R)</small>' : ''}</span>
            ${badge}
            <span class="saw-piece-dims">${dims}</span>
            <span class="saw-check">${p._done ? '&#10003;' : ''}</span>
        </li>`;
    }).join('');

    list.querySelectorAll('li[data-piece-index]').forEach(li => {
        li.addEventListener('click', () => {
            const p = plan.platzierungen[parseInt(li.dataset.pieceIndex)];
            togglePieceSawn(canvas, p);  // also refreshes workshop mode at the end
        });
    });
}

// Halbtransparente Abdeckung + grüner Haken auf einem gesägten Stück
function drawDoneOverlay(ctx, x, y, w, h) {
    ctx.fillStyle = 'rgba(255,255,255,0.55)';
    ctx.fillRect(x, y, w, h);
    const s = Math.min(w, h);
    if (s < 12) return;
    const cx = x + w / 2;
    const cy = y + h / 2;
    const r = Math.min(s * 0.32, 16);
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = '#256f3a';
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = Math.max(1.5, r * 0.18);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(cx - r * 0.42, cy + r * 0.02);
    ctx.lineTo(cx - r * 0.10, cy + r * 0.34);
    ctx.lineTo(cx + r * 0.46, cy - r * 0.34);
    ctx.stroke();
}

// Full guillotine decomposition of a panel into parts + leftovers.
// Recursively places one edge-to-edge cut per region: first separate groups
// of parts from each other, then free single parts from their region
// (largest leftover strip first, so big contiguous remnants survive).
// Output: an ordered cut list – the order IS the sawing order.
//
// Kerf convention: the saw blade sits on the far side (right/below) of the
// stated cut position, so a cut at `pos` physically destroys [pos, pos+kerf]
// and the following region starts at pos + kerf:
//
//        pos   pos+kerf
//         |    |
//   +-----+----+----------+
//   |  A  |cut |    B     |     region A keeps its exact size,
//   +-----+----+----------+     region B starts beyond the kerf
//
// This keeps every position measured from its region's edge true to size at
// the saw and avoids phantom kerf-width strips in the sequence.
// Each emitted cut carries its region bounds (x0..y1) so the step list can
// report positions relative to the piece being cut.
function computeGuillotineCuts(pieces, x0, y0, x1, y1, out, depth, kerf = 0) {
    const eps = 0.5;
    if (depth > 120) return;  // safety guard against degenerate inputs

    if (pieces.length === 0) return;  // pure leftover region, no cut needed

    if (pieces.length === 1) {
        trimSinglePiece(pieces[0], x0, y0, x1, y1, out, kerf);
        return;
    }

    // Try vertical through-cuts at every distinct part right edge: a cut is
    // valid if it separates the parts into two non-empty groups without
    // slicing through any part.
    const xs = [...new Set(pieces.map(p => p.x + p.laenge))].sort((a, b) => a - b);
    for (const cx of xs) {
        if (cx <= x0 + eps || cx >= x1 - eps) continue;
        const left = pieces.filter(p => p.x + p.laenge <= cx + eps);
        const right = pieces.filter(p => p.x >= cx - eps);
        if (left.length && right.length && left.length + right.length === pieces.length) {
            out.push({ v: true, pos: cx, a: y0, b: y1, x0, y0, x1, y1 });
            computeGuillotineCuts(left, x0, y0, cx, y1, out, depth + 1, kerf);
            computeGuillotineCuts(right, Math.min(cx + kerf, x1), y0, x1, y1, out, depth + 1, kerf);
            return;
        }
    }

    // Same for horizontal cuts at part bottom edges
    const ys = [...new Set(pieces.map(p => p.y + p.breite))].sort((a, b) => a - b);
    for (const cy of ys) {
        if (cy <= y0 + eps || cy >= y1 - eps) continue;
        const top = pieces.filter(p => p.y + p.breite <= cy + eps);
        const bot = pieces.filter(p => p.y >= cy - eps);
        if (top.length && bot.length && top.length + bot.length === pieces.length) {
            out.push({ v: false, pos: cy, a: x0, b: x1, x0, y0, x1, y1 });
            computeGuillotineCuts(top, x0, y0, x1, cy, out, depth + 1, kerf);
            computeGuillotineCuts(bot, x0, Math.min(cy + kerf, y1), x1, y1, out, depth + 1, kerf);
            return;
        }
    }
}

// Free a single part from its region: repeatedly cut off the LARGEST waste
// strip first, so the leftovers stay as large contiguous rectangles.
// A strip whose physical width is at most the kerf is not a real cut – that
// material was already destroyed by the cut that created this region.
function trimSinglePiece(p, x0, y0, x1, y1, out, kerf = 0) {
    const eps = 0.5;
    const px1 = p.x + p.laenge;
    const py1 = p.y + p.breite;
    let rx0 = x0, ry0 = y0, rx1 = x1, ry1 = y1;
    // At most 4 sides can need a trim cut; 6 is a safe upper bound
    for (let guard = 0; guard < 6; guard++) {
        // s = physical strip size beyond the part on each side (left/right/
        // top/bottom), with the kerf already deducted because the blade sits
        // on the waste side of the cut. q = strip length across the region;
        // v = strip area, used to pick the largest strip first.
        const cand = [
            { k: 'l', s: p.x - kerf - rx0, q: ry1 - ry0 },
            { k: 'r', s: rx1 - px1 - kerf, q: ry1 - ry0 },
            { k: 't', s: p.y - kerf - ry0, q: rx1 - rx0 },
            { k: 'b', s: ry1 - py1 - kerf, q: rx1 - rx0 },
        ].map(c => ({ ...c, v: c.s > eps ? c.s * c.q : 0 }));
        const best = cand.reduce((a, b) => (b.v > a.v ? b : a));
        if (best.v <= eps) break;  // nothing left to trim
        const region = { x0: rx0, y0: ry0, x1: rx1, y1: ry1 };
        // For cuts left/above the part the blade must end AT the part's edge,
        // so the stated position is part edge minus kerf; for cuts right/
        // below, the blade starts at the part's edge (position = edge).
        if (best.k === 'l') { out.push({ v: true, pos: p.x - kerf, a: ry0, b: ry1, ...region }); rx0 = p.x; }
        else if (best.k === 'r') { out.push({ v: true, pos: px1, a: ry0, b: ry1, ...region }); rx1 = px1; }
        else if (best.k === 't') { out.push({ v: false, pos: p.y - kerf, a: rx0, b: rx1, ...region }); ry0 = p.y; }
        else { out.push({ v: false, pos: py1, a: rx0, b: rx1, ...region }); ry1 = py1; }
    }
}

// Numbered cutting sequence of one plan as a step list. Uses the SAME
// guillotine decomposition as the canvas drawing, so list and drawn lines
// are guaranteed to match (same function, same input, same order).
// Positions are stated relative to the current piece's reference edge
// ("at X from left"); the resulting dimensions deduct the kerf on the far
// side of the cut (see the kerf convention at computeGuillotineCuts).
function buildCutSequence(plan, is1D, kerf) {
    const dim = (l, b) => `${toDisplay(l)}×${toDisplay(b)}`;
    if (is1D) {
        // Chop saw: cut pieces to length one after another, left to right.
        // pieceIndex refers back into plan.platzierungen for hover highlight.
        return [...plan.platzierungen]
            .sort((a, b) => a.x - b.x)
            .map(p => {
                const text = t('seq.cut_1d', { label: p.teil_label, len: formatDim(p.laenge) });
                return { text, html: escHtml(text), pieceIndex: plan.platzierungen.indexOf(p) };
            });
    }
    const cuts = [];
    computeGuillotineCuts(
        plan.platzierungen.map(p => ({ x: p.x, y: p.y, laenge: p.laenge, breite: p.breite })),
        0, 0, plan.lager_laenge, plan.lager_breite, cuts, 0, kerf);
    return cuts.map((c, i) => {
        // Region being cut in this step (the physical piece on the bench)
        const w = c.x1 - c.x0, h = c.y1 - c.y0;
        let posText, p1, p2;
        if (c.v) {
            // Vertical cut line: position measured from the region's left
            // edge. Left result keeps that exact width; the right result
            // loses one kerf to the blade.
            const off = c.pos - c.x0;
            posText = t('seq.cut_v', { pos: formatDim(off) });
            p1 = dim(off, h);
            p2 = dim(Math.max(0, c.x1 - c.pos - kerf), h);
        } else {
            // Horizontal cut line: measured from the region's top edge
            const off = c.pos - c.y0;
            posText = t('seq.cut_h', { pos: formatDim(off) });
            p1 = dim(w, off);
            p2 = dim(w, Math.max(0, c.y1 - c.pos - kerf));
        }
        const piece = dim(w, h);
        return {
            text: `${piece}: ${posText} → ${p1} + ${p2}`,
            html: `<span class="seq-piece">${piece}</span> ${escHtml(posText)} <span class="seq-arrow">→</span> ${p1} <span class="seq-plus">+</span> ${p2}`,
            cutIndex: i,  // index into the cuts array drawn on the canvas
        };
    });
}

// Hovering a cutting-sequence step highlights the cut line (2D) or the
// piece (1D) in the matching plan canvas. Uses event delegation because the
// list is rebuilt on every render.
function setupSeqHover(plansEl) {
    if (plansEl._seqHover) return;
    plansEl._seqHover = true;
    const setHighlight = (li, on) => {
        const idx = parseInt(li.dataset.planIndex);
        const plan = State.optimizationResult?.schnittplaene?.[idx];
        if (!plan) return;
        plan._hlCut = on && li.dataset.cutIndex != null ? parseInt(li.dataset.cutIndex) : null;
        plan._hlPiece = on && li.dataset.pieceIndex != null ? parseInt(li.dataset.pieceIndex) : null;
        const canvas = plansEl.querySelector(`canvas[data-plan-index="${idx}"]`);
        if (canvas) redrawPlanForCanvas(canvas);
    };
    plansEl.addEventListener('mouseover', e => {
        const li = e.target.closest('.cut-seq-list li');
        if (li) setHighlight(li, true);
    });
    plansEl.addEventListener('mouseout', e => {
        const li = e.target.closest('.cut-seq-list li');
        if (li) setHighlight(li, false);
    });
}

// Currently selected saw blade width (kerf) from the blade dropdown
function currentKerf() {
    const blade = State.blades.find(
        b => b.id === parseInt(document.getElementById('opt-blade')?.value));
    return blade?.schnittbreite || 0;
}

function draw2D(ctx, canvasW, canvasH, plan, colorMap, hits) {
    // Uniform mm→px scale: fit the panel into the padded canvas while
    // preserving the aspect ratio, then center the leftover space.
    const padding = 40;
    const drawW = canvasW - padding * 2;
    const drawH = canvasH - padding * 2;

    const scaleX = drawW / plan.lager_laenge;
    const scaleY = drawH / plan.lager_breite;
    const scale = Math.min(scaleX, scaleY);

    const stockW = plan.lager_laenge * scale;
    const stockH = plan.lager_breite * scale;
    const offsetX = padding + (drawW - stockW) / 2;
    const offsetY = padding + (drawH - stockH) / 2;

    // Stock background
    ctx.fillStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--sapNeutralBackground').trim() || '#e9ecef';
    ctx.fillRect(offsetX, offsetY, stockW, stockH);
    ctx.strokeStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--sapList_BorderColor').trim() || '#d1d5db';
    ctx.lineWidth = 1;
    ctx.strokeRect(offsetX, offsetY, stockW, stockH);

    // Parts
    plan.platzierungen.forEach(p => {
        // laenge/breite are already the actual x/y extents (rotation is
        // baked in by the optimizer) – do NOT swap them again here, or
        // rotated parts will overlap.
        const pw = p.laenge * scale;
        const ph = p.breite * scale;
        const px = offsetX + p.x * scale;
        const py = offsetY + p.y * scale;

        ctx.fillStyle = colorMap[p.teil_label] || PART_COLORS[0];
        ctx.fillRect(px, py, pw, ph);

        ctx.strokeStyle = 'rgba(0,0,0,0.3)';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(px, py, pw, ph);

        // Label text
        const fontSize = Math.max(9, Math.min(14, Math.min(pw, ph) / 4));
        ctx.font = `bold ${fontSize}px -apple-system, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const label = p.teil_label;
        const textW = ctx.measureText(label).width;

        if (textW < pw - 4 && fontSize < ph - 4) {
            ctx.fillStyle = 'rgba(0,0,0,0.4)';
            ctx.fillText(label, px + pw / 2 + 1, py + ph / 2 + 1);
            ctx.fillStyle = '#fff';
            ctx.fillText(label, px + pw / 2, py + ph / 2);
        }

        // Rotation indicator
        if (p.gedreht) {
            ctx.font = `bold ${Math.max(8, fontSize * 0.7)}px -apple-system, sans-serif`;
            ctx.fillStyle = 'rgba(255,255,255,0.8)';
            ctx.textAlign = 'right';
            ctx.textBaseline = 'top';
            ctx.fillText('R', px + pw - 3, py + 2);
        }

        if (hits) hits.push({ x: px, y: py, w: pw, h: ph, p });
        if (p._done) drawDoneOverlay(ctx, px, py, pw, ph);
    });

    // Guillotine cut lines (thin dashed) – show how the panel is decomposed
    // edge-to-edge. No numbers on the drawing (deliberate, kept uncluttered);
    // the ordered steps live in the cutting-sequence list next to the plan.
    const cuts = [];
    computeGuillotineCuts(
        plan.platzierungen.map(p => ({ x: p.x, y: p.y, laenge: p.laenge, breite: p.breite })),
        0, 0, plan.lager_laenge, plan.lager_breite, cuts, 0, currentKerf());
    if (cuts.length) {
        ctx.save();
        ctx.strokeStyle = 'rgba(0,0,0,0.55)';
        ctx.lineWidth = 0.9;
        ctx.setLineDash([5, 3]);
        cuts.forEach(c => {
            ctx.beginPath();
            if (c.v) {
                const xp = offsetX + c.pos * scale;
                ctx.moveTo(xp, offsetY + c.a * scale);
                ctx.lineTo(xp, offsetY + c.b * scale);
            } else {
                const yp = offsetY + c.pos * scale;
                ctx.moveTo(offsetX + c.a * scale, yp);
                ctx.lineTo(offsetX + c.b * scale, yp);
            }
            ctx.stroke();
        });
        // While hovering a cutting-sequence step: emphasize that cut line
        const hl = cuts[plan._hlCut];
        if (hl) {
            ctx.setLineDash([]);
            ctx.strokeStyle = 'rgba(170,8,8,0.95)';
            ctx.lineWidth = 2.5;
            ctx.beginPath();
            if (hl.v) {
                const xp = offsetX + hl.pos * scale;
                ctx.moveTo(xp, offsetY + hl.a * scale);
                ctx.lineTo(xp, offsetY + hl.b * scale);
            } else {
                const yp = offsetY + hl.pos * scale;
                ctx.moveTo(offsetX + hl.a * scale, yp);
                ctx.lineTo(offsetX + hl.b * scale, yp);
            }
            ctx.stroke();
        }
        ctx.restore();
    }

    // Dimension annotations
    ctx.fillStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--sapContent_LabelColor').trim() || '#6b7280';
    ctx.font = '11px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(formatDim(plan.lager_laenge), offsetX + stockW / 2, offsetY + stockH + 6);

    ctx.save();
    ctx.translate(offsetX - 6, offsetY + stockH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText(formatDim(plan.lager_breite), 0, 0);
    ctx.restore();
}

function draw1D(ctx, canvasW, canvasH, plan, colorMap, hits) {
    const padding = { left: 20, right: 20, top: 15, bottom: 30 };
    const barH = 50;
    const barY = padding.top;
    const drawW = canvasW - padding.left - padding.right;
    const scale = drawW / plan.lager_laenge;

    // Stock bar background
    ctx.fillStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--sapNeutralBackground').trim() || '#e9ecef';
    ctx.fillRect(padding.left, barY, drawW, barH);
    ctx.strokeStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--sapList_BorderColor').trim() || '#d1d5db';
    ctx.lineWidth = 1;
    ctx.strokeRect(padding.left, barY, drawW, barH);

    // Parts
    plan.platzierungen.forEach(p => {
        const px = padding.left + p.x * scale;
        const pw = p.laenge * scale;

        ctx.fillStyle = colorMap[p.teil_label] || PART_COLORS[0];
        ctx.fillRect(px, barY, pw, barH);

        ctx.strokeStyle = 'rgba(0,0,0,0.3)';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(px, barY, pw, barH);

        // Label
        const fontSize = Math.max(9, Math.min(12, pw / 6));
        ctx.font = `bold ${fontSize}px -apple-system, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const textW = ctx.measureText(p.teil_label).width;
        if (textW < pw - 4) {
            ctx.fillStyle = 'rgba(0,0,0,0.4)';
            ctx.fillText(p.teil_label, px + pw / 2 + 0.5, barY + barH / 2 + 0.5);
            ctx.fillStyle = '#fff';
            ctx.fillText(p.teil_label, px + pw / 2, barY + barH / 2);
        }

        if (hits) hits.push({ x: px, y: barY, w: pw, h: barH, p });
        if (p._done) drawDoneOverlay(ctx, px, barY, pw, barH);
    });

    // While hovering a cutting-sequence step: outline that piece
    const hlPiece = plan.platzierungen[plan._hlPiece];
    if (hlPiece) {
        const px = padding.left + hlPiece.x * scale;
        const pw = hlPiece.laenge * scale;
        ctx.strokeStyle = 'rgba(170,8,8,0.95)';
        ctx.lineWidth = 2.5;
        ctx.strokeRect(px + 1, barY + 1, pw - 2, barH - 2);
    }

    // Rest areas (unused at the end)
    plan.reste.forEach(rest => {
        if (rest.length >= 1 && rest[0] > 0) {
            const restLen = rest[0];
            const rx = padding.left + (plan.lager_laenge - restLen) * scale;
            const rw = restLen * scale;
            ctx.fillStyle = 'rgba(128,128,128,0.2)';
            ctx.fillRect(rx, barY, rw, barH);
            ctx.strokeStyle = 'rgba(0,0,0,0.15)';
            ctx.setLineDash([4, 2]);
            ctx.strokeRect(rx, barY, rw, barH);
            ctx.setLineDash([]);
        }
    });

    // Dimension label
    ctx.fillStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--sapContent_LabelColor').trim() || '#6b7280';
    ctx.font = '11px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(formatDim(plan.lager_laenge), padding.left + drawW / 2, barY + barH + 6);
}

// ===========================================================================
// 8. MODAL / DIALOG SYSTEM
// ===========================================================================

function openModal(title, fields, data, onSave) {
    const overlay = document.getElementById('modal-overlay');
    const titleEl = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    const saveBtn = document.getElementById('modal-save');
    const cancelBtn = document.getElementById('modal-cancel');

    titleEl.textContent = title;
    saveBtn.style.display = '';

    body.innerHTML = fields.map(f => {
        if (f.hidden) return `<div class="form-group" data-field="${f.key}" style="display:none">${fieldHtml(f, data)}</div>`;
        return `<div class="form-group" data-field="${f.key}">${fieldHtml(f, data)}</div>`;
    }).join('');

    overlay.classList.remove('hidden');
    overlay.classList.add('active');

    const firstInput = body.querySelector('input, select');
    if (firstInput) setTimeout(() => firstInput.focus(), 100);

    const save = () => {
        const formData = {};
        let valid = true;
        fields.forEach(f => {
            if (f.hidden) return;
            const el = body.querySelector(`[name="${f.key}"]`);
            if (!el) return;
            const grp = el.closest('.form-group');
            if (grp && grp.style.display === 'none') return;
            let val;
            if (f.type === 'number') {
                val = el.value === '' ? null : parseFloat(el.value);
                if (f.required && (val === null || isNaN(val))) {
                    el.style.borderColor = 'var(--sapNegativeColor, #d20a0a)';
                    valid = false;
                    return;
                }
                if (f.isDimension) {
                    val = val !== null ? toMm(val) : 0;
                }
                if (val !== null && f.min != null && val < f.min) {
                    el.style.borderColor = 'var(--sapNegativeColor, #d20a0a)';
                    valid = false;
                    return;
                }
            } else if (f.type === 'select') {
                val = el.value;
            } else {
                val = el.value.trim();
                if (f.required && !val) {
                    el.style.borderColor = 'var(--sapNegativeColor, #d20a0a)';
                    valid = false;
                    return;
                }
            }
            formData[f.key] = val;
        });
        if (!valid) return;
        closeModal();
        onSave(formData);
    };

    saveBtn.onclick = save;

    // Enter key to save from text/number inputs
    body.querySelectorAll('input').forEach(inp => {
        inp.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); save(); }
        });
    });
}

function fieldHtml(f, data) {
    const val = data?.[f.key] ?? f.default ?? '';
    const displayVal = f.isDimension && val ? toDisplay(val) : val;
    const label = f.label || t(f.labelKey || f.key);
    const unitSuffix = f.isDimension ? ` (${unitLabel()})` : '';
    const req = f.required ? ' required' : '';

    let input;
    if (f.type === 'select') {
        const opts = (f.options || []).map(o =>
            `<option value="${o.value}"${String(o.value) === String(val) ? ' selected' : ''}>${escHtml(o.text)}</option>`
        ).join('');
        input = `<select name="${f.key}" class="cs-select">${opts}</select>`;
    } else if (f.type === 'number') {
        const step = f.step ?? (f.isDimension ? 'any' : 1);
        const min = f.min != null ? ` min="${f.min}"` : '';
        const ph = f.placeholder ?? '';
        input = `<input type="number" name="${f.key}" value="${displayVal}" step="${step}"${min}${req} placeholder="${ph}">`;
    } else {
        const ph = f.placeholder ?? '';
        input = `<input type="text" name="${f.key}" value="${escAttr(displayVal)}"${req} placeholder="${ph}">`;
    }

    return `<label class="fd-form-label">${escHtml(label)}${unitSuffix}</label>${input}`;
}

function closeModal() {
    const overlay = document.getElementById('modal-overlay');
    overlay.classList.remove('active');
    overlay.classList.add('hidden');
    document.getElementById('modal-body').innerHTML = '';
    document.getElementById('modal-save').onclick = null;
}

// ---------------------------------------------------------------------------
// Specific Dialogs
// ---------------------------------------------------------------------------

function openMaterialDialog(material = null) {
    const isEdit = !!material;
    const title = isEdit ? t('mat.edit') : t('mat.new');
    const data = material ? { ...material } : { typ: 'Platte', maserung: 'keine' };

    const fields = [
        { key: 'name', label: t('mat.name'), type: 'text', required: true },
        {
            key: 'typ', label: t('mat.type'), type: 'select',
            options: [
                { value: 'Platte', text: t('mat.plate') },
                { value: 'Stange', text: t('mat.bar') },
            ]
        },
        { key: 'dicke', label: t('mat.thickness'), type: 'number', isDimension: true, platteOnly: true },
        { key: 'querschnitt_breite', label: t('mat.cross_w'), type: 'number', isDimension: true, stangeOnly: true },
        { key: 'querschnitt_tiefe', label: t('mat.cross_d'), type: 'number', isDimension: true, stangeOnly: true },
        {
            key: 'maserung', label: t('mat.grain'), type: 'select', platteOnly: true,
            options: [
                { value: 'keine', text: t('mat.grain.none') },
                { value: 'längs', text: t('mat.grain.long') },
                { value: 'quer', text: t('mat.grain.cross') },
            ]
        },
        { key: 'besaeumung', label: t('mat.trim'), type: 'number', isDimension: true },
        { key: 'rest_min_laenge', label: t('mat.min_rest_l'), type: 'number', isDimension: true },
        { key: 'rest_min_breite', label: t('mat.min_rest_w'), type: 'number', isDimension: true, platteOnly: true },
    ];

    openModal(title, fields, data, async (formData) => {
        try {
            if (isEdit) {
                await Api.updateMaterial(material.id, formData);
            } else {
                await Api.createMaterial(formData);
            }
            await renderMaterials();
            renderOptDropdowns();
        } catch { /* fetchJSON shows toast */ }
    });

    // Dynamic show/hide for typ-dependent fields
    setupMaterialTypToggle(data.typ || 'Platte');

    const typSel = document.querySelector('#modal-body [name="typ"]');
    if (typSel) {
        typSel.addEventListener('change', () => setupMaterialTypToggle(typSel.value));
    }
}

function setupMaterialTypToggle(typ) {
    const body = document.getElementById('modal-body');
    if (!body) return;
    const isPlatte = typ === 'Platte';

    body.querySelectorAll('.form-group').forEach(grp => {
        const field = grp.dataset.field;
        if (!field) return;
        // Find the field spec to check platteOnly / stangeOnly
        const isPlatteField = ['dicke', 'maserung', 'rest_min_breite'].includes(field);
        const isStangeField = ['querschnitt_breite', 'querschnitt_tiefe'].includes(field);

        if (isPlatteField) grp.style.display = isPlatte ? '' : 'none';
        if (isStangeField) grp.style.display = isPlatte ? 'none' : '';
    });
}

function openStockDialog(stock = null) {
    const isEdit = !!stock;
    const mat = getSelectedMaterial();
    if (!mat) {
        showToast(t('dlg.select_material'), 'error');
        return;
    }
    const isPlatte = mat.typ === 'Platte';
    const title = isEdit ? t('stock.edit') : t('stock.new');
    const data = stock ? { ...stock } : { stueckzahl: 1 };

    const fields = [
        { key: 'laenge', label: t('stock.length'), type: 'number', required: true, isDimension: true, min: 0.1 },
        { key: 'breite', label: t('stock.width'), type: 'number', isDimension: true, hidden: !isPlatte, min: 0.1 },
        { key: 'stueckzahl', label: t('stock.qty'), type: 'number', required: true, min: 1, step: 1 },
    ];

    openModal(title, fields, data, async (formData) => {
        formData.material_id = mat.id;
        if (!isPlatte) formData.breite = 0;
        try {
            if (isEdit) {
                await Api.updateStock(stock.id, formData);
            } else {
                await Api.createStock(formData);
            }
            await renderStock();
        } catch { /* handled */ }
    });
}

function openProjectDialog(project = null) {
    const isEdit = !!project;
    const title = isEdit ? t('proj.edit') : t('proj.new');
    const data = project ? { ...project } : {};

    const fields = [
        { key: 'name', label: t('proj.name'), type: 'text', required: true },
    ];

    openModal(title, fields, data, async (formData) => {
        try {
            if (isEdit) {
                await Api.updateProject(project.id, formData);
            } else {
                await Api.createProject(formData);
            }
            await renderProjects();
            renderOptDropdowns();
        } catch { /* handled */ }
    });
}

// Projekt als JSON exportieren – Format kompatibel mit der Desktop-App
async function exportProject() {
    const proj = State.projects.find(p => p.id === State.selectedProjectId);
    if (!proj) { showToast(t('dlg.select_project'), 'error'); return; }

    let teile = proj.teile;
    if (!teile) {
        try { teile = await Api.getParts(proj.id); } catch { return; }
    }

    const parts = teile.map(teil => {
        const mat = State.materials.find(m => m.id === teil.material_id);
        const entry = {
            label: teil.label,
            type: teil.typ,
            material: mat ? mat.name : '',
            length: teil.laenge,
            quantity: teil.stueckzahl,
            grain: teil.maserung,
        };
        if (teil.typ === 'Platte') entry.width = teil.breite;
        return entry;
    });

    const data = { project: proj.name, parts };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${proj.name}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast(t('proj.export_done'), 'info');
}

// Projekt aus JSON importieren – Material per Name→ID, fehlende melden
async function importProject(file) {
    let data;
    try {
        data = JSON.parse(await file.text());
    } catch {
        showToast(t('error.pdf_failed'), 'error');
        return;
    }

    const matByName = new Map(State.materials.map(m => [m.name, m]));

    let project;
    try {
        project = await Api.createProject({ name: data.project || 'Import' });
    } catch { return; }

    let imported = 0;
    const missing = new Set();
    for (const p of (data.parts || [])) {
        const mat = matByName.get(p.material || '');
        if (!mat) { missing.add(p.material || '?'); continue; }
        const typ = p.type === 'Stange' ? 'Stange' : 'Platte';
        try {
            await Api.createPart(project.id, {
                label: p.label || '',
                typ,
                material_id: mat.id,
                laenge: p.length || 0,
                breite: typ === 'Platte' ? (p.width || 0) : 0,
                stueckzahl: p.quantity || 1,
                gesaegt_anzahl: 0,
                maserung: p.grain || 'egal',
            });
            imported++;
        } catch { /* skip */ }
    }

    State.selectedProjectId = project.id;
    await renderProjects();
    State.projects = await Api.getProjects();
    renderOptDropdowns();

    if (missing.size > 0) {
        showToast(t('proj.import_missing', { materials: [...missing].sort().join(', ') }), 'error');
    } else {
        showToast(t('proj.import_done', { n: imported }), 'info');
    }
}

// ---------------------------------------------------------------------------
// CSV import for part lists (e.g. exported from Excel/Numbers).
// Delimiter (; , tab) and header row are auto-detected; without a header the
// column order is label, length, width, quantity, grain, material.
// Dimensions are interpreted in the currently configured display unit.
// ---------------------------------------------------------------------------

const CSV_COLS = {
    label: ['label', 'name', 'bezeichnung', 'teil', 'part', 'pièce', 'pezzo'],
    laenge: ['länge', 'laenge', 'length', 'longueur', 'lunghezza', 'l'],
    breite: ['breite', 'width', 'largeur', 'larghezza', 'b'],
    stueckzahl: ['anzahl', 'menge', 'stück', 'stueck', 'stk', 'qty', 'quantity',
        'count', 'pcs', 'quantité', 'quantita', 'quantità'],
    maserung: ['maserung', 'grain', 'veinage', 'venatura'],
    material: ['material', 'werkstoff', 'matériau', 'materiau', 'materiale'],
};

function detectCsvDelimiter(line) {
    const counts = [';', '\t', ','].map(d => ({ d, n: line.split(d).length - 1 }));
    const best = counts.reduce((a, b) => (b.n > a.n ? b : a));
    return best.n > 0 ? best.d : ';';
}

// Split one CSV line; double-quoted fields (with "" escapes) are supported
function splitCsvLine(line, delim) {
    const out = [];
    let cur = '', inQ = false;
    for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (inQ) {
            if (ch === '"') {
                if (line[i + 1] === '"') { cur += '"'; i++; } else inQ = false;
            } else cur += ch;
        } else if (ch === '"') inQ = true;
        else if (ch === delim) { out.push(cur); cur = ''; }
        else cur += ch;
    }
    out.push(cur);
    return out.map(s => s.trim());
}

function parseCsvNumber(s, delim) {
    if (s == null || s === '') return 0;
    s = String(s).replace(/\s/g, '');
    if (delim !== ',') s = s.replace(',', '.');  // allow decimal comma
    const v = parseFloat(s);
    return isNaN(v) ? 0 : v;
}

function normalizeGrain(g) {
    g = (g || '').toLowerCase();
    if (/längs|laengs|long|length/.test(g)) return 'längs';
    if (/quer|cross|trans/.test(g)) return 'quer';
    return 'egal';
}

async function importPartsCsv(file) {
    if (!State.selectedProjectId) { showToast(t('dlg.select_project'), 'error'); return; }

    let text;
    try { text = await file.text(); } catch { showToast(t('csv.invalid'), 'error'); return; }
    const lines = text.replace(/\r\n?/g, '\n').split('\n').filter(l => l.trim() !== '');
    if (!lines.length) { showToast(t('csv.invalid'), 'error'); return; }

    const delim = detectCsvDelimiter(lines[0]);
    let rows = lines.map(l => splitCsvLine(l, delim));

    // Header detection: at least 2 recognized column names
    const norm = s => (s || '').toLowerCase().replace(/[:*"]/g, '').trim();
    let colIdx = {};
    let matched = 0;
    rows[0].map(norm).forEach((cell, i) => {
        for (const [key, names] of Object.entries(CSV_COLS)) {
            if (colIdx[key] == null && names.includes(cell)) { colIdx[key] = i; matched++; }
        }
    });
    if (matched >= 2) {
        rows = rows.slice(1);
    } else {
        colIdx = { label: 0, laenge: 1, breite: 2, stueckzahl: 3, maserung: 4, material: 5 };
    }

    const cell = (row, key) => colIdx[key] != null ? (row[colIdx[key]] ?? '') : '';
    const items = rows.map(row => ({
        label: cell(row, 'label'),
        laenge: parseCsvNumber(cell(row, 'laenge'), delim),
        breite: parseCsvNumber(cell(row, 'breite'), delim),
        stueckzahl: Math.max(1, Math.round(parseCsvNumber(cell(row, 'stueckzahl'), delim)) || 1),
        maserung: normalizeGrain(cell(row, 'maserung')),
        materialName: cell(row, 'material'),
    })).filter(it => it.laenge > 0);

    if (!items.length) { showToast(t('csv.invalid'), 'error'); return; }

    // Confirm dialog + default material for rows without a (valid) material
    const fields = [{
        key: 'material_id', label: t('csv.default_material'), type: 'select',
        options: State.materials.map(m => ({ value: m.id, text: m.name })),
    }];
    openModal(t('csv.import'), fields, {}, async (formData) => {
        const defaultMat = State.materials.find(m => m.id === parseInt(formData.material_id));
        const matByName = new Map(State.materials.map(m => [m.name.toLowerCase(), m]));

        let imported = 0, skipped = 0;
        const missing = new Set();
        let nextNr = (State.parts || []).length + 1;
        for (const it of items) {
            let mat = defaultMat;
            if (it.materialName) {
                const found = matByName.get(it.materialName.toLowerCase());
                if (found) mat = found;
                else { missing.add(it.materialName); continue; }
            }
            if (!mat) { skipped++; continue; }
            const isPlatte = mat.typ === 'Platte';
            if (isPlatte && it.breite <= 0) { skipped++; continue; }
            try {
                await Api.createPart(State.selectedProjectId, {
                    label: it.label || `Teil ${nextNr}`,
                    typ: mat.typ,
                    material_id: mat.id,
                    laenge: toMm(it.laenge),
                    breite: isPlatte ? toMm(it.breite) : 0,
                    stueckzahl: it.stueckzahl,
                    gesaegt_anzahl: 0,
                    maserung: isPlatte ? it.maserung : 'egal',
                });
                imported++;
                nextNr++;
            } catch { skipped++; }
        }

        await renderParts();
        State.projects = await Api.getProjects();
        renderOptDropdowns();

        if (missing.size > 0) {
            showToast(t('proj.import_missing', { materials: [...missing].sort().join(', ') }), 'error');
        } else if (skipped > 0) {
            showToast(`${t('proj.import_done', { n: imported })} (${skipped} ✗)`, 'error');
        } else {
            showToast(t('proj.import_done', { n: imported }), 'info');
        }
    });

    // Show detected count + assumed unit above the material field
    document.getElementById('modal-body').insertAdjacentHTML('afterbegin',
        `<p style="margin:0 0 0.75rem">${escHtml(t('csv.confirm', { n: items.length, unit: unitLabel() }))}</p>`);
}

function openPartDialog(part = null) {
    const isEdit = !!part;
    if (!State.selectedProjectId) {
        showToast(t('dlg.select_project'), 'error');
        return;
    }

    const title = isEdit ? t('part.edit') : t('part.new');
    const defaultLabel = isEdit ? undefined : `Teil ${(State.parts || []).length + 1}`;
    const data = part ? { ...part } : { typ: 'Platte', stueckzahl: 1, gesaegt_anzahl: 0, maserung: 'egal', label: defaultLabel };

    const currentTyp = data.typ || 'Platte';

    const fields = [
        { key: 'label', label: t('part.label'), type: 'text', required: true },
        {
            key: 'typ', label: t('mat.type'), type: 'select',
            options: [
                { value: 'Platte', text: t('mat.plate') },
                { value: 'Stange', text: t('mat.bar') },
            ]
        },
        {
            key: 'material_id', label: t('opt.material'), type: 'select',
            options: State.materials
                .filter(m => m.typ === currentTyp)
                .map(m => ({ value: m.id, text: m.name })),
        },
        {
            key: 'maserung', label: t('mat.grain'), type: 'select', platteOnly: true,
            options: [
                { value: 'egal', text: t('part.grain.any') },
                { value: 'längs', text: t('part.grain.long') },
                { value: 'quer', text: t('part.grain.cross') },
            ]
        },
        { key: 'laenge', label: t('stock.length'), type: 'number', required: true, isDimension: true, min: 0.1 },
        { key: 'breite', label: t('stock.width'), type: 'number', isDimension: true, platteOnly: true, min: 0.1 },
        { key: 'stueckzahl', label: t('stock.qty'), type: 'number', required: true, min: 1, step: 1 },
    ];

    // Beim Bearbeiten den Gesägt-Fortschritt editierbar machen
    if (isEdit) {
        fields.push({ key: 'gesaegt_anzahl', label: t('part.sawn_count'), type: 'number', min: 0, step: 1 });
    }

    openModal(title, fields, data, async (formData) => {
        if (formData.typ === 'Stange') {
            formData.breite = 0;
        }
        const stk = parseInt(formData.stueckzahl) || 0;
        formData.gesaegt_anzahl = isEdit
            ? Math.max(0, Math.min(stk, parseInt(formData.gesaegt_anzahl) || 0))
            : (data.gesaegt_anzahl || 0);
        formData.material_id = parseInt(formData.material_id);
        try {
            if (isEdit) {
                await Api.updatePart(part.id, formData);
            } else {
                await Api.createPart(State.selectedProjectId, formData);
            }
            await renderParts();
            // Refresh projects to update offen_anzahl in optimization dropdowns
            State.projects = await Api.getProjects();
            renderOptDropdowns();
        } catch { /* handled */ }
    });

    setupPartTypToggle(currentTyp);

    const typSel = document.querySelector('#modal-body [name="typ"]');
    if (typSel) {
        typSel.addEventListener('change', () => {
            setupPartTypToggle(typSel.value);
            // Update material dropdown filter
            const matSel = document.querySelector('#modal-body [name="material_id"]');
            if (matSel) {
                const filtered = State.materials.filter(m => m.typ === typSel.value);
                matSel.innerHTML = filtered.map(m =>
                    `<option value="${m.id}">${escHtml(m.name)}</option>`
                ).join('');
            }
        });
    }
}

function setupPartTypToggle(typ) {
    const body = document.getElementById('modal-body');
    if (!body) return;
    const isPlatte = typ === 'Platte';

    body.querySelectorAll('.form-group').forEach(grp => {
        const field = grp.dataset.field;
        if (field === 'breite' || field === 'maserung') {
            grp.style.display = isPlatte ? '' : 'none';
        }
    });
}

function openBladeDialog(blade = null) {
    const isEdit = !!blade;
    const title = isEdit ? t('blade.edit') : t('blade.new');
    const data = blade ? { ...blade } : {};

    const fields = [
        { key: 'name', label: t('blade.name'), type: 'text', required: true },
        { key: 'schnittbreite', label: t('blade.kerf'), type: 'number', required: true, isDimension: true, min: 0.1, step: 0.1 },
    ];

    openModal(title, fields, data, async (formData) => {
        try {
            if (isEdit) {
                await Api.updateBlade(blade.id, formData);
            } else {
                await Api.createBlade(formData);
            }
            await renderBlades();
            renderOptDropdowns();
        } catch { /* handled */ }
    });
}

function openConfirmDialog(message, onConfirm) {
    const overlay = document.getElementById('modal-overlay');
    const titleEl = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    const saveBtn = document.getElementById('modal-save');

    titleEl.textContent = t('btn.confirm');
    body.innerHTML = `<p style="padding:8px 0">${escHtml(message)}</p>`;
    saveBtn.style.display = '';
    saveBtn.textContent = t('btn.confirm');

    overlay.classList.remove('hidden');
    overlay.classList.add('active');

    saveBtn.onclick = () => {
        closeModal();
        saveBtn.textContent = t('btn.save');
        onConfirm();
    };

    const cancelBtn = document.getElementById('modal-cancel');
    const origCancel = cancelBtn.onclick;
    cancelBtn.onclick = () => {
        closeModal();
        saveBtn.textContent = t('btn.save');
        if (origCancel) cancelBtn.onclick = origCancel;
    };
}

// ===========================================================================
// 9. EVENT HANDLERS
// ===========================================================================

// Zwischen den beiden Panels (Material, Projekte) einen ziehbaren Splitter
// einsetzen; das Breitenverhältnis wird pro Tab in localStorage gemerkt.
function setupSplitters() {
    document.querySelectorAll('.split-panel').forEach(sp => {
        if (sp._resizable) return;
        const panels = sp.querySelectorAll(':scope > .panel');
        if (panels.length !== 2) return;
        sp._resizable = true;
        sp.classList.add('resizable');

        const splitter = document.createElement('div');
        splitter.className = 'panel-splitter';
        sp.insertBefore(splitter, panels[1]);

        const key = 'cutstock.split.' + (sp.closest('.tab-content')?.id || 'x');
        let leftFr = parseFloat(localStorage.getItem(key));
        if (!(leftFr > 0.2 && leftFr < 0.8)) leftFr = 0.5;
        const apply = () => {
            sp.style.setProperty('--split-cols', `${leftFr}fr 16px ${1 - leftFr}fr`);
        };
        apply();

        let dragging = false;
        splitter.addEventListener('pointerdown', (e) => {
            dragging = true;
            splitter.classList.add('dragging');
            splitter.setPointerCapture(e.pointerId);
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });
        splitter.addEventListener('pointermove', (e) => {
            if (!dragging) return;
            const rect = sp.getBoundingClientRect();
            let frac = (e.clientX - rect.left) / rect.width;
            leftFr = Math.max(0.2, Math.min(0.8, frac));
            apply();
        });
        const end = () => {
            if (!dragging) return;
            dragging = false;
            splitter.classList.remove('dragging');
            document.body.style.userSelect = '';
            localStorage.setItem(key, String(leftFr));
        };
        splitter.addEventListener('pointerup', end);
        splitter.addEventListener('pointercancel', end);
    });
}

function initEvents() {
    setupSplitters();

    // ----- Tab switching -----
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            const tabId = btn.dataset.tab;
            const panel = document.getElementById(`tab-${tabId}`);
            if (panel) panel.classList.add('active');

            if (tabId === 'material') { renderMaterials(); }
            else if (tabId === 'projects') { renderProjects(); }
            else if (tabId === 'optimization') { renderOptDropdowns(); }
            else if (tabId === 'settings') { renderSettings(); renderBlades(); }
        });
    });

    // ----- Theme toggle -----
    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) {
        themeBtn.addEventListener('click', async () => {
            const next = THEME_CYCLE[State.settings.theme] || 'system';
            State.settings.theme = next;
            applyTheme(next);
            themeBtn.textContent = THEME_ICONS[next] || THEME_ICONS.system;
            try { await Api.updateSettings({ theme: next }); } catch { /* non-critical */ }
        });
    }

    // ----- Material CRUD -----
    document.getElementById('btn-mat-new')?.addEventListener('click', () => openMaterialDialog());
    document.getElementById('btn-mat-edit')?.addEventListener('click', () => {
        const mat = getSelectedMaterial();
        if (!mat) { showToast(t('dlg.select_material'), 'error'); return; }
        openMaterialDialog(mat);
    });
    document.getElementById('btn-mat-del')?.addEventListener('click', () => {
        const mat = getSelectedMaterial();
        if (!mat) { showToast(t('dlg.select_material'), 'error'); return; }
        openConfirmDialog(t('dlg.delete_material', { n: 0 }), async () => {
            try {
                await Api.deleteMaterial(mat.id);
                State.selectedMaterialId = null;
                await renderMaterials();
                renderOptDropdowns();
            } catch { /* handled */ }
        });
    });

    // ----- Stock CRUD -----
    document.getElementById('btn-stock-new')?.addEventListener('click', () => {
        if (!State.selectedMaterialId) { showToast(t('dlg.select_material'), 'error'); return; }
        openStockDialog();
    });
    document.getElementById('btn-stock-edit')?.addEventListener('click', () => {
        const stock = State.stock.find(s => s.id === State.selectedStockId);
        if (!stock) { showToast(t('dlg.select_material'), 'error'); return; }
        openStockDialog(stock);
    });
    document.getElementById('btn-stock-del')?.addEventListener('click', () => {
        const stock = State.stock.find(s => s.id === State.selectedStockId);
        if (!stock) { showToast(t('dlg.select_material'), 'error'); return; }
        openConfirmDialog(t('dlg.delete_stock'), async () => {
            try {
                await Api.deleteStock(stock.id);
                State.selectedStockId = null;
                await renderStock();
            } catch { /* handled */ }
        });
    });

    // ----- Project CRUD -----
    document.getElementById('btn-proj-new')?.addEventListener('click', () => openProjectDialog());
    document.getElementById('btn-proj-edit')?.addEventListener('click', () => {
        const proj = State.projects.find(p => p.id === State.selectedProjectId);
        if (!proj) { showToast(t('dlg.select_project'), 'error'); return; }
        openProjectDialog(proj);
    });
    document.getElementById('btn-proj-del')?.addEventListener('click', () => {
        const proj = State.projects.find(p => p.id === State.selectedProjectId);
        if (!proj) { showToast(t('dlg.select_project'), 'error'); return; }
        openConfirmDialog(t('dlg.delete_project'), async () => {
            try {
                await Api.deleteProject(proj.id);
                State.selectedProjectId = null;
                await renderProjects();
                renderOptDropdowns();
            } catch { /* handled */ }
        });
    });

    // ----- Projekt Export / Import (JSON, kompatibel mit Desktop-App) -----
    document.getElementById('btn-proj-export')?.addEventListener('click', () => exportProject());
    document.getElementById('btn-proj-import')?.addEventListener('click', () => {
        document.getElementById('proj-import-file')?.click();
    });
    document.getElementById('proj-import-file')?.addEventListener('change', async (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';  // allow picking the same file again
        if (file) await importProject(file);
    });

    // ----- Teile-CSV-Import -----
    document.getElementById('btn-part-csv')?.addEventListener('click', () => {
        if (!State.selectedProjectId) { showToast(t('dlg.select_project'), 'error'); return; }
        document.getElementById('part-csv-file')?.click();
    });
    document.getElementById('part-csv-file')?.addEventListener('change', async (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';  // allow picking the same file again
        if (file) await importPartsCsv(file);
    });

    // ----- Part CRUD -----
    document.getElementById('btn-part-new')?.addEventListener('click', () => {
        if (!State.selectedProjectId) { showToast(t('dlg.select_project'), 'error'); return; }
        openPartDialog();
    });
    document.getElementById('btn-part-edit')?.addEventListener('click', () => {
        const part = State.parts.find(p => p.id === State.selectedPartId);
        if (!part) { showToast(t('dlg.select_project'), 'error'); return; }
        openPartDialog(part);
    });
    document.getElementById('btn-part-del')?.addEventListener('click', () => {
        const part = State.parts.find(p => p.id === State.selectedPartId);
        if (!part) { showToast(t('dlg.select_project'), 'error'); return; }
        openConfirmDialog(t('dlg.delete_part'), async () => {
            try {
                await Api.deletePart(part.id);
                State.selectedPartId = null;
                await renderParts();
                State.projects = await Api.getProjects();
                renderOptDropdowns();
            } catch { /* handled */ }
        });
    });

    // ----- Blade CRUD -----
    document.getElementById('btn-blade-new')?.addEventListener('click', () => openBladeDialog());
    document.getElementById('btn-blade-edit')?.addEventListener('click', () => {
        const blade = State.blades.find(b => b.id === State.selectedBladeId);
        if (!blade) { showToast(t('dlg.delete_blade'), 'error'); return; }
        openBladeDialog(blade);
    });
    document.getElementById('btn-blade-del')?.addEventListener('click', () => {
        const blade = State.blades.find(b => b.id === State.selectedBladeId);
        if (!blade) { showToast(t('dlg.delete_blade'), 'error'); return; }
        openConfirmDialog(t('dlg.delete_blade'), async () => {
            try {
                await Api.deleteBlade(blade.id);
                State.selectedBladeId = null;
                await renderBlades();
                renderOptDropdowns();
            } catch { /* handled */ }
        });
    });

    // ----- Optimization -----
    document.getElementById('btn-optimize')?.addEventListener('click', async () => {
        const projId = parseInt(document.getElementById('opt-project')?.value);
        const matId = parseInt(document.getElementById('opt-material')?.value);
        const bladeId = parseInt(document.getElementById('opt-blade')?.value);
        const algo = document.getElementById('opt-algorithm')?.value || 'greedy';

        if (!projId || !matId || !bladeId) {
            showToast(t('dlg.select_all'), 'error');
            return;
        }

        const btn = document.getElementById('btn-optimize');
        btn.disabled = true;
        btn.textContent = '...';

        try {
            State.optimizationResult = await Api.optimize({
                project_id: projId,
                material_id: matId,
                blade_id: bladeId,
                algorithm: algo,
            });
            // Ergebnis mit seiner Auswahl markieren, um veraltete Anzeige zu erkennen
            State.optimizationResult._projId = String(projId);
            renderOptResults();
        } catch {
            State.optimizationResult = null;
            renderOptResults();
        } finally {
            btn.disabled = false;
            btn.textContent = t('opt.run');
        }
    });

    document.getElementById('btn-confirm')?.addEventListener('click', () => {
        if (!State.optimizationResult) return;
        openConfirmDialog(t('opt.confirm_msg'), () => confirmAllPieces());
    });

    document.getElementById('btn-pdf')?.addEventListener('click', () => {
        if (!State.optimizationResult) return;
        const projSel = document.getElementById('opt-project');
        const matSel = document.getElementById('opt-material');
        const bladeSel = document.getElementById('opt-blade');
        const matId = parseInt(matSel?.value);
        const mat = State.materials.find(m => m.id === matId);

        const is1D = mat?.typ === 'Stange';
        // Schnittfolge pro Platte mitgeben (vorformatiert, nur 2D sinnvoll)
        const kerf = currentKerf();
        const schnittfolgen = is1D ? [] : (State.optimizationResult.schnittplaene || [])
            .map(plan => buildCutSequence(plan, false, kerf).map(s => s.text));

        Api.downloadPdf({
            ergebnis: State.optimizationResult,
            projekt_name: projSel?.selectedOptions[0]?.text || '',
            material_name: matSel?.selectedOptions[0]?.text || '',
            saegeblatt_name: bladeSel?.selectedOptions[0]?.text || '',
            is_1d: is1D,
            schnittfolgen,
            schnittfolge_titel: t('seq.title'),
        });
    });

    // ----- Optimization project dropdown changes material filter -----
    document.getElementById('opt-project')?.addEventListener('change', () => {
        updateOptMaterialDropdown();
        clearOptResult();
    });

    // Auswahländerung macht den angezeigten Schnittplan ungültig
    ['opt-material', 'opt-blade', 'opt-algorithm'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', () => clearOptResult());
    });

    // ----- Settings -----
    document.getElementById('settings-lang')?.addEventListener('change', async (e) => {
        State.settings.language = e.target.value;
        try {
            await Api.updateSettings({ language: e.target.value });
            State.translations = await Api.getTranslations(e.target.value);
            applyTranslations();
            // Dynamisch erzeugte Inhalte in der neuen Sprache neu aufbauen
            renderOptDropdowns();
            if (State.optimizationResult) renderOptResults();
            renderMaterials();
            renderProjects();
            renderSettings();
        } catch { /* non-critical */ }
    });

    document.getElementById('settings-unit')?.addEventListener('change', async (e) => {
        State.settings.unit = e.target.value;
        try {
            await Api.updateSettings({ unit: e.target.value });
            // Re-render tables to show new units
            const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab;
            if (activeTab === 'material') { renderMaterials(); }
            else if (activeTab === 'projects') { renderParts(); }
        } catch { /* non-critical */ }
    });

    document.getElementById('settings-theme')?.addEventListener('change', async (e) => {
        State.settings.theme = e.target.value;
        applyTheme(e.target.value);
        const themeBtn = document.getElementById('theme-toggle');
        if (themeBtn) themeBtn.textContent = THEME_ICONS[e.target.value] || THEME_ICONS.system;
        try { await Api.updateSettings({ theme: e.target.value }); } catch { /* non-critical */ }
    });

    // ----- Etiketten-Format -----
    document.getElementById('settings-label-format')?.addEventListener('change', async (e) => {
        State.settings.label_format = e.target.value;
        updateLabelCustomVisibility();
        try { await Api.updateSettings({ label_format: e.target.value }); } catch { /* non-critical */ }
    });
    ['settings-label-w', 'settings-label-h'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', async (e) => {
            const v = Math.max(1, parseFloat(e.target.value) || 0);
            const key = id.endsWith('-w') ? 'label_custom_w' : 'label_custom_h';
            State.settings[key] = v;
            try { await Api.updateSettings({ [key]: v }); } catch { /* non-critical */ }
        });
    });

    // ----- Backup / Restore -----
    document.getElementById('btn-backup-create')?.addEventListener('click', () => Api.downloadBackup());
    document.getElementById('btn-backup-restore')?.addEventListener('click', () => {
        document.getElementById('backup-restore-file')?.click();
    });
    document.getElementById('backup-restore-file')?.addEventListener('change', (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;
        openConfirmDialog(t('set.backup_confirm'), async () => {
            try {
                await Api.restoreBackup(file);
                showToast(t('set.backup_restored'), 'info');
                setTimeout(() => location.reload(), 800);
            } catch (err) {
                const msg = String(err.message) === 'invalid_backup'
                    ? t('set.backup_invalid') : String(err.message);
                showToast(msg, 'error');
            }
        });
    });

    // ----- Schnittplan-Zoom -----
    document.addEventListener('click', (e) => {
        const zb = e.target.closest('.btn-zoom');
        if (zb) { e.preventDefault(); openPlanZoom(parseInt(zb.dataset.planIndex)); }
    });
    document.getElementById('zoom-close')?.addEventListener('click', () => closePlanZoom());
    document.getElementById('zoom-overlay')?.addEventListener('click', (e) => {
        if (e.target.id === 'zoom-overlay') closePlanZoom();
    });

    // ----- Etiketten -----
    document.getElementById('btn-labels')?.addEventListener('click', () => printPartLabels());
    document.getElementById('btn-stock-labels')?.addEventListener('click', () => printStockLabels());

    // ----- Werkstatt-Modus -----
    document.getElementById('btn-saw-mode')?.addEventListener('click', () => openSawMode());
    document.getElementById('saw-close')?.addEventListener('click', () => closeSawMode());
    document.getElementById('saw-prev')?.addEventListener('click', () => { sawPlanIdx--; renderSawMode(); });
    document.getElementById('saw-next')?.addEventListener('click', () => { sawPlanIdx++; renderSawMode(); });
    document.addEventListener('keydown', (e) => {
        if (!sawModeActive()) return;
        if (e.key === 'ArrowLeft' && sawPlanIdx > 0) { sawPlanIdx--; renderSawMode(); }
        else if (e.key === 'ArrowRight') { sawPlanIdx++; renderSawMode(); }
    });

    // ----- Update-Prüfung -----
    document.getElementById('btn-check-update')?.addEventListener('click', () => checkForUpdate());

    // ----- Externe Links im System-Browser öffnen (statt im App-Fenster) -----
    document.addEventListener('click', (e) => {
        const a = e.target.closest('a[target="_blank"]');
        if (a && a.href) { e.preventDefault(); openExternal(a.href); }
    });

    // ----- Modal overlay click to close -----
    document.getElementById('modal-overlay')?.addEventListener('click', (e) => {
        if (e.target.id === 'modal-overlay') closeModal();
    });

    // ----- Modal cancel button -----
    document.getElementById('modal-cancel')?.addEventListener('click', () => closeModal());

    // ----- Escape key closes modal / zoom / saw mode -----
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (document.getElementById('zoom-overlay')?.classList.contains('active')) {
                closePlanZoom();
                return;
            }
            if (sawModeActive()) {
                closeSawMode();
                return;
            }
            const overlay = document.getElementById('modal-overlay');
            if (overlay?.classList.contains('active')) closeModal();
        }
    });

    // ----- Window resize: redraw canvases -----
    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (State.optimizationResult) renderOptResults();
            if (sawModeActive()) renderSawMode();
        }, 250);
    });

    // ----- Hotkeys -----
    document.addEventListener('keydown', (e) => {
        const overlay = document.getElementById('modal-overlay');
        const modalOpen = overlay?.classList.contains('active');

        // Enter in modal = save
        if (modalOpen && e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
            const active = document.activeElement;
            if (active?.tagName === 'TEXTAREA') return;
            e.preventDefault();
            document.getElementById('modal-save')?.click();
            return;
        }

        if (modalOpen) return;
        if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;

        const tab = document.querySelector('.tab-btn.active')?.dataset.tab;

        // Tab switching: 1-4
        if (e.key >= '1' && e.key <= '4' && !e.ctrlKey && !e.metaKey && !e.altKey) {
            const tabs = ['material', 'projects', 'optimization', 'settings'];
            const target = tabs[parseInt(e.key) - 1];
            const btn = document.querySelector(`.tab-btn[data-tab="${target}"]`);
            if (btn) { e.preventDefault(); btn.click(); }
            return;
        }

        if (e.ctrlKey || e.metaKey || e.altKey) return;

        // Neu
        if (hotkeyMatches('new', e)) {
            e.preventDefault();
            if (tab === 'material') document.getElementById('btn-mat-new')?.click();
            else if (tab === 'projects') {
                if (State.selectedProjectId) document.getElementById('btn-part-new')?.click();
                else document.getElementById('btn-proj-new')?.click();
            }
            else if (tab === 'settings') document.getElementById('btn-blade-new')?.click();
            return;
        }

        // Bearbeiten
        if (hotkeyMatches('edit', e)) {
            e.preventDefault();
            if (tab === 'material') {
                if (State.selectedStockId) document.getElementById('btn-stock-edit')?.click();
                else document.getElementById('btn-mat-edit')?.click();
            }
            else if (tab === 'projects') {
                if (State.selectedPartId) document.getElementById('btn-part-edit')?.click();
                else document.getElementById('btn-proj-edit')?.click();
            }
            else if (tab === 'settings') document.getElementById('btn-blade-edit')?.click();
            return;
        }

        // Löschen
        if (hotkeyMatches('delete', e)) {
            e.preventDefault();
            if (tab === 'material') {
                if (State.selectedStockId) document.getElementById('btn-stock-del')?.click();
                else document.getElementById('btn-mat-del')?.click();
            }
            else if (tab === 'projects') {
                if (State.selectedPartId) document.getElementById('btn-part-del')?.click();
                else document.getElementById('btn-proj-del')?.click();
            }
            else if (tab === 'settings') document.getElementById('btn-blade-del')?.click();
            return;
        }

        // Neuer Lagerbestand (Material-Tab)
        if (hotkeyMatches('stock', e) && tab === 'material') {
            e.preventDefault();
            document.getElementById('btn-stock-new')?.click();
            return;
        }

        // Optimierung starten
        if (hotkeyMatches('optimize', e) && tab === 'optimization') {
            e.preventDefault();
            document.getElementById('btn-optimize')?.click();
            return;
        }
    });

    initHotkeyRebinding();
}

// ===========================================================================
// 9b. HOTKEY-KONFIGURATION
// ===========================================================================

function hotkeyDisplay(key) {
    const k = key.toLowerCase();
    if (k === 'delete') return t('hotkey.del_key');
    if (k === ' ' || k === 'space') return 'Space';
    return key.length === 1 ? key.toUpperCase() : key;
}

function renderHotkeyTable() {
    document.querySelectorAll('.hotkey-edit[data-action]').forEach(el => {
        if (el.classList.contains('capturing')) return;
        el.textContent = hotkeyDisplay(hotkey(el.dataset.action));
    });
}

function initHotkeyRebinding() {
    document.querySelectorAll('.hotkey-edit[data-action]').forEach(el => {
        el.addEventListener('click', () => startHotkeyCapture(el));
    });
    renderHotkeyTable();
}

function startHotkeyCapture(el) {
    if (el.classList.contains('capturing')) return;
    const action = el.dataset.action;
    el.classList.add('capturing');
    el.textContent = t('hotkey.press');

    const finish = () => {
        el.classList.remove('capturing');
        renderHotkeyTable();
        document.removeEventListener('keydown', onKey, true);
    };

    const onKey = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) return;
        if (e.key === 'Escape') { finish(); return; }

        const newKey = e.key;
        const lower = newKey.toLowerCase();

        // Konflikt mit festen Tasten oder anderen Aktionen?
        const conflict = RESERVED_KEYS.includes(lower) ||
            Object.keys(DEFAULT_HOTKEYS).some(a =>
                a !== action && hotkey(a).toLowerCase() === lower);
        if (conflict) {
            showToast(t('hotkey.conflict', { key: hotkeyDisplay(newKey) }), 'error');
            finish();
            return;
        }

        State.settings.hotkeys = { ...(State.settings.hotkeys || {}), [action]: newKey };
        finish();
        try {
            await Api.updateSettings({ hotkeys: State.settings.hotkeys });
        } catch { /* handled */ }
    };

    document.addEventListener('keydown', onKey, true);
}

// ===========================================================================
// 10. THEME MANAGEMENT
// ===========================================================================

function applyTheme(theme) {
    if (theme === 'system' || theme === 'auto') {
        document.documentElement.removeAttribute('data-theme');
    } else {
        document.documentElement.setAttribute('data-theme', theme);
    }

    // Horizon-Theme-Stylesheet (hell/dunkel) umschalten
    const dark = theme === 'dark' ||
        ((theme === 'system' || theme === 'auto') &&
            window.matchMedia('(prefers-color-scheme: dark)').matches);
    const lightSheet = document.getElementById('theme-light');
    const darkSheet = document.getElementById('theme-dark');
    if (lightSheet && darkSheet) {
        lightSheet.disabled = dark;
        darkSheet.disabled = !dark;
    }

    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) themeBtn.textContent = THEME_ICONS[theme] || THEME_ICONS.system;
}

// Bei System-Theme auf Betriebssystem-Wechsel reagieren
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (State.settings.theme === 'system' || State.settings.theme === 'auto') {
        applyTheme(State.settings.theme);
        if (State.optimizationResult) renderOptResults();
    }
});

// ===========================================================================
// 11. UTILITY
// ===========================================================================

function escHtml(str) {
    if (str == null) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escAttr(str) {
    if (str == null) return '';
    return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

// ===========================================================================
// 12. INITIALIZATION
// ===========================================================================

async function init() {
    try {
        const settings = await Api.getSettings();
        Object.assign(State.settings, settings);
        applyTheme(State.settings.theme);

        State.translations = await Api.getTranslations(State.settings.language);
        applyTranslations();

        State.materials = await Api.getMaterials();
        State.blades = await Api.getBlades();
        State.projects = await Api.getProjects();

        initEvents();
        renderMaterials();
        renderSettings();
        renderBlades();
        renderProjects();
        renderOptDropdowns();
    } catch (e) {
        console.error('Init failed:', e);
        showToast('Initialization failed. Is the server running?', 'error');
    }
}

document.addEventListener('DOMContentLoaded', init);
