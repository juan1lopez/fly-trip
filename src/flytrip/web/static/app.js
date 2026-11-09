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

  function close() {
    if (source) {
      source.close();
      source = null;
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    close();
    errorsEl.innerHTML = "";
    statusEl.innerHTML = "";
    resultsEl.innerHTML = "";
    var params = new URLSearchParams(new FormData(form)).toString();
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
            if (!stale()) errorsEl.innerHTML = html;
          });
        }
        if (!response.ok) throw new Error("validate");
        stream("/buscar/stream?" + params, stale);
      })
      .catch(function () {
        if (!stale()) errorsEl.innerHTML = "<p>No se pudo completar la búsqueda.</p>";
      });
  });

  function stream(url, stale) {
    var received = false;
    var finished = false;
    source = new EventSource(url);
    function finish() {
      finished = true;
      close();
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
