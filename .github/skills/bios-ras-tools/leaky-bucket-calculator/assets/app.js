(function () {
  'use strict';

  const CONFIG = {
    ddrPlatforms: {
      'DDR4 Memory': { label: 'DDR4 Memory', divisor: 2, speeds: [800, 1066, 1334, 1600, 1866, 2133, 2400, 2666, 2933, 3200], rawDecode: false },
      'SPR-DDR5': { label: 'SPR-DDR5', divisor: 4, speeds: [3200, 4400, 4800, 5600], rawDecode: false },
      'HBM2e': { label: 'HBM2e', divisor: 4, speeds: [3200], rawDecode: false },
      'GNR-DDR': { label: 'GNR-DDR', divisor: 8, speeds: [5200, 5600, 6400, 7200, 8000, 8800], rawDecode: true }
    },
    pcieGenerations: {
      gen1: { label: 'PCIe Gen1', dataRate: 2.5e9, burstField: 'AGGRERR', thresholdField: 'ERRTHRESH' },
      gen2: { label: 'PCIe Gen2', dataRate: 5e9, burstField: 'AGGRERR', thresholdField: 'ERRTHRESH' },
      gen3: { label: 'PCIe Gen3', dataRate: 8e9, burstField: 'G3AGGRERR', thresholdField: 'G3ERRTHRESH' },
      gen4: { label: 'PCIe Gen4', dataRate: 16e9, burstField: 'G3AGGRERR', thresholdField: 'G3ERRTHRESH' },
      gen5: { label: 'PCIe Gen5', dataRate: 32e9, burstField: 'G3AGGRERR', thresholdField: 'G3ERRTHRESH' }
    }
  };

  const MODE_META = {
    ddr: { title: 'DDR Drip Time', description: 'Select a DDR platform, enter register values, and calculate the drip interval.', badge: 'GNR raw decode enabled' },
    'pcie-registers': { title: 'PCIe From Registers', description: 'Convert EXP_BER register fields into leak time, actionable error rate, and BER.', badge: 'Register analysis' },
    'pcie-target': { title: 'PCIe Target BER', description: 'Start from target BER and threshold, then compute PCIe programming values.', badge: 'Reverse calculation' },
    reference: { title: 'Reference', description: 'Review required fields, platform assumptions, and workbook formulas.', badge: 'Workbook guide' }
  };

  let currentMode = 'ddr';
  let currentResult = null;

  function initTheme() {
    if (typeof document === 'undefined') return;
    const savedTheme = localStorage.getItem('leaky-bucket-theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeButton(savedTheme);
  }

  function updateThemeButton(theme) {
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    button.textContent = theme === 'dark' ? 'light_mode' : 'dark_mode';
    button.setAttribute('aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
  }

  function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
    const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', nextTheme);
    localStorage.setItem('leaky-bucket-theme', nextTheme);
    updateThemeButton(nextTheme);
  }

  function parseHex(value) {
    if (typeof value === 'number' && Number.isFinite(value)) return Math.trunc(value);
    const text = String(value || '').trim();
    if (!text) return NaN;
    const normalized = text.toLowerCase().startsWith('0x') ? text.slice(2) : text;
    if (!/^[0-9a-f]+$/i.test(normalized)) return NaN;
    return Number.parseInt(normalized, 16);
  }

  function toNumber(value) {
    if (typeof value === 'number') return value;
    const text = String(value || '').trim();
    if (!text) return NaN;
    return Number(text);
  }

  function toHex(value, minWidth) {
    const number = Math.trunc(value);
    return `0x${number.toString(16).toUpperCase().padStart(minWidth || 0, '0')}`;
  }

  function formatDuration(seconds) {
    if (!Number.isFinite(seconds)) return 'Invalid duration';
    const absolute = Math.abs(seconds);
    if (absolute < 1) return `${(seconds * 1000).toFixed(3)} ms`;
    if (absolute < 60) return `${seconds.toFixed(3)} s`;
    if (absolute < 3600) return `${(seconds / 60).toFixed(3)} min`;
    if (absolute < 86400) return `${(seconds / 3600).toFixed(3)} hr`;
    return `${(seconds / 86400).toFixed(3)} days`;
  }

  function calculateDdrDripTime(input) {
    const errors = [];
    const platform = CONFIG.ddrPlatforms[input.platform];
    if (!platform) errors.push('Select a supported DDR platform.');

    const speed = toNumber(input.speed);
    if (!Number.isFinite(speed) || speed <= 0) errors.push('Enter a valid DDR speed.');

    const secondCounterLimit = toNumber(input.secondCounterLimit);
    if (!Number.isInteger(secondCounterLimit) || secondCounterLimit < 0 || secondCounterLimit > 3) errors.push('Select a valid 2ND_CNTR_LIMIT value: 0, 1, 2, or 3.');

    let cfgHi;
    let cfgLo;
    let rawConfig;

    if (input.inputMode === 'raw') {
      if (!platform || !platform.rawDecode) {
        errors.push('Raw LEAKY_BUCKET_CFG decode is only supported for GNR-DDR. Enter decoded CFG_HI and CFG_LO for this platform.');
      } else {
        rawConfig = parseHex(input.rawConfig);
        if (!Number.isFinite(rawConfig)) {
          errors.push('Enter a valid raw LEAKY_BUCKET_CFG hex value.');
        } else {
          cfgHi = (rawConfig >> 6) & 0x3F;
          cfgLo = rawConfig & 0x3F;
        }
      }
    } else {
      cfgHi = parseHex(input.cfgHi);
      cfgLo = parseHex(input.cfgLo);
      if (!Number.isFinite(cfgHi)) errors.push('Enter a valid CFG_HI hex value.');
      if (!Number.isFinite(cfgLo)) errors.push('Enter a valid CFG_LO hex value.');
    }

    if (Number.isFinite(cfgHi) && (cfgHi < 0 || cfgHi > 0x3F)) errors.push('CFG_HI must fit in 6 bits.');
    if (Number.isFinite(cfgLo) && (cfgLo < 0 || cfgLo > 0x3F)) errors.push('CFG_LO must fit in 6 bits.');

    if (errors.length) return { valid: false, errors };

    const effectiveClockMhz = speed / platform.divisor;
    const limitMultiplier = secondCounterLimit === 0 ? 4 : secondCounterLimit;
    const counterTerm = cfgHi === cfgLo ? Math.pow(2, cfgHi) : Math.pow(2, cfgHi) + Math.pow(2, cfgLo);
    const seconds = limitMultiplier * 2048 * counterTerm / (effectiveClockMhz * 1e6);
    const warnings = [];

    if (cfgHi === 0 || cfgLo === 0) warnings.push('CFG_HI or CFG_LO is zero; confirm this is intended for the platform.');

    return {
      valid: true,
      errors: [],
      warnings,
      mode: 'DDR Drip Time',
      platform: input.platform,
      speed,
      seconds,
      formatted: formatDuration(seconds),
      decoded: { cfgHi, cfgLo, rawConfig, secondCounterLimit, limitMultiplier, effectiveClockMhz },
      trace: cfgHi === cfgLo
        ? `${limitMultiplier} * 2048 * 2^${cfgHi} / (${effectiveClockMhz} * 1e6)`
        : `${limitMultiplier} * 2048 * (2^${cfgHi} + 2^${cfgLo}) / (${effectiveClockMhz} * 1e6)`
    };
  }

  function calculatePcieFromRegisters(input) {
    const errors = [];
    const generation = CONFIG.pcieGenerations[input.generation];
    if (!generation) errors.push('Select a supported PCIe generation.');

    const expBerLow = parseHex(input.expBerLow);
    const expBerHigh = parseHex(input.expBerHigh);
    const threshold = toNumber(input.threshold);

    if (!Number.isFinite(expBerLow)) errors.push('Enter a valid EXP_BER[31:0] hex value.');
    if (!Number.isFinite(expBerHigh)) errors.push('Enter a valid EXP_BER[49:32] hex value.');
    if (!Number.isFinite(threshold) || threshold < 0) errors.push('Enter a valid non-negative error threshold.');
    if (Number.isFinite(expBerHigh) && expBerHigh > 0x3FFFF) errors.push('EXP_BER[49:32] must fit in 18 bits.');
    if (errors.length) return { valid: false, errors };

    const expBerDecimal = expBerLow + expBerHigh * Math.pow(2, 32);
    const seconds = expBerDecimal / 1e9;
    const minimumActionableErrorRate = seconds === 0 ? Infinity : threshold / seconds;
    const ber = minimumActionableErrorRate / generation.dataRate;
    const warnings = threshold === 0 ? ['Threshold is zero, so actionable error rate and BER are zero.'] : [];

    return {
      valid: true,
      errors: [],
      warnings,
      mode: 'PCIe From Registers',
      generation: input.generation,
      generationLabel: generation.label,
      expBerDecimal,
      seconds,
      formatted: formatDuration(seconds),
      minimumActionableErrorRate,
      ber,
      fields: { expBerLow, expBerHigh, threshold, dataRate: generation.dataRate },
      trace: `${expBerLow} + ${expBerHigh} * 2^32 = ${expBerDecimal}; ${expBerDecimal} / 1e9 = ${seconds}s`
    };
  }

  function calculatePcieTargetBer(input) {
    const errors = [];
    const generation = CONFIG.pcieGenerations[input.generation];
    if (!generation) errors.push('Select a supported PCIe generation.');

    const desiredBer = toNumber(input.desiredBer);
    const burstIntervalNs = toNumber(input.burstIntervalNs);
    const threshold = toNumber(input.threshold);

    if (!Number.isFinite(desiredBer) || desiredBer <= 0) errors.push('Enter a desired BER greater than zero.');
    if (!Number.isFinite(burstIntervalNs) || burstIntervalNs < 0) errors.push('Enter a valid non-negative burst interval in ns.');
    if (!Number.isFinite(threshold) || threshold < 0) errors.push('Enter a valid non-negative error threshold.');
    if (errors.length) return { valid: false, errors };

    const minimalActionableErrorRate = generation.dataRate * desiredBer;
    const expBerDecimal = threshold * 1e9 / minimalActionableErrorRate;
    const expBerInteger = Math.round(expBerDecimal);
    const expBerLow = expBerInteger % Math.pow(2, 32);
    const expBerHigh = Math.floor(expBerInteger / Math.pow(2, 32));

    if (expBerHigh > 0x3FFFF) {
      return { valid: false, errors: ['EXP_BER[49:32] exceeds the 18-bit range 0x3FFFF.'] };
    }

    return {
      valid: true,
      errors: [],
      warnings: [],
      mode: 'PCIe Target BER',
      generation: input.generation,
      generationLabel: generation.label,
      expBerDecimal: expBerInteger,
      expBerLow,
      expBerHigh,
      expBerLowHex: toHex(expBerLow, 8),
      expBerHighHex: toHex(expBerHigh),
      burstHex: toHex(burstIntervalNs),
      thresholdHex: toHex(threshold),
      fields: { desiredBer, burstIntervalNs, threshold, dataRate: generation.dataRate, burstField: generation.burstField, thresholdField: generation.thresholdField },
      trace: `${generation.dataRate} * ${desiredBer} = ${minimalActionableErrorRate}; ${threshold} * 1e9 / ${minimalActionableErrorRate} = ${expBerInteger}`
    };
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[character]));
  }

  function renderMessages(result) {
    const errors = result.errors || [];
    const warnings = result.warnings || [];
    return [
      ...errors.map(error => `<div class="message error">${escapeHtml(error)}</div>`),
      ...warnings.map(warning => `<div class="message warn">${escapeHtml(warning)}</div>`)
    ].join('');
  }

  function kvRows(rows) {
    return `<div class="kv-table">${rows.map(([key, value]) => `<div class="kv-row"><div>${escapeHtml(key)}</div><div>${escapeHtml(value)}</div></div>`).join('')}</div>`;
  }

  function setStatus(message) {
    if (typeof document === 'undefined') return;
    const status = document.getElementById('status');
    if (status) status.textContent = message;
  }

  function renderDdrResult(result) {
    const root = document.getElementById('ddr-result');
    if (!result.valid) {
      root.innerHTML = `<h2>Result</h2>${renderMessages(result)}`;
      return;
    }

    const rows = [
      ['CFG_HI', toHex(result.decoded.cfgHi)],
      ['CFG_LO', toHex(result.decoded.cfgLo)],
      ['2ND_CNTR_LIMIT', result.decoded.secondCounterLimit],
      ['Limit multiplier', result.decoded.limitMultiplier],
      ['Effective clock', `${result.decoded.effectiveClockMhz} MHz`]
    ];

    root.innerHTML = `
      <h2>Result</h2>
      ${renderMessages(result)}
      <div class="result-card"><div>Leaky bucket drip interval</div><div class="result-value">${escapeHtml(result.formatted)}</div><p>${result.seconds.toPrecision(8)} seconds</p></div>
      <div class="trace">${escapeHtml(result.trace)}</div>
      ${kvRows(rows)}
      ${renderDdrSpeedComparison(result)}
    `;
  }

  function renderDdrSpeedComparison(result) {
    const platform = CONFIG.ddrPlatforms[result.platform];
    const rows = platform.speeds.map(speed => {
      const comparison = calculateDdrDripTime({
        platform: result.platform,
        speed,
        inputMode: 'decoded',
        cfgHi: toHex(result.decoded.cfgHi),
        cfgLo: toHex(result.decoded.cfgLo),
        secondCounterLimit: result.decoded.secondCounterLimit
      });
      return [`DDR-${speed}`, comparison.formatted];
    });
    return `<h3 class="subhead">Same fields across supported speeds</h3>${kvRows(rows)}`;
  }

  function renderPcieRegisterResult(result) {
    const root = document.getElementById('pcie-reg-result');
    if (!result.valid) {
      root.innerHTML = `<h2>Result</h2>${renderMessages(result)}`;
      return;
    }

    root.innerHTML = `
      <h2>Result</h2>
      ${renderMessages(result)}
      <div class="result-card"><div>Bucket leak interval</div><div class="result-value">${escapeHtml(result.formatted)}</div><p>${result.seconds.toFixed(3)} seconds, BER ${result.ber.toExponential(6)}</p></div>
      <div class="trace">${escapeHtml(result.trace)}</div>
      ${kvRows([
        ['EXP_BER decimal', result.expBerDecimal],
        ['Minimum actionable error rate', result.minimumActionableErrorRate.toExponential(6)],
        ['Data rate', `${result.fields.dataRate.toExponential(3)} bits/s`],
        ['Threshold', result.fields.threshold]
      ])}
    `;
  }

  function renderPcieTargetResult(result) {
    const root = document.getElementById('target-result');
    if (!result.valid) {
      root.innerHTML = `<h2>Result</h2>${renderMessages(result)}`;
      return;
    }

    root.innerHTML = `
      <h2>Result</h2>
      ${renderMessages(result)}
      <div class="result-card"><div>EXP_BER programming value</div><div class="result-value">${escapeHtml(result.expBerHighHex)}:${escapeHtml(result.expBerLowHex.replace('0x', ''))}</div><p>Decimal: ${result.expBerDecimal}</p></div>
      <div class="trace">${escapeHtml(result.trace)}</div>
      ${kvRows([
        ['EXP_BER[31:0]', result.expBerLowHex],
        ['EXP_BER[49:32]', result.expBerHighHex],
        [result.fields.burstField, result.burstHex],
        [result.fields.thresholdField, result.thresholdHex]
      ])}
    `;
  }

  function buildResultSummary(result) {
    if (!result || !result.valid) return 'No valid result to copy.';
    if (result.mode === 'DDR Drip Time') return buildDdrSummary(result);
    if (result.mode === 'PCIe From Registers') return buildPcieRegisterSummary(result);
    if (result.mode === 'PCIe Target BER') return buildPcieTargetSummary(result);
    return 'No valid result to copy.';
  }

  function buildDdrSummary(result) {
    const rawLine = Number.isFinite(result.decoded.rawConfig) ? [`LEAKY_BUCKET_CFG: ${toHex(result.decoded.rawConfig, 8)}`] : [];
    return [
      'DDR Leaky Bucket Result',
      `Platform: ${result.platform}`,
      `DDR speed: ${result.speed}`,
      ...rawLine,
      `CFG_HI: ${toHex(result.decoded.cfgHi)}`,
      `CFG_LO: ${toHex(result.decoded.cfgLo)}`,
      `2ND_CNTR_LIMIT: ${result.decoded.secondCounterLimit}`,
      `Effective clock: ${result.decoded.effectiveClockMhz} MHz`,
      `Result: ${result.formatted}`,
      `Formula: ${result.trace}`
    ].join('\n');
  }

  function buildPcieRegisterSummary(result) {
    return [
      'PCIe From Registers Result',
      `Generation: ${result.generationLabel}`,
      `EXP_BER decimal: ${result.expBerDecimal}`,
      `Leak interval: ${result.formatted}`,
      `Leak interval seconds: ${result.seconds}`,
      `Minimum actionable error rate: ${result.minimumActionableErrorRate.toExponential(6)}`,
      `BER: ${result.ber.toExponential(6)}`,
      `Formula: ${result.trace}`
    ].join('\n');
  }

  function buildPcieTargetSummary(result) {
    return [
      'PCIe Target BER Result',
      `Generation: ${result.generationLabel}`,
      `EXP_BER decimal: ${result.expBerDecimal}`,
      `EXP_BER[31:0]: ${result.expBerLowHex}`,
      `EXP_BER[49:32]: ${result.expBerHighHex}`,
      `${result.fields.burstField}: ${result.burstHex}`,
      `${result.fields.thresholdField}: ${result.thresholdHex}`,
      `Formula: ${result.trace}`
    ].join('\n');
  }

  async function copyCurrentResult() {
    const summary = buildResultSummary(currentResult);
    try {
      await navigator.clipboard.writeText(summary);
      setStatus('Result copied');
      document.querySelectorAll('.copy-fallback').forEach(node => node.remove());
    } catch (error) {
      setStatus('Clipboard unavailable; copy from text box');
      const activePanel = document.querySelector('.mode-grid .panel:last-child') || document.getElementById('mode-root');
      const existing = document.querySelector('.copy-fallback');
      if (existing) existing.remove();
      const textarea = document.createElement('textarea');
      textarea.className = 'copy-fallback';
      textarea.value = summary;
      activePanel.appendChild(textarea);
      textarea.focus();
      textarea.select();
    }
  }

  function renderDdrMode() {
    const root = document.getElementById('mode-root');
    const platformOptions = Object.entries(CONFIG.ddrPlatforms).map(([key, value]) => `<option value="${key}">${value.label}</option>`).join('');

    root.innerHTML = `
      <div class="mode-grid">
        <section class="panel">
          <h2>Inputs</h2>
          <div class="register-box">
            Required fields:
            <code>LEAKY_BUCKET_CFG -> LEAKY_BKT_CFG_HI / LEAKY_BKT_CFG_LO</code>
            <code>LEAKY_BKT_2ND_CNTR_REG -> 2ND_CNTR_LIMIT</code>
          </div>
          <div class="field-grid">
            <div class="field"><label for="ddr-platform">Platform</label><select id="ddr-platform">${platformOptions}</select></div>
            <div class="field"><label for="ddr-speed">DDR speed</label><select id="ddr-speed"></select></div>
            <div class="field"><label for="ddr-input-mode">Input mode</label><select id="ddr-input-mode"><option value="raw">Raw LEAKY_BUCKET_CFG</option><option value="decoded">Decoded CFG_HI / CFG_LO</option></select></div>
            <div class="field"><label for="ddr-limit">2ND_CNTR_LIMIT</label><select id="ddr-limit" class="mono"><option value="0">0</option><option value="1">1</option><option value="2">2</option><option value="3" selected>3</option></select></div>
          </div>
          <div id="ddr-raw-fields" class="field"><label for="ddr-raw">LEAKY_BUCKET_CFG</label><input id="ddr-raw" class="mono" value="0x000002C7"></div>
          <div id="ddr-decoded-fields" class="field-grid" hidden>
            <div class="field"><label for="ddr-hi">CFG_HI</label><input id="ddr-hi" class="mono" value="0xB"></div>
            <div class="field"><label for="ddr-lo">CFG_LO</label><input id="ddr-lo" class="mono" value="0x7"></div>
          </div>
          <div class="button-row"><button id="ddr-calc" class="primary">Calculate</button><button id="ddr-copy" class="secondary">Copy result</button></div>
        </section>
        <section id="ddr-result" class="panel"><h2>Result</h2><p>Enter values and calculate to see the drip interval.</p></section>
      </div>`;

    const platformSelect = document.getElementById('ddr-platform');
    const speedSelect = document.getElementById('ddr-speed');
    const inputMode = document.getElementById('ddr-input-mode');
    platformSelect.value = 'GNR-DDR';

    function refreshInputMode() {
      const raw = inputMode.value === 'raw';
      document.getElementById('ddr-raw-fields').hidden = !raw;
      document.getElementById('ddr-decoded-fields').hidden = raw;
    }

    function refreshSpeeds() {
      const platform = CONFIG.ddrPlatforms[platformSelect.value];
      speedSelect.innerHTML = platform.speeds.map(speed => `<option value="${speed}">${speed}</option>`).join('');
      speedSelect.value = platformSelect.value === 'GNR-DDR' ? '6400' : String(platform.speeds[0]);
      inputMode.value = platform.rawDecode ? 'raw' : 'decoded';
      refreshInputMode();
    }

    function readInput() {
      return {
        platform: platformSelect.value,
        speed: Number(speedSelect.value),
        inputMode: inputMode.value,
        rawConfig: document.getElementById('ddr-raw').value,
        cfgHi: document.getElementById('ddr-hi').value,
        cfgLo: document.getElementById('ddr-lo').value,
        secondCounterLimit: document.getElementById('ddr-limit').value
      };
    }

    function calculateAndRender() {
      const result = calculateDdrDripTime(readInput());
      currentResult = result;
      renderDdrResult(result);
      setStatus(result.valid ? 'DDR result calculated' : 'Fix DDR inputs');
    }

    platformSelect.addEventListener('change', () => { refreshSpeeds(); calculateAndRender(); });
    speedSelect.addEventListener('change', calculateAndRender);
    inputMode.addEventListener('change', () => { refreshInputMode(); calculateAndRender(); });
    document.getElementById('ddr-calc').addEventListener('click', calculateAndRender);
    document.getElementById('ddr-copy').addEventListener('click', copyCurrentResult);
    refreshSpeeds();
    calculateAndRender();
  }

  function renderPcieRegistersMode() {
    const root = document.getElementById('mode-root');
    const generationOptions = Object.entries(CONFIG.pcieGenerations).map(([key, value]) => `<option value="${key}">${value.label}</option>`).join('');

    root.innerHTML = `
      <div class="mode-grid">
        <section class="panel">
          <h2>Inputs</h2>
          <div class="register-box">
            Required fields:
            <code>LEKBER0.EXP_BER[31:0]</code>
            <code>LEKBER1.EXP_BER[17:0]</code>
            <code>LEKBERR threshold field for selected generation</code>
          </div>
          <div class="field-grid">
            <div class="field"><label for="pcie-generation">PCIe generation</label><select id="pcie-generation">${generationOptions}</select></div>
            <div class="field"><label for="pcie-threshold">Error threshold</label><input id="pcie-threshold" class="mono" value="16"></div>
            <div class="field"><label for="pcie-low">EXP_BER[31:0]</label><input id="pcie-low" class="mono" value="0xD4A51000"></div>
            <div class="field"><label for="pcie-high">EXP_BER[49:32]</label><input id="pcie-high" class="mono" value="0xE8"></div>
          </div>
          <div class="button-row"><button id="pcie-reg-calc" class="primary">Calculate</button><button id="pcie-reg-copy" class="secondary">Copy result</button></div>
        </section>
        <section id="pcie-reg-result" class="panel"><h2>Result</h2><p>Enter values and calculate to see PCIe leak behavior.</p></section>
      </div>`;

    document.getElementById('pcie-generation').value = 'gen5';

    function readInput() {
      return {
        generation: document.getElementById('pcie-generation').value,
        expBerLow: document.getElementById('pcie-low').value,
        expBerHigh: document.getElementById('pcie-high').value,
        threshold: document.getElementById('pcie-threshold').value
      };
    }

    function calculateAndRender() {
      const result = calculatePcieFromRegisters(readInput());
      currentResult = result;
      renderPcieRegisterResult(result);
      setStatus(result.valid ? 'PCIe register result calculated' : 'Fix PCIe inputs');
    }

    document.getElementById('pcie-reg-calc').addEventListener('click', calculateAndRender);
    document.getElementById('pcie-reg-copy').addEventListener('click', copyCurrentResult);
    calculateAndRender();
  }

  function renderPcieTargetMode() {
    const root = document.getElementById('mode-root');
    const generationOptions = Object.entries(CONFIG.pcieGenerations).map(([key, value]) => `<option value="${key}">${value.label}</option>`).join('');

    root.innerHTML = `
      <div class="mode-grid">
        <section class="panel">
          <h2>Inputs</h2>
          <div class="register-box">
            Target calculation outputs:
            <code>LEKBER0.EXP_BER[31:0]</code>
            <code>LEKBER1.EXP_BER[17:0] and burst field</code>
            <code>LEKBERR threshold field</code>
          </div>
          <div class="field-grid">
            <div class="field"><label for="target-generation">PCIe generation</label><select id="target-generation">${generationOptions}</select></div>
            <div class="field"><label for="target-ber">Desired BER</label><input id="target-ber" class="mono" value="1e-12"></div>
            <div class="field"><label for="target-burst">Burst interval ns</label><input id="target-burst" class="mono" value="2"></div>
            <div class="field"><label for="target-threshold">Error threshold</label><input id="target-threshold" class="mono" value="16"></div>
          </div>
          <div class="button-row"><button id="target-calc" class="primary">Calculate</button><button id="target-copy" class="secondary">Copy result</button></div>
        </section>
        <section id="target-result" class="panel"><h2>Result</h2><p>Enter target behavior and calculate register values.</p></section>
      </div>`;

    document.getElementById('target-generation').value = 'gen5';

    function readInput() {
      return {
        generation: document.getElementById('target-generation').value,
        desiredBer: document.getElementById('target-ber').value,
        burstIntervalNs: document.getElementById('target-burst').value,
        threshold: document.getElementById('target-threshold').value
      };
    }

    function calculateAndRender() {
      const result = calculatePcieTargetBer(readInput());
      currentResult = result;
      renderPcieTargetResult(result);
      setStatus(result.valid ? 'PCIe target values calculated' : 'Fix PCIe target inputs');
    }

    document.getElementById('target-calc').addEventListener('click', calculateAndRender);
    document.getElementById('target-copy').addEventListener('click', copyCurrentResult);
    calculateAndRender();
  }

  function renderReferenceMode() {
    const root = document.getElementById('mode-root');
    root.innerHTML = `
      <div class="mode-grid">
        <section class="panel">
          <h2>DDR Required Inputs</h2>
          <div class="register-box">
            <code>LEAKY_BUCKET_CFG -> LEAKY_BKT_CFG_HI / LEAKY_BKT_CFG_LO</code>
            <code>LEAKY_BKT_2ND_CNTR_REG -> 2ND_CNTR_LIMIT</code>
          </div>
          ${kvRows([
            ['DDR4 Memory clock', 'DDR / 2 MHz'],
            ['SPR-DDR5 clock', 'DDR / 4 MHz'],
            ['HBM2e clock', 'DDR / 4 MHz'],
            ['GNR-DDR clock', 'DDR / 8 MHz'],
            ['GNR CFG_HI', 'LEAKY_BUCKET_CFG bits[11:6]'],
            ['GNR CFG_LO', 'LEAKY_BUCKET_CFG bits[5:0]']
          ])}
        </section>
        <section class="panel">
          <h2>PCIe Required Inputs</h2>
          <div class="register-box">
            <code>LEKBER0.EXP_BER[31:0]</code>
            <code>LEKBER1.EXP_BER[17:0]</code>
            <code>G3AGGRERR / AGGRERR burst interval</code>
            <code>G3ERRTHRESH / ERRTHRESH threshold</code>
          </div>
          ${kvRows(Object.values(CONFIG.pcieGenerations).map(item => [item.label, `${item.dataRate.toExponential(3)} bits/s`]))}
        </section>
      </div>
      <section class="panel reference-note">
        <h2>Notes</h2>
        <p>Only GNR-DDR raw LEAKY_BUCKET_CFG decode is automated in this version. For DDR4, SPR-DDR5, and HBM2e, enter decoded CFG_HI and CFG_LO fields unless the platform bit definition is added later.</p>
      </section>`;
    currentResult = null;
    setStatus('Reference loaded');
  }

  function renderMode(mode) {
    if (mode === 'ddr') renderDdrMode();
    if (mode === 'pcie-registers') renderPcieRegistersMode();
    if (mode === 'pcie-target') renderPcieTargetMode();
    if (mode === 'reference') renderReferenceMode();
  }

  function setMode(mode) {
    currentMode = mode;
    const meta = MODE_META[mode];
    document.getElementById('mode-title').textContent = meta.title;
    document.getElementById('mode-description').textContent = meta.description;
    document.getElementById('mode-badge').textContent = meta.badge;
    document.querySelectorAll('.nav-button').forEach(button => {
      button.classList.toggle('active', button.dataset.mode === mode);
    });
    renderMode(mode);
  }

  function bootApp() {
    if (typeof document === 'undefined' || !document.getElementById('mode-root')) return;
    initTheme();
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) themeToggle.addEventListener('click', toggleTheme);
    document.querySelectorAll('.nav-button').forEach(button => {
      button.addEventListener('click', () => setMode(button.dataset.mode));
    });
    setMode(currentMode);
  }

  const apiTarget = typeof window !== 'undefined' ? window : globalThis;
  apiTarget.LeakyBucketCalculator = {
    CONFIG,
    parseHex,
    toHex,
    formatDuration,
    calculateDdrDripTime,
    calculatePcieFromRegisters,
    calculatePcieTargetBer,
    buildResultSummary
  };

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', bootApp);
    } else {
      bootApp();
    }
  }
})();