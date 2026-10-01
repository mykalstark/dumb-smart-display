/* Shared interactions for the local control panel. */
(function () {
  'use strict';
  document.documentElement.classList.add('enhanced');

  window.togglePw = function (id, button) {
    var input = document.getElementById(id);
    var show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.textContent = show ? 'Hide' : 'Show';
    button.setAttribute('aria-pressed', String(show));
    var label = button.dataset.fieldLabel || button.getAttribute('aria-label').replace(/^Show /, '');
    button.dataset.fieldLabel = label;
    button.setAttribute('aria-label', (show ? 'Hide ' : 'Show ') + label);
  };

  window.toggleSection = function (name, forceOpen) {
    var header = document.getElementById('hdr-' + name);
    var body = document.getElementById('body-' + name);
    var open = typeof forceOpen === 'boolean' ? forceOpen : !body.classList.contains('visible');
    header.classList.toggle('open', open);
    header.setAttribute('aria-expanded', String(open));
    body.classList.toggle('visible', open);
  };

  function updateCount() {
    var count = document.querySelectorAll('input[name^="modules__enabled__"]:checked, #module-list input[type="checkbox"]:checked').length;
    document.querySelectorAll('[data-enabled-count]').forEach(function (el) { el.textContent = count; });
  }

  window.syncModuleSection = function (name, enabled, initial) {
    var section = document.getElementById('section-' + name);
    section.querySelectorAll('[data-required]').forEach(function (input) { input.required = enabled; });
    var status = section.querySelector('[data-module-status]');
    status.textContent = enabled ? 'Enabled' : 'Disabled';
    status.classList.toggle('off', !enabled);
    if (enabled && !initial) window.toggleSection(name, true);
    updateCount();
  };

  var tabs = Array.from(document.querySelectorAll('[data-settings-tab]'));
  var panels = Array.from(document.querySelectorAll('.settings-panel'));
  function selectPanel(id, focus) {
    var chosen = document.getElementById(id);
    if (!panels.includes(chosen)) return;
    panels.forEach(function (panel) { panel.hidden = panel !== chosen; });
    tabs.forEach(function (tab) {
      var selected = tab.hash === '#' + id;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
  }
  function followHash() {
    var id = location.hash.slice(1);
    if (id.indexOf('module-') === 0 && document.getElementById('section-' + id.slice(7))) {
      selectPanel('module-settings');
      window.toggleSection(id.slice(7), true);
      document.getElementById('hdr-' + id.slice(7)).focus();
    } else {
      selectPanel(panels.some(function (p) { return p.id === id; }) ? id : 'general');
    }
  }
  if (tabs.length) {
    document.querySelector('.settings-tabs').setAttribute('role', 'tablist');
    tabs.forEach(function (tab, i) {
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-controls', tab.hash.slice(1));
      tab.addEventListener('click', function (event) {
        event.preventDefault();
        selectPanel(tab.hash.slice(1));
        history.replaceState(null, '', tab.hash);
      });
      tab.addEventListener('keydown', function (event) {
        var index;
        if (event.key === 'ArrowRight') index = (i + 1) % tabs.length;
        if (event.key === 'ArrowLeft') index = (i + tabs.length - 1) % tabs.length;
        if (event.key === 'Home') index = 0;
        if (event.key === 'End') index = tabs.length - 1;
        if (index === undefined) return;
        event.preventDefault();
        selectPanel(tabs[index].hash.slice(1), true);
        history.replaceState(null, '', tabs[index].hash);
      });
    });
    panels.forEach(function (panel) { panel.setAttribute('role', 'tabpanel'); });
    followHash();
    window.addEventListener('hashchange', followHash);
    document.querySelectorAll('input[name^="modules__enabled__"]').forEach(function (input) {
      window.syncModuleSection(input.id.replace('mod_en_', ''), input.checked, true);
    });
    document.getElementById('config-form').addEventListener('invalid', function (event) {
      // Report the first invalid field; later panels must not hide it again.
      var first = this.querySelector('input:invalid, select:invalid, textarea:invalid');
      if (first && event.target !== first) { event.preventDefault(); return; }
      var panel = event.target.closest('.settings-panel');
      if (panel) selectPanel(panel.id);
      var section = event.target.closest('.module-section');
      if (section) window.toggleSection(section.id.replace('section-', ''), true);
      var details = event.target.closest('details');
      if (details) details.open = true;
    }, true);
    document.getElementById('location__location_name').addEventListener('input', function (event) {
      document.getElementById('summary-location').textContent = event.target.value || 'Not set';
    });
    document.getElementById('hardware__simulate').addEventListener('change', function (event) {
      document.getElementById('summary-mode').textContent = event.target.checked ? 'Simulator' : 'Hardware';
    });
  }

  window.addEvent = function (listId, prefix) {
    var list = document.getElementById(listId);
    var index = list.children.length;
    var row = document.createElement('div');
    row.className = 'event-row';
    [['text', 'name', 'Event name'], ['date', 'date', 'Event date']].forEach(function (item) {
      var input = document.createElement('input');
      input.type = item[0];
      input.name = prefix + '__' + index + '__' + item[1];
      input.placeholder = item[2];
      input.setAttribute('aria-label', item[2]);
      row.appendChild(input);
    });
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn-remove-event';
    button.textContent = 'Remove';
    button.addEventListener('click', function () { window.removeEvent(button); });
    row.appendChild(button);
    list.appendChild(row);
    row.querySelector('input').focus();
    list.dispatchEvent(new Event('change', { bubbles: true }));
  };
  window.removeEvent = function (button) {
    var list = button.closest('.events-list');
    button.closest('.event-row').remove();
    list.querySelectorAll('.event-row').forEach(function (row, i) {
      row.querySelectorAll('input').forEach(function (input) { input.name = input.name.replace(/__\d+__/, '__' + i + '__'); });
    });
    list.parentElement.querySelector('.btn-add-event').focus();
    list.dispatchEvent(new Event('change', { bubbles: true }));
  };

  /* Compare current values to their initial state, including structural edits. */
  var form = document.querySelector('[data-dirty-form]');
  if (form) {
    var dirty = false;
    var submitting = false;
    var bar = document.querySelector('.save-bar');
    function snapshot() {
      var controls = form.id === 'modules-form' ? document.querySelectorAll('#module-list input') : form.querySelectorAll('input[name], select[name], textarea[name]');
      return JSON.stringify(Array.from(controls).map(function (el) {
        return [el.name, el.type === 'checkbox' ? el.checked : el.value];
      }));
    }
    var initial = snapshot();
    function checkChanges() {
      dirty = snapshot() !== initial;
      bar.classList.toggle('dirty', dirty);
      bar.querySelector('.save-state').textContent = dirty ? 'Unsaved changes' : 'No unsaved changes';
    }
    document.addEventListener('input', checkChanges);
    document.addEventListener('change', checkChanges);
    document.addEventListener('modules-reordered', checkChanges);
    form.addEventListener('submit', function () {
      submitting = true;
      bar.querySelector('.save-state').textContent = 'Saving changes…';
      bar.querySelector('button[type="submit"]').setAttribute('aria-busy', 'true');
    });
    window.addEventListener('beforeunload', function (event) {
      if (dirty && !submitting) { event.preventDefault(); event.returnValue = ''; }
    });
  }
})();
