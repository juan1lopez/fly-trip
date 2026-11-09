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
    var url = "/buscar/stream?" + params;

    var received = false;
    source = new EventSource(url);
    source.addEventListener("status", function (e) {
      received = true;
      statusEl.innerHTML = e.data;
    });
    source.addEventListener("results", function (e) {
      received = true;
      resultsEl.innerHTML = e.data;
    });
    source.addEventListener("done", close);
    source.onerror = function () {
      close();
      if (received) return;
      // EventSource hides the body of a 422: ask again (validation is cheap, no search runs).
      fetch(url).then(function (response) {
        return response.text().then(function (html) {
          errorsEl.innerHTML =
            response.status === 422 ? html : "<p>No se pudo completar la búsqueda.</p>";
          if (response.body && response.body.cancel) response.body.cancel();
        });
      });
    };
  });
})();
