/**
 * RAS Register Decoder - Application Logic
 * 
 * Loads register data from JSON and provides:
 * - Domain browser (sidebar)
 * - Register search and list
 * - Single register decode (input hex value -> field breakdown)
 * - Bitfield visualization
 * - Batch decode
 */

// =============================================================================
// State
// =============================================================================

let APP = {
    data: null,          // Full register database
    registers: {},       // Register map (name -> definition)
    features: [],        // Sidebar domain list
    currentFeature: '',  // Selected domain filter
    expandedDomains: new Set(),
    currentRegister: null, // Currently selected register for decode
    sortField: 'name',
    sortAsc: true,
    filteredRegs: [],    // Current filtered register list
    platform: 'BHS',
};

const PLATFORM_CONFIG = {
    BHS: { dataPath: 'data/BHS/registers.json' },
    OKS: { dataPath: 'data/OKS/registers.json' },
};

// =============================================================================
// Initialization
// =============================================================================

document.addEventListener('DOMContentLoaded', async () => {
    initTheme();
    APP.platform = getRequestedPlatform();
    document.getElementById('platform-select').value = APP.platform;
    await loadData(APP.platform);
    bindUIEvents();
    renderPlatformUI();
});

function getRequestedPlatform() {
    const requested = new URLSearchParams(window.location.search).get('platform')?.toUpperCase();
    return PLATFORM_CONFIG[requested] ? requested : 'BHS';
}

async function loadData(platform) {
    const config = PLATFORM_CONFIG[platform];
    if (!config) return;

    try {
        const resp = await fetch(`${config.dataPath}?v=${Date.now()}`, { cache: 'no-store' });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        APP.data = await resp.json();
        APP.platform = platform;
        APP.registers = APP.data.registers || {};
        Object.entries(APP.registers).forEach(([key, reg]) => {
            reg.key = key;
        });
        APP.features = buildDomainGroups();
        APP.filteredRegs = Object.values(APP.registers);
        document.querySelector('.platform-badge').textContent = APP.data.metadata?.platform || platform;
        document.title = `RAS Register Decoder - ${APP.data.metadata?.platform || platform}`;
        console.log(`Loaded ${Object.keys(APP.registers).length} ${platform} registers`);
    } catch (e) {
        console.error('Failed to load register data:', e);
        document.querySelector('.content').innerHTML = `
            <div class="loading" style="flex-direction:column;gap:12px;">
                <p style="color:var(--error);font-weight:600;">Failed to load register data</p>
                <p>Make sure <code>${config.dataPath}</code> exists.</p>
                <p style="font-size:0.8rem;">Run the extraction scripts first:<br>
                <code>python extract/extract_ivg_registers.py</code><br>
                <code>python extract/extract_eds_definitions.py</code><br>
                <code>python extract/merge_and_validate.py</code></p>
            </div>`;
    }
}

/**
 * Build sidebar domains from each register's explicit ui_domain.
 * Returns array of { id, name, register_count, domain_ids }
 */
function buildDomainGroups() {
    if (APP.platform !== 'BHS') {
        return buildDataFeatureGroups();
    }

    const DOMAIN_DEFS = [
        {
            id: 'ieh',
            name: 'IEH',
            type: 'parent',
            child_ids: ['ieh-global', 'ieh-satellite'],
            domain_ids: ['ieh-global', 'ieh-satellite'],
        },
        {
            id: 'ieh-global',
            name: 'Global IEH',
            type: 'child',
            parent_id: 'ieh',
            domain_ids: ['ieh-global'],
        },
        {
            id: 'ieh-satellite',
            name: 'Satellite IEH',
            type: 'child',
            parent_id: 'ieh',
            domain_ids: ['ieh-satellite'],
        },
        {
            id: 'memory',
            name: 'Memory',
            domain_ids: ['memory'],
        },
        {
            id: 'mca',
            name: 'MCA',
            domain_ids: ['mca'],
        },
        {
            id: 'pcie',
            name: 'PCIe',
            domain_ids: ['pcie'],
        },
        {
            id: 'upi',
            name: 'UPI',
            domain_ids: ['upi'],
        },
        {
            id: 'platform',
            name: 'Platform',
            domain_ids: ['platform'],
        },
        {
            id: 'general',
            name: 'General',
            domain_ids: ['general'],
        },
    ];

    const domains = [];
    const allRegs = Object.values(APP.registers);

    for (const domainDef of DOMAIN_DEFS) {
        const domainSet = new Set(domainDef.domain_ids);
        const matchingRegs = allRegs.filter(reg =>
            (reg.ui_domains || []).some(domainId => domainSet.has(domainId))
        );
        if (matchingRegs.length > 0) {
            domains.push({
                ...domainDef,
                register_count: matchingRegs.length,
            });
        }
    }

    return domains;
}

