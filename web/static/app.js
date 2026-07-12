'use strict';

// ===========================================================================
// 1. STATE
// ===========================================================================

const State = {
    settings: { language: 'de', unit: 'mm', theme: 'system' },
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
    return text;
};

const applyTranslations = () => {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        el.textContent = t(key);
    });
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

    getSettings: () => fetchJSON('/api/settings'),
    updateSettings: (data) => fetchJSON('/api/settings', 'PUT', data),
    getTranslations: (lang) => fetchJSON(`/api/i18n/${lang}`),
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
            position: 'fixed', bottom: '20px', right: '20px',
            zIndex: '2000', display: 'flex', flexDirection: 'column', gap: '8px',
        });
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.textContent = message;
    Object.assign(toast.style, {
        padding: '10px 18px',
        borderRadius: '6px',
        fontSize: '13px',
        color: '#fff',
        background: type === 'error' ? 'var(--danger, #dc2626)' : 'var(--accent, #2563eb)',
        boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
        opacity: '0',
        transition: 'opacity 0.3s ease',
        maxWidth: '360px',
        wordWrap: 'break-word',
    });
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
        return `<tr class="${selected}" data-id="${m.id}">
            <td>${escHtml(m.name)}</td>
            <td>${typLabel}</td>
            <td class="num">${dims}</td>
            <td>${grain}</td>
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
        return `<tr class="${selected}" data-id="${s.id}">
            <td class="num">${formatDim(s.laenge)}</td>
            <td class="num" style="${isPlatte ? '' : 'display:none'}">${formatDim(s.breite)}</td>
            <td class="num">${s.stueckzahl}</td>
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
        return `<tr class="${selected}" data-id="${p.id}"><td>${escHtml(p.name)}</td></tr>`;
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
        tbody.innerHTML = `<tr><td colspan="7" class="empty-state">${t('dlg.select_project')}</td></tr>`;
        State.parts = [];
        State.selectedPartId = null;
        return;
    }

    try {
        State.parts = await Api.getParts(State.selectedProjectId);
    } catch { return; }

    if (State.parts.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty-state">${t('parts.empty')}</td></tr>`;
        State.selectedPartId = null;
        return;
    }

    tbody.innerHTML = State.parts.map(p => {
        const selected = p.id === State.selectedPartId ? ' selected' : '';
        const mat = State.materials.find(m => m.id === p.material_id);
        const matName = mat ? mat.name : `#${p.material_id}`;
        const isPlatte = p.typ === 'Platte';
        const pct = p.stueckzahl > 0 ? Math.round((p.gesaegt_anzahl / p.stueckzahl) * 100) : 0;
        const statusText = `${p.gesaegt_anzahl}/${p.stueckzahl}`;
        const statusClass = p.gesaegt_anzahl >= p.stueckzahl ? 'status-cut' : 'status-open';
        return `<tr class="${selected}" data-id="${p.id}">
            <td>${escHtml(p.label)}</td>
            <td>${t(TYP_KEY[p.typ] || p.typ)}</td>
            <td>${escHtml(matName)}</td>
            <td class="num">${formatDim(p.laenge)}</td>
            <td class="num">${isPlatte ? formatDim(p.breite) : ''}</td>
            <td class="num">${p.stueckzahl}</td>
            <td>
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

    if (projSel) {
        projSel.innerHTML = State.projects.map(p =>
            `<option value="${p.id}">${escHtml(p.name)}</option>`
        ).join('');
    }

    updateOptMaterialDropdown();

    if (bladeSel) {
        bladeSel.innerHTML = State.blades.map(b =>
            `<option value="${b.id}">${escHtml(b.name)} (${formatDim(b.schnittbreite)})</option>`
        ).join('');
    }

    if (algoSel) {
        algoSel.innerHTML = [
            { value: 'greedy', key: 'opt.algo_greedy' },
            { value: 'nested', key: 'opt.algo_nested' },
            { value: 'ga', key: 'opt.algo_ga' },
        ].map(a => `<option value="${a.value}">${t(a.key)}</option>`).join('');
    }
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

    if (statsEl) {
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
            <div class="stat-card">
                <div class="stat-icon">&#9888;</div>
                <div><div class="stat-value">${missing.length}</div>
                <div class="stat-label">${t('stat.parts_missing')}</div></div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">&#9851;</div>
                <div><div class="stat-value">${waste.toFixed(1)}%</div>
                <div class="stat-label">${t('stat.total_waste')}</div></div>
            </div>
        `;
        statsEl.className = 'opt-stats';
    }

    if (plansEl) {
        const matId = parseInt(document.getElementById('opt-material')?.value);
        const mat = State.materials.find(m => m.id === matId);
        const is1D = mat?.typ === 'Stange';

        plansEl.innerHTML = plans.map((plan, i) => {
            const canvasHeight = is1D ? 100 : 400;
            return `<div class="cut-plan-card">
                <div class="plan-header">
                    <strong>${t('opt.preview')} ${i + 1}</strong>
                    <span>${formatDim(plan.lager_laenge)}${plan.lager_breite ? ' x ' + formatDim(plan.lager_breite) : ''}</span>
                    <span>${plan.platzierungen.length} ${t('proj.parts')}</span>
                    <span class="waste">${t('stat.total_waste')}: ${plan.verschnitt_prozent.toFixed(1)}%</span>
                </div>
                <canvas class="cut-plan-canvas" data-plan-index="${i}"
                    style="width:100%;height:${canvasHeight}px"></canvas>
            </div>`;
        }).join('');
        plansEl.className = 'cut-plans';

        requestAnimationFrame(() => {
            plansEl.querySelectorAll('canvas').forEach(canvas => {
                const idx = parseInt(canvas.dataset.planIndex);
                drawCutPlan(canvas, plans[idx], mat);
            });
        });
    }

    if (actionsEl) actionsEl.style.display = '';

    if (missing.length > 0) {
        showToast(`${t('opt.missing')}: ${missing.join(', ')}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Settings Tab
// ---------------------------------------------------------------------------

function renderSettings() {
    const langSel = document.getElementById('settings-lang');
    const unitSel = document.getElementById('settings-unit');
    const themeSel = document.getElementById('settings-theme');

    if (langSel) langSel.value = State.settings.language;
    if (unitSel) unitSel.value = State.settings.unit;
    if (themeSel) themeSel.value = State.settings.theme;
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
        return `<tr class="${selected}" data-id="${b.id}">
            <td>${escHtml(b.name)}</td>
            <td class="num">${formatDim(b.schnittbreite)}</td>
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

    // Build label-to-color map
    const labels = [...new Set(plan.platzierungen.map(p => p.teil_label))];
    const colorMap = {};
    labels.forEach((label, i) => {
        colorMap[label] = PART_COLORS[i % PART_COLORS.length];
    });

    if (is1D) {
        draw1D(ctx, canvasW, canvasH, plan, colorMap);
    } else {
        draw2D(ctx, canvasW, canvasH, plan, colorMap);
    }
}

function draw2D(ctx, canvasW, canvasH, plan, colorMap) {
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
        .getPropertyValue('--bg-tertiary').trim() || '#e9ecef';
    ctx.fillRect(offsetX, offsetY, stockW, stockH);
    ctx.strokeStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--border-color').trim() || '#d1d5db';
    ctx.lineWidth = 1;
    ctx.strokeRect(offsetX, offsetY, stockW, stockH);

    // Parts
    plan.platzierungen.forEach(p => {
        const pw = (p.gedreht ? p.breite : p.laenge) * scale;
        const ph = (p.gedreht ? p.laenge : p.breite) * scale;
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
    });

    // Dimension annotations
    ctx.fillStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--text-secondary').trim() || '#6b7280';
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

function draw1D(ctx, canvasW, canvasH, plan, colorMap) {
    const padding = { left: 20, right: 20, top: 15, bottom: 30 };
    const barH = 50;
    const barY = padding.top;
    const drawW = canvasW - padding.left - padding.right;
    const scale = drawW / plan.lager_laenge;

    // Stock bar background
    ctx.fillStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--bg-tertiary').trim() || '#e9ecef';
    ctx.fillRect(padding.left, barY, drawW, barH);
    ctx.strokeStyle = getComputedStyle(document.documentElement)
        .getPropertyValue('--border-color').trim() || '#d1d5db';
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
    });

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
        .getPropertyValue('--text-secondary').trim() || '#6b7280';
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
            const el = body.querySelector(`[name="${f.key}"]`);
            if (!el) return;
            let val;
            if (f.type === 'number') {
                val = el.value === '' ? null : parseFloat(el.value);
                if (f.required && (val === null || isNaN(val))) {
                    el.style.borderColor = 'var(--danger)';
                    valid = false;
                    return;
                }
                if (f.isDimension) {
                    val = val !== null ? toMm(val) : 0;
                }
                if (val !== null && f.min != null && val < f.min) {
                    el.style.borderColor = 'var(--danger)';
                    valid = false;
                    return;
                }
            } else if (f.type === 'select') {
                val = el.value;
            } else {
                val = el.value.trim();
                if (f.required && !val) {
                    el.style.borderColor = 'var(--danger)';
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
        input = `<select name="${f.key}">${opts}</select>`;
    } else if (f.type === 'number') {
        const step = f.step ?? (f.isDimension ? 'any' : 1);
        const min = f.min != null ? ` min="${f.min}"` : '';
        const ph = f.placeholder ?? '';
        input = `<input type="number" name="${f.key}" value="${displayVal}" step="${step}"${min}${req} placeholder="${ph}">`;
    } else {
        const ph = f.placeholder ?? '';
        input = `<input type="text" name="${f.key}" value="${escAttr(displayVal)}"${req} placeholder="${ph}">`;
    }

    return `<label>${escHtml(label)}${unitSuffix}</label>${input}`;
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

function openPartDialog(part = null) {
    const isEdit = !!part;
    if (!State.selectedProjectId) {
        showToast(t('dlg.select_project'), 'error');
        return;
    }

    const title = isEdit ? t('part.edit') : t('part.new');
    const data = part ? { ...part } : { typ: 'Platte', stueckzahl: 1, gesaegt_anzahl: 0, maserung: 'egal' };

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

    openModal(title, fields, data, async (formData) => {
        if (formData.typ === 'Stange') {
            formData.breite = 0;
        }
        formData.gesaegt_anzahl = data.gesaegt_anzahl || 0;
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

function initEvents() {
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
        const projId = parseInt(document.getElementById('opt-project')?.value);
        const matId = parseInt(document.getElementById('opt-material')?.value);

        openConfirmDialog(t('opt.confirm_msg'), async () => {
            try {
                await Api.confirmOptimization({
                    project_id: projId,
                    material_id: matId,
                    schnittplaene: State.optimizationResult.schnittplaene,
                });
                showToast(t('opt.done'), 'info');
                State.optimizationResult = null;
                renderOptResults();
                // Refresh data since stock & parts changed
                State.projects = await Api.getProjects();
                State.materials = await Api.getMaterials();
            } catch { /* handled */ }
        });
    });

    document.getElementById('btn-pdf')?.addEventListener('click', () => {
        if (!State.optimizationResult) return;
        const projSel = document.getElementById('opt-project');
        const matSel = document.getElementById('opt-material');
        const bladeSel = document.getElementById('opt-blade');
        const matId = parseInt(matSel?.value);
        const mat = State.materials.find(m => m.id === matId);

        Api.downloadPdf({
            ergebnis: State.optimizationResult,
            projekt_name: projSel?.selectedOptions[0]?.text || '',
            material_name: matSel?.selectedOptions[0]?.text || '',
            saegeblatt_name: bladeSel?.selectedOptions[0]?.text || '',
            is_1d: mat?.typ === 'Stange',
        });
    });

    // ----- Optimization project dropdown changes material filter -----
    document.getElementById('opt-project')?.addEventListener('change', () => {
        updateOptMaterialDropdown();
    });

    // ----- Settings -----
    document.getElementById('settings-lang')?.addEventListener('change', async (e) => {
        State.settings.language = e.target.value;
        try {
            await Api.updateSettings({ language: e.target.value });
            State.translations = await Api.getTranslations(e.target.value);
            applyTranslations();
            // Re-render active tab to apply translations in dynamic content
            renderOptDropdowns();
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

    // ----- Modal overlay click to close -----
    document.getElementById('modal-overlay')?.addEventListener('click', (e) => {
        if (e.target.id === 'modal-overlay') closeModal();
    });

    // ----- Modal cancel button -----
    document.getElementById('modal-cancel')?.addEventListener('click', () => closeModal());

    // ----- Escape key closes modal -----
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
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
        }, 250);
    });
}

// ===========================================================================
// 10. THEME MANAGEMENT
// ===========================================================================

function applyTheme(theme) {
    if (theme === 'system') {
        document.documentElement.removeAttribute('data-theme');
    } else {
        document.documentElement.setAttribute('data-theme', theme);
    }
    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) themeBtn.textContent = THEME_ICONS[theme] || THEME_ICONS.system;
}

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
