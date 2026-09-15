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
    if (modalState) renderModalBanco();
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
            if (fila.dataset.resuelta !== "true") renderResumenFila(fila);
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
    document.querySelectorAll(".conc-fila .conc-doc-ref").forEach(function (ref) {
      usados[ref.dataset.modulo + ":" + ref.dataset.idx] = true;
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
  // Dropdown genérico (cuenta o documento) — usado por el buscador de
  // cada línea del modal y por el buscador de documentos de cada línea
  // con auxiliar. Cierra solo, navega con flechas/Enter/Escape, igual
  // comportamiento que el buscador de la cuenta bancaria de arriba.
  // -------------------------------------------------------------------

  function habilitarDropdown(input, resultsEl, buscarFn, renderItemFn, seleccionarFn, autoSanar) {
    var estado = { activo: false, items: [], index: -1 };

    function cerrar() {
      resultsEl.hidden = true;
      resultsEl.innerHTML = "";
      estado.activo = false;
    }

    function marcar(i) {
      var nodos = resultsEl.querySelectorAll(".cuenta-search-item");
      nodos.forEach(function (n) { n.classList.remove("active"); });
      if (i >= 0 && i < nodos.length) {
        nodos[i].classList.add("active");
        nodos[i].scrollIntoView({ block: "nearest" });
      }
      estado.index = i;
    }

    function render(lista) {
      resultsEl.innerHTML = "";
      if (!lista.length) { cerrar(); return; }
      lista.forEach(function (item) {
        var el = document.createElement("div");
        el.className = "cuenta-search-item";
        renderItemFn(el, item);
        el.addEventListener("mousedown", function (ev) {
          ev.preventDefault();
          seleccionarFn(item);
          cerrar();
        });
        resultsEl.appendChild(el);
      });
      resultsEl.hidden = false;
      estado.items = lista;
      estado.activo = true;
      estado.index = -1;
    }

    input.addEventListener("input", function () { render(buscarFn(input.value)); });
    input.addEventListener("focus", function () { if (input.value.trim()) render(buscarFn(input.value)); });
    input.addEventListener("keydown", function (ev) {
      if (!estado.activo) return;
      if (ev.key === "ArrowDown") { ev.preventDefault(); marcar(Math.min(estado.index + 1, estado.items.length - 1)); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); marcar(Math.max(estado.index - 1, 0)); }
      else if (ev.key === "Enter") { if (estado.index >= 0) { ev.preventDefault(); seleccionarFn(estado.items[estado.index]); cerrar(); } }
      else if (ev.key === "Escape") { cerrar(); }
    });
    // Al salir del campo: si el texto quedó calzando EXACTO con un
    // resultado pero `seleccionarFn` nunca se disparó (por ejemplo, el
    // autocompletado nativo del navegador metió el texto en vez de que
    // el usuario haya hecho clic en una de nuestras opciones — pasa con
    // Chrome en campos sin `name` que el usuario ya escribió antes), se
    // corrige solo en vez de quedar con un texto "fantasma" que no
    // corresponde a ninguna selección real. Busca contra la lista COMPLETA
    // (`autoSanar.todos()`), no contra `buscarFn` — el texto ya formateado
    // ("1104-01 — DEUDORES CLIENTES") no calza con el buscador de palabras
    // sueltas por el guion largo del medio.
    input.addEventListener("blur", function () {
      setTimeout(function () {
        if (autoSanar) {
          var texto = input.value.trim();
          if (texto) {
            var exacto = autoSanar.todos().filter(function (item) { return autoSanar.textoDe(item) === texto; })[0];
            if (exacto) seleccionarFn(exacto);
          }
        }
        cerrar();
      }, 120);
    });
  }

  function crearCampoBusqueda(valorInicial, placeholder) {
    var wrap = document.createElement("div");
    wrap.className = "cuenta-search";
    var input = document.createElement("input");
    input.type = "text";
    input.className = "cuenta-search-input";
    input.placeholder = placeholder || "Buscar…";
    // `autocomplete="off"` solo, Chrome lo ignora seguido en campos que
    // el usuario ya llenó antes en la misma página — un `name` al azar
    // (sin relación con datos reales) le quita la pista que usa para
    // sugerir autocompletado.
    input.autocomplete = "off";
    input.name = "cyg-no-autofill-" + Math.random().toString(36).slice(2);
    input.spellcheck = false;
    input.value = valorInicial || "";
    var results = document.createElement("div");
    results.className = "cuenta-search-results";
    results.hidden = true;
    wrap.appendChild(input);
    wrap.appendChild(results);
    return { wrap: wrap, input: input, results: results };
  }

  // -------------------------------------------------------------------
  // Estado por fila: `LINEAS_POR_FILA[rowIndex]` es la lista de líneas
  // de detalle YA CONFIRMADAS (desde "Crear y conciliar") — el modal
  // trabaja sobre una copia hasta que se confirma. Cada línea:
  // { codigo, descripcion, monto, documentos: [{modulo, idx, rut,
  // nombre, tipo_doc, numero_doc, fecha_iso, monto}, ...] }.
  // -------------------------------------------------------------------

  var LINEAS_POR_FILA = {};

  function esCuentaAuxiliar(codigo) {
    return Object.keys(AUX_MODULOS).some(function (m) { return AUX_MODULOS[m].cuenta_codigo === codigo; });
  }

  function moduloDeCuenta(codigo) {
    var encontrado = null;
    Object.keys(AUX_MODULOS).forEach(function (m) { if (AUX_MODULOS[m].cuenta_codigo === codigo) encontrado = m; });
    return encontrado;
  }

  function montoDeLinea(linea) {
    return linea.documentos.length ? linea.documentos.reduce(function (s, d) { return s + num(d.monto); }, 0) : num(linea.monto);
  }

  function renderResumenFila(fila) {
    var rowIndex = fila.dataset.row;
    var lineas = LINEAS_POR_FILA[rowIndex] || [];
    var resumen = fila.querySelector(".conc-resumen");
    var etiqueta = fila.querySelector(".conc-abrir-modal-label");
    resumen.innerHTML = "";

    if (lineas.length) {
      fila.dataset.resuelta = "true";
      var totalDocs = lineas.reduce(function (acc, l) { return acc + l.documentos.length; }, 0);
      var box = document.createElement("div");
      box.className = "conc-resumen-resuelto";
      var info = document.createElement("div");
      info.className = "conc-resumen-info";
      var strong = document.createElement("strong");
      strong.textContent = lineas.map(function (l) { return l.codigo; }).join(" + ");
      var span = document.createElement("span");
      span.textContent = lineas.length + (lineas.length === 1 ? " línea" : " líneas")
        + (totalDocs ? " · " + totalDocs + (totalDocs === 1 ? " documento" : " documentos") : "");
      info.appendChild(strong);
      info.appendChild(span);
      box.appendChild(info);
      resumen.appendChild(box);
      if (etiqueta) etiqueta.textContent = "Editar comprobante";
    } else {
      fila.dataset.resuelta = "false";
      var pendiente = document.createElement("div");
      pendiente.className = "conc-resumen-pendiente";
      pendiente.appendChild(document.createTextNode("Sin conciliar"));
      if (buscarPropuestaAutomatica(fila)) {
        pendiente.appendChild(document.createTextNode(" · "));
        var hint = document.createElement("span");
        hint.className = "conc-resumen-propuesta-hint";
        hint.textContent = "Propuesta disponible";
        pendiente.appendChild(hint);
      }
      resumen.appendChild(pendiente);
      if (etiqueta) etiqueta.textContent = "Crear comprobante";
    }
  }

  function commitLineasAFormulario(fila, lineas) {
    var rowIndex = fila.dataset.row;
    var lineasLimpias = lineas.filter(function (l) { return l.codigo; });
    LINEAS_POR_FILA[rowIndex] = lineasLimpias;

    var cont = fila.querySelector(".conc-lineas-hidden");
    cont.innerHTML = "";

    function agregarOculto(name, val) {
      var inp = document.createElement("input");
      inp.type = "hidden";
      inp.name = name;
      inp.value = val === undefined || val === null ? "" : val;
      cont.appendChild(inp);
    }

    agregarOculto("lineas_" + rowIndex + "_total", lineasLimpias.length);
    lineasLimpias.forEach(function (linea, li) {
      var prefijo = "lineas_" + rowIndex + "_" + li;
      agregarOculto(prefijo + "_codigo", linea.codigo);
      agregarOculto(prefijo + "_descripcion", linea.descripcion);
      agregarOculto(prefijo + "_monto", linea.documentos.length ? "" : (linea.monto || 0));
      agregarOculto(prefijo + "_docs_total", linea.documentos.length);
      linea.documentos.forEach(function (doc, di) {
        var dprefijo = prefijo + "_doc_" + di;
        agregarOculto(dprefijo + "_modulo", doc.modulo);
        agregarOculto(dprefijo + "_idx", doc.idx);
        agregarOculto(dprefijo + "_rut", doc.rut);
        agregarOculto(dprefijo + "_nombre", doc.nombre);
        agregarOculto(dprefijo + "_tipo_doc", doc.tipo_doc);
        agregarOculto(dprefijo + "_numero_doc", doc.numero_doc);
        agregarOculto(dprefijo + "_fecha_iso", doc.fecha_iso);
        agregarOculto(dprefijo + "_monto", doc.monto);

        var ref = document.createElement("span");
        ref.className = "conc-doc-ref";
        ref.hidden = true;
        ref.dataset.modulo = doc.modulo;
        ref.dataset.idx = doc.idx;
        cont.appendChild(ref);
      });
    });

    renderResumenFila(fila);
    recomputarEstadoDocumentos();
    actualizarContadores();
  }

  // -------------------------------------------------------------------
  // Modal "Crear comprobante" — banco fijo + N líneas de detalle, cada
  // una una cuenta con un monto o (si es Clientes/Proveedores/
  // Honorarios) una cuenta con uno o más documentos adjuntos (14-09-2026,
  // a partir de un mockup de referencia del usuario).
  // -------------------------------------------------------------------

  var modalState = null; // { fila, rowIndex, movimiento, lineas }

  function buscarDocumentosModulo(texto, modulo, limite) {
    var pool = documentosDisponibles([modulo]);
    var q = normalizar(texto).trim();
    if (q) {
      var partes = q.split(/\s+/);
      pool = pool.filter(function (docFila) {
        var hay = normalizar([docFila.dataset.nombre, docFila.dataset.rut, docFila.dataset.tipoDocumento, docFila.dataset.numeroDocumento].join(" "));
        return partes.every(function (p) { return hay.indexOf(p) !== -1; });
      });
    }
    return pool.slice(0, limite || MAX_RESULTADOS);
  }

  function documentoYaUsadoEnModal(modulo, idx) {
    return modalState.lineas.some(function (l) {
      return l.documentos.some(function (d) { return d.modulo === modulo && d.idx === idx; });
    });
  }

  function renderItemCuenta(el, cuenta) {
    el.innerHTML =
      '<span class="cuenta-search-item-codigo">' + cuenta.codigo + "</span>" +
      '<span class="cuenta-search-item-desc">' + cuenta.descripcion + "</span>";
  }

  // Panel de documentos de una línea con cuenta auxiliar (14-09-2026,
  // corregido a partir de una captura del usuario que mostró que el panel
  // no se desplegaba): SIEMPRE visible en cuanto la línea usa una cuenta
  // con auxiliar (no depende de un dropdown flotante que se abre/cierra
  // con foco) — una tabla con los documentos disponibles de ese módulo,
  // filtrable en vivo, con un botón "Agregar" por fila; los ya adjuntos
  // se muestran arriba como chips removibles.
  function construirAreaDocumentos(linea) {
    var wrap = document.createElement("div");
    wrap.className = "conc-linea-docs";

    var modulo = moduloDeCuenta(linea.codigo);
    if (!modulo) return wrap;

    var chips = document.createElement("div");
    chips.className = "conc-linea-docs-chips";
    wrap.appendChild(chips);

    var etiqueta = document.createElement("div");
    etiqueta.className = "conc-linea-docs-label";
    etiqueta.textContent = "Documentos de " + (AUX_MODULOS[modulo] ? AUX_MODULOS[modulo].titulo : modulo) + " (el monto de la línea es la suma de los que agregues):";
    wrap.appendChild(etiqueta);

    var buscarInput = document.createElement("input");
    buscarInput.type = "text";
    buscarInput.className = "conc-linea-docs-buscar-input";
    buscarInput.placeholder = "Buscar por N°, RUT o nombre…";
    wrap.appendChild(buscarInput);

    var tableWrap = document.createElement("div");
    tableWrap.className = "table-wrap conc-linea-docs-tabla-wrap";
    var table = document.createElement("table");
    table.className = "data-table conc-linea-docs-tabla";
    var thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>N°</th><th>Tipo</th><th>Fecha</th><th>Contraparte</th><th style=\"text-align:right\">Monto</th><th></th></tr>";
    var tbody = document.createElement("tbody");
    table.appendChild(thead);
    table.appendChild(tbody);
    tableWrap.appendChild(table);
    wrap.appendChild(tableWrap);

    function renderChips() {
      chips.innerHTML = "";
      linea.documentos.forEach(function (doc, di) {
        var chip = document.createElement("span");
        chip.className = "conc-doc-chip";
        var texto = document.createElement("span");
        texto.textContent = doc.nombre + (doc.rut ? " (" + doc.rut + ")" : "") + " · " + formatoClp(num(doc.monto));
        chip.appendChild(texto);
        var btnX = document.createElement("button");
        btnX.type = "button";
        btnX.className = "conc-doc-chip-quitar";
        btnX.title = "Quitar documento";
        btnX.textContent = "✕";
        btnX.addEventListener("click", function () {
          linea.documentos.splice(di, 1);
          renderModalLineas();
          recomputarModalTotales();
        });
        chip.appendChild(btnX);
        chips.appendChild(chip);
      });
    }

    function renderTabla() {
      var candidatos = buscarDocumentosModulo(buscarInput.value, modulo, 30).filter(function (docFila) {
        return !documentoYaUsadoEnModal(modulo, docFila.dataset.idx);
      });
      tbody.innerHTML = "";
      if (!candidatos.length) {
        var trVacio = document.createElement("tr");
        var tdVacio = document.createElement("td");
        tdVacio.colSpan = 6;
        tdVacio.className = "muted";
        tdVacio.textContent = buscarInput.value.trim()
          ? "Sin resultados."
          : "No hay documentos disponibles de este módulo — cárgalos arriba, en \"Documentos auxiliares\".";
        trVacio.appendChild(tdVacio);
        tbody.appendChild(trVacio);
        return;
      }
      candidatos.forEach(function (docFila) {
        var tr = document.createElement("tr");
        var tdNum = document.createElement("td");
        tdNum.textContent = docFila.dataset.numeroDocumento;
        var tdTipo = document.createElement("td");
        tdTipo.textContent = docFila.dataset.tipoDocumento;
        var tdFecha = document.createElement("td");
        tdFecha.textContent = docFila.dataset.fecha || docFila.dataset.fechaIso;
        var tdContraparte = document.createElement("td");
        tdContraparte.textContent = docFila.dataset.nombre + (docFila.dataset.rut ? " (" + docFila.dataset.rut + ")" : "");
        var tdMonto = document.createElement("td");
        tdMonto.style.textAlign = "right";
        tdMonto.textContent = formatoClp(num(docFila.dataset.monto));
        var tdAccion = document.createElement("td");
        var btnAgregar = document.createElement("button");
        btnAgregar.type = "button";
        btnAgregar.className = "btn-link";
        btnAgregar.textContent = "Agregar";
        btnAgregar.addEventListener("click", function () {
          linea.documentos.push({
            modulo: modulo, idx: docFila.dataset.idx, rut: docFila.dataset.rut, nombre: docFila.dataset.nombre,
            tipo_doc: docFila.dataset.tipoDocumento, numero_doc: docFila.dataset.numeroDocumento,
            fecha_iso: docFila.dataset.fechaIso, monto: num(docFila.dataset.monto),
          });
          renderModalLineas();
          recomputarModalTotales();
        });
        tdAccion.appendChild(btnAgregar);
        tr.appendChild(tdNum);
        tr.appendChild(tdTipo);
        tr.appendChild(tdFecha);
        tr.appendChild(tdContraparte);
        tr.appendChild(tdMonto);
        tr.appendChild(tdAccion);
        tbody.appendChild(tr);
      });
    }

    buscarInput.addEventListener("input", renderTabla);
    renderChips();
    renderTabla();

    return wrap;
  }

  function renderModalLineas() {
    var tbody = document.getElementById("conc-modal-lineas-tbody");
    tbody.innerHTML = "";
    var esCargo = modalState.movimiento.cargo > 0;

    modalState.lineas.forEach(function (linea, li) {
      var tr = document.createElement("tr");
      tr.className = "conc-linea-row";

      var tdNum = document.createElement("td");
      tdNum.className = "conc-modal-num";
      tdNum.textContent = li + 2;
      tr.appendChild(tdNum);

      var tdCuenta = document.createElement("td");
      var textoActual = linea.codigo ? linea.codigo + " — " + linea.descripcion : "";
      var campo = crearCampoBusqueda(textoActual, "Seleccionar cuenta contable");
      tdCuenta.appendChild(campo.wrap);
      if (linea.codigo && esCuentaAuxiliar(linea.codigo)) {
        tdCuenta.appendChild(construirAreaDocumentos(linea));
      }
      tr.appendChild(tdCuenta);

      habilitarDropdown(
        campo.input, campo.results,
        function (texto) { return buscarCuentas(texto); },
        renderItemCuenta,
        function (cuenta) {
          if (linea.codigo === cuenta.codigo) return; // ya estaba elegida — no reinicia sus documentos
          linea.codigo = cuenta.codigo;
          linea.descripcion = cuenta.descripcion;
          linea.documentos = [];
          renderModalLineas();
          recomputarModalTotales();
        },
        { textoDe: function (cuenta) { return cuenta.codigo + " — " + cuenta.descripcion; }, todos: function () { return CUENTAS; } }
      );

      var montoLinea = montoDeLinea(linea);
      var tdDebe = document.createElement("td");
      tdDebe.className = "conc-col-monto";
      var tdHaber = document.createElement("td");
      tdHaber.className = "conc-col-monto";
      var tdMonto = esCargo ? tdDebe : tdHaber;
      if (linea.documentos.length) {
        tdMonto.textContent = formatoClp(montoLinea);
      } else {
        var inputMonto = document.createElement("input");
        inputMonto.type = "number";
        inputMonto.min = "0";
        inputMonto.step = "1";
        inputMonto.className = "conc-linea-monto-input";
        inputMonto.value = linea.monto || "";
        inputMonto.addEventListener("input", function () {
          linea.monto = num(inputMonto.value);
          recomputarModalTotales();
        });
        tdMonto.appendChild(inputMonto);
      }
      tr.appendChild(tdDebe);
      tr.appendChild(tdHaber);

      var tdQuitar = document.createElement("td");
      var btnQuitar = document.createElement("button");
      btnQuitar.type = "button";
      btnQuitar.className = "conc-linea-quitar";
      btnQuitar.title = "Quitar línea";
      btnQuitar.textContent = "✕";
      btnQuitar.addEventListener("click", function () {
        modalState.lineas.splice(li, 1);
        renderModalLineas();
        recomputarModalTotales();
      });
      tdQuitar.appendChild(btnQuitar);
      tr.appendChild(tdQuitar);

      tbody.appendChild(tr);
    });
  }

  function renderModalBanco() {
    var tbody = document.getElementById("conc-modal-banco-tbody");
    tbody.innerHTML = "";
    var bancoCodigo = document.getElementById("cuenta-banco-codigo").value;
    var bancoDescripcion = document.getElementById("cuenta-banco-descripcion").value;
    var esCargo = modalState.movimiento.cargo > 0;
    var monto = esCargo ? modalState.movimiento.cargo : modalState.movimiento.abono;

    var tr = document.createElement("tr");
    var tdNum = document.createElement("td");
    tdNum.className = "conc-modal-num";
    tdNum.textContent = "1";
    var tdCuenta = document.createElement("td");
    tdCuenta.textContent = bancoCodigo ? bancoCodigo + " — " + bancoDescripcion : "Elige la cuenta bancaria arriba primero";
    var tdDebe = document.createElement("td");
    tdDebe.className = "conc-col-monto";
    var tdHaber = document.createElement("td");
    tdHaber.className = "conc-col-monto";
    if (esCargo) { tdHaber.textContent = formatoClp(monto); } else { tdDebe.textContent = formatoClp(monto); }
    var tdVacia = document.createElement("td");
    tr.appendChild(tdNum);
    tr.appendChild(tdCuenta);
    tr.appendChild(tdDebe);
    tr.appendChild(tdHaber);
    tr.appendChild(tdVacia);
    tbody.appendChild(tr);
  }

  function renderModalCabecera() {
    var mov = modalState.movimiento;
    var esCargo = mov.cargo > 0;
    var monto = esCargo ? mov.cargo : mov.abono;

    var contMov = document.getElementById("conc-modal-mov");
    contMov.innerHTML = "";
    var info = document.createElement("div");
    info.className = "conc-modal-mov-info";
    var fechaEl = document.createElement("div");
    fechaEl.className = "conc-modal-mov-fecha";
    fechaEl.textContent = mov.fecha;
    var detalleEl = document.createElement("div");
    detalleEl.className = "conc-modal-mov-detalle";
    detalleEl.textContent = mov.detalle;
    var subEl = document.createElement("div");
    subEl.className = "conc-modal-mov-sub";
    subEl.textContent = "Cartola bancaria";
    info.appendChild(fechaEl);
    info.appendChild(detalleEl);
    info.appendChild(subEl);
    var montoEl = document.createElement("div");
    montoEl.className = "conc-modal-mov-monto " + (esCargo ? "cargo" : "abono");
    montoEl.textContent = (esCargo ? "− " : "") + formatoClp(monto);
    contMov.appendChild(info);
    contMov.appendChild(montoEl);

    document.getElementById("conc-modal-tipo").textContent = esCargo ? "Egreso" : "Ingreso";
    document.getElementById("conc-modal-fecha").textContent = mov.fecha;
    document.getElementById("conc-modal-glosa").value = mov.detalle;
  }

  function recomputarModalTotales() {
    var esCargo = modalState.movimiento.cargo > 0;
    var montoMovimiento = esCargo ? modalState.movimiento.cargo : modalState.movimiento.abono;
    var sumaLineas = modalState.lineas.reduce(function (acc, l) { return acc + montoDeLinea(l); }, 0);

    var debeTotal = esCargo ? sumaLineas : montoMovimiento;
    var haberTotal = esCargo ? montoMovimiento : sumaLineas;

    document.getElementById("conc-modal-debe").textContent = formatoClp(debeTotal);
    document.getElementById("conc-modal-haber").textContent = formatoClp(haberTotal);

    var cuadra = Math.round(debeTotal) === Math.round(haberTotal) && Math.round(sumaLineas) === Math.round(montoMovimiento);
    var badge = document.getElementById("conc-cuadra-badge");
    badge.textContent = cuadra ? "Cuadra" : "No cuadra";
    badge.className = "conc-cuadra-badge " + (cuadra ? "ok" : "bad");

    var todasConCuenta = modalState.lineas.length > 0 && modalState.lineas.every(function (l) { return !!l.codigo; });
    document.getElementById("conc-modal-crear").disabled = !(cuadra && todasConCuenta);
  }

  function abrirModal(fila) {
    var rowIndex = fila.dataset.row;
    var fecha = valor(fila, 'input[name^="fecha_"]');
    var detalle = fila.querySelector(".conc-mov-detalle").value;
    var cargo = num(valor(fila, 'input[name^="cargo_"]'));
    var abono = num(valor(fila, 'input[name^="abono_"]'));

    var lineasExistentes = LINEAS_POR_FILA[rowIndex];
    var lineas;
    if (lineasExistentes && lineasExistentes.length) {
      lineas = JSON.parse(JSON.stringify(lineasExistentes));
    } else {
      var montoMov = cargo > 0 ? cargo : abono;
      var propuesta = buscarPropuestaAutomatica(fila);
      if (propuesta) {
        var modulo = propuesta.dataset.modulo;
        var info = AUX_MODULOS[modulo];
        var cuenta = CUENTAS_POR_CODIGO[info.cuenta_codigo];
        lineas = [{
          codigo: info.cuenta_codigo, descripcion: cuenta ? cuenta.descripcion : "", monto: 0,
          documentos: [{
            modulo: modulo, idx: propuesta.dataset.idx, rut: propuesta.dataset.rut, nombre: propuesta.dataset.nombre,
            tipo_doc: propuesta.dataset.tipoDocumento, numero_doc: propuesta.dataset.numeroDocumento,
            fecha_iso: propuesta.dataset.fechaIso, monto: num(propuesta.dataset.monto),
          }],
        }];
      } else {
        lineas = [{ codigo: "", descripcion: "", monto: montoMov, documentos: [] }];
      }
    }

    modalState = {
      fila: fila, rowIndex: rowIndex,
      movimiento: { fecha: fecha, detalle: detalle, cargo: cargo, abono: abono },
      lineas: lineas,
    };

    renderModalCabecera();
    renderModalBanco();
    renderModalLineas();
    recomputarModalTotales();
    document.getElementById("conc-modal").hidden = false;
  }

  function cerrarModal() {
    document.getElementById("conc-modal").hidden = true;
    modalState = null;
  }

  document.addEventListener("click", function (ev) {
    var boton = ev.target.closest(".conc-abrir-modal");
    if (!boton) return;
    var fila = boton.closest(".conc-fila");
    if (fila) abrirModal(fila);
  });

  document.getElementById("conc-modal-close").addEventListener("click", cerrarModal);
  document.getElementById("conc-modal-cancelar").addEventListener("click", cerrarModal);
  document.getElementById("conc-modal").addEventListener("mousedown", function (ev) {
    if (ev.target.id === "conc-modal") cerrarModal();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && modalState) cerrarModal();
  });

  document.getElementById("conc-agregar-cuenta").addEventListener("click", function () {
    if (!modalState) return;
    modalState.lineas.push({ codigo: "", descripcion: "", monto: 0, documentos: [] });
    renderModalLineas();
    recomputarModalTotales();
  });

  document.getElementById("conc-modal-glosa").addEventListener("input", function (ev) {
    if (modalState) modalState.movimiento.detalle = ev.target.value;
  });

  document.getElementById("conc-modal-crear").addEventListener("click", function () {
    if (!modalState || document.getElementById("conc-modal-crear").disabled) return;
    var fila = modalState.fila;
    fila.querySelector(".conc-mov-detalle").value = modalState.movimiento.detalle;
    commitLineasAFormulario(fila, modalState.lineas);
    cerrarModal();
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
      var resuelta = fila.dataset.resuelta === "true";
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
      if (fila.dataset.resuelta !== "true") {
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
  // Arranque: reconstruye el estado de cada fila a partir de `data-
  // lineas-iniciales` (vacío en una carga nueva; con las líneas ya
  // armadas si la página se re-mostró tras un error de validación al
  // descargar — ver `app/conciliacion/routes.py:descargar`).
  // -------------------------------------------------------------------

  document.querySelectorAll(".conc-fila").forEach(function (fila) {
    var lineas = [];
    try {
      lineas = JSON.parse(fila.dataset.lineasIniciales || "[]");
    } catch (e) {
      lineas = [];
    }
    if (lineas.length) {
      commitLineasAFormulario(fila, lineas);
    } else {
      renderResumenFila(fila);
    }
  });
  recomputarEstadoDocumentos();
  actualizarContadores();
})();
