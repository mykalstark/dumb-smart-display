
(function () {
  /* Read the current global time format from the Location selector */
  function getFmt() {
    var el = document.getElementById('location__time_format');
    return el ? el.value : '24h';
  }

  /* Parse a stored "HH:MM" string into { h, m } integers */
  function parseHHMM(str) {
    var parts = (str || '18:30').split(':');
    return { h: parseInt(parts[0], 10) || 0, m: parseInt(parts[1], 10) || 0 };
  }

  /*
   * todInit — populate the visible hour/min/ampm inputs from the hidden HH:MM
   * field and show/hide the AM/PM selector based on the current format.
   */
  function todInit(wrap) {
    var hidden = wrap.querySelector('input[type="hidden"]');
    var hourEl = wrap.querySelector('.tod-hour');
    var minEl  = wrap.querySelector('.tod-min');
    var ampmEl = wrap.querySelector('.tod-ampm');
    if (!hidden || !hourEl || !minEl || !ampmEl) { return; }

    var fmt = getFmt();
    var t   = parseHHMM(hidden.value);

    if (fmt === '12h') {
      hourEl.min = 1; hourEl.max = 12;
      hourEl.value = t.h % 12 || 12;
      ampmEl.value = t.h >= 12 ? 'PM' : 'AM';
      ampmEl.style.display = '';
    } else {
      hourEl.min = 0; hourEl.max = 23;
      hourEl.value = t.h;
      ampmEl.style.display = 'none';
    }
    minEl.value = String(t.m).padStart(2, '0');
  }

  /*
   * todSync — write the current hour/min/ampm inputs back to the hidden HH:MM
   * field so the correct value is submitted with the form.
   */
  function todSync(wrap) {
    var hidden = wrap.querySelector('input[type="hidden"]');
    var hourEl = wrap.querySelector('.tod-hour');
    var minEl  = wrap.querySelector('.tod-min');
    var ampmEl = wrap.querySelector('.tod-ampm');
    if (!hidden || !hourEl || !minEl || !ampmEl) { return; }

    var fmt = getFmt();
    var h = parseInt(hourEl.value, 10) || 0;
    var m = Math.min(59, Math.max(0, parseInt(minEl.value, 10) || 0));

    if (fmt === '12h') {
      if (ampmEl.value === 'PM' && h !== 12) { h += 12; }
      if (ampmEl.value === 'AM' && h === 12) { h = 0; }
    }
    h = Math.min(23, Math.max(0, h));
    hidden.value = String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
  }

  /* Wire up every tod-field on the page */
  document.querySelectorAll('.tod-field').forEach(function (wrap) {
    todInit(wrap);
    ['tod-hour', 'tod-min', 'tod-ampm'].forEach(function (cls) {
      var el = wrap.querySelector('.' + cls);
      if (el) {
        el.addEventListener('change', function () { todSync(wrap); });
        el.addEventListener('input',  function () { todSync(wrap); });
      }
    });
  });

  /* Re-initialize all tod-fields whenever the global Time Format selector changes */
  var fmtSel = document.getElementById('location__time_format');
  if (fmtSel) {
    fmtSel.addEventListener('change', function () {
      /* The hidden 24-hour value is already synchronized by widget edits. */
      document.querySelectorAll('.tod-field').forEach(todInit);
    });
  }
})();


