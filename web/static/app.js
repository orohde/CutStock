'use strict';

// ===========================================================================
// 1. STATE
// ===========================================================================

const State = {
    settings: { language: 'de', unit: 'mm', theme: 'system', hotkeys: {},
                 api_enabled: false, api_port: 8421, api_key: '' },
    translations: {},
    materials: [],
    stock: [],
    optMode: 'project',   // Optimieren nach 'project' oder 'material' (Sammelplan)
    sammel: null,         // Sammelplan-Infos des gewählten Materials (Material-Modus)
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
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        el.title = t(el.getAttribute('data-i18n-title'));
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

// UI-Cookie veraltet (API-Key anderswo geändert)? Einmal neu laden, damit der
// Server ein frisches Cookie setzt – nicht in einer Schleife.
function reloadForFreshUiCookie() {
    if (storageGet('sessionStorage', 'cutstock_401_reload')) return false;
    if (!storageSet('sessionStorage', 'cutstock_401_reload', '1')) return false;
    location.reload();
    return true;
}

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
    if (resp.status === 401 && reloadForFreshUiCookie()) {
        throw new Error('HTTP 401');
    }
    storageRemove('sessionStorage', 'cutstock_401_reload');
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
    uploadMaterialImage: (id, file) => {
        const fd = new FormData();
        fd.append('file', file);
        return fetch(API_BASE + `/api/materials/${id}/image`, { method: 'POST', body: fd })
            .then(r => { if (!r.ok) throw new Error(r.status); });
    },
    deleteMaterialImage: (id) => fetch(API_BASE + `/api/materials/${id}/image`, { method: 'DELETE' })
        .then(r => { if (!r.ok) throw new Error(r.status); }),
    materialImageUrl: (id) => API_BASE + `/api/materials/${id}/image`,

    getStock: (materialId) => fetchJSON(`/api/stock?material_id=${materialId}`),
    createStock: (data) => fetchJSON('/api/stock', 'POST', data),
    updateStock: (id, data) => fetchJSON(`/api/stock/${id}`, 'PUT', data),
    deleteStock: (id) => fetchJSON(`/api/stock/${id}`, 'DELETE'),

    getPieces: (stockId) => fetchJSON(`/api/stock/${stockId}/pieces`),
    updatePiece: (id, data) => fetchJSON(`/api/pieces/${id}`, 'PUT', data),

    getDefects: (stockId) => fetchJSON(`/api/stock/${stockId}/defects`),
    getDefectsForPiece: (pieceId) => fetchJSON(`/api/pieces/${pieceId}/defects`),
    createDefect: (pieceId, data) => fetchJSON(`/api/pieces/${pieceId}/defects`, 'POST', data),
    updateDefect: (id, data) => fetchJSON(`/api/defects/${id}`, 'PUT', data),
    deleteDefect: (id) => fetchJSON(`/api/defects/${id}`, 'DELETE'),

    getBlades: () => fetchJSON('/api/blades'),
    createBlade: (data) => fetchJSON('/api/blades', 'POST', data),
    updateBlade: (id, data) => fetchJSON(`/api/blades/${id}`, 'PUT', data),
    deleteBlade: (id) => fetchJSON(`/api/blades/${id}`, 'DELETE'),

    getProjects: () => fetchJSON('/api/projects'),
    getProject: (id) => fetchJSON(`/api/projects/${id}`),
    createProject: (data) => fetchJSON('/api/projects', 'POST', data),
    updateProject: (id, data) => fetchJSON(`/api/projects/${id}`, 'PUT', data),
    cloneProject: (id) => fetchJSON(`/api/projects/${id}/clone`, 'POST'),
    copyPartsToProject: (targetId, partIds) => fetchJSON(`/api/projects/${targetId}/copy-parts`, 'POST', { part_ids: partIds }),
    deleteProject: (id) => fetchJSON(`/api/projects/${id}`, 'DELETE'),

    getParts: (projectId) => fetchJSON(`/api/projects/${projectId}/parts`),
    createPart: (projectId, data) => fetchJSON(`/api/projects/${projectId}/parts`, 'POST', data),
    updatePart: (id, data) => fetchJSON(`/api/parts/${id}`, 'PUT', data),
    deletePart: (id) => fetchJSON(`/api/parts/${id}`, 'DELETE'),

    optimize: (data) => fetchJSON('/api/optimize', 'POST', data),
    // Gespeicherter Plan; null wenn es (noch) keinen gibt
    getSavedPlan: (projectId, materialId) =>
        fetchJSON(`/api/projects/${projectId}/plans/${materialId}`),
    setPieceSawn: (pieceId, gesaegt) => fetchJSON(`/api/plan-pieces/${pieceId}`, 'POST', { gesaegt }),
    confirmAllPieces: (planId) => fetchJSON(`/api/plans/${planId}/confirm-all`, 'POST'),
    restartProject: (projectId) => fetchJSON(`/api/projects/${projectId}/restart`, 'POST'),
    discardPlan: (planId) => fetchJSON(`/api/plans/${planId}`, 'DELETE'),
    getSammel: (materialId) => fetchJSON(`/api/sammel/${materialId}`),
    optimizeSammel: (data) => fetchJSON('/api/sammel/optimize', 'POST', data),
    compareSammel: (data) => fetchJSON('/api/sammel/compare', 'POST', data),
    getFillCandidates: (projectId, materialId) =>
        fetchJSON(`/api/projects/${projectId}/fill-candidates/${materialId}`),
    getAllParts: () => fetchJSON('/api/parts'),
    createCutList: (data) => fetchJSON('/api/cut-lists', 'POST', data),
    takePartStock: (projectId, materialId) =>
        fetchJSON(`/api/projects/${projectId}/take-stock/${materialId}`, 'POST'),

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
    getLicense: () => fetchJSON('/api/license'),

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
        tbody.innerHTML = `<tr><td colspan="5" class="empty-state">${t('mat.empty')}</td></tr>`;
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
        const imgCell = m.hat_bild
            ? `<div class="mat-thumb-wrap"><img class="mat-thumb" src="${Api.materialImageUrl(m.id)}" loading="lazy" alt=""></div>`
            : '';
        return `<tr class="fd-table__row ${selected}" data-id="${m.id}">
            <td class="fd-table__cell mat-img-col">${imgCell}</td>
            <td class="fd-table__cell">${escHtml(m.name)}${m.kuerzel ? ` <span class="mat-code">${escHtml(m.kuerzel)}</span>` : ''}</td>
            <td class="fd-table__cell">${typLabel}</td>
            <td class="fd-table__cell num">${dims}</td>
            <td class="fd-table__cell">${grain}</td>
        </tr>`;
    }).join('');
    setupImageHoverPreview(tbody);

    tbody.querySelectorAll('tr[data-id]').forEach(row => {
        row.addEventListener('click', () => selectMaterialRow(parseInt(row.dataset.id)));
        row.addEventListener('dblclick', () => {
            selectMaterialRow(parseInt(row.dataset.id));
            openMaterialDialog(getSelectedMaterial());
        });
    });

    renderStock();
}

// Schwebende Vollbild-Vorschau für Material-Miniaturen, im Fenster gehalten
function setupImageHoverPreview(container) {
    let box = document.getElementById('img-hover-preview');
    if (!box) {
        box = document.createElement('div');
        box.id = 'img-hover-preview';
        box.className = 'img-hover-preview';
        box.innerHTML = '<img alt="">';
        document.body.appendChild(box);
    }
    const img = box.querySelector('img');
    const place = (thumb) => {
        const r = thumb.getBoundingClientRect();
        const w = box.offsetWidth, h = box.offsetHeight, m = 8;
        // bevorzugt rechts neben der Miniatur, sonst links; vertikal mittig, geklemmt
        let x = r.right + m;
        if (x + w > window.innerWidth - m) x = Math.max(m, r.left - m - w);
        let y = r.top + r.height / 2 - h / 2;
        y = Math.max(m, Math.min(y, window.innerHeight - h - m));
        box.style.left = `${x}px`;
        box.style.top = `${y}px`;
    };
    container.querySelectorAll('img.mat-thumb').forEach(thumb => {
        thumb.addEventListener('mouseenter', () => {
            img.onload = () => place(thumb);
            img.src = thumb.src;
            box.classList.add('active');
            place(thumb);
        });
        thumb.addEventListener('mouseleave', () => box.classList.remove('active'));
    });
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

    const piecesMap = {};
    const defectCounts = {};
    await Promise.all(State.stock.map(async s => {
        try {
            const pieces = await Api.getPieces(s.id);
            piecesMap[s.id] = pieces;
            defectCounts[s.id] = pieces.reduce((sum, p) => sum + (p.defekt_count || 0), 0);
        } catch {
            piecesMap[s.id] = [];
            defectCounts[s.id] = 0;
        }
    }));

    tbody.innerHTML = State.stock.map(s => {
        const selected = s.id === State.selectedStockId ? ' selected' : '';
        const badge = defectCounts[s.id] > 0
            ? ` <span class="defect-badge" title="${t('defect.title')}">${defectCounts[s.id]}</span>`
            : '';
        const expandable = s.stueckzahl > 1;
        return `<tr class="fd-table__row ${selected}" data-id="${s.id}">
            <td class="fd-table__cell num">${s.ist_rest ? `<span class="rest-badge" title="${escAttr(t('stock.is_rest'))}">${escHtml(t('labels.rest'))}</span> ` : ''}${formatDim(s.laenge)}${badge}</td>
            <td class="fd-table__cell num" style="${isPlatte ? '' : 'display:none'}">${formatDim(s.breite)}</td>
            <td class="fd-table__cell num${expandable ? ' expand-toggle' : ''}" data-stock-id="${s.id}">${expandable ? '<span class="expand-arrow">&#9654;</span> ' : ''}${s.stueckzahl}</td>
        </tr>`;
    }).join('');

    tbody.querySelectorAll('td.expand-toggle').forEach(cell => {
        cell.addEventListener('click', (e) => {
            e.stopPropagation();
            const stockId = parseInt(cell.dataset.stockId);
            const parentRow = cell.closest('tr');
            const arrow = cell.querySelector('.expand-arrow');
            const existing = tbody.querySelectorAll(`tr.piece-row[data-parent="${stockId}"]`);
            if (existing.length > 0) {
                existing.forEach(r => r.remove());
                if (arrow) arrow.innerHTML = '&#9654;';
                cell.classList.remove('expanded');
                return;
            }
            if (arrow) arrow.innerHTML = '&#9660;';
            cell.classList.add('expanded');
            const pieces = piecesMap[stockId] || [];
            const pieceRows = pieces.map(p => {
                const pBadge = p.defekt_count > 0
                    ? ` <span class="defect-badge">${p.defekt_count}</span>` : '';
                const note = p.notiz ? ` <span class="piece-note">${escHtml(p.notiz)}</span>` : '';
                const ort = p.lagerort_effektiv
                    ? ` <span class="piece-location">&#128205; ${escHtml(p.lagerort_effektiv)}</span>` : '';
                const res = p.reserviert_fuer
                    ? ` <span class="piece-reserved" title="${escAttr(t('piece.reserved_hint'))}">&#128274; ${escHtml(p.reserviert_fuer)}</span>` : '';
                return `<tr class="fd-table__row piece-row" data-parent="${stockId}" data-piece-id="${p.id}"
                        title="${escAttr(t('piece.edit_hint'))}">
                    <td class="fd-table__cell piece-cell" colspan="${isPlatte ? 3 : 2}">
                        <span class="piece-code">${escHtml(p.code || '#' + p.nr)}</span>${ort}${res}${note}${pBadge}
                    </td>
                </tr>`;
            }).join('');
            parentRow.insertAdjacentHTML('afterend', pieceRows);
            tbody.querySelectorAll(`tr.piece-row[data-parent="${stockId}"]`).forEach(r => {
                r.addEventListener('dblclick', (ev) => {
                    ev.stopPropagation();
                    const piece = pieces.find(x => x.id === parseInt(r.dataset.pieceId));
                    if (piece) openPieceDialog(piece);
                });
            });
        });
    });

    tbody.querySelectorAll('tr[data-id]').forEach(row => {
        row.addEventListener('click', () => selectStockRow(parseInt(row.dataset.id)));
        row.addEventListener('dblclick', () => {
            selectStockRow(parseInt(row.dataset.id));
            openStockDialog(State.stock.find(s => s.id === State.selectedStockId));
        });
    });
}