function buildDataFeatureGroups() {
    const featureGroups = APP.data.features || [];
    const registerFeatures = new Map(
        Object.values(APP.registers).map(reg => [getRegisterKey(reg), new Set(reg.features || [])])
    );

    return featureGroups.map(feature => ({
        id: feature.id,
        name: feature.name,
        register_count: feature.register_count,
        domain_ids: [feature.id],
        matches: reg => registerFeatures.get(getRegisterKey(reg))?.has(feature.id),
    }));
}

function bindUIEvents() {
    if (!APP.data) return;

    document.getElementById('reg-search').addEventListener('input', onRegSearch);
    document.getElementById('reg-search').addEventListener('focus', onRegSearchFocus);
    document.getElementById('reg-search').addEventListener('keydown', onRegSearchKey);
    document.getElementById('btn-decode').addEventListener('click', onDecode);
    document.getElementById('reg-value').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') onDecode();
    });
    document.getElementById('list-filter').addEventListener('input', onListFilter);
    document.getElementById('feature-filter').addEventListener('change', onFeatureFilterChange);
    document.getElementById('btn-copy-result').addEventListener('click', onCopyResult);
    document.getElementById('btn-close-result').addEventListener('click', closeDecodeResult);
    document.getElementById('theme-toggle').addEventListener('click', toggleTheme);
    document.getElementById('platform-select').addEventListener('change', onPlatformChange);
    
    // Close dropdown on outside click
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.search-wrapper')) {
            document.getElementById('reg-dropdown').classList.remove('show');
        }
    });
    
    // Sortable columns
    document.querySelectorAll('.sortable').forEach(th => {
        th.addEventListener('click', () => onSort(th.dataset.sort));
    });

}

function renderPlatformUI() {
    if (!APP.data) return;

    renderFeatureList();
    renderRegisterList();
    updateTotalCount();

    // Populate domain filter dropdown
    const featureSelect = document.getElementById('feature-filter');
    featureSelect.innerHTML = '<option value="">All Domains</option>';
    APP.features.forEach(f => {
        if (f.type === 'parent') return;
        const opt = document.createElement('option');
        opt.value = f.id;
        opt.textContent = `${f.name} (${f.register_count})`;
        featureSelect.appendChild(opt);
    });
}

async function onPlatformChange(event) {
    const platform = event.target.value;
    if (platform === APP.platform) return;

    APP.currentFeature = '';
    APP.expandedDomains.clear();
    APP.currentRegister = null;
    document.getElementById('reg-search').value = '';
    document.getElementById('reg-value').value = '';
    document.getElementById('list-filter').value = '';
    closeDecodeResult();

    await loadData(platform);
    if (!APP.data) return;

    const params = new URLSearchParams(window.location.search);
    params.set('platform', platform);
    history.replaceState(null, '', `${window.location.pathname}?${params}`);
    renderPlatformUI();
}

// =============================================================================
// Theme
// =============================================================================

function initTheme() {
    const saved = localStorage.getItem('ras-decoder-theme');
    if (saved === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
        document.getElementById('theme-toggle').textContent = '☀️';
    }
}

