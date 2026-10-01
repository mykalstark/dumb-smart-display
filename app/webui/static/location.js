/* Explicit searches: no autocomplete requests or address lookup on page load. */
(function () {
  'use strict';
  var picker = document.querySelector('.location-picker');
  if (!picker) return;
  var query = document.getElementById('location-query');
  var button = document.getElementById('location-search-button');
  var status = document.getElementById('location-search-status');
  var results = document.getElementById('location-results');
  var list = document.getElementById('location-result-list');
  var address = document.getElementById('location__address');
  var latitude = document.getElementById('location__latitude');
  var longitude = document.getElementById('location__longitude');
  var selected = document.getElementById('location-selected-label');
  var requestId = 0;
  var controller;

  function pendingSelection() {
    query.setCustomValidity(query.value.trim() && query.value.trim() !== address.value
      ? 'Choose a matching location before saving, or clear the search to keep your current location.' : '');
  }
  function clearResults() {
    results.hidden = true;
    list.replaceChildren();
  }
  query.addEventListener('input', function () {
    requestId++;
    if (controller) controller.abort();
    button.disabled = false;
    button.removeAttribute('aria-busy');
    clearResults();
    status.textContent = '';
    pendingSelection();
  });
  query.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') { event.preventDefault(); search(); }
  });

  async function search() {
    var text = query.value.trim();
    if (text.length < 3) {
      status.textContent = 'Enter a city and state or a street address to search.';
      query.focus();
      return;
    }
    var current = ++requestId;
    if (controller) controller.abort();
    controller = new AbortController();
    clearResults();
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    status.textContent = 'Finding matching locations…';
    try {
      var response = await fetch(picker.dataset.searchUrl, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: text }), signal: controller.signal,
      });
      if (response.redirected) throw new Error('Your session expired. Sign in again to search.');
      var data = await response.json();
      if (current !== requestId) return;
      if (!response.ok) throw new Error(data.error || 'Search is unavailable. Please try again.');
      if (!data.results.length) {
        status.textContent = 'No matching locations. Try adding your state, postal code, or country.';
        return;
      }
      data.results.forEach(function (place) {
        var choice = document.createElement('button');
        choice.type = 'button';
        choice.className = 'location-result';
        choice.textContent = place.label;
        choice.addEventListener('click', function () {
          latitude.value = place.latitude;
          longitude.value = place.longitude;
          address.value = place.label;
          query.value = place.label;
          selected.textContent = place.label;
          query.setCustomValidity('');
          clearResults();
          status.textContent = 'Location selected. Save & restart to apply it.';
          query.dispatchEvent(new Event('change', { bubbles: true }));
          query.focus();
        });
        list.appendChild(choice);
      });
      results.hidden = false;
      status.textContent = data.results.length + ' matching location' + (data.results.length === 1 ? '.' : 's.') + ' Choose the right one below.';
    } catch (error) {
      if (current !== requestId || error.name === 'AbortError') return;
      status.textContent = error.message === 'Failed to fetch'
        ? 'Could not connect. Please try again, or use manual coordinates.' : error.message;
    } finally {
      if (current === requestId) { button.disabled = false; button.removeAttribute('aria-busy'); }
    }
  }
  button.addEventListener('click', search);
  [latitude, longitude].forEach(function (input) {
    input.addEventListener('input', function () {
      requestId++;
      if (controller) controller.abort();
      button.disabled = false;
      button.removeAttribute('aria-busy');
      address.value = '';
      query.value = '';
      query.setCustomValidity('');
      clearResults();
      status.textContent = '';
      selected.textContent = 'Using manually entered coordinates.';
    });
  });
})();
