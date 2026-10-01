(function () {
  'use strict';
  var list = document.getElementById('module-list');
  var dragged = null;
  function updatePositions(announce) {
    var items = Array.from(list.children);
    var position = 0;
    items.forEach(function (item, i) {
      var enabled = item.querySelector('input[type="checkbox"]').checked;
      var badge = item.querySelector('.position-badge');
      badge.textContent = enabled ? String(++position).padStart(2, '0') : '—';
      badge.setAttribute('aria-label', enabled ? 'Playback position ' + position : 'Excluded from playback');
      item.classList.toggle('disabled-item', !enabled);
      var status = item.querySelector('[data-module-status]');
      status.textContent = enabled ? 'Enabled' : 'Disabled';
      status.classList.toggle('off', !enabled);
      item.querySelector('[data-move="up"]').disabled = i === 0;
      item.querySelector('[data-move="down"]').disabled = i === items.length - 1;
    });
    document.querySelectorAll('[data-enabled-count]').forEach(function (el) { el.textContent = position; });
    if (announce) document.getElementById('reorder-status').textContent = announce;
    document.dispatchEvent(new Event('modules-reordered'));
  }

  list.addEventListener('click', function (event) {
    var button = event.target.closest('[data-move]');
    if (!button) return;
    var item = button.closest('.module-item');
    if (button.dataset.move === 'up' && item.previousElementSibling) {
      list.insertBefore(item, item.previousElementSibling);
    } else if (button.dataset.move === 'down' && item.nextElementSibling) {
      list.insertBefore(item.nextElementSibling, item);
    }
    updatePositions(item.dataset.label + ' moved to row ' + (Array.from(list.children).indexOf(item) + 1) + '.');
    // Retain keyboard focus even when the chosen direction reaches its boundary.
    var focus = button.disabled ? item.querySelector('[data-move="' + (button.dataset.move === 'up' ? 'down' : 'up') + '"]') : button;
    focus.focus();
  });
  list.addEventListener('change', function () { updatePositions(); });
  list.addEventListener('dragstart', function (event) {
    var item = event.target.closest('.module-item');
    if (!item) return;
    dragged = item;
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', item.dataset.module);
    setTimeout(function () { if (dragged === item) item.classList.add('dragging'); }, 0);
  });
  list.addEventListener('dragover', function (event) {
    if (!dragged) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    var target = event.target.closest('.module-item');
    if (!target || target === dragged) return;
    list.querySelectorAll('.module-item').forEach(function (item) { item.classList.remove('drag-over'); });
    target.classList.add('drag-over');
    var rect = target.getBoundingClientRect();
    list.insertBefore(dragged, event.clientY > rect.top + rect.height / 2 ? target.nextSibling : target);
  });
  list.addEventListener('drop', function (event) { if (dragged) event.preventDefault(); });
  list.addEventListener('dragend', function () {
    var label = dragged ? dragged.dataset.label : '';
    list.querySelectorAll('.module-item').forEach(function (item) { item.classList.remove('dragging', 'drag-over'); });
    dragged = null;
    updatePositions(label ? label + ' reordered.' : '');
  });
  updatePositions();
})();
