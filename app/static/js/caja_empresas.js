// "Empresas Caja": buscador de cuentas (mismo patrón que conciliacion.js),
// carga AJAX de los 3 archivos de documentos (Clientes/Proveedores/
// Honorarios) sin recargar la página, y cálculo en vivo del saldo corrido
// mostrado como subtotal después de cada módulo — incluyendo mostrar u
// ocultar el panel de "Préstamo Socio" según si el saldo queda negativo.
(function () {
  var CUENTAS = window.CYG_PLAN_CUENTAS || [];
  var MAX_RESULTADOS = 8;
  var activo = null; // { input, results, items, index }

  function normalizar(s) {
    return (s || "")
      .toString()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
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
    recomputar();
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
      recomputar();
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

  // ---------------------------------------------------------------------
  // Carga AJAX de los 3 archivos de documentos.
  // ---------------------------------------------------------------------

  function csrfToken() {
    var el = document.getElementById("csrf-token-global");
    return el ? el.value : "";
  }

  function cargarModulo(modulo) {
    var fileInput = document.getElementById("archivo-" + modulo);
    var boton = document.querySelector('[data-cargar-modulo="' + modulo + '"]');
    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
      alert("Elige primero un archivo para " + modulo + ".");
      return;
    }
    var datos = new FormData();
    datos.append("archivo", fileInput.files[0]);
    datos.append("csrf_token", csrfToken());

    var textoOriginal = boton ? boton.innerHTML : "";
    if (boton) { boton.disabled = true; boton.textContent = "Cargando…"; }

    var errorBox = document.getElementById("error-" + modulo);
    var wrap = document.getElementById("wrap-" + modulo);

    fetch("/caja_empresas/cargar/" + modulo, { method: "POST", body: datos })
      .then(function (resp) { return resp.text().then(function (html) { return { ok: resp.ok, html: html }; }); })
      .then(function (result) {
        if (result.ok) {
          if (errorBox) { errorBox.hidden = true; errorBox.innerHTML = ""; }
          if (wrap) wrap.innerHTML = result.html;
        } else if (errorBox) {
          // Un archivo inválido no borra lo que ya estaba cargado — solo
          // se avisa el problema junto al botón de carga de este módulo.
          errorBox.innerHTML = result.html;
          errorBox.hidden = false;
        }
        recomputar();
      })
      .catch(function () {
        if (errorBox) {
          errorBox.innerHTML = '<div class="alert alert-error">No se pudo cargar el archivo — intenta de nuevo.</div>';
          errorBox.hidden = false;
        }
      })
      .finally(function () {
        if (boton) { boton.disabled = false; boton.innerHTML = textoOriginal; }
      });
  }

  document.addEventListener("click", function (ev) {
    var boton = ev.target.closest("[data-cargar-modulo]");
    if (!boton) return;
    ev.preventDefault();
    cargarModulo(boton.dataset.cargarModulo);
  });

  // ---------------------------------------------------------------------
  // Saldo corrido en vivo.
  // ---------------------------------------------------------------------

  function num(v) {
    var n = parseFloat(v);
    return isNaN(n) ? 0 : n;
  }

  function formatoClp(n) {
    var signo = n < 0 ? "-" : "";
    var entero = Math.round(Math.abs(n)).toString();
    var conPuntos = entero.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return "$" + signo + conPuntos;
  }

  function totalDocumentosSeleccionados(modulo) {
    var total = 0;
    document.querySelectorAll('.fila-documento[data-modulo="' + modulo + '"]').forEach(function (fila) {
      var chk = fila.querySelector(".chk-documento");
      var montoInput = fila.querySelector('input[name^="' + modulo + '_monto_"]');
      if (chk && chk.checked && montoInput) total += num(montoInput.value);
    });
    return total;
  }

  function totalMensual(prefijo) {
    var total = 0;
    document.querySelectorAll('.input-monto-mes[data-prefijo="' + prefijo + '"]').forEach(function (input) {
      total += num(input.value);
    });
    return total;
  }

  function setMetric(id, valor) {
    var el = document.getElementById(id);
    if (el) el.textContent = formatoClp(valor);
  }

  function recomputar() {
    var saldoInicialInput = document.getElementById("saldo-inicial");
    var saldo = num(saldoInicialInput ? saldoInicialInput.value : 0);

    saldo += totalDocumentosSeleccionados("clientes");
    setMetric("subtotal-clientes", saldo);

    saldo -= totalDocumentosSeleccionados("proveedores");
    setMetric("subtotal-proveedores", saldo);

    saldo -= totalDocumentosSeleccionados("honorarios");
    setMetric("subtotal-honorarios", saldo);

    saldo -= totalMensual("f29");
    setMetric("subtotal-f29", saldo);

    saldo -= totalMensual("remimp");
    setMetric("subtotal-remimp", saldo);

    saldo -= totalMensual("credito");
    setMetric("subtotal-credito", saldo);

    var panel = document.getElementById("panel-prestamo-socio");
    var check = document.getElementById("prestamo-socio-check");
    if (panel && check) {
      if (saldo < 0) {
        panel.hidden = false;
      } else if (!check.checked) {
        panel.hidden = true;
      }
      var prestamoMonto = check.checked ? num(document.getElementById("prestamo-socio-monto").value) : 0;
      saldo += prestamoMonto;
    }

    setMetric("saldo-final", saldo);
    var metricFinal = document.getElementById("metric-saldo-final");
    if (metricFinal) metricFinal.classList.toggle("warn", saldo < 0);
  }

  document.addEventListener("input", function (ev) {
    if (ev.target.id === "saldo-inicial" || ev.target.classList.contains("input-monto-mes") || ev.target.id === "prestamo-socio-monto") {
      recomputar();
    }
  });
  document.addEventListener("change", function (ev) {
    if (ev.target.classList.contains("chk-documento") || ev.target.id === "prestamo-socio-check") {
      recomputar();
    }
  });

  // ---------------------------------------------------------------------
  // Validación antes de generar (convención ya usada en conciliacion.js):
  // corre en fase de "capture" para llegar antes que el overlay de carga
  // global de base.html.
  // ---------------------------------------------------------------------

  document.addEventListener("submit", function (ev) {
    var form = ev.target.closest("#form-caja-empresas");
    if (!form) return;
    var errorBox = document.getElementById("caja-empresas-error");
    var problemas = [];

    // Clientes/Proveedores/Honorarios no necesitan validación de cuenta:
    // la cuenta contra la que se cobra/paga es fija por módulo (no se
    // elige en pantalla) — solo la fecha y el monto (ya vienen del
    // archivo) importan, y esos siempre están completos si se llegó a
    // cargar el archivo.

    document.querySelectorAll(".input-monto-mes").forEach(function (input) {
      var valor = num(input.value);
      if (valor <= 0) return;
      var fila = input.closest("tr");
      var fechaInput = fila && fila.querySelector(".input-fecha-mes");
      if (fechaInput && !fechaInput.value) {
        var etiqueta = fila.querySelector("td") ? fila.querySelector("td").textContent : "un mes";
        var msg = "Falta la fecha de " + etiqueta + " (" + input.dataset.prefijo + ").";
        if (problemas.indexOf(msg) === -1) problemas.push(msg);
      }
    });

    var check = document.getElementById("prestamo-socio-check");
    if (check && check.checked) {
      var monto = document.getElementById("prestamo-socio-monto");
      var fecha = document.getElementById("prestamo-socio-fecha");
      if (!monto || num(monto.value) <= 0) problemas.push("Préstamo Socio: ingresa un monto mayor a cero.");
      if (!fecha || !fecha.value) problemas.push("Préstamo Socio: falta la fecha del asiento.");
    }

    var saldoFinalTexto = document.getElementById("saldo-final");
    var saldoFinalNegativo = saldoFinalTexto && saldoFinalTexto.textContent.indexOf("-") === 1;
    if (saldoFinalNegativo && !(check && check.checked)) {
      problemas.push("El saldo final queda negativo — marca “Agregar asiento Préstamo Socio” e ingresa un monto.");
    }

    if (!problemas.length) {
      if (errorBox) errorBox.hidden = true;
      return;
    }

    ev.preventDefault();
    if (errorBox) {
      errorBox.textContent = problemas.join("\n");
      errorBox.hidden = false;
      errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, true);

  recomputar();
})();
