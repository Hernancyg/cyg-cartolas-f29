// Buscador de cuentas ("Concepto") para la pestaña Conciliación. Vainilla
// JS, sin dependencias: filtra window.CYG_PLAN_CUENTAS (código +
// descripción) por texto, con navegación de teclado, y mantiene las
// métricas de "Conciliados"/"Pendientes" al día según cuántas filas
// tengan una cuenta seleccionada.
(function () {
  var CUENTAS = window.CYG_PLAN_CUENTAS || [];
  var MAX_RESULTADOS = 8;
  var activo = null; // { input, results, items, index }

  function normalizar(s) {
    return (s || "")
      .toString()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, ""); // sin tildes, para que "econom" encuentre "económico"
  }

  function buscar(texto) {
    var q = normalizar(texto).trim();
    if (!q) return [];
    var partes = q.split(/\s+/);
    return CUENTAS.filter(function (c) {
      var hay = normalizar(c.codigo + " " + c.descripcion);
      return partes.every(function (p) { return hay.indexOf(p) !== -1; });
    }).slice(0, MAX_RESULTADOS);
  }

  function actualizarContadores() {
    var filas = document.querySelectorAll(".fila-conciliacion");
    var conciliados = 0;
    filas.forEach(function (fila) {
      var codigo = fila.querySelector(".cuenta-codigo");
      if (codigo && codigo.value) conciliados++;
    });
    var total = filas.length;
    var elTotal = document.getElementById("stat-total");
    var elConc = document.getElementById("stat-conciliados");
    var elPend = document.getElementById("stat-pendientes");
    if (elTotal) elTotal.textContent = total;
    if (elConc) elConc.textContent = conciliados;
    if (elPend) elPend.textContent = total - conciliados;

    // Si el admin ya corrigió lo que faltaba (todas las filas conciliadas
    // y la cuenta bancaria elegida), se limpia el aviso de error en vez de
    // dejarlo pegado en pantalla hasta el próximo intento de descarga.
    var bancoCodigo = document.getElementById("cuenta-banco-codigo");
    var errorBox = document.getElementById("conciliacion-error");
    if (errorBox && !errorBox.hidden && conciliados === total && bancoCodigo && bancoCodigo.value) {
      errorBox.hidden = true;
    }
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
        // mousedown (no click) para que dispare antes que el "blur" del input
        ev.preventDefault();
        seleccionar(input, cuenta);
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

  function seleccionar(input, cuenta) {
    var fila = input.closest(".fila-conciliacion") || input.closest("tr");
    input.value = cuenta.codigo + " — " + cuenta.descripcion;
    var codigoInput = input.parentElement.querySelector(".cuenta-codigo");
    var descInput = input.parentElement.querySelector(".cuenta-descripcion");
    if (codigoInput) codigoInput.value = cuenta.codigo;
    if (descInput) descInput.value = cuenta.descripcion;
    if (fila) fila.classList.add("fila-conciliada");
    cerrarDropdown();
    actualizarContadores();
  }

  document.addEventListener("input", function (ev) {
    var input = ev.target.closest(".cuenta-search-input");
    if (!input) return;
    var wrap = input.closest(".cuenta-search");
    var resultsEl = wrap && wrap.querySelector(".cuenta-search-results");
    if (!resultsEl) return;

    // Si el usuario borra el texto tras haber elegido una cuenta, la fila
    // vuelve a quedar "pendiente" en vez de arrastrar una cuenta fantasma.
    var codigoInput = wrap.querySelector(".cuenta-codigo");
    var descInput = wrap.querySelector(".cuenta-descripcion");
    if (codigoInput && codigoInput.value) {
      var fila = input.closest(".fila-conciliacion");
      codigoInput.value = "";
      if (descInput) descInput.value = "";
      if (fila) fila.classList.remove("fila-conciliada");
      actualizarContadores();
    }

    renderResultados(input, resultsEl, buscar(input.value));
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
        seleccionar(input, activo.items[activo.index]);
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
      renderResultados(input, resultsEl, buscar(input.value));
    }
  });

  document.addEventListener("focusout", function (ev) {
    var input = ev.target.closest(".cuenta-search-input");
    if (!input) return;
    // pequeño delay: el mousedown del item ya alcanzó a correr antes de esto.
    // Solo cerramos el dropdown de ESTE input: si el usuario ya enfocó otra
    // fila y abrió su propio dropdown antes de que venza el delay, "activo"
    // habrá cambiado y no debemos pisarlo.
    setTimeout(function () {
      if (activo && activo.input === input) cerrarDropdown();
    }, 120);
  });

  actualizarContadores();

  // Validación antes de descargar (09-09-2026, ronda del archivo de
  // salida): la cuenta bancaria de arriba y el "Concepto" de cada fila
  // son obligatorios para poder armar los comprobantes — si falta algo,
  // se avisa en pantalla en vez de dejar que el servidor lo rechace sin
  // explicación. Se registra en fase de "capture" (tercer argumento
  // true) para que corra ANTES que el listener de `base.html` que
  // muestra el overlay de carga global: así, si esta validación cancela
  // el envío con `preventDefault()`, ese overlay ya no llega a mostrarse
  // (revisa `event.defaultPrevented` antes de mostrarse él mismo).
  document.addEventListener("submit", function (ev) {
    var form = ev.target.closest("#form-conciliacion");
    if (!form) return;
    var errorBox = document.getElementById("conciliacion-error");
    var problemas = [];

    var bancoCodigo = document.getElementById("cuenta-banco-codigo");
    var bancoFalta = !bancoCodigo || !bancoCodigo.value;
    if (bancoFalta) {
      problemas.push("Selecciona arriba la cuenta bancaria con la que se está conciliando esta cartola.");
    }

    var filasSinConcepto = [];
    document.querySelectorAll(".fila-conciliacion").forEach(function (fila) {
      var codigo = fila.querySelector(".cuenta-codigo");
      if (!codigo || !codigo.value) {
        filasSinConcepto.push(parseInt(fila.dataset.row, 10) + 1);
      }
    });
    if (filasSinConcepto.length === 1) {
      problemas.push("Clasifica el movimiento de la fila " + filasSinConcepto[0] + " antes de descargar.");
    } else if (filasSinConcepto.length > 1) {
      problemas.push("Clasifica los movimientos de las filas " + filasSinConcepto.join(", ") + " antes de descargar.");
    }

    if (!problemas.length) {
      if (errorBox) errorBox.hidden = true;
      return; // todo listo, el formulario se envía normalmente
    }

    ev.preventDefault();
    if (errorBox) {
      errorBox.textContent = problemas.join("\n");
      errorBox.hidden = false;
      errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    if (bancoFalta) {
      var bancoInput = document.getElementById("cuenta-banco-input");
      if (bancoInput) bancoInput.focus();
    } else if (filasSinConcepto.length) {
      var primeraFila = document.querySelector('.fila-conciliacion[data-row="' + (filasSinConcepto[0] - 1) + '"]');
      var primerInput = primeraFila && primeraFila.querySelector(".cuenta-search-input");
      if (primerInput) primerInput.focus();
    }
  }, true);
})();