function toggleTheme() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    if (isDark) {
        document.documentElement.removeAttribute('data-theme');
        document.getElementById('theme-toggle').textContent = '🌙';
        localStorage.setItem('ras-decoder-theme', 'light');
    } else {
        document.documentElement.setAttribute('data-theme', 'dark');
        document.getElementById('theme-toggle').textContent = '☀️';
        localStorage.setItem('ras-decoder-theme', 'dark');
    }
}

// =============================================================================
// Domain Sidebar
// =============================================================================

function renderFeatureList() {
    const container = document.getElementById('feature-list');
    
    // "All" item
    let html = `<div class="feature-item active" data-feature="">
        <span>All Registers</span>
        <span class="count">${Object.keys(APP.registers).length}</span>
    </div>`;
    
    APP.features.forEach(f => {
        if (f.type === 'parent') {
            const expanded = APP.expandedDomains.has(f.id);
            html += `<div class="feature-item feature-parent ${expanded ? 'expanded' : ''}" data-toggle-domain="${f.id}">
                <span class="feature-label"><span class="chevron">›</span>${f.name}</span>
                <span class="count">${f.register_count}</span>
            </div>`;
            return;
        }

        if (f.parent_id && !APP.expandedDomains.has(f.parent_id)) {
            return;
        }

        html += `<div class="feature-item ${f.parent_id ? 'feature-child' : ''}" data-feature="${f.id}">
            <span>${f.name}</span>
            <span class="count">${f.register_count}</span>
        </div>`;
    });
    
    container.innerHTML = html;
    
    // Click handlers
    container.querySelectorAll('.feature-item').forEach(item => {
        item.addEventListener('click', () => {
            const domainToToggle = item.dataset.toggleDomain;
            if (domainToToggle) {
                if (APP.expandedDomains.has(domainToToggle)) {
                    APP.expandedDomains.delete(domainToToggle);
                } else {
                    APP.expandedDomains.add(domainToToggle);
                }
                renderFeatureList();
                return;
            }

            container.querySelectorAll('.feature-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            APP.currentFeature = item.dataset.feature;
            document.getElementById('feature-filter').value = APP.currentFeature;
            filterRegisters();
        });
    });
}

// =============================================================================
// Register List
// =============================================================================

function filterRegisters() {
    const textFilter = document.getElementById('list-filter').value.toLowerCase();
    const featureFilter = APP.currentFeature || document.getElementById('feature-filter').value;
    
    APP.filteredRegs = Object.values(APP.registers).filter(reg => {
        // Domain filter
        if (featureFilter) {
            const domain = APP.features.find(f => f.id === featureFilter);
            if (domain) {
                const matchesDomain = domain.matches
                    ? domain.matches(reg)
                    : (reg.ui_domains || []).some(domainId => domain.domain_ids.includes(domainId));
                if (!matchesDomain) {
                    return false;
                }
            }
        }
        // Text filter
        if (textFilter) {
            const searchStr = `${getRegisterDisplayName(reg)} ${getRegisterKey(reg)} ${reg.address || ''} ${getRegisterDomainLabel(reg)}`.toLowerCase();
            if (!searchStr.includes(textFilter)) return false;
        }
        return true;
    });
    
    // Sort
    APP.filteredRegs.sort((a, b) => {
        let va = a[APP.sortField] || '';
        let vb = b[APP.sortField] || '';
        if (typeof va === 'string') va = va.toLowerCase();
        if (typeof vb === 'string') vb = vb.toLowerCase();
        if (va < vb) return APP.sortAsc ? -1 : 1;
        if (va > vb) return APP.sortAsc ? 1 : -1;
        return 0;
    });
    
    renderRegisterList();
}

function renderRegisterList() {
    const tbody = document.getElementById('register-tbody');
    const regs = APP.filteredRegs;
    
    const displayRegs = regs;
    
    let html = '';
    displayRegs.forEach(reg => {
        const fieldCount = (reg.fields || []).length;
        
        html += `<tr>
            <td><span class="reg-name" data-reg="${getRegisterKey(reg)}">${getRegisterDisplayName(reg)}</span></td>
            <td class="reg-addr">${reg.address || '-'}</td>
            <td>${reg.width || 32}b</td>
            <td>${fieldCount > 0 ? fieldCount : '<span style="color:var(--text-muted)">-</span>'}</td>
            <td><button class="btn-decode-small" data-reg="${getRegisterKey(reg)}">Decode</button></td>
        </tr>`;
    });
    
    tbody.innerHTML = html;
    
    // Status
    const status = document.getElementById('list-status');
    status.textContent = `Showing ${regs.length} registers`;
    
    // Event handlers for decode buttons and register names
    tbody.querySelectorAll('.btn-decode-small').forEach(btn => {
        btn.addEventListener('click', () => selectRegisterForDecode(btn.dataset.reg));
    });
    tbody.querySelectorAll('.reg-name').forEach(el => {
        el.addEventListener('click', () => showRegisterDetail(el.dataset.reg));
    });
}

function onListFilter() {
    filterRegisters();
}

function onFeatureFilterChange() {
    APP.currentFeature = document.getElementById('feature-filter').value;
    const selectedFeature = APP.features.find(f => f.id === APP.currentFeature);
    if (selectedFeature?.parent_id) {
        APP.expandedDomains.add(selectedFeature.parent_id);
        renderFeatureList();
    }
    // Sync sidebar
    document.querySelectorAll('.feature-item').forEach(item => {
        item.classList.toggle('active', item.dataset.feature === APP.currentFeature);
    });
    filterRegisters();
}

function onSort(field) {
    if (APP.sortField === field) {
        APP.sortAsc = !APP.sortAsc;
    } else {
        APP.sortField = field;
        APP.sortAsc = true;
    }
    filterRegisters();
}

function updateTotalCount() {
    document.getElementById('total-count').textContent = 
        `${Object.keys(APP.registers).length} registers`;
}

function getRegisterKey(reg) {
    return reg.key || reg.name;
}

function getRegisterDisplayName(reg) {
    return reg.display_name || reg.name || getRegisterKey(reg);
}

function getRegisterDomainLabel(reg) {
    if (APP.platform !== 'BHS') {
        return (reg.features || []).join(' | ');
    }
    const labels = {
        'ieh-global': 'Global IEH',
        'ieh-satellite': 'Satellite IEH',
        memory: 'Memory',
        mca: 'MCA',
        pcie: 'PCIe',
        upi: 'UPI',
        platform: 'Platform',
        general: 'General',
    };
    return (reg.ui_domains || []).map(domainId => labels[domainId]).filter(Boolean).join(' | ');
}

function domainMatchesCurrentFeature(reg) {
    if (!APP.currentFeature) return false;
    const domain = APP.features.find(f => f.id === APP.currentFeature);
    if (!domain) return false;
    if (domain.matches) return domain.matches(reg);
    return (reg.ui_domains || []).some(domainId => domain.domain_ids.includes(domainId));
}

function findRegister(identifier) {
    if (!identifier) return null;
    if (APP.registers[identifier]) return APP.registers[identifier];

    const lower = identifier.toLowerCase();
    const keyMatch = Object.entries(APP.registers).find(([key]) => key.toLowerCase() === lower);
    if (keyMatch) return keyMatch[1];

    const matches = Object.values(APP.registers).filter(reg =>
        getRegisterDisplayName(reg).toLowerCase() === lower ||
        (reg.name || '').toLowerCase() === lower
    );
    if (matches.length === 0) return null;
    if (matches.length === 1) return matches[0];
    return matches.find(domainMatchesCurrentFeature) || matches[0];
}

// =============================================================================
// Register Search (Decoder)
// =============================================================================

let searchHighlight = -1;

function onRegSearch(e) {
    const query = e.target.value.toLowerCase();
    const dropdown = document.getElementById('reg-dropdown');
    
    if (!query || query.length < 2) {
        dropdown.classList.remove('show');
        return;
    }
    
    // Search registers
    const results = Object.values(APP.registers)
        .filter(r =>
            getRegisterDisplayName(r).toLowerCase().includes(query) ||
            getRegisterKey(r).toLowerCase().includes(query) ||
            (r.address && r.address.toLowerCase().includes(query))
        )
        .slice(0, 20);
    
    if (results.length === 0) {
        dropdown.classList.remove('show');
        return;
    }
    
    dropdown.innerHTML = results.map((r, i) => 
        `<div class="dropdown-item${i === 0 ? ' highlighted' : ''}" data-reg="${getRegisterKey(r)}">
            ${getRegisterDisplayName(r)}<span class="addr">${[getRegisterDomainLabel(r), r.address || ''].filter(Boolean).join(' | ')}</span>
        </div>`
    ).join('');
    
    dropdown.classList.add('show');
    searchHighlight = 0;
    
    // Click handlers
    dropdown.querySelectorAll('.dropdown-item').forEach(item => {
        item.addEventListener('click', () => {
            selectRegisterForDecode(item.dataset.reg);
            dropdown.classList.remove('show');
        });
    });
}

function onRegSearchFocus() {
    const query = document.getElementById('reg-search').value;
    if (query.length >= 2) {
        onRegSearch({ target: { value: query } });
    }
}

function onRegSearchKey(e) {
    const dropdown = document.getElementById('reg-dropdown');
    const items = dropdown.querySelectorAll('.dropdown-item');
    
    if (!dropdown.classList.contains('show') || items.length === 0) return;
    
    if (e.key === 'ArrowDown') {
        e.preventDefault();
        searchHighlight = Math.min(searchHighlight + 1, items.length - 1);
        items.forEach((item, i) => item.classList.toggle('highlighted', i === searchHighlight));
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        searchHighlight = Math.max(searchHighlight - 1, 0);
        items.forEach((item, i) => item.classList.toggle('highlighted', i === searchHighlight));
    } else if (e.key === 'Enter') {
        e.preventDefault();
        if (items[searchHighlight]) {
            selectRegisterForDecode(items[searchHighlight].dataset.reg);
            dropdown.classList.remove('show');
        }
    } else if (e.key === 'Escape') {
        dropdown.classList.remove('show');
    }
}

function showRegisterDetail(regName) {
    const reg = findRegister(regName);
    if (!reg) return;
    
    APP.currentRegister = reg;
    document.getElementById('reg-search').value = getRegisterDisplayName(reg);
    
    // Show detail panel
    const resultDiv = document.getElementById('decode-result');
    resultDiv.style.display = 'block';
    
    document.getElementById('result-reg-name').textContent = getRegisterDisplayName(reg);
    document.getElementById('result-meta').textContent = 
        `${reg.width || 32}-bit | Address: ${reg.address || 'N/A'} | ` +
        `Default: ${reg.default_value || 'N/A'} | Fields: ${(reg.fields || []).length}`;
    
    // Hide bitfield visual for detail view (no value to show)
    document.getElementById('bitfield-visual').innerHTML = '';
    renderEdsReference(reg);
    renderCscriptsCommands(reg);
    
    // Show field table
    renderFieldTable(reg, 0n);
    
    resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function closeDecodeResult() {
    document.getElementById('decode-result').style.display = 'none';
    const cscriptsPanel = document.getElementById('cscripts-command-panel');
    if (cscriptsPanel) cscriptsPanel.style.display = 'none';
}

function selectRegisterForDecode(regName) {
    const reg = findRegister(regName);
    if (!reg) return;
    
    APP.currentRegister = reg;
    document.getElementById('reg-search').value = getRegisterDisplayName(reg);
    document.getElementById('reg-value').focus();
    
    // If there's already a value, decode immediately
    const val = document.getElementById('reg-value').value.trim();
    if (val) onDecode();
}

// =============================================================================
// Decode Logic
// =============================================================================

function onDecode() {
    const regInput = document.getElementById('reg-search').value.trim();
    const valInput = document.getElementById('reg-value').value.trim();
    
    if (!regInput) return;
    
    // Find register
    let reg = findRegister(regInput);
    if (!reg) {
        // Try to find by address
        reg = Object.values(APP.registers).find(r => 
            r.address && r.address.toLowerCase() === regInput.toLowerCase()
        );
    }
    
    if (!reg) {
        alert(`Register "${regInput}" not found.`);
        return;
    }
    
    APP.currentRegister = reg;
    
    // Parse value
    let value = 0n;
    if (valInput) {
        try {
            const cleaned = valInput.replace(/^0x/i, '').replace(/[_\s]/g, '');
            value = BigInt('0x' + cleaned);
        } catch {
            alert(`Invalid hex value: "${valInput}"`);
            return;
        }
    }
    
    // Render decode result
    renderDecodeResult(reg, value);
}

function renderDecodeResult(reg, value) {
    const resultDiv = document.getElementById('decode-result');
    resultDiv.style.display = 'block';
    
    // Header
    document.getElementById('result-reg-name').textContent = getRegisterDisplayName(reg);
    document.getElementById('result-meta').textContent = 
        `${reg.width || 32}-bit | Address: ${reg.address || 'N/A'} | ` +
        `Value: 0x${value.toString(16).toUpperCase().padStart((reg.width || 32) / 4, '0')}`;
    
    // Bitfield visual
    renderBitfieldVisual(reg, value);
    renderEdsReference(reg);
    renderCscriptsCommands(reg);
    
    // Field table
    renderFieldTable(reg, value);
    
    // Scroll to result
    resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function renderBitfieldVisual(reg, value) {
    const container = document.getElementById('bitfield-visual');
    const width = reg.width || 32;
    const fields = reg.fields || [];
    
    // Build bit-to-field map
    const bitFieldMap = {};
    fields.forEach(field => {
        const [high, low] = field.bits;
        for (let i = low; i <= high; i++) {
            bitFieldMap[i] = field;
        }
    });
    
    // Render bits from MSB to LSB (show top 32 bits for 64-bit regs, or all for 32-bit)
    const displayBits = Math.min(width, 32);
    const startBit = width - 1;
    const endBit = width - displayBits;
    
    let html = '';
    for (let bit = startBit; bit >= endBit; bit--) {
        const bitVal = (value >> BigInt(bit)) & 1n;
        const field = bitFieldMap[bit];
        const access = field ? field.access : 'RSVD';
        const isStart = field && field.bits[0] === bit;
        
        html += `<div class="bit-cell${isStart ? ' field-start' : ''}" 
                      data-access="${access}" 
                      title="${field ? field.name + ' [' + field.bits[0] + ':' + field.bits[1] + ']' : 'Reserved'}">
            <div class="bit-num">${bit}</div>
            <div class="bit-val">${bitVal}</div>
        </div>`;
    }
    
    container.innerHTML = html;
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderEdsReference(reg) {
    const panel = document.getElementById('eds-reference-panel');
    const content = document.getElementById('eds-reference-content');
    const rawToggle = document.getElementById('eds-raw-toggle');
    const rawText = document.getElementById('eds-raw-text');
    const edsRefs = reg.eds_refs || [];

    if (!panel || !content || !rawToggle || !rawText) return;

    const primary = edsRefs[0] || {};
    const sectionLine = primary.section_number
        ? `EDS ${escapeHtml(primary.section_number)} - ${escapeHtml(primary.section_title || '')}`
        : Number.isInteger(primary.page)
            ? 'EDS reference'
            : 'No EDS reference available';
    const parentLine = primary.parent_section_number
        ? `Parent: EDS ${escapeHtml(primary.parent_section_number)} - ${escapeHtml(primary.parent_section_title || '')}`
        : '';
    const pageLine = Number.isInteger(primary.page) ? `Page ${primary.page}` : '';
    const description = reg.eds_description || reg.description || (edsRefs.length
        ? ''
        : 'This register does not have a confirmed EDS register-section mapping in the current Web dataset.');

    content.innerHTML = `
        <div class="eds-section-line">${sectionLine}</div>
        ${parentLine ? `<div class="eds-parent-line">${parentLine}</div>` : ''}
        ${pageLine ? `<div class="eds-page-line">${pageLine}</div>` : ''}
        ${description ? `<div class="eds-description">${escapeHtml(description)}</div>` : ''}
    `;

    rawText.textContent = reg.eds_raw_text || '';
    rawText.style.display = 'none';
    rawToggle.style.display = reg.eds_raw_text ? 'inline-flex' : 'none';
    rawToggle.textContent = 'Show EDS raw text';
    rawToggle.onclick = () => {
        const shouldShow = rawText.style.display === 'none';
        rawText.style.display = shouldShow ? 'block' : 'none';
        rawToggle.textContent = shouldShow ? 'Hide EDS raw text' : 'Show EDS raw text';
    };
    panel.style.display = 'block';
}

function renderCscriptsCommands(reg) {
    const panel = document.getElementById('cscripts-command-panel');
    const content = document.getElementById('cscripts-command-content');
    const commands = reg.cscripts_commands || [];

    if (!panel || !content) return;

    if (commands.length === 0) {
        content.innerHTML = '<div class="cscripts-empty">No exact CScripts command mapped for this register yet.</div>';
        panel.style.display = 'block';
        return;
    }

    content.innerHTML = commands.map((command, index) => {
        const title = command.kind === 'msr'
            ? `MSR direct read${command.address ? ` (${escapeHtml(command.address)})` : ''}`
            : `Namednode path${command.address_key ? ` (${escapeHtml(command.address_key)})` : ''}`;
        const commandLines = command.kind === 'msr'
            ? [command.read_command, command.thread_command]
            : [command.read_command, command.show_command];
        const source = command.source ? `<div class="cscripts-source">Source: ${escapeHtml(command.source)}</div>` : '';

        return `
            <div class="cscripts-command-item">
                <div class="cscripts-command-title">${index + 1}. ${title}</div>
                <pre class="cscripts-command-code">${escapeHtml(commandLines.filter(Boolean).join('\n'))}</pre>
                ${source}
            </div>
        `;
    }).join('');
    panel.style.display = 'block';
}

function renderFieldTable(reg, value) {
    const tbody = document.getElementById('field-tbody');
    const fields = reg.fields || [];
    
    if (fields.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:20px;">
            No field definitions available for this register.<br>
            <small>See the EDS Reference above for the extracted register details.</small>
        </td></tr>`;
        return;
    }
    
    // Sort fields by bit position (high to low)
    const sortedFields = [...fields].sort((a, b) => b.bits[0] - a.bits[0]);
    
    // Check if this is an MC STATUS register and get MCA decode info
    let mcaDecode = null;
    if (reg.name && reg.name.match(/^IA32_MC\d+_STATUS$/) && value !== 0n &&
        typeof decodeMCiStatus === 'function') {
        mcaDecode = decodeMCiStatus(reg.name, value);
    }
    
    let html = '';
    sortedFields.forEach(field => {
        const [high, low] = field.bits;
        const bitWidth = high - low + 1;
        const mask = (1n << BigInt(bitWidth)) - 1n;
        const fieldValue = (value >> BigInt(low)) & mask;
        
        const isNonZero = fieldValue !== 0n;
        const accessClass = (field.access || '').toLowerCase().replace('/', '');
        
        // Build description with MCA decode annotation
        let description = field.description || '';
        if (mcaDecode && isNonZero) {
            if (field.name === 'MSCOD' && mcaDecode.mscodDecode) {
                description = `<span class="mca-decode"><strong>⮕ ${mcaDecode.mscodDecode.description}</strong></span>`
                    + `<br><small style="color:var(--text-muted);">[${mcaDecode.mscodDecode.table}] Bank ${mcaDecode.bank} (${mcaDecode.ip})</small>`;
            } else if (field.name === 'MCACOD' && mcaDecode.mcacodDecode) {
                description = `<span class="mca-decode"><strong>⮕ ${mcaDecode.mcacodDecode.description}</strong></span>`
                    + `<br><small style="color:var(--text-muted);">[${mcaDecode.mcacodDecode.table}] Bank ${mcaDecode.bank} (${mcaDecode.ip})</small>`;
            }
        }
        
        html += `<tr>
            <td style="font-family:var(--font-mono);white-space:nowrap;">${high === low ? high : high + ':' + low}</td>
            <td class="field-name">${field.name}</td>
            <td><span class="access-badge ${accessClass}">${field.access || '-'}</span></td>
            <td class="field-value ${isNonZero ? 'nonzero' : ''}">${fieldValue.toString(2).padStart(bitWidth, '0')}b</td>
            <td class="field-value ${isNonZero ? 'nonzero' : ''}" style="font-family:var(--font-mono);">0x${fieldValue.toString(16).toUpperCase()}</td>
            <td>${description}</td>
        </tr>`;
    });
    
    tbody.innerHTML = html;
}

// =============================================================================
// Copy to Clipboard
// =============================================================================

function onCopyResult() {
    if (!APP.currentRegister) return;
    
    const reg = APP.currentRegister;
    const valInput = document.getElementById('reg-value').value.trim();
    let value = 0n;
    if (valInput) {
        const cleaned = valInput.replace(/^0x/i, '').replace(/[_\s]/g, '');
        value = BigInt('0x' + cleaned);
    }
    
    const fields = reg.fields || [];
    const sortedFields = [...fields].sort((a, b) => b.bits[0] - a.bits[0]);
    
    // Check for MCA decode
    let mcaDecode = null;
    if (reg.name && reg.name.match(/^IA32_MC\d+_STATUS$/) && value !== 0n &&
        typeof decodeMCiStatus === 'function') {
        mcaDecode = decodeMCiStatus(reg.name, value);
    }

    let text = `Register: ${getRegisterDisplayName(reg)}\n`;
    text += `Address: ${reg.address || 'N/A'}\n`;
    text += `Width: ${reg.width || 32}-bit\n`;
    text += `Value: 0x${value.toString(16).toUpperCase().padStart((reg.width || 32) / 4, '0')}\n`;
    if (mcaDecode) {
        text += `Bank: ${mcaDecode.bank} (${mcaDecode.ip})\n`;
        if (mcaDecode.mscodDecode) text += `MSCOD Decode: ${mcaDecode.mscodDecode.description} [${mcaDecode.mscodDecode.table}]\n`;
        if (mcaDecode.mcacodDecode) text += `MCACOD Decode: ${mcaDecode.mcacodDecode.description} [${mcaDecode.mcacodDecode.table}]\n`;
    }
    text += `${'='.repeat(80)}\n`;
    text += `${'Bits'.padEnd(8)}${'Field'.padEnd(25)}${'Access'.padEnd(8)}${'Value'.padEnd(12)}Description\n`;
    text += `${'-'.repeat(80)}\n`;
    
    sortedFields.forEach(field => {
        const [high, low] = field.bits;
        const bitWidth = high - low + 1;
        const mask = (1n << BigInt(bitWidth)) - 1n;
        const fieldValue = (value >> BigInt(low)) & mask;
        const bits = high === low ? `${high}` : `${high}:${low}`;
        
        let desc = field.description || '';
        if (mcaDecode && fieldValue !== 0n) {
            if (field.name === 'MSCOD' && mcaDecode.mscodDecode) desc = `>>> ${mcaDecode.mscodDecode.description}`;
            else if (field.name === 'MCACOD' && mcaDecode.mcacodDecode) desc = `>>> ${mcaDecode.mcacodDecode.description}`;
        }
        text += `${bits.padEnd(8)}${field.name.padEnd(25)}${(field.access || '-').padEnd(8)}0x${fieldValue.toString(16).toUpperCase().padEnd(10)}${desc}\n`;
    });
    
    navigator.clipboard.writeText(text).then(() => {
        const btn = document.getElementById('btn-copy-result');
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = 'Copy to Clipboard', 2000);
    });
}

// =============================================================================
// Keyboard Shortcuts
// =============================================================================

document.addEventListener('keydown', (e) => {
    // Ctrl+K: Focus search
    if (e.ctrlKey && e.key === 'k') {
        e.preventDefault();
        document.getElementById('reg-search').focus();
    }
    // Ctrl+D: Focus value input
    if (e.ctrlKey && e.key === 'd') {
        e.preventDefault();
        document.getElementById('reg-value').focus();
    }
});
