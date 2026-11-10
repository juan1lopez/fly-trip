// Live search: streams results from /buscar/stream into #status and #results.
// Server-rendered, autoescaped HTML fragments only; no eval, no inline handlers.
(function () {
  "use strict";
  var form = document.getElementById("search-form");
  if (!form) return;
  var statusEl = document.getElementById("status");
  var resultsEl = document.getElementById("results");
  var errorsEl = document.getElementById("errors");
  var source = null;
  var searchId = 0;
  var lastParams = "";

  function close() {
    if (source) {
      source.close();
      source = null;
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    run(new URLSearchParams(new FormData(form)).toString(), false);
  });

  // -- search mode and month pills ------------------------------------------------------
  var modeInput = form.elements["modo"];
  var monthFields = document.getElementById("month-fields");
  var dateFields = document.getElementById("date-fields");
  var toggle = document.getElementById("toggle-mode");
  var pills = Array.prototype.slice.call(form.querySelectorAll("#month-pills [data-month]"));

  function setMode(mode) {
    modeInput.value = mode;
    monthFields.hidden = mode !== "mes";
    dateFields.hidden = mode === "mes";
    toggle.textContent = mode === "mes" ? "Fechas exactas" : "Buscar por mes";
    toggle.setAttribute("aria-expanded", mode === "mes" ? "false" : "true");
  }

  toggle.addEventListener("click", function () {
    setMode(modeInput.value === "mes" ? "fechas" : "mes");
  });

  // The selection is always a contiguous range (at most 4 months, which the server enforces).
  function selectRange(first, last) {
    pills.forEach(function (pill) {
      var on = pill.dataset.month >= first && pill.dataset.month <= last;
      pill.classList.toggle("on", on);
      pill.setAttribute("aria-pressed", on ? "true" : "false");
    });
    form.elements["mes"].value = first;
    form.elements["hasta_mes"].value = last;
  }

  pills.forEach(function (pill, index) {
    pill.addEventListener("click", function () {
      var month = pill.dataset.month;
      var first = form.elements["mes"].value;
      var last = form.elements["hasta_mes"].value;
      if (month < first) first = month;
      else if (month > last) last = month;
      else if (month === first && first !== last) first = pills[index + 1].dataset.month;
      else if (month === last && first !== last) last = pills[index - 1].dataset.month;
      else if (first !== last) {
        first = month;
        last = month;
      }
      selectRange(first, last);
    });
  });

  // A calendar day searches exact dates for that day and that origin, keeping everything else
  // of the search that drew the calendar (lastParams). The form itself is not touched.
  resultsEl.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("button[data-day]");
    if (!button) return;
    var params = new URLSearchParams(
      lastParams || new URLSearchParams(new FormData(form)).toString()
    );
    params.set("modo", "fechas");
    params.set("desde", button.dataset.day);
    params.set("hasta", button.dataset.day);
    params.delete("origenes");
    params.append("origenes", button.dataset.origin);
    run(params.toString(), false);
  });

  // "Actualizar" re-runs the same search, ignoring the cache; later edits to the form do not count.
  resultsEl.addEventListener("click", function (event) {
    if (event.target.closest && event.target.closest("#refresh") && lastParams) {
      run(lastParams, true);
    }
  });

  // aria-busy keeps screen readers from announcing every partial update of #results.
  function busy(on) {
    resultsEl.setAttribute("aria-busy", on ? "true" : "false");
  }

  function run(params, refresh) {
    lastParams = params;
    close();
    busy(true);
    errorsEl.innerHTML = "";
    statusEl.innerHTML = "";
    resultsEl.innerHTML = "";
    var id = ++searchId;
    var stale = function () {
      return id !== searchId;
    };

    // Validate first: EventSource cannot read the body of a 422, and this never starts a search.
    fetch("/buscar/validar?" + params)
      .then(function (response) {
        if (stale()) return;
        if (response.status === 422) {
          return response.text().then(function (html) {
            if (stale()) return;
            errorsEl.innerHTML = html;
            busy(false);
          });
        }
        if (!response.ok) throw new Error("validate");
        stream("/buscar/stream?" + params + (refresh ? "&refrescar=1" : ""), stale);
      })
      .catch(function () {
        if (stale()) return;
        errorsEl.innerHTML = "<p>No se pudo completar la búsqueda.</p>";
        busy(false);
      });
  }

  function stream(url, stale) {
    var received = false;
    var finished = false;
    source = new EventSource(url);
    function finish() {
      finished = true;
      close();
      if (!stale()) busy(false);
    }
    source.addEventListener("status", function (e) {
      if (stale()) return finish();
      received = true;
      statusEl.innerHTML = e.data;
    });
    source.addEventListener("results", function (e) {
      if (stale()) return finish();
      received = true;
      resultsEl.innerHTML = e.data;
    });
    source.addEventListener("error", function (e) {
      // Server-sent "error" event (has data); connection errors have none.
      if (!e.data || stale()) return;
      errorsEl.innerHTML = e.data;
      finish();
    });
    source.addEventListener("done", finish);
    source.onerror = function () {
      if (finished) return;
      finish();
      if (stale()) return;
      errorsEl.innerHTML = received
        ? "<p>Se perdió la conexión con la búsqueda.</p>"
        : "<p>No se pudo completar la búsqueda.</p>";
    };
  }
})();