(function () {
  var _source = null;
  var previousFocus;

  /* Stage metadata -------------------------------------------------- */
  var STAGES = {
    '1': { label: 'Checking for updates…',      pct: '12%', pip: 1 },
    '2': { label: 'Pulling latest code…',        pct: '30%', pip: 2 },
    '3': { label: 'Running install script…',     pct: '65%', pip: 3 },
    '4': { label: 'Restarting display service…', pct: '82%', pip: 4 },
    '5': { label: 'Restarting web UI service…',  pct: '94%', pip: 5 },
  };

  /* DOM refs (resolved on open) ------------------------------------- */
  var elModal, elBar, elStageLabel, elLog, elResult, elCloseRow;
  var elPips = [];

  function resolveEls() {
    elModal      = document.getElementById('upd-modal');
    elBar        = document.getElementById('upd-bar');
    elStageLabel = document.getElementById('upd-stage-label');
    elLog        = document.getElementById('upd-log');
    elResult     = document.getElementById('upd-result');
    elCloseRow   = document.getElementById('upd-close-row');
    elPips       = [1,2,3,4,5].map(function(n){ return document.getElementById('upd-pip-' + n); });
  }

  /* Helpers --------------------------------------------------------- */
  function setBar(pct, cls) {
    elBar.style.width = pct;
    if (cls) { elBar.className = 'upd-bar ' + cls; }
  }

  function setPips(activeIdx, cls) {
    elPips.forEach(function(pip, i) {
      pip.className = 'upd-stage-pip' +
        (i < activeIdx  ? ' complete' :
         i === activeIdx ? (' ' + (cls || 'active')) : '');
    });
  }

  function appendLog(text, muted) {
    var line = document.createElement('div');
    line.textContent = text;
    if (muted) { line.className = 'log-muted'; }
    elLog.appendChild(line);
    elLog.scrollTop = elLog.scrollHeight;
  }

  function showResult(html, isOk) {
    elResult.innerHTML = '<div class="' + (isOk ? 'upd-result-ok' : 'upd-result-err') + '">' + html + '</div>';
  }

  /* Open ------------------------------------------------------------- */
  window.openUpdateModal = function () {
    resolveEls();
    previousFocus = document.activeElement;

    /* Reset */
    elModal.hidden   = false;
    elCloseRow.hidden = true;
    elResult.innerHTML = '';
    elLog.innerHTML  = '';
    elBar.className  = 'upd-bar';
    setBar('5%');
    setPips(-1);
    elStageLabel.textContent = 'Starting…';
    document.getElementById('upd-title').textContent = 'Updating…';
    document.body.style.overflow = 'hidden';
    elModal.querySelector('.upd-box').focus();

    /* Open SSE stream */
    if (_source) { _source.close(); }
    _source = new EventSource(elModal.dataset.streamUrl);

    /* Default message → log line */
    _source.addEventListener('message', function (e) {
      appendLog(e.data);
    });

    /* Stage advance */
    _source.addEventListener('stage', function (e) {
      var s = STAGES[e.data];
      if (!s) { return; }
      setBar(s.pct);
      setPips(parseInt(e.data, 10) - 1);
      elStageLabel.textContent = s.label;
    });

    /* Success */
    _source.addEventListener('success', function () {
      _source.close();
      setBar('100%', 'complete');
      setPips(5);
      elStageLabel.textContent = 'Complete';
      document.getElementById('upd-title').textContent = 'Update complete';
      showResult('✓ Update complete — both services are restarting. This page will refresh in 12 seconds.', true);
      setTimeout(function () { location.reload(); }, 12000);
    });

    /* Already up to date */
    _source.addEventListener('uptodate', function () {
      _source.close();
      setBar('100%', 'complete');
      setPips(5);
      elStageLabel.textContent = 'Up to date';
      document.getElementById('upd-title').textContent = 'Already up to date';
      showResult('✓ Nothing to update — already on the latest version.', true);
      elCloseRow.hidden = false;
    });

    /* Failure */
    _source.addEventListener('fail', function () {
      _source.close();
      elBar.className = 'upd-bar err';
      setPips(elPips.filter(function(p){ return p.classList.contains('complete') || p.classList.contains('active'); }).length - 1, 'err');
      elStageLabel.textContent = 'Failed';
      document.getElementById('upd-title').textContent = 'Update failed';
      showResult('✗ Update failed — see the log above for details.', false);
      elCloseRow.hidden = false;
    });

    /* SSE transport error (e.g. server restarted mid-stream) */
    _source.onerror = function () {
      if (!_source || _source.readyState === EventSource.CLOSED) { return; }
      _source.close();
      /* If we already completed, treat the connection drop as expected */
      if (elBar.classList.contains('complete')) { return; }
      appendLog('Connection lost — the service may be restarting.', true);
      elStageLabel.textContent = 'Connection lost';
      showResult('Connection to the web UI was lost. If an update was in progress, wait a moment then refresh.', false);
      elCloseRow.hidden = false;
    };
  };

  document.getElementById('upd-modal').addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !elCloseRow.hidden) window.closeUpdateModal();
    if (event.key === 'Tab') {
      event.preventDefault();
      if (!elCloseRow.hidden) elCloseRow.querySelector('button').focus();
    }
  });

  /* Close ------------------------------------------------------------ */
  window.closeUpdateModal = function () {
    if (_source) { _source.close(); _source = null; }
    elModal.hidden = true;
    document.body.style.overflow = '';
    if (previousFocus) previousFocus.focus();
  };
})();


(function () {
  var fileInput   = document.getElementById('ah-file-input');
  var previewWrap = document.getElementById('ah-preview-wrap');
  var previewImg  = document.getElementById('ah-preview-img');
  var placeholder = document.getElementById('ah-placeholder');
  var deleteBtn   = document.getElementById('ah-delete-btn');
  var status      = document.getElementById('ah-status');

  if (!fileInput) { return; }

  fileInput.addEventListener('change', function () {
    var file = fileInput.files[0];
    if (!file) { return; }
    var fd = new FormData();
    fd.append('photo', file);
    status.textContent = 'Uploading\u2026';
    fetch('/after-hours/upload', { method: 'POST', body: fd })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          previewImg.src = '/static/uploads/' + data.filename + '?t=' + Date.now();
          previewWrap.style.display = '';
          placeholder.style.display = 'none';
          deleteBtn.style.display = '';
          status.textContent = 'Photo uploaded successfully.';
        } else {
          status.textContent = 'Upload failed: ' + (data.error || 'unknown error');
        }
      })
      .catch(function (err) { status.textContent = 'Upload error: ' + err; });
    fileInput.value = '';
  });

  window.ahDelete = function () {
    status.textContent = 'Deleting\u2026';
    fetch('/after-hours/delete', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          previewImg.src = '';
          previewWrap.style.display = 'none';
          placeholder.style.display = 'flex';
          deleteBtn.style.display = 'none';
          status.textContent = 'Photo deleted.';
        } else {
          status.textContent = 'Delete failed.';
        }
      })
      .catch(function (err) { status.textContent = 'Delete error: ' + err; });
  };
})();
