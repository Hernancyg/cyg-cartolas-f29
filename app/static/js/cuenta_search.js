// Buscador de cuentas del plan de cuentas (mismo patrón que
// caja_empresas.js/conciliacion.js, extraído en un archivo propio sin la
// llamada a `recomputar()` — específica del saldo corrido de Empresas
// Caja, no aplica en páginas que solo necesitan elegir una cuenta, como
// "Depreciación → Cuentas contables").
//
// Requiere `window.CYG_PLAN_CUENTAS` (lista de {codigo, descripcion,
// es_banco, requiere_centro_costo}) y la misma estructura HTML que la
// macro `cuenta_search` de app/templates/caja_empresas/_macros.html
// (`.cuenta-search` > `.cuenta-search-input` + `.cuenta-codigo` +
// `.cuenta-descripcion` + `.cuenta-search-results`).
(function () {
  var CUENTAS = window.CYG_PLAN_CUENTAS || [];
  var MAX_RESULTADOS = 8;
  var activo = null; // { input, results, items, index }

  function normalizar(s) {
    return (s || "")
      .toString()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "");
  }

  function buscarCuentas(texto) {
    var q = normalizar(texto).trim();
    if (!q) return [];
    var partes = q.split(/\s+/);
    return CUENTAS.filter(function (c) {
      var hay = normalizar(c.codigo + " " + c.descripcion);
      return partes.every(function (p) { return hay.indexOf(p) !== -1; });
    }).slice(0, MAX_RESULTADOS);
  }

  function cerrarDropdown() {
    if (!activo) return;
    activo.results.hidden = true;
    activo.results.innerHTML = "";
    activo = null;
  }

  function renderResultados(input, resultsEl, lista) {
    resultsEl.innerHTML = "";
    if (!lista.length) {
      resultsEl.hidden = true;
      activo = null;
      return;
    }
    lista.forEach(function (cuenta, i) {
      var item = document.createElement("div");
      item.className = "cuenta-search-item";
      item.dataset.index = i;
      item.innerHTML =
        '<span class="cuenta-search-item-codigo">' + cuenta.codigo + "</span>" +
        '<span class="cuenta-search-item-desc">' + cuenta.descripcion + "</span>";
      item.addEventListener("mousedown", function (ev) {
        ev.preventDefault();
        seleccionarCuenta(input, cuenta);
      });
      resultsEl.appendChild(item);
    });
    resultsEl.hidden = false;
    activo = { input: input, results: resultsEl, items: lista, index: -1 };
  }

  function marcarActivo(index) {
    if (!activo) return;
    var nodos = activo.results.querySelectorAll(".cuenta-search-item");
    nodos.forEach(function (n) { n.classList.remove("active"); });
    if (index >= 0 && index < nodos.length) {
      nodos[index].classList.add("active");
      nodos[index].scrollIntoView({ block: "nearest" });
    }
    activo.index = index;
  }

  function seleccionarCuenta(input, cuenta) {
    var wrap = input.closest(".cuenta-search");
    input.value = cuenta.codigo + " — " + cuenta.descripcion;
    var codigoInput = wrap.querySelector(".cuenta-codigo");
    var descInput = wrap.querySelector(".cuenta-descripcion");
    if (codigoInput) codigoInput.value = cuenta.codigo;
    if (descInput) descInput.value = cuenta.descripcion;
    cerrarDropdown();
  }

  document.addEventListener("input", function (ev) {
    var input = ev.target.closest(".cuenta-search-input");
    if (!input) return;
    var wrap = input.closest(".cuenta-search");
    var resultsEl = wrap && wrap.querySelector(".cuenta-search-results");
    if (!resultsEl) return;

    var codigoInput = wrap.querySelector(".cuenta-codigo");
    var descInput = wrap.querySelector(".cuenta-descripcion");
    if (codigoInput && codigoInput.value) {
      codigoInput.value = "";
      if (descInput) descInput.value = "";
    }

    renderResultados(input, resultsEl, buscarCuentas(input.value));
    if (activo) marcarActivo(-1);
  });

  document.addEventListener("keydown", function (ev) {
    var input = ev.target.closest(".cuenta-search-input");
    if (!input || !activo || activo.input !== input) return;
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      marcarActivo(Math.min(activo.index + 1, activo.items.length - 1));
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      marcarActivo(Math.max(activo.index - 1, 0));
    } else if (ev.key === "Enter") {
      if (activo.index >= 0) {
        ev.preventDefault();
        seleccionarCuenta(input, activo.items[activo.index]);
      }
    } else if (ev.key === "Escape") {
      cerrarDropdown();
    }
  });

  document.addEventListener("focusin", function (ev) {
    var input = ev.target.closest(".cuenta-search-input");
    if (!input) return;
    var wrap = input.closest(".cuenta-search");
    var resultsEl = wrap && wrap.querySelector(".cuenta-search-results");
    if (resultsEl && input.value.trim()) {
      renderResultados(input, resultsEl, buscarCuentas(input.value));
    }
  });

  document.addEventListener("focusout", function (ev) {
    var input = ev.target.closest(".cuenta-search-input");
    if (!input) return;
    setTimeout(function () {
      if (activo && activo.input === input) cerrarDropdown();
    }, 120);
  });
})();
