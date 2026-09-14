// Pestaña "Conciliación". Vainilla JS, sin dependencias. Dos partes:
//
// 1) El buscador de la cuenta bancaria fija (arriba de la tabla) — sin
//    cambios respecto a la primera ronda: filtra window.CYG_PLAN_CUENTAS.
//
// 2) Conciliación asistida (14-09-2026): cada movimiento vive en una
//    "fila" (`.conc-fila`) con 4 estados posibles en su columna derecha —
//    todo el estado (qué documento/cuenta quedó elegido, qué documentos
//    ya se usaron) vive en el DOM (inputs ocultos + `data-estado`), no en
//    variables globales, para que sobreviva a que el admin cargue más
//    documentos auxiliares o reordene qué mira primero:
//      - "resuelto": ya tiene una cuenta/documento asignado.
//      - "staged": hay una propuesta automática (monto Y rut calzan
//        exacto contra un documento auxiliar todavía disponible) que el
//        admin no ha confirmado todavía.
//      - "idle": no hay propuesta automática.
//      - "buscando": el admin abrió el buscador combinado (documentos
//        auxiliares disponibles + plan de cuentas) para resolverlo a
//        mano — elegir un resultado ahí resuelve la fila directo (sin
//        paso de "staged" intermedio, a diferencia de la propuesta
//        automática, que sí pide confirmarla con "Crear comprobante").
(function () {
  var CUENTAS = window.CYG_PLAN_CUENTAS || [];
  var AUX_MODULOS = window.CYG_AUX_MODULOS || {};
  var CUENTAS_POR_CODIGO = {};
  CUENTAS.forEach(function (c) { CUENTAS_POR_CODIGO[c.codigo] = c; });

  var MAX_RESULTADOS = 8;

  function normalizar(s) {
    return (s || "")
      .toString()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, ""); // sin tildes, para que "econom" encuentre "economico"
  }

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

  function valor(fila, selector) {
    var el = fila.querySelector(selector);
    return el ? el.value : "";
  }

  function fijar(fila, selector, val) {
    var el = fila.querySelector(selector);
    if (el) el.value = val || "";
  }

  // -------------------------------------------------------------------
  // Buscador de la cuenta bancaria fija (arriba de la tabla).
  // -------------------------------------------------------------------

  var activoBanco = null; // { input, results, items, index }

  function buscarCuentas(texto) {
    var q = normalizar(texto).trim();
    if (!q) return [];
    var partes = q.split(/\s+/);
    return CUENTAS.filter(function (c) {
      var hay = normalizar(c.codigo + " " + c.descripcion);
      return partes.every(function (p) { return hay.indexOf(p) !== -1; });
    }).slice(0, MAX_RESULTADOS);
  }

  function cerrarDropdownBanco() {
    if (!activoBanco) return;
    activoBanco.results.hidden = true;
    activoBanco.results.innerHTML = "";
    activoBanco = null;
  }

  function renderResultadosBanco(input, resultsEl, lista) {
    resultsEl.innerHTML = "";
    if (!lista.length) {
      resultsEl.hidden = true;
      activoBanco = null;
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
        seleccionarBanco(input, cuenta);
      });
      resultsEl.appendChild(item);
    });
    resultsEl.hidden = false;
    activoBanco = { input: input, results: resultsEl, items: lista, index: -1 };
  }

  function marcarActivoBanco(index) {
    if (!activoBanco) return;
    var nodos = activoBanco.results.querySelectorAll(".cuenta-search-item");
    nodos.forEach(function (n) { n.classList.remove("active"); });
    if (index >= 0 && index < nodos.length) {
      nodos[index].classList.add("active");
      nodos[index].scrollIntoView({ block: "nearest" });
    }
    activoBanco.index = index;
  }

  function seleccionarBanco(input, cuenta) {
    input.value = cuenta.codigo + " — " + cuenta.descripcion;
    var wrap = input.closest(".cuenta-search");
    var codigoInput = wrap.querySelector(".cuenta-codigo");
    var descInput = wrap.querySelector(".cuenta-descripcion");
    if (codigoInput) codigoInput.value = cuenta.codigo;
    if (descInput) descInput.value = cuenta.descripcion;
    cerrarDropdownBanco();
    actualizarContadores();
  }

  document.addEventListener("input", function (ev) {
    var input = ev.target.closest(".cuenta-search-input");
    if (!input || input.closest(".conc-buscar-combinado")) return;
    var wrap = input.closest(".cuenta-search");
    var resultsEl = wrap && wrap.querySelector(".cuenta-search-results");
    if (!resultsEl) return;

    var codigoInput = wrap.querySelector(".cuenta-codigo");
    if (codigoInput && codigoInput.value) {
      codigoInput.value = "";
      var descInput = wrap.querySelector(".cuenta-descripcion");
      if (descInput) descInput.value = "";
      actualizarContadores();
    }

    renderResultadosBanco(input, resultsEl, buscarCuentas(input.value));
    if (activoBanco) marcarActivoBanco(-1);
  });

  document.addEventListener("keydown", function (ev) {
    var input = ev.target.closest(".cuenta-search-input");
    if (!input || input.closest(".conc-buscar-combinado")) return;
    if (!activoBanco || activoBanco.input !== input) return;

    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      marcarActivoBanco(Math.min(activoBanco.index + 1, activoBanco.items.length - 1));
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      marcarActivoBanco(Math.max(activoBanco.index - 1, 0));
    } else if (ev.key === "Enter") {
      if (activoBanco.index >= 0) {
        ev.preventDefault();
        seleccionarBanco(input, activoBanco.items[activoBanco.index]);
      }
    } else if (ev.key === "Escape") {
      cerrarDropdownBanco();
    }
  });

  document.addEventListener("focusin", function (ev) {
    var input = ev.target.closest(".cuenta-search-input");
    if (!input || input.closest(".conc-buscar-combinado")) return;
    var wrap = input.closest(".cuenta-search");
    var resultsEl = wrap && wrap.querySelector(".cuenta-search-results");
    if (resultsEl && input.value.trim()) {
      renderResultadosBanco(input, resultsEl, buscarCuentas(input.value));
    }
  });

  document.addEventListener("focusout", function (ev) {
    var input = ev.target.closest(".cuenta-search-input");
    if (!input || input.closest(".conc-buscar-combinado")) return;
    setTimeout(function () {
      if (activoBanco && activoBanco.input === input) cerrarDropdownBanco();
    }, 120);
  });

  // -------------------------------------------------------------------
  // Documentos auxiliares: carga AJAX (mismo patrón que
  // caja_empresas.js:cargarModulo) y estado disponible/usado.
  // -------------------------------------------------------------------

  function csrfToken() {
    var el = document.getElementById("csrf-token-global");
    return el ? el.value : "";
  }

  function cargarAuxiliar(modulo) {
    var fileInput = document.getElementById("archivo-aux-" + modulo);
    var boton = document.querySelector('[data-cargar-aux="' + modulo + '"]');
    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
      alert("Elige primero un archivo para " + modulo + ".");
      return;
    }
    var datos = new FormData();
    datos.append("archivo", fileInput.files[0]);
    datos.append("csrf_token", csrfToken());

    var textoOriginal = boton ? boton.innerHTML : "";
    if (boton) { boton.disabled = true; boton.textContent = "Cargando…"; }

    var errorBox = document.getElementById("error-aux-" + modulo);
    var wrap = document.getElementById("wrap-aux-" + modulo);

    fetch("/conciliacion/cargar-auxiliar/" + modulo, { method: "POST", body: datos })
      .then(function (resp) { return resp.text().then(function (html) { return { ok: resp.ok, html: html }; }); })
      .then(function (result) {
        if (result.ok) {
          if (errorBox) { errorBox.hidden = true; errorBox.innerHTML = ""; }
          if (wrap) wrap.innerHTML = result.html;
          recomputarEstadoDocumentos();
          document.querySelectorAll(".conc-fila").forEach(function (fila) {
            if (!valor(fila, ".conc-concepto-codigo")) inicializarFila(fila);
          });
        } else if (errorBox) {
          errorBox.innerHTML = result.html;
          errorBox.hidden = false;
        }
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
    var boton = ev.target.closest("[data-cargar-aux]");
    if (!boton) return;
    ev.preventDefault();
    cargarAuxiliar(boton.dataset.cargarAux);
  });

  function recomputarEstadoDocumentos() {
    var usados = {};
    document.querySelectorAll(".conc-fila").forEach(function (fila) {
      var modulo = valor(fila, ".conc-aux-modulo");
      var idx = valor(fila, ".conc-aux-doc-idx");
      if (modulo && idx !== "") usados[modulo + ":" + idx] = true;
    });
    document.querySelectorAll(".fila-doc-auxiliar").forEach(function (docFila) {
      var key = docFila.dataset.modulo + ":" + docFila.dataset.idx;
      var usado = !!usados[key];
      docFila.dataset.estado = usado ? "usado" : "disponible";
      var celda = docFila.querySelector(".conc-doc-estado");
      if (celda) celda.innerHTML = usado ? '<span class="badge-usado">Usado</span>' : '<span class="badge-ok">Disponible</span>';
    });
  }

  function documentosDisponibles(modulos) {
    var lista = [];
    document.querySelectorAll(".fila-doc-auxiliar").forEach(function (docFila) {
      if (docFila.dataset.estado !== "disponible") return;
      if (modulos.indexOf(docFila.dataset.modulo) === -1) return;
      lista.push(docFila);
    });
    return lista;
  }

  // -------------------------------------------------------------------
  // Matching automático: monto Y rut deben calzar exacto (14-09-2026,
  // confirmado por el usuario) — si el texto del movimiento no trae un
  // RUT reconocible, no se propone nada automático (queda "idle").
  // -------------------------------------------------------------------

  var RUT_REGEX = /\b(\d{1,2}\.?\d{3}\.?\d{3})-([0-9kK])\b/;

  function extraerRut(texto) {
    var m = RUT_REGEX.exec(texto || "");
    if (!m) return null;
    return m[1].replace(/\./g, "") + "-" + m[2].toUpperCase();
  }

  function normalizarRut(rut) {
    return (rut || "").replace(/\./g, "").replace(/\s+/g, "").toUpperCase();
  }

  function modulosParaDireccion(direccion) {
    return Object.keys(AUX_MODULOS).filter(function (m) { return AUX_MODULOS[m].direccion === direccion; });
  }

  function buscarPropuestaAutomatica(fila) {
    var abono = num(valor(fila, ".conc-col-mov input[name^='abono_']"));
    var cargo = num(valor(fila, ".conc-col-mov input[name^='cargo_']"));
    var esAbono = abono > 0;
    var monto = esAbono ? abono : cargo;
    if (!monto) return null;

    var detalle = valor(fila, ".conc-mov-detalle");
    var rut = extraerRut(detalle);
    if (!rut) return null;
    var rutNorm = normalizarRut(rut);

    var modulos = modulosParaDireccion(esAbono ? "abono" : "cargo");
    var candidatos = documentosDisponibles(modulos).filter(function (docFila) {
      return Math.round(num(docFila.dataset.monto)) === Math.round(monto) && normalizarRut(docFila.dataset.rut) === rutNorm;
    });
    return candidatos.length ? candidatos[0] : null;
  }

  // -------------------------------------------------------------------
  // Estado por fila (idle / staged / buscando / resuelto).
  // -------------------------------------------------------------------

  function cajaDe(fila, sufijo) {
    return fila.querySelector(".conc-box-" + sufijo);
  }

  function ocultarTodas(fila) {
    ["resuelto", "staged", "idle", "buscando"].forEach(function (s) {
      var caja = cajaDe(fila, s);
      if (caja) caja.hidden = true;
    });
  }

  function textoResuelto(fila) {
    var auxTipo = valor(fila, ".conc-aux-tipo");
    var codigo = valor(fila, ".conc-concepto-codigo");
    var descripcion = valor(fila, ".conc-concepto-descripcion");
    if (auxTipo) {
      var tipoDoc = valor(fila, ".conc-aux-tipo-doc");
      var numeroDoc = valor(fila, ".conc-aux-numero-doc");
      var rut = valor(fila, ".conc-aux-rut");
      return {
        nombre: valor(fila, ".conc-aux-nombre") + (rut ? " (" + rut + ")" : ""),
        detalle: [tipoDoc, numeroDoc].join(" ").trim() + " · " + codigo + " — " + descripcion,
      };
    }
    return { nombre: codigo, detalle: descripcion };
  }

  function mostrarResuelto(fila) {
    ocultarTodas(fila);
    var info = textoResuelto(fila);
    fila.querySelector(".conc-resuelto-nombre").textContent = info.nombre;
    fila.querySelector(".conc-resuelto-detalle").textContent = info.detalle;
    cajaDe(fila, "resuelto").hidden = false;
  }

  function mostrarStaged(fila, docFila) {
    ocultarTodas(fila);
    fila.dataset.propuestaModulo = docFila.dataset.modulo;
    fila.dataset.propuestaIdx = docFila.dataset.idx;
    var info = AUX_MODULOS[docFila.dataset.modulo] || {};
    fila.querySelector(".conc-staged-nombre").textContent =
      docFila.dataset.nombre + (docFila.dataset.rut ? " (" + docFila.dataset.rut + ")" : "");
    fila.querySelector(".conc-staged-detalle").textContent =
      (info.titulo || docFila.dataset.modulo) + " · " + docFila.dataset.tipoDocumento + " " + docFila.dataset.numeroDocumento +
      " · " + formatoClp(num(docFila.dataset.monto));
    cajaDe(fila, "staged").hidden = false;
  }

  function mostrarIdle(fila) {
    ocultarTodas(fila);
    delete fila.dataset.propuestaModulo;
    delete fila.dataset.propuestaIdx;
    cajaDe(fila, "idle").hidden = false;
  }

  function mostrarBuscando(fila) {
    ocultarTodas(fila);
    cajaDe(fila, "buscando").hidden = false;
    var input = fila.querySelector(".conc-buscar-input");
    if (input) { input.value = ""; input.focus(); }
  }

  function inicializarFila(fila) {
    if (valor(fila, ".conc-concepto-codigo")) {
      mostrarResuelto(fila);
      return;
    }
    var propuesta = buscarPropuestaAutomatica(fila);
    if (propuesta) {
      mostrarStaged(fila, propuesta);
    } else {
      mostrarIdle(fila);
    }
  }

  function limpiarResolucion(fila) {
    [".conc-concepto-codigo", ".conc-concepto-descripcion", ".conc-aux-tipo", ".conc-aux-modulo",
      ".conc-aux-doc-idx", ".conc-aux-rut", ".conc-aux-nombre", ".conc-aux-tipo-doc",
      ".conc-aux-numero-doc", ".conc-aux-fecha-iso"].forEach(function (sel) { fijar(fila, sel, ""); });
  }

  function commitDoc(fila, docFila) {
    var info = AUX_MODULOS[docFila.dataset.modulo] || {};
    var cuenta = CUENTAS_POR_CODIGO[info.cuenta_codigo];
    fijar(fila, ".conc-concepto-codigo", info.cuenta_codigo);
    fijar(fila, ".conc-concepto-descripcion", cuenta ? cuenta.descripcion : "");
    fijar(fila, ".conc-aux-tipo", info.tipo_auxiliar);
    fijar(fila, ".conc-aux-modulo", docFila.dataset.modulo);
    fijar(fila, ".conc-aux-doc-idx", docFila.dataset.idx);
    fijar(fila, ".conc-aux-rut", docFila.dataset.rut);
    fijar(fila, ".conc-aux-nombre", docFila.dataset.nombre);
    fijar(fila, ".conc-aux-tipo-doc", docFila.dataset.tipoDocumento);
    fijar(fila, ".conc-aux-numero-doc", docFila.dataset.numeroDocumento);
    fijar(fila, ".conc-aux-fecha-iso", docFila.dataset.fechaIso);
  }

  function commitCuenta(fila, codigo, descripcion) {
    fijar(fila, ".conc-concepto-codigo", codigo);
    fijar(fila, ".conc-concepto-descripcion", descripcion);
    fijar(fila, ".conc-aux-tipo", "");
    fijar(fila, ".conc-aux-modulo", "");
    fijar(fila, ".conc-aux-doc-idx", "");
    fijar(fila, ".conc-aux-rut", "");
    fijar(fila, ".conc-aux-nombre", "");
    fijar(fila, ".conc-aux-tipo-doc", "");
    fijar(fila, ".conc-aux-numero-doc", "");
    fijar(fila, ".conc-aux-fecha-iso", "");
  }

  document.addEventListener("click", function (ev) {
    var fila = ev.target.closest(".conc-fila");
    if (!fila) return;

    if (ev.target.closest(".conc-crear-comprobante")) {
      var modulo = fila.dataset.propuestaModulo;
      var idx = fila.dataset.propuestaIdx;
      var docFila = modulo && document.querySelector('.fila-doc-auxiliar[data-modulo="' + modulo + '"][data-idx="' + idx + '"]');
      if (!docFila || docFila.dataset.estado !== "disponible") {
        inicializarFila(fila); // la propuesta ya no está disponible (otra fila se la ganó) — se recalcula
        return;
      }
      commitDoc(fila, docFila);
      mostrarResuelto(fila);
      recomputarEstadoDocumentos();
      actualizarContadores();
    } else if (ev.target.closest(".conc-buscar-toggle")) {
      mostrarBuscando(fila);
    } else if (ev.target.closest(".conc-cancelar-buscar")) {
      cerrarDropdownRow();
      inicializarFila(fila);
    } else if (ev.target.closest(".conc-editar")) {
      limpiarResolucion(fila);
      recomputarEstadoDocumentos();
      inicializarFila(fila);
      actualizarContadores();
    }
  });

  // -------------------------------------------------------------------
  // Buscador combinado por fila: documentos auxiliares disponibles +
  // plan de cuentas. Elegir un resultado resuelve la fila directo.
  // -------------------------------------------------------------------

  var activoRow = null; // { fila, input, results, items, index }

  function buscarCombinado(texto) {
    var q = normalizar(texto).trim();
    if (!q) return [];
    var partes = q.split(/\s+/);
    var resultados = [];

    documentosDisponibles(Object.keys(AUX_MODULOS)).forEach(function (docFila) {
      var hay = normalizar([docFila.dataset.nombre, docFila.dataset.rut, docFila.dataset.tipoDocumento, docFila.dataset.numeroDocumento].join(" "));
      if (partes.every(function (p) { return hay.indexOf(p) !== -1; })) {
        resultados.push({ tipo: "doc", el: docFila });
      }
    });
    CUENTAS.forEach(function (c) {
      var hay = normalizar(c.codigo + " " + c.descripcion);
      if (partes.every(function (p) { return hay.indexOf(p) !== -1; })) {
        resultados.push({ tipo: "cuenta", cuenta: c });
      }
    });
    return resultados.slice(0, MAX_RESULTADOS);
  }

  function cerrarDropdownRow() {
    if (!activoRow) return;
    activoRow.results.hidden = true;
    activoRow.results.innerHTML = "";
    activoRow = null;
  }

  function renderResultadosRow(fila, input, resultsEl, lista) {
    resultsEl.innerHTML = "";
    if (!lista.length) {
      resultsEl.hidden = true;
      activoRow = null;
      return;
    }
    lista.forEach(function (item, i) {
      var el = document.createElement("div");
      el.className = "cuenta-search-item";
      el.dataset.index = i;
      if (item.tipo === "doc") {
        var info = AUX_MODULOS[item.el.dataset.modulo] || {};
        el.innerHTML =
          '<span class="conc-buscar-item-tipo">' + (info.titulo || item.el.dataset.modulo) + "</span>" +
          '<span class="cuenta-search-item-codigo">' + item.el.dataset.nombre + (item.el.dataset.rut ? " (" + item.el.dataset.rut + ")" : "") + "</span>" +
          '<span class="cuenta-search-item-desc">' + item.el.dataset.tipoDocumento + " " + item.el.dataset.numeroDocumento +
          " · " + formatoClp(num(item.el.dataset.monto)) + "</span>";
      } else {
        el.innerHTML =
          '<span class="cuenta-search-item-codigo">' + item.cuenta.codigo + "</span>" +
          '<span class="cuenta-search-item-desc">' + item.cuenta.descripcion + "</span>";
      }
      el.addEventListener("mousedown", function (ev) {
        ev.preventDefault();
        seleccionarRow(fila, input, item);
      });
      resultsEl.appendChild(el);
    });
    resultsEl.hidden = false;
    activoRow = { fila: fila, input: input, results: resultsEl, items: lista, index: -1 };
  }

  function marcarActivoRow(index) {
    if (!activoRow) return;
    var nodos = activoRow.results.querySelectorAll(".cuenta-search-item");
    nodos.forEach(function (n) { n.classList.remove("active"); });
    if (index >= 0 && index < nodos.length) {
      nodos[index].classList.add("active");
      nodos[index].scrollIntoView({ block: "nearest" });
    }
    activoRow.index = index;
  }

  function seleccionarRow(fila, input, item) {
    if (item.tipo === "doc") {
      commitDoc(fila, item.el);
    } else {
      commitCuenta(fila, item.cuenta.codigo, item.cuenta.descripcion);
    }
    cerrarDropdownRow();
    mostrarResuelto(fila);
    recomputarEstadoDocumentos();
    actualizarContadores();
  }

  document.addEventListener("input", function (ev) {
    var input = ev.target.closest(".conc-buscar-combinado .cuenta-search-input");
    if (!input) return;
    var fila = input.closest(".conc-fila");
    var resultsEl = input.closest(".conc-buscar-combinado").querySelector(".cuenta-search-results");
    if (!fila || !resultsEl) return;
    renderResultadosRow(fila, input, resultsEl, buscarCombinado(input.value));
    if (activoRow) marcarActivoRow(-1);
  });

  document.addEventListener("keydown", function (ev) {
    var input = ev.target.closest(".conc-buscar-combinado .cuenta-search-input");
    if (!input || !activoRow || activoRow.input !== input) return;

    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      marcarActivoRow(Math.min(activoRow.index + 1, activoRow.items.length - 1));
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      marcarActivoRow(Math.max(activoRow.index - 1, 0));
    } else if (ev.key === "Enter") {
      if (activoRow.index >= 0) {
        ev.preventDefault();
        seleccionarRow(activoRow.fila, input, activoRow.items[activoRow.index]);
      }
    } else if (ev.key === "Escape") {
      cerrarDropdownRow();
    }
  });

  document.addEventListener("focusout", function (ev) {
    var input = ev.target.closest(".conc-buscar-combinado .cuenta-search-input");
    if (!input) return;
    setTimeout(function () {
      if (activoRow && activoRow.input === input) cerrarDropdownRow();
    }, 120);
  });

  // -------------------------------------------------------------------
  // Filtro Abono/Cargo (arriba de la lista de movimientos).
  // -------------------------------------------------------------------

  document.addEventListener("click", function (ev) {
    var boton = ev.target.closest(".conc-filtro-btn");
    if (!boton) return;
    document.querySelectorAll(".conc-filtro-btn").forEach(function (b) { b.classList.remove("active"); });
    boton.classList.add("active");
    var filtro = boton.dataset.filtro;
    document.querySelectorAll(".conc-fila").forEach(function (fila) {
      fila.hidden = filtro !== "todos" && fila.dataset.tipo !== filtro;
    });
  });

  // -------------------------------------------------------------------
  // Contadores + validación antes de descargar.
  // -------------------------------------------------------------------

  function actualizarContadores() {
    var filas = document.querySelectorAll(".conc-fila");
    var conciliados = 0;
    filas.forEach(function (fila) {
      var resuelta = !!valor(fila, ".conc-concepto-codigo");
      fila.classList.toggle("conc-fila-resuelta", resuelta);
      if (resuelta) conciliados++;
    });
    var total = filas.length;
    var elTotal = document.getElementById("stat-total");
    var elConc = document.getElementById("stat-conciliados");
    var elPend = document.getElementById("stat-pendientes");
    if (elTotal) elTotal.textContent = total;
    if (elConc) elConc.textContent = conciliados;
    if (elPend) elPend.textContent = total - conciliados;

    var bancoCodigo = document.getElementById("cuenta-banco-codigo");
    var errorBox = document.getElementById("conciliacion-error");
    if (errorBox && !errorBox.hidden && conciliados === total && bancoCodigo && bancoCodigo.value) {
      errorBox.hidden = true;
    }
  }

  // Validación antes de descargar: la cuenta bancaria de arriba y la
  // resolución de cada movimiento (documento o cuenta) son obligatorias.
  // Fase de "capture" para correr antes que el overlay de carga global de
  // `base.html` (revisa `event.defaultPrevented` antes de mostrarse).
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

    var filasSinResolver = [];
    document.querySelectorAll(".conc-fila").forEach(function (fila) {
      if (!valor(fila, ".conc-concepto-codigo")) {
        filasSinResolver.push(parseInt(fila.dataset.row, 10) + 1);
      }
    });
    if (filasSinResolver.length === 1) {
      problemas.push("Resuelve el movimiento de la fila " + filasSinResolver[0] + " antes de descargar.");
    } else if (filasSinResolver.length > 1) {
      problemas.push("Resuelve los movimientos de las filas " + filasSinResolver.join(", ") + " antes de descargar.");
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
    if (bancoFalta) {
      var bancoInput = document.getElementById("cuenta-banco-input");
      if (bancoInput) bancoInput.focus();
    } else if (filasSinResolver.length) {
      var primeraFila = document.querySelector('.conc-fila[data-row="' + (filasSinResolver[0] - 1) + '"]');
      if (primeraFila) primeraFila.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, true);

  // -------------------------------------------------------------------
  // Arranque.
  // -------------------------------------------------------------------

  recomputarEstadoDocumentos();
  document.querySelectorAll(".conc-fila").forEach(inicializarFila);
  actualizarContadores();
})();
