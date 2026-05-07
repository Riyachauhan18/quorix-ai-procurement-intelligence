// =========================================
//  AI Tender Copilot — app.js
// =========================================
document.addEventListener('DOMContentLoaded', function () {

  // ── State ─────────────────────────────────────────────────────
  var lastResult = null;
  var multiBidders = [];
  var extractedData = null;

  // ── Tab switching ─────────────────────────────────────────────
  document.querySelectorAll('.tab-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var tab = btn.dataset.tab;
      document.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
      document.querySelectorAll('.tab-content').forEach(function (c) { c.style.display = 'none'; });
      btn.classList.add('active');
      document.getElementById('tab-' + tab).style.display = 'block';
      if (tab === 'audit') loadAudit();
    });
  });

  // ── Policy pills live update ───────────────────────────────────
  var minTEl = document.getElementById('min-turnover');
  var minEEl = document.getElementById('min-experience');

  function updatePills() {
    var t = parseFloat(minTEl.value) || 0;
    var e = parseFloat(minEEl.value) || 0;
    var tStr = t.toLocaleString('en-IN');
    document.getElementById('pill-t').textContent = tStr;
    document.getElementById('pill-e').textContent = e;
    document.getElementById('baseline-t').textContent = tStr;
    document.getElementById('baseline-e').textContent = e;
  }
  minTEl.addEventListener('input', function () { updatePills(); renderTradeOff(); liveReevaluate(); });
  minEEl.addEventListener('input', function () { updatePills(); renderTradeOff(); liveReevaluate(); });
  updatePills();
  renderTradeOff();   // initial render

  function liveReevaluate() {
    if (document.getElementById('results-section').style.display !== 'none') runEvaluate();
  }

  // ── File Upload & Extraction (Enterprise Flow) ─────────────────
  var fileInput = document.getElementById('file-input');
  var fileNameDisplay = document.getElementById('file-name-display');
  var startExtractBtn = document.getElementById('start-extract-btn');
  var extractStatusContainer = document.getElementById('extraction-status-container');
  var extractStatusText = document.getElementById('extraction-status-text');

  // Step 1: File Selection UI Update
  function updateFileUI() {
    if (fileInput.files && fileInput.files[0]) {
      fileNameDisplay.textContent = 'Selected: ' + fileInput.files[0].name;
      fileNameDisplay.classList.add('active');
      startExtractBtn.disabled = false;
    } else {
      fileNameDisplay.textContent = 'No document selected';
      fileNameDisplay.classList.remove('active');
      startExtractBtn.disabled = true;
    }
  }
  fileInput.addEventListener('change', updateFileUI);
  fileInput.addEventListener('input', updateFileUI);

  // Step 2: Explicit Extraction Trigger
  startExtractBtn.addEventListener('click', function() {
    if (!fileInput.files || !fileInput.files[0]) return;
    
    // UI Loading State
    startExtractBtn.disabled = true;
    fileInput.disabled = true;
    document.getElementById('extract-result').style.display = 'none';
    extractStatusContainer.style.display = 'flex';
    
    // Sequential Status Messages
    extractStatusText.textContent = "Parsing document structure...";
    
    setTimeout(function() {
      if (extractStatusContainer.style.display !== 'none') {
        extractStatusText.textContent = "Extracting bidder entities...";
      }
    }, 1200);

    setTimeout(function() {
      if (extractStatusContainer.style.display !== 'none') {
        extractStatusText.textContent = "Validating policy thresholds...";
      }
    }, 2400);

    // Backend Execution
    doExtract(fileInput.files[0]);
  });

  function doExtract(file) {
    var fd = new FormData();
    fd.append('file', file);
    
    // Hard Timeout Protection (10 seconds)
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);

    fetch('/api/extract', { method: 'POST', body: fd, signal: controller.signal })
      .then(function (r) { 
        clearTimeout(timeoutId);
        if (!r.ok) throw new Error('Server returned ' + r.status);
        return r.json(); 
      })
      .then(function (d) {
        if (d.status === "NON_PROCUREMENT" || d.status === "unsupported_document") {
          finishExtract(false, d.message || "Invalid document type detected.");
          return;
        }
        if (d.status === "error") {
          finishExtract(false, d.message || "Extraction failed.");
          return;
        }

        extractStatusText.textContent = "Document parsing completed successfully";
        extractStatusText.style.color = "var(--green)";
        
        setTimeout(function() {
          extractedData = d;
          showExtractResult(d);
          finishExtract(true);
        }, 800);
      })
      .catch(function (err) { 
        clearTimeout(timeoutId);
        var msg = "Extraction failed.";
        if (err.name === 'AbortError') msg = "Analysis timed out. Try a smaller file.";
        else if (err.message) msg = err.message;
        
        finishExtract(false, msg);
      });
  }

  function finishExtract(success, errorMsg) {
    if (!success && errorMsg) {
      extractStatusText.textContent = errorMsg;
      extractStatusText.style.color = "var(--red)";
      // Keep it visible for 3 seconds so user can read it, then hide
      setTimeout(() => {
        extractStatusContainer.style.display = 'none';
        extractStatusText.style.color = "";
      }, 4000);
    } else {
      extractStatusContainer.style.display = 'none';
      extractStatusText.style.color = "";
    }
    
    startExtractBtn.disabled = false;
    fileInput.disabled = false;
  }

  function showExtractResult(d) {
    var formatCurrency = function(val) {
      if (val === null || val === undefined) return '<span class="ext-not-detected">Not Detected</span>';
      return '₹' + Number(val).toLocaleString('en-IN');
    };
    
    var formatExp = function(val) {
      if (val === null || val === undefined) return '<span class="ext-not-detected">Not Detected</span>';
      return val + ' yrs';
    };

    var fieldsHtml = [
      ['Company', d.company || 'Unknown Bidder'],
      ['Turnover', formatCurrency(d.turnover)],
      ['Experience', formatExp(d.experience)],
      ['Blacklisted', d.blacklisted === 'yes' ? 'Yes' : 'No'],
      ['Price', formatCurrency(d.price)],
    ].map(function (f) {
      return '<div class="ext-row"><span class="ext-key">' + f[0] + '</span><span class="ext-val">' + f[1] + '</span></div>';
    }).join('');

    document.getElementById('extract-fields').innerHTML = fieldsHtml;
    document.getElementById('extract-conf').textContent = d.confidence + ' Confidence';
    document.getElementById('extract-result').style.display = 'block';
  }

  document.getElementById('autofill-btn').addEventListener('click', function () {
    if (!extractedData) return;
    document.getElementById('company-name').value = extractedData.company;
    document.getElementById('turnover').value     = extractedData.turnover;
    document.getElementById('experience').value   = extractedData.experience;
    document.getElementById('blacklisted').value  = extractedData.blacklisted;
    document.getElementById('price').value        = extractedData.price;
    
    // Manually trigger validation since .value change doesn't fire 'input' event
    validateInputs();
    renderTradeOff();
  });

  // ── Validation Logic ──────────────────────────────────────────
  var evalBtn = document.getElementById('evaluate-btn');
  var evalHint = document.getElementById('eval-hint');
  var companyInput = document.getElementById('company-name');
  var turnoverInput = document.getElementById('turnover');
  var experienceInput = document.getElementById('experience');

  function validateInputs() {
    var c = companyInput.value.trim();
    var t = turnoverInput.value.trim();
    var e = experienceInput.value.trim();
    var isValid = c && t && e;
    evalBtn.disabled = !isValid;
    evalHint.style.display = isValid ? 'none' : 'block';
  }

  [companyInput, turnoverInput, experienceInput].forEach(function (el) {
    el.addEventListener('input', validateInputs);
  });
  validateInputs(); // initial check

  evalBtn.addEventListener('click', runEvaluate);
  document.querySelectorAll('#tab-single input, #tab-single select').forEach(function (el) {
    el.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !evalBtn.disabled) runEvaluate(); });
  });

  function runEvaluate() {
    var payload = {
      company:        document.getElementById('company-name').value.trim() || "Unknown Bidder",
      turnover:       parseFloat(document.getElementById('turnover').value)    || 0,
      experience:     parseFloat(document.getElementById('experience').value)  || 0,
      blacklisted:    document.getElementById('blacklisted').value,
      price:          parseFloat(document.getElementById('price').value)       || 0,
      min_turnover:   parseFloat(minTEl.value)  || 0,
      min_experience: parseFloat(minEEl.value)  || 0,
    };
    
    if (typeof extractedData !== 'undefined' && extractedData) {
      payload.file_name = extractedData.file_name;
      payload.file_type = extractedData.file_type;
      payload.extraction_timestamp = extractedData.extraction_timestamp;
      payload.extraction_confidence = extractedData.extraction_confidence;
      payload.extracted_fields = extractedData.extracted_fields;
    }

    setBtnLoading(true);
    
    // 8-Second Evaluation Timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000);

    fetch('/api/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal
    })
      .then(function (r) {
        clearTimeout(timeoutId);
        if (!r.ok) throw new Error('Evaluation service unavailable.');
        return r.json();
      })
      .then(function (d) {
        setBtnLoading(false);
        lastResult = Object.assign({}, d, {
          min_turnover: payload.min_turnover,
          min_experience: payload.min_experience,
          price_raw: payload.price,
          blacklisted_raw: payload.blacklisted,
        });
        renderExecSummary(d);
        renderResult(d);
      })
      .catch(function (err) {
        clearTimeout(timeoutId);
        setBtnLoading(false);
        var msg = err.name === 'AbortError' ? "Evaluation timed out. Please try again." : err.message;
        showErrResult(msg);
      });
  }

  function setBtnLoading(on) {
    var btn = document.getElementById('evaluate-btn');
    if (!btn) return;
    btn.disabled = on;
    btn.innerHTML = on
      ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="animation:spin .8s linear infinite"><path d="M21 12a9 9 0 1 1-9-9"/></svg> Evaluating Bidder…'
      : '<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> <span>Evaluate Bidder Eligibility</span>';
  }

  // ── Trade-off Analysis (live) ─────────────────────────────────
  function renderTradeOff() {
    var mt = parseFloat(minTEl.value) || 1000000;
    var me = parseFloat(minEEl.value) || 3;
    var el = document.getElementById('tradeoff-items');
    fetch('/api/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ min_turnover: mt, min_experience: me, turnover: 0, experience: 0, blacklisted: 'no', price: 0 }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.trade_off) return;
        var icons = { warning: '&#9888;', info: 'i', balanced: '~', success: '&#10003;' };
        el.innerHTML = d.trade_off.map(function (t) {
          return '<div class="to-item ' + t.type + '"><span>' + (icons[t.type] || '') + '</span> ' + t.text + '</div>';
        }).join('');
      })
      .catch(function () {});
  }

  // ── Executive Summary ───────────────────────────────────────
  function safeSetText(id, val) {
    var el = document.getElementById(id);
    if (el) el.textContent = val || '—';
  }
  function safeSetHtml(id, val) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = val || '';
  }

  function renderExecSummary(d) {
    safeSetText('es-company', d.company);
    safeSetText('es-score', d.scores.total + '/100');
    safeSetText('es-risk', d.overall_risk);
    safeSetText('es-conf', d.confidence);
    safeSetText('es-rec', d.policy_rec);
  }

  // ── Error state ────────────────────────────────────────
  function showErrResult(msg) {
    document.getElementById('results-section').style.display = 'block';
    var banner = document.getElementById('verdict-banner');
    banner.className = 'verdict-banner fail';
    document.getElementById('verdict-icon-wrap').innerHTML = xIcon(24);
    document.getElementById('verdict-label').textContent = 'ERROR';
    document.getElementById('verdict-company').textContent = 'Backend connection failed';
    document.getElementById('just-text').textContent = msg + '\n\nMake sure Flask server is running:\n  py server.py\nThen visit: http://localhost:5000';
    document.getElementById('alerts-list').innerHTML = '<div class="alert-item danger">Cannot connect to backend. Run: py server.py</div>';
  }

  // ── Render Result ─────────────────────────────────────────────
  function renderResult(d) {
    var sec = document.getElementById('results-section');
    sec.style.display = 'block';
    sec.classList.remove('fade-up');
    void sec.offsetWidth;
    sec.classList.add('fade-up');

    var pass = d.verdict === 'PASS';

    // Verdict
    var banner = document.getElementById('verdict-banner');
    if (banner) banner.className = 'verdict-banner ' + (pass ? 'pass' : 'fail');
    
    var iconWrap = document.getElementById('verdict-icon-wrap');
    if (iconWrap) iconWrap.innerHTML = pass ? checkIcon(24) : xIcon(24);
    
    safeSetText('verdict-label', d.verdict);
    safeSetText('verdict-company', d.company);
    safeSetText('conf-value', d.confidence);
    safeSetText('check-count', d.pass_count + '/' + d.total + ' criteria met');

    // Score ring
    var sc    = d.scores.total;
    var circ  = 314.16;
    var fill  = document.getElementById('ring-fill');
    if (fill) {
      fill.style.strokeDashoffset = circ;
      fill.style.stroke = sc >= 70 ? '#22c55e' : sc >= 50 ? '#f59e0b' : '#ef4444';
      document.getElementById('ring-num').textContent = sc;
      setTimeout(function () {
        fill.style.strokeDashoffset = circ * (1 - sc / 100);
      }, 60);
    }

    // Score bars
    animBar('sbar-t', 'sval-t', d.scores.turnover);
    animBar('sbar-e', 'sval-e', d.scores.experience);
    animBar('sbar-c', 'sval-c', d.scores.compliance);

    // Stats
    safeSetText('st-price', d.stats.price);
    safeSetText('st-turnover', d.stats.turnover);
    safeSetText('st-exp', d.stats.experience);

    // Checks
    var cList = document.getElementById('checks-list');
    cList.innerHTML = 
      renderCheck(d.checks.turnover,   'Turnover Check') +
      renderCheck(d.checks.experience, 'Experience Check') +
      renderCheck(d.checks.blacklist,  'Blacklist Check');

    // Risks
    var rList = document.getElementById('risk-list');
    var finIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>';
    var capIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>';
    var compIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>';
    
    rList.innerHTML = 
      renderRisk(d.risks.financial,  'Financial Risk',  'Turnover vs. thresholds.', finIcon) +
      renderRisk(d.risks.capability, 'Capability Risk', 'Experience & track record.', capIcon) +
      renderRisk(d.risks.compliance, 'Compliance Risk', (d.risks.compliance === 'High' ? 'Active blacklist detected.' : 'Clean regulatory record.'), compIcon);

    // Alerts
    var aHtml = (d.alerts || []).map(function (a) {
      return '<div class="alert-item ' + a.type + '">' + alertIcon(a.type) + a.text + '</div>';
    }).join('');
    document.getElementById('alerts-list').innerHTML = aHtml || '<p class="no-alerts">No alerts for current configuration.</p>';

    // Fairness
    var fb = document.getElementById('fairness-badge');
    fb.className = 'fairness-badge ' + (d.fairness.level === 'High' ? 'high' : '');
    fb.textContent = d.fairness.level + ' Fairness';
    document.getElementById('fairness-text').textContent = d.fairness.insight;

    // What-if Scenarios
    var wiSection = document.getElementById('whatif-section');
    var wiList = document.getElementById('whatif-list');
    var scenarios = [];

    if (d.disqualifications) scenarios = scenarios.concat(d.disqualifications);
    if (d.improvements) scenarios = scenarios.concat(d.improvements);

    if (scenarios.length > 0) {
      wiSection.style.display = 'block';
      wiList.innerHTML = scenarios.map(function(s) {
        return '<div class="whatif-box"><div class="whatif-text">' + s + '</div></div>';
      }).join('');
    } else {
      wiSection.style.display = 'none';
    }

    // Justification
    document.getElementById('just-text').textContent = d.justification;
  }

  function renderCheck(chk, label) {
    var pass = chk.passed;
    return '<div class="check-item ' + (pass ? 'pass' : 'fail') + '">' +
           '<div class="ci-icon">' + (pass ? checkIcon(15) : xIcon(15)) + '</div>' +
           '<div class="ci-body">' +
             '<span class="ci-name">' + label + '</span>' +
             '<span class="ci-desc">' + chk.desc + '</span>' +
           '</div>' +
           '<div class="ci-badge ' + (pass ? 'pass' : 'fail') + '">' + (pass ? 'PASS' : 'FAIL') + '</div>' +
           '</div>';
  }

  function renderRisk(level, label, desc, iconSvg) {
    return '<div class="risk-item">' +
           '<div class="risk-label-row">' + iconSvg + ' ' + label + '</div>' +
           '<div class="risk-badge ' + level.toLowerCase() + '">' + level + '</div>' +
           '<div class="risk-desc">' + desc + '</div>' +
           '</div>';
  }

  function animBar(barId, valId, val) {
    var b = document.getElementById(barId);
    var v = document.getElementById(valId);
    if (!b || !v) return;
    b.style.width = '0%';
    v.textContent = val;
    setTimeout(function () { b.style.width = val + '%'; }, 60);
  }

  // ── Download Report ───────────────────────────────────────────
  document.getElementById('download-btn').addEventListener('click', function () {
    if (!lastResult) return;
    var payload = {
      company:    lastResult.company,
      turnover:   lastResult.stats.turnover,
      experience: lastResult.stats.experience,
      price:      lastResult.stats.price,
      blacklisted: lastResult.blacklisted_raw === 'yes' ? 'Yes' : 'No',
      min_turnover:   'Rs.' + Number(lastResult.min_turnover).toLocaleString('en-IN'),
      min_experience: lastResult.min_experience,
      verdict:    lastResult.verdict,
      confidence: lastResult.confidence,
      score:      lastResult.scores.total,
      t_score:    lastResult.scores.turnover,
      e_score:    lastResult.scores.experience,
      c_score:    lastResult.scores.compliance,
      risk_fin:   lastResult.risks.financial,
      risk_cap:   lastResult.risks.capability,
      risk_comp:  lastResult.risks.compliance,
      justification: lastResult.justification,
    };
    fetch('/api/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.blob(); })
      .then(function (blob) {
        var url = URL.createObjectURL(blob);
        var a   = document.createElement('a');
        a.href  = url;
        a.download = 'tender_report.txt';
        a.click();
        URL.revokeObjectURL(url);
      });
  });

  // ── Multi-Bidder ──────────────────────────────────────────────
  document.getElementById('add-bidder-btn').addEventListener('click', function () {
    var company = document.getElementById('m-company').value.trim();
    if (!company) { alert('Please enter a company name.'); return; }
    var bidder = {
      company:    company,
      turnover:   parseFloat(document.getElementById('m-turnover').value)    || 0,
      experience: parseFloat(document.getElementById('m-experience').value)  || 0,
      blacklisted: document.getElementById('m-blacklisted').value,
      price:      parseFloat(document.getElementById('m-price').value)       || 0,
    };
    multiBidders.push(bidder);
    renderQueue();
    document.getElementById('m-company').value = '';
    document.getElementById('m-turnover').value = '';
    document.getElementById('m-experience').value = '';
    document.getElementById('m-price').value = '';
  });

  function renderQueue() {
    var el = document.getElementById('bidder-queue');
    if (multiBidders.length === 0) { el.innerHTML = '<p class="empty-msg">No bidders added yet.</p>'; return; }
    el.innerHTML = multiBidders.map(function (b, i) {
      return '<div class="queue-item">' +
        '<span class="queue-item-name">' + b.company + '</span>' +
        '<span class="queue-item-meta">Rs.' + Number(b.turnover).toLocaleString('en-IN') + ' | ' + b.experience + ' yrs</span>' +
        '<button class="queue-remove" data-idx="' + i + '" title="Remove">&times;</button>' +
      '</div>';
    }).join('');
    document.querySelectorAll('.queue-remove').forEach(function (btn) {
      btn.addEventListener('click', function () {
        multiBidders.splice(parseInt(btn.dataset.idx), 1);
        renderQueue();
      });
    });
  }

  document.getElementById('compare-btn').addEventListener('click', function () {
    if (multiBidders.length === 0) { alert('Add at least one bidder.'); return; }
    var payload = {
      bidders:        multiBidders,
      min_turnover:   parseFloat(document.getElementById('m-min-turnover').value)   || 1000000,
      min_experience: parseFloat(document.getElementById('m-min-experience').value) || 3,
    };
    fetch('/api/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) { renderComparison(d); })
      .catch(function (err) { alert('Compare failed: ' + err.message); });
  });

  function renderComparison(d) {
    document.getElementById('competition-card').style.display = 'block';
    document.getElementById('imp-total').textContent = d.total_evaluated || 0;
    document.getElementById('imp-qual').textContent  = d.qualified || 0;
    document.getElementById('imp-rate').textContent  = (d.qualification_rate || 0) + '%';
    if (d.recommended) {
      var fdb = document.getElementById('final-decision-box');
      fdb.style.display = 'block';
      document.getElementById('fd-name').textContent   = d.recommended;
      document.getElementById('fd-conf').textContent   = d.decision_confidence || 'N/A';
      document.getElementById('fd-reason').textContent = d.recommended_reason || '';
    }
    document.getElementById('comparison-section').style.display = 'block';
    var recBadge = document.getElementById('recommended-badge');
    if (d.recommended) { recBadge.style.display = 'inline-block'; recBadge.textContent = 'Recommended: ' + d.recommended; }
    var tbody = document.getElementById('comp-tbody');
    tbody.innerHTML = d.results.map(function (r) {
      var isRec = r.company === d.recommended;
      return '<tr class="' + (isRec ? 'recommended-row' : '') + '">' +
        '<td>' + (isRec ? '<span class="recommended-star">&#9733; </span>' : '') + r.company + '</td>' +
        '<td><strong>' + r.score + '</strong>/100</td>' +
        '<td><span class="risk-badge ' + r.risk_financial + '">' + r.risk_financial + '</span></td>' +
        '<td><span class="risk-badge ' + r.risk_capability + '">' + r.risk_capability + '</span></td>' +
        '<td><span class="risk-badge ' + r.risk_compliance + '">' + r.risk_compliance + '</span></td>' +
        '<td><span class="verdict-cell ' + r.verdict.toLowerCase() + '">' + r.verdict + '</span></td>' +
        '<td>' + (r.checks.t ? '&#10003;' : '&#10007;') + ' ' + (r.checks.e ? '&#10003;' : '&#10007;') + ' ' + (r.checks.b ? '&#10003;' : '&#10007;') + '</td>' +
      '</tr>';
    }).join('');
  }

  // ── Audit Trail ───────────────────────────────────────────────
  document.getElementById('refresh-audit-btn').addEventListener('click', loadAudit);

  function loadAudit() {
    fetch('/api/audit')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var tbody = document.getElementById('audit-tbody');
        if (!d.trail || d.trail.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" class="empty-msg">No evaluations recorded yet.</td></tr>';
          return;
        }
        tbody.innerHTML = d.trail.map(function (e) {
          var cls = e.verdict === 'PASS' ? 'pass' : 'fail';
          var riskCls = e.risk === 'Low' ? 'Low' : e.risk === 'Medium' ? 'Medium' : 'High';
          return '<tr>' +
            '<td>' + e.timestamp + '</td>' +
            '<td>' + e.company + '</td>' +
            '<td><span class="verdict-cell ' + cls + '">' + e.verdict + '</span></td>' +
            '<td>' + e.score + '/100</td>' +
            '<td>' + (e.risk || 'Not Provided') + '</span></td>' +
            '<td>' + (e.confidence || 'Not Provided') + '</td>' +
            '<td style="font-size:10px;color:#475569">' + (e.policy_ver || 'Not Provided') + '</td>' +
            '<td style="font-size:11px">' + (e.criteria || 'Not Provided') + '</td>' +
          '</tr>';
        }).join('');
      });
  }

  // ── SVG helpers ───────────────────────────────────────────────
  function checkIcon(s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
  }
  function xIcon(s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
  }
  function alertIcon(type) {
    var icons = {
      warning: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      danger:  '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
      info:    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
      success: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px"><polyline points="20 6 9 17 4 12"/></svg>',
    };
    return icons[type] || '';
  }

}); // end DOMContentLoaded