// Einzelstück bearbeiten: Notiz und eigener Lagerort (leer = Lagerort des Materials)
function openPieceDialog(piece) {
    const mat = getSelectedMaterial();
    const fields = [
        { key: 'notiz', label: t('piece.note'), type: 'text' },
        { key: 'lagerort', label: t('piece.location'), type: 'text',
          placeholder: mat?.lagerort || t('mat.location_hint') },
    ];
    openModal(`${t('piece.edit')} ${piece.code || '#' + piece.nr}`, fields, piece, async (formData) => {
        try {
            await Api.updatePiece(piece.id, { notiz: formData.notiz || '', lagerort: formData.lagerort || '' });
            await renderStock();
        } catch { /* handled */ }
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
        const copies = p.anzahl > 1 ? ` <span class="proj-copies">×${p.anzahl}</span>` : '';
        return `<tr class="fd-table__row ${selected}" data-id="${p.id}"><td class="fd-table__cell">${escHtml(p.name)}${copies}${planBadge(p)}${sammelBadge(p)}${cutListBadge(p)}</td></tr>`;
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

// Fortschritt der gespeicherten Pläne eines Projekts als kleines Badge
function planBadge(project) {
    const plaene = project.plaene || [];
    if (!plaene.length) return '';
    const total = plaene.reduce((s, p) => s + p.gesamt, 0);
    const done = plaene.reduce((s, p) => s + p.gesaegt, 0);
    const cls = total > 0 && done >= total ? 'plan-badge plan-badge--done' : 'plan-badge';
    return ` <span class="${cls}" title="${escAttr(t('plan.badge_title'))}">${done}/${total}</span>`;
}

// Hinweis, dass Material dieses Projekts in einem Sammelplan gesägt wird
function sammelBadge(project) {
    const names = Object.values(project.sammel || {});
    if (!names.length) return '';
    return ` <span class="plan-badge sammel-badge" title="${escAttr(names.join(', '))}">&#128279; ${escHtml(t('sammel.badge'))}</span>`;
}

// Schnittliste: gesägte Teile gehen ins Regal ihres Herkunftsprojekts
function cutListBadge(project) {
    if (project.art !== 'liste') return '';
    return ` <span class="plan-badge sammel-badge" title="${escAttr(t('parts.list_hint'))}">&#128203; ${escHtml(t('parts.list_badge'))}</span>`;
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
        // Fortschritt über alle Exemplare des Projekts (gesamt = Stück × Anzahl)
        const gesamt = p.gesamt_anzahl || p.stueckzahl;
        const pct = gesamt > 0 ? Math.round((p.gesaegt_anzahl / gesamt) * 100) : 0;
        const statusText = `${p.gesaegt_anzahl}/${gesamt}`;
        const statusClass = p.gesaegt_anzahl >= gesamt ? 'status-cut' : 'status-open';
        const qtyText = gesamt !== p.stueckzahl ? `${p.stueckzahl} <small>(${gesamt})</small>` : p.stueckzahl;
        return `<tr class="fd-table__row ${selected}" data-id="${p.id}">
            <td class="fd-table__cell">${escHtml(p.label)}</td>
            <td class="fd-table__cell">${t(TYP_KEY[p.typ] || p.typ)}</td>
            <td class="fd-table__cell">${escHtml(matName)}</td>
            <td class="fd-table__cell">${grain}</td>
            <td class="fd-table__cell num">${formatDim(p.laenge)}</td>
            <td class="fd-table__cell num">${isPlatte ? formatDim(p.breite) : ''}</td>
            <td class="fd-table__cell num">${qtyText}</td>
            <td class="fd-table__cell">
                <div style="display:flex;align-items:center;gap:8px">
                    <div class="progress-bar" style="flex:1;min-width:60px">
                        <div class="progress-fill" style="width:${pct}%"></div>
                    </div>
                    <span class="status-badge ${statusClass}">${statusText}</span>
                    ${p.vorrat > 0 ? `<span class="stock-badge" title="${escAttr(t('fill.stock_hint'))}">&#128230; ${p.vorrat}</span>` : ''}
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

    applyOptMode();

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

    // Gespeicherten Plan zur (wiederhergestellten) Auswahl laden – auch, um
    // nach Änderungen an Teilen den Hinweis „veraltet“ aktuell zu halten.
    updateFillButton();
    loadSavedPlan();
}

// Plan des gewählten Projekts/Materials vom Server holen und anzeigen.
async function loadSavedPlan() {
    const matId = parseInt(document.getElementById('opt-material')?.value);
    const mode = State.optMode;
    if (mode === 'material' && matId) await loadSammel(matId);
    renderSammelPanel();
    const projId = optProjId();
    if (!projId || !matId) { clearOptResult(); return; }
    let plan = null;
    try { plan = await Api.getSavedPlan(projId, matId); } catch { /* offline o.ä. */ }
    // Auswahl hat sich während des Ladens geändert → Ergebnis verwerfen
    if (State.optMode !== mode || optProjId() !== projId ||
        parseInt(document.getElementById('opt-material')?.value) !== matId) return;
    if (!plan) { clearOptResult(); return; }
    adoptPlan(plan);
    const bladeSel = document.getElementById('opt-blade');
    if (plan.saegeblatt_id && bladeSel?.querySelector(`option[value="${plan.saegeblatt_id}"]`)) {
        bladeSel.value = String(plan.saegeblatt_id);
    }
    const algoSel = document.getElementById('opt-algorithm');
    if (plan.algorithmus && algoSel?.querySelector(`option[value="${plan.algorithmus}"]`)) {
        algoSel.value = plan.algorithmus;
    }
    renderOptResults({ quiet: true });
    if (sawModeActive()) renderSawMode();
}

// Server-Plan als angezeigtes Ergebnis übernehmen (_done = gesägt-Markierung).
function adoptPlan(plan) {
    plan._projId = String(plan.projekt_id);
    State.fillSel = {
        key: `${plan.projekt_id}:${plan.material_id}`,
        items: plan.fuellteile || [],
        alle: !!plan.fuell_alle_reste,
    };
    updateFillButton();
    (plan.schnittplaene || []).forEach(sp =>
        sp.platzierungen.forEach(p => { p._done = !!p.gesaegt; }));
    State.optimizationResult = plan;
}

// Gesägt-Zustand aus einer Server-Antwort in den angezeigten Plan übernehmen,
// ohne alles neu aufzubauen (Canvas-Klick-Handler bleiben bestehen).
function applyPlanState(plan) {
    const cur = State.optimizationResult;
    if (!cur || cur.plan_id !== plan.plan_id) { adoptPlan(plan); renderOptResults({ quiet: true }); return; }
    const byId = new Map();
    (plan.schnittplaene || []).forEach(sp => byId.set(sp.id, sp));
    (cur.schnittplaene || []).forEach(sp => {
        const neu = byId.get(sp.id);
        if (!neu) return;
        sp.lagerstueck_id = neu.lagerstueck_id;
        sp.verbraucht = neu.verbraucht;
        sp.stueck_code = neu.stueck_code;
        sp.lagerort = neu.lagerort;
        sp.reste_stuecke = neu.reste_stuecke;
        const st = new Map(neu.platzierungen.map(p => [p.id, p]));
        sp.platzierungen.forEach(p => {
            const n = st.get(p.id);
            if (n) { p.gesaegt = n.gesaegt; p._done = !!n.gesaegt; }
        });
    });
    cur.version = plan.version;
    cur.lager_fehlt = plan.lager_fehlt;
    cur.veraltet = plan.veraltet;
    renderPlanInfo();
    document.querySelectorAll('.plan-piece-info').forEach(el => {
        const sp = cur.schnittplaene?.[parseInt(el.dataset.planIndex)];
        if (sp) el.innerHTML = planPieceInfo(sp);
    });
}

// Angezeigten Schnittplan verwerfen (Auswahl passt nicht mehr dazu).
function clearOptResult() {
    if (!State.optimizationResult) return;
    State.optimizationResult = null;
    renderOptResults();
}

// ---------------------------------------------------------------------------
// Sammelplan: ein Material, mehrere Projekte gemeinsam optimieren
// ---------------------------------------------------------------------------

// Projekt, dem der angezeigte Plan gehört: im Material-Modus das Sammel-Projekt
function optProjId() {
    if (State.optMode === 'material') return State.sammel?.sammel_id || 0;
    return parseInt(document.getElementById('opt-project')?.value) || 0;
}

function optProjName() {
    if (State.optMode === 'material') return State.sammel?.name || '';
    return document.getElementById('opt-project')?.selectedOptions[0]?.text || '';
}

// Modus-Umschalter: Projekt-Auswahl bzw. Projektliste und passende Knöpfe zeigen
function applyOptMode() {
    const sammel = State.optMode === 'material';
    const modeSel = document.getElementById('opt-mode');
    if (modeSel) modeSel.value = State.optMode;
    document.getElementById('opt-project-group')?.classList.toggle('hidden', sammel);
    document.getElementById('btn-fill')?.classList.toggle('hidden', sammel);
    document.getElementById('btn-restart')?.classList.toggle('hidden', sammel);
}

async function loadSammel(matId) {
    let info = null;
    try { info = await Api.getSammel(matId); } catch { /* offline o.ä. */ }
    if (!info) { State.sammel = null; return; }
    const alt = State.sammel?.material_id === matId ? State.sammel : null;
    // Auswahl: bisherige Haken behalten, sonst Mitglieder bzw. alle mit offenen Teilen
    const mitglieder = info.kandidaten.filter(k => k.mitglied).map(k => k.projekt_id);
    const auswahl = alt?.auswahl
        || new Set(mitglieder.length ? mitglieder
            : info.kandidaten.filter(k => k.offen > 0).map(k => k.projekt_id));
    State.sammel = { ...info, material_id: matId, auswahl, vergleich: null };
}

function formatMenge(wert, is1D) {
    const loc = State.settings.language || undefined;
    return is1D
        ? `${(wert / 1000).toLocaleString(loc, { maximumFractionDigits: 2 })} m`
        : `${(wert / 1e6).toLocaleString(loc, { maximumFractionDigits: 2 })} m²`;
}

function renderSammelPanel() {
    const el = document.getElementById('sammel-panel');
    if (!el) return;
    const matId = parseInt(document.getElementById('opt-material')?.value);

    if (State.optMode !== 'material') {
        // Projekt-Modus: Hinweis, wenn dieses Material im Sammelplan gesägt wird
        const proj = State.projects.find(p => p.id === optProjId());
        const name = proj?.sammel?.[matId];
        el.classList.toggle('hidden', !name);
        el.innerHTML = name ? `<div class="sammel-hint">
            <span>&#128279; ${escHtml(t('sammel.in_plan_hint', { name }))}</span>
            <button id="btn-open-sammel" class="fd-button fd-button--compact" type="button">${escHtml(t('sammel.open'))}</button></div>` : '';
        document.getElementById('btn-open-sammel')?.addEventListener('click', () => {
            setOptMode('material', matId);
        });
        return;
    }

    el.classList.remove('hidden');
    const s = State.sammel;
    if (!s || s.material_id !== matId) { el.innerHTML = ''; return; }
    if (!s.kandidaten.length) {
        el.innerHTML = `<p class="sammel-note">${escHtml(t('sammel.none'))}</p>`;
        return;
    }
    const mat = State.materials.find(m => m.id === matId);
    const is1D = mat?.typ === 'Stange';
    const rows = s.kandidaten.map(k => {
        const notes = [];
        if (k.mitglied) notes.push(t('sammel.member'));
        if (k.einzelplan === 'offen') notes.push(t('sammel.replaces_single'));
        if (k.gesperrt > 0) notes.push(t('sammel.locked', { n: k.gesperrt }));
        const disabled = k.offen <= 0 && !k.mitglied;
        return `<tr class="fd-table__row${disabled ? ' sammel-row-disabled' : ''}" data-pid="${k.projekt_id}">
            <td class="fd-table__cell"><input type="checkbox" class="cs-checkbox sammel-check"${s.auswahl.has(k.projekt_id) ? ' checked' : ''}${disabled ? ' disabled' : ''}></td>
            <td class="fd-table__cell">${escHtml(k.name)}</td>
            <td class="fd-table__cell num">${k.offen}</td>
            <td class="fd-table__cell num">${formatMenge(k.bedarf, is1D)}</td>
            <td class="fd-table__cell sammel-note">${escHtml(notes.join(' · '))}</td>
        </tr>`;
    }).join('');
    el.innerHTML = `
        <h4 class="fd-title fd-title--h6">${escHtml(t('sammel.projects'))}</h4>
        <table class="fd-table"><thead class="fd-table__header"><tr class="fd-table__row">
            <th class="fd-table__cell"></th>
            <th class="fd-table__cell">${escHtml(t('opt.project').replace(':', ''))}</th>
            <th class="fd-table__cell num">${escHtml(t('sammel.col_open'))}</th>
            <th class="fd-table__cell num">${escHtml(t('sammel.col_need'))}</th>
            <th class="fd-table__cell">${escHtml(t('sammel.col_note'))}</th>
        </tr></thead><tbody class="fd-table__body">${rows}</tbody></table>
        <div class="toolbar">
            <button id="btn-sammel-compare" class="fd-button" type="button">${escHtml(t('sammel.compare'))}</button>
            <div id="sammel-compare" class="sammel-compare">${sammelVergleichHtml(is1D)}</div>
        </div>`;
    el.querySelectorAll('.sammel-check').forEach(cb => cb.addEventListener('change', () => {
        const pid = parseInt(cb.closest('tr').dataset.pid);
        if (cb.checked) s.auswahl.add(pid); else s.auswahl.delete(pid);
        s.vergleich = null;
        document.getElementById('sammel-compare').innerHTML = '';
    }));
    document.getElementById('btn-sammel-compare')?.addEventListener('click', () => compareSammel());
}

function sammelRequest() {
    const s = State.sammel;
    return {
        material_id: s.material_id,
        projekt_ids: [...s.auswahl],
        blade_id: parseInt(document.getElementById('opt-blade')?.value),
        algorithm: document.getElementById('opt-algorithm')?.value || 'greedy',
        reste_zuerst: !!document.getElementById('opt-rests-first')?.checked,
    };
}

function sammelVergleichHtml(is1D) {
    const v = State.sammel?.vergleich;
    if (!v) return '';
    const ganz = (n) => t(is1D ? (n === 1 ? 'sammel.bar_one' : 'sammel.bar_n')
                               : (n === 1 ? 'sammel.board_one' : 'sammel.board_n'), { n });
    const rest = (n) => t(n === 1 ? 'sammel.rest_one' : 'sammel.rest_n', { n });
    const teil = (ganze, reste) => ganz(ganze) + (reste ? ' + ' + rest(reste) : '');
    const gG = v.getrennt_bretter - v.getrennt_reste, gR = v.getrennt_reste;
    const zG = v.gemeinsam_bretter - v.gemeinsam_reste, zR = v.gemeinsam_reste;
    // Ganze Stangen/Platten zählen: Reste liegen ohnehin im Lager
    const weniger = gG > zG ? ganz(gG - zG) : (gG === zG && gR > zR ? rest(gR - zR) : '');
    const fazit = weniger
        ? `<span class="sammel-saving">${escHtml(t('sammel.fewer', { what: weniger }))}</span>`
        : `<span>${escHtml(t(is1D ? 'sammel.no_fewer_bars' : 'sammel.no_fewer_boards'))}</span>`;
    const missing = v.fehlende_getrennt || v.fehlende_gemeinsam
        ? `<div class="sammel-note">&#9888; ${escHtml(t('sammel.compare_missing'))}</div>` : '';
    return `${fazit}<div class="sammel-note">${escHtml(t('sammel.compare_result',
        { sep: teil(gG, gR), tog: teil(zG, zR) }))}</div>${missing}`;
}

async function compareSammel() {
    const s = State.sammel;
    if (!s?.auswahl.size) { showToast(t('sammel.select_projects'), 'error'); return; }
    const out = document.getElementById('sammel-compare');
    if (out) out.textContent = '…';
    try { s.vergleich = await Api.compareSammel(sammelRequest()); } catch { if (out) out.textContent = ''; return; }
    const mat = State.materials.find(m => m.id === s.material_id);
    if (out) out.innerHTML = sammelVergleichHtml(mat?.typ === 'Stange');
}

async function optimizeSammel() {
    const s = State.sammel;
    if (!s?.auswahl.size) { showToast(t('sammel.select_projects'), 'error'); return; }
    const ersetzt = s.kandidaten.filter(k => s.auswahl.has(k.projekt_id) && k.einzelplan === 'offen');
    if (ersetzt.length && !(await confirmAsync(
        t('sammel.confirm_replace', { names: ersetzt.map(k => k.name).join(', ') })))) return;
    const cur = State.optimizationResult;
    const started = cur?.plan_id && s.sammel_id && cur.projekt_id === s.sammel_id &&
        (cur.schnittplaene || []).some(p => p.verbraucht);
    if (started && !(await confirmAsync(t('plan.reoptimize_started')))) return;
    const plan = await Api.optimizeSammel(sammelRequest());
    await loadSammel(s.material_id);
    State.sammel.auswahl = s.auswahl;
    State.sammel.vergleich = s.vergleich;
    renderSammelPanel();
    adoptPlan(plan);
    renderOptResults();
}

function setOptMode(mode, matId) {
    State.optMode = mode;
    storageSet('localStorage', 'cutstock_opt_mode', mode);
    State.optimizationResult = null;
    applyOptMode();
    updateOptMaterialDropdown();
    const matSel = document.getElementById('opt-material');
    if (matId && matSel?.querySelector(`option[value="${matId}"]`)) matSel.value = String(matId);
    updateFillButton();
    renderOptResults();
    loadSavedPlan();
}

function updateOptMaterialDropdown() {
    const projSel = document.getElementById('opt-project');
    const matSel = document.getElementById('opt-material');
    if (!projSel || !matSel) return;

    if (State.optMode === 'material') {
        // Alle Materialien mit offenen Teilen in irgendeinem Projekt oder mit Sammelplan.
        // Je Material die Zahl der Projekte, die es brauchen – die lohnenden zuerst.
        const projekte = new Map();
        const add = (mid, pid) => {
            if (!projekte.has(mid)) projekte.set(mid, new Set());
            if (pid) projekte.get(mid).add(pid);
        };
        State.projects.forEach(p => {
            (p.teile || []).forEach(tl => { if (tl.offen_anzahl > 0) add(tl.material_id, p.id); });
            Object.keys(p.sammel || {}).forEach(mid => add(parseInt(mid), 0));
        });
        const anzahl = m => projekte.get(m.id).size;
        matSel.innerHTML = State.materials.filter(m => projekte.has(m.id))
            .sort((a, b) => anzahl(b) - anzahl(a) || a.name.localeCompare(b.name))
            .map(m => {
                const n = anzahl(m);
                const info = n ? ` (${t(n === 1 ? 'sammel.one_project' : 'sammel.n_projects', { n })})` : '';
                return `<option value="${m.id}">${escHtml(m.name)}${info}</option>`;
            }).join('');
        return;
    }

    const projectId = parseInt(projSel.value);
    const project = State.projects.find(p => p.id === projectId);
    const materialIds = new Set();

    if (project?.teile) {
        project.teile.forEach(t => {
            if (t.offen_anzahl > 0) materialIds.add(t.material_id);
        });
    }
    // Auch fertig gesägte Materialien bleiben wählbar, solange es einen Plan gibt
    (project?.plaene || []).forEach(p => materialIds.add(p.material_id));

    const filtered = materialIds.size > 0
        ? State.materials.filter(m => materialIds.has(m.id))
        : State.materials;

    matSel.innerHTML = filtered.map(m =>
        `<option value="${m.id}">${escHtml(m.name)}</option>`
    ).join('');
}

function renderOptResults({ quiet = false } = {}) {
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
    const fillerCount = plans.reduce((sum, p) => sum + p.platzierungen.filter(x => x.ist_fuellteil).length, 0);
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
                <div class="stat-sub stat-danger">${escHtml(summarizeLabels(missing))}</div></div>
            </div>`
            : `<div class="stat-card">
                <div class="stat-icon">&#9888;</div>
                <div><div class="stat-value">0</div>
                <div class="stat-label">${t('stat.parts_missing')}</div></div>
            </div>`;

        const materialbedarf = result.materialbedarf || [];
        const bedarfCard = materialbedarf.length > 0
            ? `<div class="stat-card">
                <div class="stat-icon">&#128722;</div>
                <div><div class="stat-value">${materialbedarf.reduce((s, m) => s + m.anzahl, 0)}</div>
                <div class="stat-label">${t('stat.material_needed')}</div>
                <div class="stat-sub">${materialbedarf.map(m => {
                    const dims = m.breite > 0
                        ? formatDim(m.laenge) + ' × ' + formatDim(m.breite)
                        : formatDim(m.laenge);
                    return m.anzahl + '× ' + dims;
                }).join(', ')}</div>
                <button class="fd-button fd-button--compact btn-add-bedarf" type="button"
                    style="margin-top:4px">${t('stat.add_to_stock')}</button></div>
            </div>`
            : '';

        // Sammelplan: Legende mit Farbe und Stückzahl je Projekt
        const projects = sammelProjects();
        const projectsCard = projects.length
            ? `<div class="stat-card">
                <div class="stat-icon">&#128279;</div>
                <div><div class="stat-value">${projects.length}</div>
                <div class="stat-label">${t('sammel.stat_projects')}</div>
                <div class="stat-sub sammel-legend">${projects.map(pr =>
                    `<span><span class="saw-dot" style="background:${pr.color}"></span>${escHtml(pr.name || '–')} ${pr.count}</span>`
                ).join('')}</div></div>
            </div>`
            : '';

        statsEl.innerHTML = `
            <div class="stat-card">
                <div class="stat-icon">&#128196;</div>
                <div><div class="stat-value">${plans.length}</div>
                <div class="stat-label">${t('stat.stock_used')}</div></div>
            </div>
            <div class="stat-card">
                <div class="stat-icon">&#9998;</div>
                <div><div class="stat-value">${totalParts}</div>
                <div class="stat-label">${t('stat.parts_placed')}</div>
                ${fillerCount ? `<div class="stat-sub">${escHtml(t('fill.of_which', { n: fillerCount }))}</div>` : ''}</div>
            </div>
            ${missingCard}
            ${bedarfCard}
            ${projectsCard}
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

        const addBedarfBtn = statsEl.querySelector('.btn-add-bedarf');
        if (addBedarfBtn) {
            addBedarfBtn.addEventListener('click', async () => {
                const matId = parseInt(document.getElementById('opt-material')?.value);
                for (const m of materialbedarf) {
                    await Api.createStock({
                        material_id: matId,
                        laenge: m.laenge,
                        breite: m.breite,
                        stueckzahl: m.anzahl,
                    });
                }
                showToast(t('stat.stock_added'), 'info');
                await renderStock();
            });
        }
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
            if (is1D) return `<div class="cut-plan-card">
                ${barHeadHtml(plan, i, mat)}
                <div class="plan-piece-info" data-plan-index="${i}">${planPieceInfo(plan)}</div>
                <canvas class="cut-plan-canvas" data-plan-index="${i}"
                    style="width:100%;height:${canvasHeight}px"></canvas>
                ${seqHtml}
            </div>`;
            return `<div class="cut-plan-card">
                ${plateHeadHtml(plan, i, mat)}
                <div class="plan-piece-info" data-plan-index="${i}">${planPieceInfo(plan)}</div>
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
    renderPlanInfo();

    if (missing.length > 0 && !quiet) {
        showToast(`${t('opt.missing')}: ${summarizeLabels(missing)}`, 'error');
    }
}

// Gleiche Labels zusammenfassen: ["A","A","B"] → "A ×2, B"
function summarizeLabels(labels) {
    const counts = new Map();
    labels.forEach(l => counts.set(l, (counts.get(l) || 0) + 1));
    return [...counts].map(([l, n]) => n > 1 ? `${l} ×${n}` : l).join(', ');
}

// Kopfzeile des gespeicherten Plans: Stand, Fortschritt, Warnhinweise.
function renderPlanInfo() {
    const el = document.getElementById('plan-info');
    const result = State.optimizationResult;
    if (!el) return;
    if (!result?.plan_id) { el.innerHTML = ''; el.classList.add('hidden'); return; }
    const plans = result.schnittplaene || [];
    const total = plans.reduce((s, p) => s + p.platzierungen.length, 0);
    const done = plans.reduce((s, p) => s + p.platzierungen.filter(x => x._done).length, 0);
    const when = result.erstellt
        ? new Date(result.erstellt * 1000).toLocaleString(State.settings.language || undefined,
            { dateStyle: 'short', timeStyle: 'short' })
        : '';
    const warn = [];
    if (result.veraltet) warn.push(t('plan.outdated'));
    if (result.lager_fehlt) warn.push(t('plan.stock_missing'));
    const vorrat = result.vorrat_verfuegbar || [];
    const vorratHtml = vorrat.length
        ? `<span class="plan-stock">&#128230; ${escHtml(t('fill.from_shelf'))}: ${escHtml(vorrat.map(v => `${v.label} ×${v.anzahl}`).join(', '))}
            <button id="btn-take-stock" class="fd-button fd-button--compact" type="button">${escHtml(t('fill.take'))}</button></span>`
        : '';
    el.innerHTML = `
        <span>${escHtml(t('plan.saved', { date: when }))}</span>
        <span class="plan-progress">${escHtml(t('plan.progress', { done, total }))}</span>
        ${warn.map(w => `<span class="plan-warning">&#9888; ${escHtml(w)}</span>`).join('')}
        ${vorratHtml}`;
    document.getElementById('btn-take-stock')?.addEventListener('click', takePartStock);
    el.classList.remove('hidden');
    const restartBtn = document.getElementById('btn-restart');
    if (restartBtn) restartBtn.classList.toggle('fd-button--emphasized', total > 0 && done >= total);
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
    const lockInp = document.getElementById('settings-nr-lock');
    if (lockInp) lockInp.value = State.settings.nr_lock_days ?? 1;
    const resChk = document.getElementById('settings-reservation');
    if (resChk) resChk.checked = State.settings.reservation !== false;

    const wInp = document.getElementById('settings-label-w');
    const hInp = document.getElementById('settings-label-h');
    if (wInp) wInp.value = State.settings.label_custom_w ?? 89;
    if (hInp) hInp.value = State.settings.label_custom_h ?? 36;
    updateLabelCustomVisibility();

    // API settings
    const apiEn = document.getElementById('settings-api-enabled');
    const apiPort = document.getElementById('settings-api-port');
    const apiKey = document.getElementById('settings-api-key');
    if (apiEn) apiEn.checked = !!State.settings.api_enabled;
    if (apiPort) apiPort.value = State.settings.api_port ?? 8421;
    if (apiKey) apiKey.value = State.settings.api_key ?? '';
    updateApiDetailVisibility();

    const vEl = document.getElementById('app-version');
    if (vEl) {
        Api.getVersion()
            .then(v => { vEl.textContent = v.version; State.versionInfo = v; })
            .catch(() => { vEl.textContent = '—'; });
    }
}

// ---------------------------------------------------------------------------
// License
// ---------------------------------------------------------------------------

async function renderLicense() {
    const typeEl = document.getElementById('license-type');
    const holderEl = document.getElementById('license-holder');
    const expiresEl = document.getElementById('license-expires');
    const noteEl = document.getElementById('license-note');
    const keyInput = document.getElementById('license-key-input');
    const removeBtn = document.getElementById('btn-license-remove');
    if (!typeEl) return;

    try {
        const lic = await Api.getLicense();
        State.licenseInfo = lic;

        if (lic.valid && lic.type === 'commercial') {
            typeEl.textContent = t('lic.commercial');
            typeEl.className = 'read-only license-badge license-commercial';
            holderEl.textContent = lic.holder || '—';
            expiresEl.textContent = lic.expires || t('lic.unlimited');
            document.querySelectorAll('.license-detail').forEach(el => el.style.display = '');
            noteEl.style.display = 'none';
            if (keyInput) keyInput.value = State.settings.license_key || '';
            if (removeBtn) removeBtn.style.display = '';
        } else if (lic.type === 'expired') {
            typeEl.textContent = t('lic.expired');
            typeEl.className = 'read-only license-badge license-expired';
            holderEl.textContent = lic.holder || '—';
            expiresEl.textContent = lic.expires || '';
            document.querySelectorAll('.license-detail').forEach(el => el.style.display = '');
            noteEl.textContent = t('lic.error_expired');
            noteEl.style.display = '';
            if (keyInput) keyInput.value = State.settings.license_key || '';
            if (removeBtn) removeBtn.style.display = '';
        } else {
            typeEl.textContent = t('lic.community');
            typeEl.className = 'read-only license-badge license-community';
            document.querySelectorAll('.license-detail').forEach(el => el.style.display = 'none');
            noteEl.textContent = t('lic.note_community');
            noteEl.style.display = '';
            if (keyInput) keyInput.value = '';
            if (removeBtn) removeBtn.style.display = 'none';
        }
    } catch {
        typeEl.textContent = t('lic.community');
        typeEl.className = 'read-only license-badge license-community';
    }

    updateLicenseFooter();
}

function updateLicenseFooter() {
    const badge = document.getElementById('footer-license-badge');
    if (!badge) return;
    const lic = State.licenseInfo;
    if (lic?.valid && lic.type === 'commercial') {
        badge.textContent = lic.holder;
        badge.className = 'footer-license license-commercial';
    } else {
        badge.textContent = 'Community (PolyForm Noncommercial)';
        badge.className = 'footer-license license-community';
    }
}

async function activateLicense() {
    const keyInput = document.getElementById('license-key-input');
    const key = keyInput?.value?.trim();
    if (!key) return;

    await Api.updateSettings({ license_key: key });
    State.settings.license_key = key;

    const lic = await Api.getLicense();
    if (lic.valid) {
        showToast(t('lic.activated'), 'info');
    } else if (lic.error === 'expired') {
        showToast(t('lic.error_expired'), 'error');
    } else {
        showToast(t('lic.invalid'), 'error');
    }
    await renderLicense();
}

async function removeLicense() {
    await Api.updateSettings({ license_key: '' });
    State.settings.license_key = '';
    const keyInput = document.getElementById('license-key-input');
    if (keyInput) keyInput.value = '';
    showToast(t('lic.removed'), 'info');
    await renderLicense();
}

// Breite/Höhe-Felder nur beim benutzerdefinierten Etikettenformat zeigen
function updateLabelCustomVisibility() {
    const isCustom = document.getElementById('settings-label-format')?.value === 'custom';
    document.querySelectorAll('.label-custom-field').forEach(el => {
        el.style.display = isCustom ? '' : 'none';
    });
}

// Port/Key-Felder nur zeigen wenn API aktiviert
function updateApiDetailVisibility() {
    const on = document.getElementById('settings-api-enabled')?.checked;
    document.querySelectorAll('.api-detail-field, .api-hint').forEach(el => {
        el.style.display = on ? '' : 'none';
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

// Neueste Version von GitHub holen: { tag, url } (url = Release-Seite)
async function fetchLatestRelease(info) {
    const resp = await fetch(info.releases_api, {
        headers: { 'Accept': 'application/vnd.github+json' },
    });
    if (!resp.ok) throw new Error('github');
    const rel = await resp.json();
    return { tag: (rel.tag_name || '').trim(), url: rel.html_url || info.github_url };
}

const UPDATE_CACHE_KEY = 'cutstock_update_check';
const UPDATE_CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000;

// Ist eine neuere Version da, erscheint oben ein Knopf, der die Anleitung öffnet
function showUpdateButton(info, release) {
    const btn = document.getElementById('btn-update-available');
    if (!btn) return;
    const newer = release.tag && compareVersions(release.tag, info.version) > 0;
    btn.style.display = newer ? '' : 'none';
    btn.onclick = newer ? () => openUpdateDialog(info, release) : null;
}

// Beim Start im Hintergrund prüfen – höchstens einmal am Tag, Fehler still ignorieren
async function autoCheckUpdate() {
    try {
        const info = State.versionInfo || await Api.getVersion();
        State.versionInfo = info;
        let release = null;
        try {
            const cached = JSON.parse(storageGet('localStorage', UPDATE_CACHE_KEY) || 'null');
            if (cached && Date.now() - cached.ts < UPDATE_CHECK_INTERVAL_MS) release = cached;
        } catch { /* Cache defekt → neu prüfen */ }
        if (!release) {
            release = await fetchLatestRelease(info);
            storageSet('localStorage', UPDATE_CACHE_KEY, JSON.stringify({ ...release, ts: Date.now() }));
        }
        showUpdateButton(info, release);
    } catch { /* offline o. ä. – kein Hinweis */ }
}

async function checkForUpdate() {
    showToast(t('set.checking_update'), 'info');
    try {
        const info = State.versionInfo || await Api.getVersion();
        const release = await fetchLatestRelease(info);
        storageSet('localStorage', UPDATE_CACHE_KEY, JSON.stringify({ ...release, ts: Date.now() }));
        showUpdateButton(info, release);
        if (release.tag && compareVersions(release.tag, info.version) > 0) {
            openUpdateDialog(info, release);
        } else {
            showToast(t('set.up_to_date', { version: info.version }), 'info');
        }
    } catch {
        showToast(t('set.update_failed'), 'error');
    }
}

// Anleitung zum Aktualisieren: Docker-Plattformen bzw. Download für die Desktop-App
function openUpdateDialog(info, release) {
    const overlay = document.getElementById('modal-overlay');
    const body = document.getElementById('modal-body');
    const steps = key => `<ol>${t(key).split('\n').map(s => `<li>${escHtml(s)}</li>`).join('')}</ol>`;
    const releaseLink = (label, cls = '') =>
        `<a class="fd-button ${cls}" href="${escAttr(release.url)}" target="_blank" rel="noopener">`
        + `<span>${escHtml(label)}</span><span class="ext-arrow" aria-hidden="true"> ↗</span></a>`;

    let guide;
    if (info.docker) {
        guide = `<p>${escHtml(t('upd.how_docker'))}</p>
            <details open><summary>${escHtml(t('upd.synology'))}</summary>
                ${steps('upd.synology_steps')}
                <p class="update-hint">${escHtml(t('upd.synology_hint'))}</p></details>
            <details><summary>${escHtml(t('upd.unraid'))}</summary>${steps('upd.unraid_steps')}</details>
            <details><summary>${escHtml(t('upd.compose'))}</summary>
                <pre>docker compose pull\ndocker compose up -d</pre></details>`;
    } else {
        guide = `<p>${escHtml(t('upd.desktop'))}</p>
            <div class="toolbar">${releaseLink(t('upd.download'), 'fd-button--emphasized')}</div>`;
    }

    document.getElementById('modal-title').textContent = t('upd.title', { version: release.tag });
    body.innerHTML = `<div class="update-guide">
        <p>${escHtml(t('upd.current', { current: info.version }))}</p>
        ${guide}
        <div class="toolbar">${releaseLink(t('upd.whats_new'), 'fd-button--transparent')}</div>
    </div>`;
    document.getElementById('modal-save').style.display = 'none';
    document.getElementById('modal-cancel').textContent = t('btn.close');
    overlay.classList.remove('hidden');
    overlay.classList.add('active');
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

// Projekt eines Teils im Sammelplan/Füllteil: „Label → Projekt“
function partProject(label) {
    const i = label.indexOf(' → ');
    return i < 0 ? '' : label.slice(i + 3);
}

// Projekte des Ergebnisses mit Farbe und Stückzahl (nur im Sammelplan)
function sammelProjects() {
    if (State.optMode !== 'material') return [];
    const counts = new Map();
    (State.optimizationResult?.schnittplaene || []).forEach(sp =>
        sp.platzierungen.forEach(p => {
            const proj = partProject(p.teil_label);
            counts.set(proj, (counts.get(proj) || 0) + 1);
        }));
    return [...counts.keys()].sort().map((name, i) =>
        ({ name, count: counts.get(name), color: PART_COLORS[i % PART_COLORS.length] }));
}

// Konsistente Label→Farbe-Zuordnung über alle Schnittpläne des Ergebnisses.
// Im Sammelplan bekommt jedes Projekt eine Farbe, damit die Stapel stimmen.
function buildColorMap() {
    const map = {};
    const labels = new Set();
    (State.optimizationResult?.schnittplaene || []).forEach(sp =>
        sp.platzierungen.forEach(p => labels.add(p.teil_label)));
    const projects = sammelProjects();
    if (projects.length) {
        const byName = Object.fromEntries(projects.map(pr => [pr.name, pr.color]));
        labels.forEach(label => { map[label] = byName[partProject(label)]; });
        return map;
    }
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
        draw1D(ctx, canvasW, canvasH, plan, colorMap, hits, material?.besaeumung || 0);
    } else {
        draw2D(ctx, canvasW, canvasH, plan, colorMap, hits, material?.besaeumung || 0);
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

// Ein Stück im Schnittplan als gesägt markieren/zurücknehmen. Der Server
// führt Fortschritt des Teils UND Lagerbestand (gespeicherter Plan).
async function togglePieceSawn(canvas, placement) {
    const result = State.optimizationResult;
    if (!result || !placement.id) return;
    const willBeDone = !placement._done;
    placement._done = willBeDone;
    redrawPlanForCanvas(canvas);

    let res;
    try {
        res = await Api.setPieceSawn(placement.id, willBeDone);
    } catch {
        placement._done = !willBeDone;
        redrawPlanForCanvas(canvas);
        return;
    }
    applyPlanState(res.plan);
    if (res.teil) updatePartInState(res.teil);
    await refreshAfterSawing();

    // Rebuild the workshop-mode view (if open) with the new state
    if (sawModeActive()) renderSawMode();
}

// Geänderten Teil-Fortschritt in State.projects übernehmen.
function updatePartInState(teil) {
    const proj = State.projects.find(p => p.id === teil.projekt_id);
    const idx = proj?.teile?.findIndex(x => x.id === teil.id) ?? -1;
    if (idx >= 0) proj.teile[idx] = teil;
}

// Lagerbestand und Projektliste nach dem Abhaken auffrischen.
async function refreshAfterSawing() {
    const matId = parseInt(document.getElementById('opt-material')?.value);
    if (State.selectedMaterialId === matId) {
        try { State.stock = await Api.getStock(matId); renderStock(); } catch { /* ignore */ }
    }
    try {
        State.projects = await Api.getProjects();
        renderProjects();
    } catch { /* ignore */ }
}

// „Bestätigen": alle noch nicht markierten Stücke auf einmal als gesägt markieren.
async function confirmAllPieces() {
    const result = State.optimizationResult;
    if (!result?.plan_id) return;
    try {
        const plan = await Api.confirmAllPieces(result.plan_id);
        applyPlanState(plan);
    } catch { return; }
    document.querySelectorAll('.cut-plan-canvas').forEach(c => redrawPlanForCanvas(c));
    await refreshAfterSawing();
    showToast(t('opt.done'), 'info');
}

// ---------------------------------------------------------------------------
// Füllteile: Teile anderer Projekte (gleiches Material) im aktuellen Plan mitsägen
// ---------------------------------------------------------------------------

function currentFillKey() {
    return `${document.getElementById('opt-project')?.value}:${document.getElementById('opt-material')?.value}`;
}

// Füllteil-Auswahl für den Optimierungs-Request (nur wenn sie zur Auswahl passt)
function fillRequest(projId, matId) {
    const sel = State.fillSel;
    if (!sel || sel.key !== `${projId}:${matId}`) return {};
    return { fuellteile: sel.items, fuell_alle_reste: sel.alle };
}

function updateFillButton() {
    const btn = document.getElementById('btn-fill');
    if (!btn) return;
    const n = State.fillSel?.key === currentFillKey() ? (State.fillSel.items || []).length : 0;
    btn.textContent = n ? `${t('fill.button').replace('…', '')} (${n})` : t('fill.button');
}

// ---------------------------------------------------------------------------
// Reiter „Teile“: Teile aller Projekte, daraus eine Schnittliste erstellen
// ---------------------------------------------------------------------------

// Auswahl bleibt beim Filtern erhalten: teil_id -> Menge
const PartsSel = new Map();

async function renderAllParts() {
    let teile;
    try {
        teile = await Api.getAllParts();
        if (!State.materials.length) State.materials = await Api.getMaterials();
    } catch { return; }
    State.allParts = teile;

    const matSel = document.getElementById('parts-material');
    const projSel = document.getElementById('parts-project');
    const keep = (sel) => sel.value;
    const matVal = keep(matSel), projVal = keep(projSel);
    const matIds = new Set(teile.map(x => x.material_id));
    matSel.innerHTML = `<option value="">${escHtml(t('parts.all'))}</option>` +
        State.materials.filter(m => matIds.has(m.id))
            .map(m => `<option value="${m.id}">${escHtml(m.name)}</option>`).join('');
    const projekte = [...new Map(teile.map(x => [x.projekt_id, x.projekt])).entries()];
    projSel.innerHTML = `<option value="">${escHtml(t('parts.all'))}</option>` +
        projekte.map(([id, name]) => `<option value="${id}">${escHtml(name)}</option>`).join('');
    matSel.value = matIds.has(parseInt(matVal)) ? matVal : '';
    projSel.value = projekte.some(([id]) => String(id) === projVal) ? projVal : '';
    // Teile, die es nicht mehr gibt, aus der Auswahl nehmen
    const ids = new Set(teile.map(x => x.teil_id));
    [...PartsSel.keys()].forEach(id => { if (!ids.has(id)) PartsSel.delete(id); });
    renderAllPartsTable();
}

function renderAllPartsTable() {
    const tbody = document.querySelector('#all-parts-table tbody');
    if (!tbody) return;
    const matId = parseInt(document.getElementById('parts-material').value) || 0;
    const projId = parseInt(document.getElementById('parts-project').value) || 0;
    const onlyOpen = document.getElementById('parts-only-open').checked;
    const matName = (id) => State.materials.find(m => m.id === id)?.name || '';
    const rows = (State.allParts || []).filter(x =>
        (!matId || x.material_id === matId) && (!projId || x.projekt_id === projId)
        && (!onlyOpen || x.offen > 0));
    tbody.innerHTML = rows.length ? rows.map(x => {
        const menge = PartsSel.get(x.teil_id);
        return `<tr class="fd-table__row" data-teil="${x.teil_id}">
            <td class="fd-table__cell"><input type="checkbox" class="cs-checkbox parts-check"${menge ? ' checked' : ''}></td>
            <td class="fd-table__cell">${escHtml(x.label)}</td>
            <td class="fd-table__cell">${escHtml(x.projekt)}</td>
            <td class="fd-table__cell">${escHtml(matName(x.material_id))}</td>
            <td class="fd-table__cell num">${dimText(x.laenge, x.breite)}</td>
            <td class="fd-table__cell num">${x.offen}</td>
            <td class="fd-table__cell num">${x.vorrat || ''}</td>
            <td class="fd-table__cell"><input type="number" class="parts-qty" min="1" step="1" style="width:5rem"
                value="${menge || ''}" placeholder="${x.offen || 1}"></td>
        </tr>`;
    }).join('') : `<tr><td class="empty-state" colspan="8">${escHtml(t('parts.none'))}</td></tr>`;

    tbody.querySelectorAll('tr[data-teil]').forEach(tr => {
        const id = parseInt(tr.dataset.teil);
        const teil = State.allParts.find(x => x.teil_id === id);
        const check = tr.querySelector('.parts-check');
        const qty = tr.querySelector('.parts-qty');
        // Ohne eigene Angabe: so viele wie offen, bei fertigen Teilen eins
        check.addEventListener('change', () => {
            if (check.checked) {
                const n = parseInt(qty.value) || teil.offen || 1;
                qty.value = n;
                PartsSel.set(id, n);
            } else {
                PartsSel.delete(id);
            }
            updatePartsSelection();
        });
        qty.addEventListener('input', () => {
            const n = parseInt(qty.value) || 0;
            check.checked = n > 0;
            if (n > 0) PartsSel.set(id, n); else PartsSel.delete(id);
            updatePartsSelection();
        });
    });
    updatePartsSelection();
}

function updatePartsSelection() {
    const n = PartsSel.size;
    document.getElementById('parts-selected').textContent = n ? t('parts.selected', { n }) : '';
    document.getElementById('btn-create-cutlist').disabled = n === 0;
}

function createCutList() {
    if (!PartsSel.size) return;
    const overlay = document.getElementById('modal-overlay');
    const body = document.getElementById('modal-body');
    const saveBtn = document.getElementById('modal-save');
    document.getElementById('modal-title').textContent = t('parts.create_list');
    saveBtn.style.display = '';
    saveBtn.textContent = t('btn.save');
    const datum = new Date().toLocaleDateString(State.settings?.language || undefined);
    body.innerHTML = `<div class="form-group">
        <label class="fd-form-label" for="cutlist-name">${escHtml(t('parts.list_name'))}</label>
        <input id="cutlist-name" class="fd-input" type="text" maxlength="200"
            value="${escAttr(t('parts.list_default', { datum }))}">
    </div>
    <p class="saw-hint">${escHtml(t('parts.list_hint'))}</p>`;
    overlay.classList.remove('hidden');
    overlay.classList.add('active');
    const input = document.getElementById('cutlist-name');
    input.focus();
    input.select();
    saveBtn.onclick = async () => {
        const name = input.value.trim();
        if (!name) { input.focus(); return; }
        try {
            const liste = await Api.createCutList({
                name,
                eintraege: [...PartsSel.entries()].map(([teil_id, menge]) => ({ teil_id, menge })),
            });
            closeModal();
            PartsSel.clear();
            showToast(t('parts.list_created', { name: liste.name }), 'success');
            // Direkt zur neuen Liste im Projekte-Reiter
            State.selectedProjectId = liste.id;
            document.querySelector('.tab-btn[data-tab="projects"]')?.click();
        } catch (e) {
            showToast(e.message, 'error');
        }
    };
}

async function openFillDialog() {
    const projId = parseInt(document.getElementById('opt-project')?.value);
    const matId = parseInt(document.getElementById('opt-material')?.value);
    if (!projId || !matId) return;
    const mat = State.materials.find(m => m.id === matId);
    const is1D = mat?.typ === 'Stange';
    let kandidaten = [];
    try { kandidaten = await Api.getFillCandidates(projId, matId); } catch { return; }

    const key = `${projId}:${matId}`;
    const sel = State.fillSel?.key === key ? State.fillSel : { key, items: [], alle: false };
    const gewaehlt = new Map(sel.items.map(f => [f.teil_id, f]));

    const overlay = document.getElementById('modal-overlay');
    const body = document.getElementById('modal-body');
    const saveBtn = document.getElementById('modal-save');
    document.getElementById('modal-title').textContent = t('fill.title');
    saveBtn.style.display = '';
    saveBtn.textContent = t('btn.save');

    const hint = is1D ? t('fill.hint_1d') : t('fill.hint_2d');
    const rows = kandidaten.map(k => {
        const f = gewaehlt.get(k.teil_id);
        const modus = f?.modus || (is1D ? 'auffuellen' : 'fest');
        return `<tr class="fd-table__row" data-teil="${k.teil_id}">
            <td class="fd-table__cell"><input type="checkbox" class="cs-checkbox fill-check"${f ? ' checked' : ''}></td>
            <td class="fd-table__cell">${escHtml(k.label)}</td>
            <td class="fd-table__cell">${escHtml(k.projekt)}</td>
            <td class="fd-table__cell num">${dimText(k.laenge, k.breite)}</td>
            <td class="fd-table__cell num">${k.offen}</td>
            <td class="fd-table__cell num">${k.vorrat || ''}</td>
            <td class="fd-table__cell">
                <select class="cs-select fill-mode"${is1D ? '' : ' disabled'}>
                    <option value="auffuellen"${modus === 'auffuellen' ? ' selected' : ''}>${escHtml(t('fill.mode_fill'))}</option>
                    <option value="fest"${modus === 'fest' ? ' selected' : ''}>${escHtml(t('fill.mode_fixed'))}</option>
                </select>
            </td>
            <td class="fd-table__cell"><input type="number" class="fill-qty" min="0" step="1" style="width:5rem"
                value="${f?.menge || ''}" placeholder="${escAttr(modus === 'fest' ? '' : t('fill.qty_max'))}"></td>
        </tr>`;
    }).join('');
    body.innerHTML = kandidaten.length ? `
        <p class="saw-hint" style="margin-bottom:.5rem">${escHtml(hint)}</p>
        ${is1D ? `<label class="opt-check" style="margin-bottom:.5rem"><input type="checkbox" id="fill-all-rests" class="cs-checkbox"${sel.alle ? ' checked' : ''}>
            <span>${escHtml(t('fill.all_rests'))}</span></label>` : ''}
        <div class="fill-table-wrap"><table class="fd-table fill-table"><thead class="fd-table__header"><tr class="fd-table__row">
            <th class="fd-table__cell"></th>
            <th class="fd-table__cell">${escHtml(t('fill.part'))}</th>
            <th class="fd-table__cell">${escHtml(t('fill.project'))}</th>
            <th class="fd-table__cell">${escHtml(t('fill.size'))}</th>
            <th class="fd-table__cell">${escHtml(t('fill.open'))}</th>
            <th class="fd-table__cell">${escHtml(t('fill.stock'))}</th>
            <th class="fd-table__cell">${escHtml(t('fill.mode'))}</th>
            <th class="fd-table__cell">${escHtml(t('fill.qty'))}</th>
        </tr></thead><tbody>${rows}</tbody></table></div>`
        : `<p class="empty-state">${escHtml(t('fill.none'))}</p>`;

    // Menge eintippen hakt das Teil automatisch an
    body.querySelectorAll('tr[data-teil]').forEach(tr => {
        tr.querySelector('.fill-qty')?.addEventListener('input', () => {
            tr.querySelector('.fill-check').checked = true;
        });
    });

    overlay.classList.remove('hidden');
    overlay.classList.add('active');
    saveBtn.onclick = () => {
        const items = [];
        body.querySelectorAll('tr[data-teil]').forEach(tr => {
            if (!tr.querySelector('.fill-check').checked) return;
            const modus = is1D ? tr.querySelector('.fill-mode').value : 'fest';
            const menge = Math.max(0, parseInt(tr.querySelector('.fill-qty').value) || 0);
            if (modus === 'fest' && menge <= 0) return;
            items.push({ teil_id: parseInt(tr.dataset.teil), modus, menge });
        });
        State.fillSel = { key, items, alle: !!document.getElementById('fill-all-rests')?.checked };
        closeModal();
        updateFillButton();
        showToast(t('fill.saved_hint'), 'info');
    };
}

// Teile-Vorrat des angezeigten Projekts übernehmen und neu optimieren
async function takePartStock() {
    const result = State.optimizationResult;
    if (!result?.plan_id) return;
    try { await Api.takePartStock(result.projekt_id, result.material_id); } catch { return; }
    try { State.projects = await Api.getProjects(); } catch { /* ignore */ }
    renderProjects();
    showToast(t('fill.taken'), 'info');
    document.getElementById('btn-optimize')?.click();
}

// „Plan verwerfen": Plan löschen und reservierte Bretter freigeben.
// Bereits Gesägtes (Fortschritt, Lagerbuchungen) bleibt, wie es ist.
async function discardPlan() {
    const result = State.optimizationResult;
    if (!result?.plan_id) return;
    try { await Api.discardPlan(result.plan_id); } catch { return; }
    clearOptResult();
    try { State.projects = await Api.getProjects(); } catch { /* ignore */ }
    renderProjects();
    if (State.optMode === 'material') { if (State.sammel) State.sammel.material_id = 0; loadSavedPlan(); }
    else { updateOptMaterialDropdown(); renderSammelPanel(); }
    showToast(t('plan.discarded'), 'info');
}

// „Projekt neu starten": Fortschritt auf 0, Pläne löschen (Lager bleibt).
async function restartProject() {
    const projId = parseInt(document.getElementById('opt-project')?.value);
    if (!projId) return;
    try { await Api.restartProject(projId); } catch { return; }
    clearOptResult();
    try { State.projects = await Api.getProjects(); } catch { /* ignore */ }
    renderProjects();
    renderOptDropdowns();
    showToast(t('plan.restarted'), 'info');
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

// Aufschrift eines Einzelstücks, z.B. "AP4040-07" (wie core.models.stueck_code)
function pieceCode(mat, nr) {
    if (!nr) return '';
    return mat?.kuerzel ? `${mat.kuerzel}-${String(nr).padStart(2, '0')}` : `#${nr}`;
}

function dimText(laenge, breite) {
    return breite > 0
        ? `${toDisplay(laenge)} × ${toDisplay(breite)} ${unitLabel()}`
        : formatDim(laenge);
}

// One label per placed part; the ID references the panel/bar in the plan
function printPartLabels() {
    const result = State.optimizationResult;
    if (!result?.schnittplaene?.length) return;
    const projName = optProjName();
    const matId = parseInt(document.getElementById('opt-material')?.value);
    const matName = State.materials.find(m => m.id === matId)?.name || '';

    const labels = [];
    result.schnittplaene.forEach((plan, i) => {
        plan.platzierungen.forEach(p => {
            // Füllteile/Sammelplan: „Label → Projekt“ – das Projekt gehört in Zeile 2
            const [titel, herkunft] = p.teil_label.split(' → ');
            labels.push({
                title: titel,
                line1: dimText(p.laenge, p.breite) + (p.gedreht ? '  (R)' : ''),
                line2: [herkunft || (State.optMode === 'material' ? '' : projName), matName]
                    .filter(Boolean).join(' · '),
                id_text: `P${i + 1}`,
            });
        });
    });
    Api.downloadLabels({ labels, filename: `${t('labels.button')}-${projName || 'Teile'}` });
}

// One label per physical stock piece (quantity > 1 → several labels);
// the #ID is written onto the wood and uniquely identifies the remnant.
async function printStockLabels() {
    const mat = getSelectedMaterial();
    if (!mat) { showToast(t('dlg.select_material'), 'error'); return; }
    if (!State.stock.length) { showToast(t('stock.empty'), 'error'); return; }

    // Ein Etikett je Einzelstück, mit seinem Code (das schreibt man aufs Material)
    const labels = [];
    for (const s of State.stock) {
        let pieces = [];
        try { pieces = await Api.getPieces(s.id); } catch { /* ignore */ }
        pieces.slice(0, 200).forEach(p => labels.push({
            title: mat.name,
            line1: dimText(s.laenge, s.breite),
            line2: p.lagerort_effektiv || t('labels.stock'),
            id_text: p.code || `#${p.nr}`,
        }));
    }
    Api.downloadLabels({ labels, filename: `${t('labels.button')}-${mat.name}` });
}

// Etiketten für die beim Sägen entstandenen Reste eines Bretts
function printRestLabels(plan) {
    const mat = State.materials.find(m => m.id === State.optimizationResult?.material_id);
    const labels = (plan.reste_stuecke || []).map(r => ({
        title: mat?.name || '',
        line1: dimText(r.laenge, r.breite),
        line2: r.lagerort || t('labels.rest'),
        id_text: r.code,
    }));
    if (!labels.length) return;
    Api.downloadLabels({ labels, filename: `${t('labels.button')}-${t('labels.rest')}` });
}

// "Nimm AP4040-07 · 640 mm · Regal 2" bzw. nach dem Anfangen "Reste beschriften: …"
// Kopf einer Stange: was man in die Hand nimmt, wie viele Teile, wohin der Rest geht
function barHeadHtml(plan, i, mat) {
    const art = plan.ist_rest ? t('bar.rest') : t('bar.whole');
    const n = plan.platzierungen.length;
    const minL = mat?.rest_min_laenge ?? 0;
    const reste = (plan.reste || []).map(r => r[0]).filter(l => l > 0.5);
    const restText = reste.length
        ? reste.map(l => `${t('bar.left', { menge: formatDim(Math.round(l)) })} → ${t(l >= minL ? 'bar.to_stock' : 'bar.to_waste')}`).join(', ')
        : t('bar.no_left');
    return `<div class="plan-header bar-head">
        <strong>${escHtml(t('bar.title', { n: i + 1 }))} · ${escHtml(art)} ${formatDim(plan.lager_laenge + 2 * (mat?.besaeumung || 0))}</strong>
        <span>${escHtml(n === 1 ? t('bar.one_part') : t('bar.n_parts', { n }))} · ${escHtml(restText)}</span>
        <button class="fd-button btn-zoom" data-plan-index="${i}" type="button" title="${escAttr(t('opt.zoom'))}" aria-label="${escAttr(t('opt.zoom'))}">&#128269;</button>
    </div>`;
}

function plateHeadHtml(plan, i, mat) {
    const trim = 2 * (mat?.besaeumung || 0);
    const art = plan.ist_rest ? t('bar.rest') : t('plate.whole');
    const n = plan.platzierungen.length;
    const minL = mat?.rest_min_laenge ?? 0;
    const minB = mat?.rest_min_breite ?? 0;
    // Gleiche Regel wie beim Einbuchen (db.rest_einbuchen)
    const reste = (plan.reste || []).filter(r => r[0] > 0.5 && r[1] > 0.5);
    const lager = reste.filter(r => r[0] >= minL && r[1] >= minB);
    const klein = reste.length - lager.length;
    const restTexte = lager.map(r => t('plate.rest_to_stock',
        { masse: `${formatDim(Math.round(r[0]))} × ${formatDim(Math.round(r[1]))}` }));
    if (klein) restTexte.push(klein === 1 ? t('plate.small_one') : t('plate.small_n', { n: klein }));
    const used = t('plate.used', { p: (100 - plan.verschnitt_prozent).toFixed(0) });
    return `<div class="plan-header bar-head">
        <strong>${escHtml(t('plate.title', { n: i + 1 }))} · ${escHtml(art)} ${formatDim(plan.lager_laenge + trim)} × ${formatDim(plan.lager_breite + trim)}</strong>
        <span>${escHtml(n === 1 ? t('bar.one_part') : t('bar.n_parts', { n }))} · ${escHtml(used)}</span>
        ${restTexte.length ? `<span>${escHtml(restTexte.join(', '))}</span>` : `<span>${escHtml(t('bar.no_left'))}</span>`}
        <button class="fd-button btn-zoom" data-plan-index="${i}" type="button" title="${escAttr(t('opt.zoom'))}" aria-label="${escAttr(t('opt.zoom'))}">&#128269;</button>
    </div>`;
}

function planPieceInfo(plan) {
    const parts = [];
    if (plan.stueck_code) {
        const where = plan.lagerort ? ` · &#128205; ${escHtml(plan.lagerort)}` : '';
        parts.push(`<span class="plan-take">${plan.verbraucht ? '' : escHtml(t('plan.take')) + ' '}<strong>${escHtml(plan.stueck_code)}</strong>${where}</span>`);
    }
    const reste = plan.reste_stuecke || [];
    if (reste.length) {
        parts.push(`<span class="plan-rests">${escHtml(t('plan.label_rests'))}: ${reste.map(r =>
            `<strong>${escHtml(r.code)}</strong> ${dimText(r.laenge, r.breite)}${r.lagerort ? ' (' + escHtml(r.lagerort) + ')' : ''}`
        ).join(', ')}</span>`);
    }
    return parts.join('');
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
        `${t(is1D ? 'bar.title' : 'plate.title', { n: sawPlanIdx + 1 })} / ${plans.length}`;
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

    // Welches Stück nehmen / welche Reste beschriften
    const info = document.getElementById('saw-piece-info');
    if (info) {
        const hasRests = (plan.reste_stuecke || []).length > 0;
        info.innerHTML = planPieceInfo(plan) + (hasRests
            ? ` <button id="saw-rest-labels" class="fd-button fd-button--compact" type="button">${escHtml(t('plan.print_rest_labels'))}</button>`
            : '');
        document.getElementById('saw-rest-labels')?.addEventListener('click', () => printRestLabels(plan));
    }

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

// Schraffur für Füllteile (Teile anderer Projekte, die ins Regal gehen)
function drawFillerHatch(ctx, x, y, w, h) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.clip();
    ctx.strokeStyle = 'rgba(255,255,255,0.45)';
    ctx.lineWidth = 2;
    for (let d = -h; d < w; d += 8) {
        ctx.beginPath();
        ctx.moveTo(x + d, y + h);
        ctx.lineTo(x + d + h, y);
        ctx.stroke();
    }
    ctx.restore();
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
        // Defects are cut out as waste at their position in between.
        // pieceIndex refers back into plan.platzierungen for hover highlight.
        const steps = [
            ...plan.platzierungen.map(p => ({ x: p.x, p })),
            ...(plan.defekte || []).map(d => ({ x: d.position, d })),
        ].sort((a, b) => a.x - b.x);
        return steps.map(({ p, d }) => {
            const text = p
                ? t('seq.cut_1d', { label: p.teil_label, len: formatDim(p.laenge) })
                : t('seq.cut_defect', { from: formatDim(d.position),
                                        to: formatDim(d.position + d.laenge) });
            return p
                ? { text, html: escHtml(text), pieceIndex: plan.platzierungen.indexOf(p) }
                : { text, html: escHtml(text) };
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

function draw2D(ctx, canvasW, canvasH, plan, colorMap, hits, besaeumung = 0) {
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

    // Defects (red hatched areas)
    if (plan.defekte?.length) {
        plan.defekte.forEach(d => {
            const dx = offsetX + d.position * scale;
            const dy = offsetY + d.position_y * scale;
            const dw = d.laenge * scale;
            const dh = d.breite * scale;
            ctx.save();
            ctx.fillStyle = 'rgba(200, 30, 30, 0.15)';
            ctx.fillRect(dx, dy, dw, dh);
            ctx.strokeStyle = 'rgba(200, 30, 30, 0.6)';
            ctx.lineWidth = 1;
            ctx.strokeRect(dx, dy, dw, dh);
            ctx.beginPath();
            ctx.rect(dx, dy, dw, dh);
            ctx.clip();
            ctx.strokeStyle = 'rgba(200, 30, 30, 0.35)';
            ctx.lineWidth = 1;
            const step = 8;
            for (let i = -dh; i < dw + dh; i += step) {
                ctx.moveTo(dx + i, dy);
                ctx.lineTo(dx + i + dh, dy + dh);
            }
            ctx.stroke();
            ctx.restore();
        });
    }

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
        if (p.ist_fuellteil) drawFillerHatch(ctx, px, py, pw, ph);

        ctx.strokeStyle = 'rgba(0,0,0,0.3)';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(px, py, pw, ph);

        // Beschriftung: Teilname, darunter die Maße (wie bei den Stangen)
        const fontSize = Math.max(9, Math.min(14, Math.min(pw, ph) / 4));
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const fits = (txt, font) => { ctx.font = font; return ctx.measureText(txt).width < pw - 4; };
        const nameFont = `bold ${fontSize}px -apple-system, sans-serif`;
        const dimFont = `${Math.max(8, fontSize - 2)}px -apple-system, sans-serif`;
        let name = p.teil_label;
        if (!fits(name, nameFont)) name = p.teil_label.split(' → ')[0];
        const dims = `${formatDim(Math.round(p.laenge))} × ${formatDim(Math.round(p.breite))}`;
        const showName = fits(name, nameFont) && fontSize < ph - 4;
        const showDims = showName && fits(dims, dimFont) && fontSize * 2.4 < ph - 4;
        const shadowText = (txt, font, y) => {
            ctx.font = font;
            ctx.fillStyle = 'rgba(0,0,0,0.4)';
            ctx.fillText(txt, px + pw / 2 + 1, y + 1);
            ctx.fillStyle = '#fff';
            ctx.fillText(txt, px + pw / 2, y);
        };
        const cy = py + ph / 2;
        if (showDims) {
            shadowText(name, nameFont, cy - fontSize * 0.6);
            shadowText(dims, dimFont, cy + fontSize * 0.65);
        } else if (showName) {
            shadowText(name, nameFont, cy);
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
    ctx.fillText(formatDim(plan.lager_laenge + 2 * besaeumung), offsetX + stockW / 2, offsetY + stockH + 6);

    ctx.save();
    ctx.translate(offsetX - 6, offsetY + stockH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText(formatDim(plan.lager_breite + 2 * besaeumung), 0, 0);
    ctx.restore();
}

function draw1D(ctx, canvasW, canvasH, plan, colorMap, hits, besaeumung = 0) {
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

    // Defects (red hatched areas)
    if (plan.defekte?.length) {
        plan.defekte.forEach(d => {
            const dx = padding.left + d.position * scale;
            const dw = d.laenge * scale;
            ctx.save();
            ctx.fillStyle = 'rgba(200, 30, 30, 0.15)';
            ctx.fillRect(dx, barY, dw, barH);
            ctx.strokeStyle = 'rgba(200, 30, 30, 0.6)';
            ctx.lineWidth = 1;
            ctx.strokeRect(dx, barY, dw, barH);
            ctx.beginPath();
            ctx.rect(dx, barY, dw, barH);
            ctx.clip();
            ctx.strokeStyle = 'rgba(200, 30, 30, 0.35)';
            ctx.lineWidth = 1;
            const step = 8;
            for (let i = -barH; i < dw + barH; i += step) {
                ctx.moveTo(dx + i, barY);
                ctx.lineTo(dx + i + barH, barY + barH);
            }
            ctx.stroke();
            ctx.restore();
        });
    }

    // Parts
    plan.platzierungen.forEach(p => {
        const px = padding.left + p.x * scale;
        const pw = p.laenge * scale;

        ctx.fillStyle = colorMap[p.teil_label] || PART_COLORS[0];
        ctx.fillRect(px, barY, pw, barH);
        if (p.ist_fuellteil) drawFillerHatch(ctx, px, barY, pw, barH);

        ctx.strokeStyle = 'rgba(0,0,0,0.3)';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(px, barY, pw, barH);

        // Name und Länge des Teils; passt der Name nicht, ohne Projekt, sonst nur die Länge
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const text = (str, y, bold) => {
            ctx.font = `${bold ? 'bold ' : ''}12px -apple-system, sans-serif`;
            ctx.fillStyle = 'rgba(0,0,0,0.4)';
            ctx.fillText(str, px + pw / 2 + 0.5, y + 0.5);
            ctx.fillStyle = '#fff';
            ctx.fillText(str, px + pw / 2, y);
        };
        const fits = (str, bold) => {
            ctx.font = `${bold ? 'bold ' : ''}12px -apple-system, sans-serif`;
            return ctx.measureText(str).width < pw - 6;
        };
        const name = [p.teil_label, p.teil_label.split(' → ')[0]].find(n => fits(n, true));
        const len = String(toDisplay(p.laenge));
        const lenFits = fits(len, false);
        const mid = barY + barH / 2;
        if (name && lenFits) { text(name, mid - 8, true); text(len, mid + 9, false); }
        else if (name) text(name, mid, true);
        else if (lenFits) text(len, mid, false);

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

    // Rest areas: [length, x] – one per segment next to a defect
    plan.reste.forEach(rest => {
        if (rest.length >= 1 && rest[0] > 0) {
            const restLen = rest[0];
            const rx = padding.left + (rest[1] ?? plan.lager_laenge - restLen) * scale;
            const rw = restLen * scale;
            ctx.fillStyle = 'rgba(128,128,128,0.2)';
            ctx.fillRect(rx, barY, rw, barH);
            ctx.strokeStyle = 'rgba(0,0,0,0.15)';
            ctx.setLineDash([4, 2]);
            ctx.strokeRect(rx, barY, rw, barH);
            ctx.setLineDash([]);

            const restText = formatDim(Math.round(restLen));
            ctx.font = '10px -apple-system, sans-serif';
            const rTextW = ctx.measureText(restText).width;
            if (rTextW < rw - 4) {
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillStyle = 'rgba(0,0,0,0.5)';
                ctx.fillText(restText, rx + rw / 2, barY + barH / 2);
            } else {
                ctx.textAlign = 'right';
                ctx.textBaseline = 'bottom';
                ctx.fillStyle = getComputedStyle(document.documentElement)
                    .getPropertyValue('--sapContent_LabelColor').trim() || '#6b7280';
                ctx.fillText(restText, rx + rw, barY - 2);
            }
        }
    });

    // Anreißmaße: Schnittstellen ab dem echten Stangenanfang (Ende jedes Teils plus
    // Besäumung), dazu 0 und die volle Länge. Gezeichnet wird die besäumte Stange.
    const labelColor = getComputedStyle(document.documentElement)
        .getPropertyValue('--sapContent_LabelColor').trim() || '#6b7280';
    ctx.fillStyle = labelColor;
    ctx.strokeStyle = labelColor;
    ctx.lineWidth = 1;
    ctx.font = '11px -apple-system, sans-serif';
    ctx.textBaseline = 'top';
    const marks = [...new Set([0, ...plan.platzierungen.map(p => Math.round(p.x + p.laenge + besaeumung)),
                               Math.round(plan.lager_laenge + 2 * besaeumung)])].sort((a, b) => a - b);
    let frei = -Infinity;   // rechter Rand der zuletzt geschriebenen Zahl
    marks.forEach((m, k) => {
        const mx = padding.left + Math.min(Math.max(m - besaeumung, 0), plan.lager_laenge) * scale;
        ctx.beginPath();
        ctx.moveTo(mx, barY + barH);
        ctx.lineTo(mx, barY + barH + 4);
        ctx.stroke();
        const txt = String(toDisplay(m));
        const w = ctx.measureText(txt).width;
        const last = k === marks.length - 1;
        ctx.textAlign = k === 0 ? 'left' : last ? 'right' : 'center';
        const left = k === 0 ? mx : last ? mx - w : mx - w / 2;
        if (left < frei + 6) return;   // überlappt die vorige Zahl
        ctx.fillText(txt, mx, barY + barH + 6);
        frei = left + w;
    });
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
    saveBtn.textContent = t('btn.save');
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
            } else if (f.type === 'checkbox') {
                val = el.checked;
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
    } else if (f.type === 'checkbox') {
        input = `<input type="checkbox" name="${f.key}" class="cs-checkbox"${val ? ' checked' : ''}>`;
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

// Schließt nur, wenn Drücken UND Loslassen auf dem Hintergrund passieren.
// Sonst schließt ein Markieren im Dialog, das außerhalb endet, den Dialog.
function onBackdropClick(el, fn) {
    if (!el) return;
    let downOnBackdrop = false;
    el.addEventListener('mousedown', (e) => { downOnBackdrop = e.target === el; });
    el.addEventListener('click', (e) => {
        if (downOnBackdrop && e.target === el) fn();
        downOnBackdrop = false;
    });
}

function closeModal() {
    const overlay = document.getElementById('modal-overlay');
    overlay.classList.remove('active');
    overlay.classList.add('hidden');
    document.getElementById('modal-body').innerHTML = '';
    document.getElementById('modal-save').onclick = null;
    document.getElementById('modal-cancel').textContent = t('btn.cancel');
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
        { key: 'kuerzel', label: t('mat.code'), type: 'text', placeholder: t('mat.code_hint') },
        { key: 'lagerort', label: t('mat.location'), type: 'text', placeholder: t('mat.location_hint') },
        { key: 'lagerort_reste', label: t('mat.location_rest'), type: 'text', placeholder: t('mat.location_rest_hint') },
    ];

    openModal(title, fields, data, async (formData) => {
        try {
            let mat;
            if (isEdit) {
                mat = await Api.updateMaterial(material.id, formData);
            } else {
                mat = await Api.createMaterial(formData);
            }
            const mid = isEdit ? material.id : mat?.id;
            if (mid && _matImgPendingFile) {
                try { await Api.uploadMaterialImage(mid, _matImgPendingFile); } catch { /* ignore */ }
            }
            if (mid && _matImgPendingDelete) {
                try { await Api.deleteMaterialImage(mid); } catch { /* ignore */ }
            }
            _matImgPendingFile = null;
            _matImgPendingDelete = false;
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

    // Image upload section
    _matImgPendingFile = null;
    _matImgPendingDelete = false;
    const imgSection = document.createElement('div');
    imgSection.className = 'form-group mat-img-upload';
    imgSection.innerHTML = `<label class="fd-form-label">${t('mat.image')}</label>
        <div class="mat-img-preview-wrap"></div>
        <div class="mat-img-actions">
            <button type="button" class="fd-button fd-button--compact mat-img-choose">${isEdit && data.hat_bild ? t('mat.image.change') : t('mat.image.upload')}</button>
            ${isEdit && data.hat_bild ? `<button type="button" class="fd-button fd-button--compact fd-button--negative mat-img-remove">${t('mat.image.remove')}</button>` : ''}
        </div>
        <input type="file" accept="image/*" style="display:none" class="mat-img-input">`;
    document.getElementById('modal-body').appendChild(imgSection);

    const previewWrap = imgSection.querySelector('.mat-img-preview-wrap');
    if (isEdit && data.hat_bild) {
        previewWrap.innerHTML = `<img class="mat-img-preview" src="${Api.materialImageUrl(material.id)}">`;
    }

    const fileInput = imgSection.querySelector('.mat-img-input');
    imgSection.querySelector('.mat-img-choose').addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
        if (!fileInput.files.length) return;
        _matImgPendingFile = fileInput.files[0];
        _matImgPendingDelete = false;
        const url = URL.createObjectURL(_matImgPendingFile);
        previewWrap.innerHTML = `<img class="mat-img-preview" src="${url}">`;
        const rmBtn = imgSection.querySelector('.mat-img-remove');
        if (!rmBtn) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'fd-button fd-button--compact fd-button--negative mat-img-remove';
            btn.textContent = t('mat.image.remove');
            btn.addEventListener('click', removeImg);
            imgSection.querySelector('.mat-img-actions').appendChild(btn);
        }
    });

    function removeImg() {
        _matImgPendingFile = null;
        _matImgPendingDelete = true;
        previewWrap.innerHTML = '';
        const rmBtn = imgSection.querySelector('.mat-img-remove');
        if (rmBtn) rmBtn.remove();
        imgSection.querySelector('.mat-img-choose').textContent = t('mat.image.upload');
    }

    const rmBtn = imgSection.querySelector('.mat-img-remove');
    if (rmBtn) rmBtn.addEventListener('click', removeImg);
}
let _matImgPendingFile = null;
let _matImgPendingDelete = false;

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
        { key: 'ist_rest', label: t('stock.is_rest'), type: 'checkbox' },
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

async function openDefectListDialog(stockId) {
    const stock = State.stock.find(s => s.id === stockId);
    if (!stock) return;
    const mat = getSelectedMaterial();
    const isPlatte = mat?.typ === 'Platte';

    let pieces = [];
    let defects = [];
    try {
        pieces = await Api.getPieces(stockId);
        defects = await Api.getDefects(stockId);
    } catch { return; }

    const overlay = document.getElementById('modal-overlay');
    const titleEl = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    const saveBtn = document.getElementById('modal-save');
    const cancelBtn = document.getElementById('modal-cancel');

    titleEl.textContent = `${t('defect.title')} — ${formatDim(stock.laenge)}${isPlatte ? ' × ' + formatDim(stock.breite) : ''}`;
    saveBtn.textContent = t('defect.new');
    saveBtn.style.display = '';

    const renderList = () => {
        if (defects.length === 0) {
            body.innerHTML = `<p class="empty-state">${t('defect.empty')}</p>`;
        } else {
            const widthCol = isPlatte ? `<th class="fd-table__cell">${t('defect.position_y')}</th>
                <th class="fd-table__cell">${t('defect.width')}</th>` : '';
            const rows = defects.map(d => {
                const widthCells = isPlatte
                    ? `<td class="fd-table__cell num">${formatDim(d.position_y)}</td>
                       <td class="fd-table__cell num">${formatDim(d.breite)}</td>` : '';
                return `<tr class="fd-table__row" data-defect-id="${d.id}">
                    <td class="fd-table__cell num">${escHtml(pieceCode(getSelectedMaterial(), d.stueck_nr))}</td>
                    <td class="fd-table__cell num">${formatDim(d.position)}</td>
                    <td class="fd-table__cell num">${formatDim(d.laenge)}</td>
                    ${widthCells}
                    <td class="fd-table__cell">
                        <button class="fd-button fd-button--compact defect-edit-btn" data-id="${d.id}">${t('btn.edit')}</button>
                        <button class="fd-button fd-button--compact fd-button--negative defect-del-btn" data-id="${d.id}">${t('btn.delete')}</button>
                    </td>
                </tr>`;
            }).join('');
            body.innerHTML = `<table class="fd-table"><thead class="fd-table__header"><tr class="fd-table__row">
                <th class="fd-table__cell">${t('piece.nr')}</th>
                <th class="fd-table__cell">${t('defect.position')}</th>
                <th class="fd-table__cell">${t('defect.length')}</th>
                ${widthCol}
                <th class="fd-table__cell"></th>
            </tr></thead><tbody class="fd-table__body">${rows}</tbody></table>`;

            body.querySelectorAll('.defect-edit-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const d = defects.find(x => x.id === parseInt(btn.dataset.id));
                    if (d) {
                        overlay.classList.remove('active');
                        openDefectDialog(stockId, isPlatte, pieces, d, async () => {
                            defects = await Api.getDefects(stockId);
                            await renderStock();
                            openDefectListDialog(stockId);
                        });
                    }
                });
            });
            body.querySelectorAll('.defect-del-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        await Api.deleteDefect(parseInt(btn.dataset.id));
                        defects = await Api.getDefects(stockId);
                        renderList();
                        await renderStock();
                    } catch { /* handled */ }
                });
            });
        }
    };

    renderList();

    saveBtn.onclick = () => {
        overlay.classList.remove('active');
        openDefectDialog(stockId, isPlatte, pieces, null, async () => {
            defects = await Api.getDefects(stockId);
            await renderStock();
            openDefectListDialog(stockId);
        });
    };
    cancelBtn.onclick = () => overlay.classList.remove('active');

    overlay.classList.remove('hidden');
    overlay.classList.add('active');
}

function openDefectDialog(stockId, isPlatte, pieces, defect, onDone) {
    const isEdit = !!defect;
    const title = isEdit ? t('defect.edit') : t('defect.new');
    const data = defect
        ? { ...defect, _piece_id: defect.einzelstueck_id }
        : { position: 0, position_y: 0, laenge: 0, breite: 0, _piece_id: pieces[0]?.id || 0 };

    const pieceOptions = pieces.map(p => ({
        value: String(p.id),
        text: `${p.code || '#' + p.nr}${p.notiz ? ' – ' + p.notiz : ''}`,
    }));

    const fields = [
        { key: '_piece_id', label: t('piece.nr'), type: 'select', options: pieceOptions, required: true },
        { key: 'position', label: t('defect.position'), type: 'number', required: true, isDimension: true, min: 0 },
        { key: 'position_y', label: t('defect.position_y'), type: 'number', isDimension: true, hidden: !isPlatte, min: 0 },
        { key: 'laenge', label: t('defect.length'), type: 'number', required: true, isDimension: true, min: 0.1 },
        { key: 'breite', label: t('defect.width'), type: 'number', isDimension: true, hidden: !isPlatte, min: 0.1 },
    ];

    openModal(title, fields, data, async (formData) => {
        if (!isPlatte) { formData.position_y = 0; formData.breite = 0; }
        const pieceId = parseInt(formData._piece_id);
        delete formData._piece_id;
        try {
            if (isEdit) {
                await Api.updateDefect(defect.id, formData);
            } else {
                await Api.createDefect(pieceId, formData);
            }
            if (onDone) await onDone();
        } catch { /* handled */ }
    });
}

function openProjectDialog(project = null) {
    const isEdit = !!project;
    const title = isEdit ? t('proj.edit') : t('proj.new');
    const data = project ? { ...project } : { anzahl: 1 };

    const fields = [
        { key: 'name', label: t('proj.name'), type: 'text', required: true },
        { key: 'anzahl', label: t('proj.copies'), type: 'number', min: 1, step: 1, required: true },
    ];

    openModal(title, fields, data, async (formData) => {
        formData.anzahl = Math.max(1, parseInt(formData.anzahl) || 1);
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

    const ver = State.versionInfo ? State.versionInfo.version : '';
    const data = { version: ver, project: proj.name, copies: proj.anzahl || 1, parts };
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

// Projekt aus JSON importieren – fehlende Materialien automatisch anlegen
async function importProject(file) {
    let data;
    try {
        data = JSON.parse(await file.text());
    } catch {
        showToast(t('error.pdf_failed'), 'error');
        return;
    }

    if (data.version) {
        const cur = State.versionInfo ? State.versionInfo.version : '';
        if (cur && data.version > cur) {
            showToast(t('proj.import_version_newer', { v: data.version }), 'warning');
        }
    }

    const matByName = new Map(State.materials.map(m => [m.name, m]));

    let project;
    try {
        project = await Api.createProject({
            name: data.project || 'Import',
            anzahl: Math.max(1, parseInt(data.copies) || 1),
        });
    } catch { return; }

    let imported = 0;
    const created = [];
    for (const p of (data.parts || [])) {
        let mat = matByName.get(p.material || '');
        if (!mat && p.material) {
            try {
                const typ = p.type === 'Stange' ? 'Stange' : 'Platte';
                mat = await Api.createMaterial({
                    name: p.material,
                    typ,
                    maserung: p.grain || 'keine',
                });
                matByName.set(p.material, mat);
                State.materials.push(mat);
                created.push(p.material);
            } catch { /* skip */ }
        }
        if (!mat) continue;
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
    State.materials = await Api.getMaterials();
    renderOptDropdowns();
    renderMaterials();

    let msg = t('proj.import_done', { n: imported });
    if (created.length > 0) {
        msg += ' ' + t('proj.import_materials_created', { materials: created.join(', ') });
    }
    showToast(msg, 'info');
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

function openTrapezoidHelper() {
    if (!State.selectedProjectId) {
        showToast(t('dlg.select_project'), 'error');
        return;
    }
    const platteMats = State.materials.filter(m => m.typ === 'Platte');
    if (!platteMats.length) {
        showToast(t('mat.empty'), 'error');
        return;
    }

    const title = t('trap.title');
    const data = {
        prefix: 'Stufe',
        material_id: platteMats[0]?.id,
        edge: '',
        depth_left: '',
        depth_right: '',
        offset: 0,
        count: 1,
        maserung: 'egal',
    };

    const fields = [
        { key: 'prefix', label: t('trap.prefix'), type: 'text', required: true },
        {
            key: 'material_id', label: t('opt.material'), type: 'select',
            options: platteMats.map(m => ({ value: m.id, text: m.name })),
        },
        {
            key: 'maserung', label: t('mat.grain'), type: 'select',
            options: [
                { value: 'egal', text: t('part.grain.any') },
                { value: 'längs', text: t('part.grain.long') },
                { value: 'quer', text: t('part.grain.cross') },
            ]
        },
        { key: 'edge', label: t('trap.edge'), type: 'number', required: true, isDimension: true, min: 1 },
        { key: 'depth_left', label: t('trap.depth_left'), type: 'number', required: true, isDimension: true, min: 1 },
        { key: 'depth_right', label: t('trap.depth_right'), type: 'number', required: true, isDimension: true, min: 1 },
        { key: 'offset', label: t('trap.offset'), type: 'number', isDimension: true, min: 0, default: 0 },
        { key: 'count', label: t('stock.qty'), type: 'number', required: true, min: 1, step: 1 },
    ];

    openModal(title, fields, data, async (formData) => {
        const edgeMm = formData.edge;
        const dL = formData.depth_left;
        const dR = formData.depth_right;
        const offMm = formData.offset || 0;

        const rectW = edgeMm;
        const rectH = Math.max(dL, dR) + offMm;
        const count = parseInt(formData.count) || 1;

        for (let i = 1; i <= count; i++) {
            const partData = {
                label: count === 1 ? formData.prefix : `${formData.prefix} ${i}`,
                typ: 'Platte',
                material_id: parseInt(formData.material_id),
                laenge: rectW,
                breite: rectH,
                stueckzahl: 1,
                gesaegt_anzahl: 0,
                maserung: formData.maserung,
            };
            try {
                await Api.createPart(State.selectedProjectId, partData);
            } catch { /* handled */ }
        }
        showToast(t('trap.created', { n: count }));
        await renderParts();
        State.projects = await Api.getProjects();
        renderOptDropdowns();
    });

    // Live preview of calculated rectangle
    const body = document.getElementById('modal-body');
    const previewDiv = document.createElement('div');
    previewDiv.id = 'trap-preview';
    previewDiv.style.cssText = 'margin-top:1rem;padding:0.75rem;border-radius:8px;background:var(--sapBackgroundColor,#f5f6f7);text-align:center;';
    body.appendChild(previewDiv);

    const updatePreview = () => {
        const edgeEl = body.querySelector('[name="edge"]');
        const dLEl = body.querySelector('[name="depth_left"]');
        const dREl = body.querySelector('[name="depth_right"]');
        const offEl = body.querySelector('[name="offset"]');
        const edge = parseFloat(edgeEl?.value) || 0;
        const dL = parseFloat(dLEl?.value) || 0;
        const dR = parseFloat(dREl?.value) || 0;
        const off = parseFloat(offEl?.value) || 0;

        if (!edge || (!dL && !dR)) {
            previewDiv.innerHTML = '';
            return;
        }

        const maxD = Math.max(dL, dR);
        const rectW = edge;
        const rectH = maxD + off;

        // SVG preview
        const svgW = 240, svgH = 140, pad = 20;
        const drawW = svgW - 2 * pad, drawH = svgH - 2 * pad;
        const scale = Math.min(drawW / rectW, drawH / rectH);
        const w = rectW * scale, h = rectH * scale;
        const ox = (svgW - w) / 2, oy = (svgH - h) / 2;

        // Trapezoid corners inside bounding rect
        const tL = dL / rectH * h;
        const tR = dR / rectH * h;

        const dimText = t('trap.result_dim', { w: toDisplay(rectW * (toMm(1) || 1)), h: toDisplay(rectH * (toMm(1) || 1)), unit: unitLabel() });
        // We work in display units already since edge/dL/dR are in display units from the input
        const dimTextSimple = `${t('trap.result_dim', { w: edge, h: +(maxD + off).toFixed(1), unit: unitLabel() })}`;

        previewDiv.innerHTML = `
            <svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}">
                <rect x="${ox}" y="${oy}" width="${w}" height="${h}"
                      fill="none" stroke="var(--sapNeutralBorderColor,#89919a)" stroke-width="1.5" stroke-dasharray="6 3"/>
                <polygon points="${ox},${oy + h - tL} ${ox + w},${oy + h - tR} ${ox + w},${oy + h} ${ox},${oy + h}"
                         fill="var(--sapAccentColor6,#ed884a)" fill-opacity="0.3"
                         stroke="var(--sapAccentColor6,#ed884a)" stroke-width="2"/>
            </svg>
            <div style="font-weight:600;margin-top:0.25rem;">${escHtml(dimTextSimple)}</div>`;
    };

    ['edge', 'depth_left', 'depth_right', 'offset'].forEach(name => {
        const el = body.querySelector(`[name="${name}"]`);
        if (el) el.addEventListener('input', updatePreview);
    });
    updatePreview();
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

// Bestätigungsdialog als Promise: true bei „Bestätigen“, false bei „Abbrechen“.
function confirmAsync(message) {
    return new Promise(resolve => {
        openConfirmDialog(message, () => resolve(true));
        const cancelBtn = document.getElementById('modal-cancel');
        const handler = cancelBtn.onclick;
        cancelBtn.onclick = (e) => { if (handler) handler(e); resolve(false); };
    });
}

function openConfirmDialog(message, onConfirm) {
    const overlay = document.getElementById('modal-overlay');
    const titleEl = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    const saveBtn = document.getElementById('modal-save');

    titleEl.textContent = t('btn.confirm');
    body.innerHTML = `<p style="padding:8px 0;white-space:pre-line">${escHtml(message)}</p>`;
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

function openCopyPartsDialog() {
    const overlay = document.getElementById('modal-overlay');
    const titleEl = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');
    const saveBtn = document.getElementById('modal-save');

    const selectedPart = State.parts.find(p => p.id === State.selectedPartId);
    const targets = State.projects.filter(p => p.id !== State.selectedProjectId);

    if (targets.length === 0) {
        showToast(t('part.no_target'), 'error');
        return;
    }

    titleEl.textContent = t('part.copy_to');
    const optionsHtml = targets.map(p => `<option value="${p.id}">${escHtml(p.name)}</option>`).join('');
    body.innerHTML = `
        <div style="display:flex;flex-direction:column;gap:12px;padding:8px 0">
            <div>
                <label class="fd-form-label">${t('part.copy_mode')}</label>
                <select id="copy-mode" class="fd-select" style="width:100%">
                    <option value="selected">${t('part.copy_selected')}</option>
                    <option value="all">${t('part.copy_all')}</option>
                </select>
            </div>
            <div>
                <label class="fd-form-label">${t('part.target_project')}</label>
                <select id="copy-target" class="fd-select" style="width:100%">${optionsHtml}</select>
            </div>
        </div>`;

    const modeSelect = body.querySelector('#copy-mode');
    if (!selectedPart) modeSelect.value = 'all';

    saveBtn.style.display = '';
    saveBtn.textContent = t('part.copy_btn');
    overlay.classList.remove('hidden');
    overlay.classList.add('active');

    saveBtn.onclick = async () => {
        const targetId = parseInt(body.querySelector('#copy-target').value);
        const mode = body.querySelector('#copy-mode').value;
        const ids = mode === 'all'
            ? State.parts.map(p => p.id)
            : [State.selectedPartId];
        closeModal();
        saveBtn.textContent = t('btn.save');
        try {
            await Api.copyPartsToProject(targetId, ids);
            showToast(t('part.copied'), 'success');
        } catch { /* handled */ }
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
        let leftFr = parseFloat(storageGet('localStorage', key));
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
            storageSet('localStorage', key, String(leftFr));
        };
        splitter.addEventListener('pointerup', end);
        splitter.addEventListener('pointercancel', end);
    });
}

function initEvents() {
    setupSplitters();

    // ----- Quit (Desktop only) -----
    document.getElementById('btn-quit')?.addEventListener('click', () => {
        openConfirmDialog(t('app.quit_confirm'), async () => {
            try {
                await fetchJSON('/api/shutdown', 'POST');
            } catch { /* server already stopping */ }
            document.body.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:var(--sapTextColor)"><h2>${t('app.quit_done')}</h2></div>`;
            setTimeout(() => window.close(), 1000);
        });
    });

    // ----- Tab switching -----
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            // Tabs sind <a href="#">: Link-Navigation unterdrücken (manche Browser
            // laden die Seite sonst neu und landen wieder auf dem ersten Tab)
            e.preventDefault();
            document.querySelectorAll('.tab-btn').forEach(b => {
                b.classList.remove('active');
                b.setAttribute('aria-selected', 'false');
            });
            document.querySelectorAll('.tab-content').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            btn.setAttribute('aria-selected', 'true');
            const tabId = btn.dataset.tab;
            storageSet('sessionStorage', 'cutstock_tab', tabId);
            const panel = document.getElementById(`tab-${tabId}`);
            if (panel) panel.classList.add('active');

            if (tabId === 'material') { renderMaterials(); }
            else if (tabId === 'projects') { renderProjects(); }
            else if (tabId === 'parts') { renderAllParts(); }
            else if (tabId === 'optimization') { renderOptDropdowns(); }
            else if (tabId === 'settings') { renderSettings(); renderBlades(); renderLicense(); }
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
    document.getElementById('btn-mat-del')?.addEventListener('click', async () => {
        const mat = getSelectedMaterial();
        if (!mat) { showToast(t('dlg.select_material'), 'error'); return; }
        let stock;
        try { stock = await Api.getStock(mat.id); } catch { return; }
        const n = stock.reduce((sum, s) => sum + s.stueckzahl, 0);
        openConfirmDialog(t('dlg.delete_material', { n }), async () => {
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

    document.getElementById('btn-stock-defects')?.addEventListener('click', () => {
        if (!State.selectedStockId) { showToast(t('defect.select_stock'), 'error'); return; }
        openDefectListDialog(State.selectedStockId);
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

    document.getElementById('btn-proj-clone')?.addEventListener('click', async () => {
        const proj = State.projects.find(p => p.id === State.selectedProjectId);
        if (!proj) { showToast(t('dlg.select_project'), 'error'); return; }
        try {
            const cloned = await Api.cloneProject(proj.id);
            State.selectedProjectId = cloned.id;
            await renderProjects();
            renderOptDropdowns();
            showToast(t('proj.cloned'), 'success');
        } catch { /* handled */ }
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

    // ----- Trapez-Helfer -----
    document.getElementById('btn-part-trapez')?.addEventListener('click', () => openTrapezoidHelper());

    // ----- Teile kopieren -----
    document.getElementById('btn-part-copy')?.addEventListener('click', () => {
        if (!State.selectedProjectId) { showToast(t('dlg.select_project'), 'error'); return; }
        if (State.parts.length === 0) { showToast(t('parts.empty'), 'error'); return; }
        openCopyPartsDialog();
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
        if (State.optMode === 'material') {
            const btn = document.getElementById('btn-optimize');
            btn.disabled = true;
            btn.textContent = '...';
            try {
                await optimizeSammel();
                try { State.projects = await Api.getProjects(); renderProjects(); } catch { /* ignore */ }
            } catch {
                await loadSavedPlan();
            } finally {
                btn.disabled = false;
                btn.textContent = t('opt.run');
            }
            return;
        }
        const projId = parseInt(document.getElementById('opt-project')?.value);
        const matId = parseInt(document.getElementById('opt-material')?.value);
        const bladeId = parseInt(document.getElementById('opt-blade')?.value);
        const algo = document.getElementById('opt-algorithm')?.value || 'greedy';

        if (!projId || !matId || !bladeId) {
            showToast(t('dlg.select_all'), 'error');
            return;
        }

        // Angefangener Plan: angefangene Bretter bleiben, der Rest wird neu verteilt
        const cur = State.optimizationResult;
        const started = cur?.plan_id && String(cur.projekt_id) === String(projId) &&
            cur.material_id === matId && (cur.schnittplaene || []).some(p => p.verbraucht);
        if (started && !(await confirmAsync(t('plan.reoptimize_started')))) return;

        const btn = document.getElementById('btn-optimize');
        btn.disabled = true;
        btn.textContent = '...';

        try {
            adoptPlan(await Api.optimize({
                project_id: projId,
                material_id: matId,
                blade_id: bladeId,
                algorithm: algo,
                reste_zuerst: !!document.getElementById('opt-rests-first')?.checked,
                ...fillRequest(projId, matId),
            }));
            renderOptResults();
            try { State.projects = await Api.getProjects(); renderProjects(); } catch { /* ignore */ }
        } catch {
            // Gespeicherten Stand wieder anzeigen (z.B. keine offenen Teile mehr)
            await loadSavedPlan();
        } finally {
            btn.disabled = false;
            btn.textContent = t('opt.run');
        }
    });

    document.getElementById('btn-confirm')?.addEventListener('click', () => {
        if (!State.optimizationResult) return;
        openConfirmDialog(t('opt.confirm_msg'), () => confirmAllPieces());
    });

    document.getElementById('btn-fill')?.addEventListener('click', () => openFillDialog());
    ['opt-project', 'opt-material'].forEach(id =>
        document.getElementById(id)?.addEventListener('change', () => updateFillButton()));

    document.getElementById('btn-discard-plan')?.addEventListener('click', () => {
        if (!State.optimizationResult) return;
        openConfirmDialog(t('plan.discard_confirm'), () => discardPlan());
    });

    // „Reste zuerst“ merken (pro Browser)
    const restsFirst = document.getElementById('opt-rests-first');
    if (restsFirst) {
        restsFirst.checked = storageGet('localStorage', 'cutstock_rests_first') === '1';
        restsFirst.addEventListener('change', () =>
            storageSet('localStorage', 'cutstock_rests_first', restsFirst.checked ? '1' : '0'));
    }

    // ----- Lager-Einstellungen -----
    document.getElementById('settings-nr-lock')?.addEventListener('change', async (e) => {
        const v = Math.max(0, parseFloat(e.target.value) || 0);
        e.target.value = v;
        State.settings.nr_lock_days = v;
        try { await Api.updateSettings({ nr_lock_days: v }); } catch { /* non-critical */ }
    });
    document.getElementById('settings-reservation')?.addEventListener('change', async (e) => {
        State.settings.reservation = e.target.checked;
        try { await Api.updateSettings({ reservation: e.target.checked }); } catch { /* non-critical */ }
    });

    document.getElementById('btn-restart')?.addEventListener('click', () => {
        if (!State.optimizationResult) return;
        openConfirmDialog(t('plan.restart_confirm'), () => restartProject());
    });

    document.getElementById('btn-pdf')?.addEventListener('click', () => {
        if (!State.optimizationResult) return;
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
            projekt_name: optProjName(),
            material_name: mat?.name || '',
            material_id: matId || 0,
            saegeblatt_name: bladeSel?.selectedOptions[0]?.text || '',
            is_1d: is1D,
            schnittfolgen,
            schnittfolge_titel: t('seq.title'),
            nach_projekt: State.optMode === 'material',
        });
    });

    document.getElementById('opt-mode')?.addEventListener('change', (e) => {
        setOptMode(e.target.value, parseInt(document.getElementById('opt-material')?.value));
    });

    // ----- Optimization project dropdown changes material filter -----
    document.getElementById('opt-project')?.addEventListener('change', () => {
        updateOptMaterialDropdown();
        loadSavedPlan();
    });

    // Anderes Material → dessen gespeicherten Plan zeigen. Sägeblatt/Algorithmus
    // wirken erst beim nächsten Optimieren, der gespeicherte Plan bleibt stehen.
    document.getElementById('opt-material')?.addEventListener('change', () => loadSavedPlan());

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

    // ----- API Settings -----
    document.getElementById('settings-api-enabled')?.addEventListener('change', async (e) => {
        State.settings.api_enabled = e.target.checked;
        updateApiDetailVisibility();
        try { await Api.updateSettings({ api_enabled: e.target.checked }); } catch { /* non-critical */ }
    });
    document.getElementById('settings-api-port')?.addEventListener('change', async (e) => {
        const v = Math.max(1024, Math.min(65535, parseInt(e.target.value) || 8421));
        e.target.value = v;
        State.settings.api_port = v;
        try { await Api.updateSettings({ api_port: v }); } catch { /* non-critical */ }
    });
    document.getElementById('btn-api-key-gen')?.addEventListener('click', async () => {
        const key = Array.from(crypto.getRandomValues(new Uint8Array(24)),
            b => b.toString(16).padStart(2, '0')).join('');
        document.getElementById('settings-api-key').value = key;
        State.settings.api_key = key;
        try { await Api.updateSettings({ api_key: key }); } catch { /* non-critical */ }
        showToast(t('set.api_key_generated'), 'info');
    });
    document.getElementById('btn-api-key-copy')?.addEventListener('click', () => {
        const key = document.getElementById('settings-api-key')?.value;
        if (key) {
            navigator.clipboard.writeText(key).then(
                () => showToast(t('set.api_key_copied'), 'info'),
                () => showToast('Copy failed', 'error'));
        }
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
    onBackdropClick(document.getElementById('zoom-overlay'), () => closePlanZoom());

    // ----- Reiter „Teile“ -----
    ['parts-material', 'parts-project', 'parts-only-open'].forEach(id =>
        document.getElementById(id)?.addEventListener('change', () => renderAllPartsTable()));
    document.getElementById('btn-create-cutlist')?.addEventListener('click', () => createCutList());

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

    // ----- Lizenz -----
    document.getElementById('btn-license-activate')?.addEventListener('click', () => activateLicense());
    document.getElementById('btn-license-remove')?.addEventListener('click', () => removeLicense());

    // ----- Update-Prüfung -----
    document.getElementById('btn-check-update')?.addEventListener('click', () => checkForUpdate());

    // ----- Externe Links im System-Browser öffnen (statt im App-Fenster) -----
    document.addEventListener('click', (e) => {
        const a = e.target.closest('a[target="_blank"]');
        if (a && a.href) { e.preventDefault(); openExternal(a.href); }
    });

    // ----- Modal overlay click to close -----
    onBackdropClick(document.getElementById('modal-overlay'), () => closeModal());

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
        if (e.key >= '1' && e.key <= '5' && !e.ctrlKey && !e.metaKey && !e.altKey) {
            const tabs = ['material', 'projects', 'parts', 'optimization', 'settings'];
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
    if (theme === 'system') {
        document.documentElement.removeAttribute('data-theme');
    } else {
        document.documentElement.setAttribute('data-theme', theme);
    }

    // Horizon-Theme-Stylesheet (hell/dunkel) umschalten
    const dark = theme === 'dark' ||
        (theme === 'system' &&
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
    if (State.settings.theme === 'system') {
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

// Web Storage kann fehlen oder schon beim Zugriff werfen (SecurityError in
// manchen Webviews, blockierte Website-Daten, private Modi). Dann gelten die
// Defaults und es wird nichts gespeichert – aber auch nichts geworfen.
// area: 'localStorage' oder 'sessionStorage'.
function storageGet(area, key) {
    try { return window[area].getItem(key); } catch { return null; }
}

function storageSet(area, key, value) {
    try { window[area].setItem(key, value); return true; } catch { return false; }
}

function storageRemove(area, key) {
    try { window[area].removeItem(key); } catch { /* ignorieren */ }
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

        try {
            const deskResp = await fetchJSON('/api/is-desktop');
            if (deskResp.desktop) document.getElementById('btn-quit').style.display = '';
        } catch { /* not available — hide button */ }

        State.optMode = storageGet('localStorage', 'cutstock_opt_mode') === 'material'
            ? 'material' : 'project';
        initEvents();
        renderMaterials();
        renderSettings();
        renderBlades();
        renderLicense();
        renderProjects();
        renderOptDropdowns();
        autoCheckUpdate();

        // Zuletzt offenen Tab wiederherstellen (überlebt ein Neuladen der Seite)
        const lastTab = storageGet('sessionStorage', 'cutstock_tab');
        if (lastTab && lastTab !== 'material') {
            document.querySelector(`.tab-btn[data-tab="${CSS.escape(lastTab)}"]`)?.click();
        }
    } catch (e) {
        console.error('Init failed:', e);
        showToast('Initialization failed. Is the server running?', 'error');
    }
}

document.addEventListener('DOMContentLoaded', init);
