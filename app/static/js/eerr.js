/* EERR Dinámico (24-09-2026) — flujo por pasos en una sola página.
   El servidor entrega las cuentas (GET /eerr/datos) y calcula el informe
   (POST /eerr/informe, que además guarda conceptos y asignación de la
   empresa); acá solo se maneja la interacción y se dibuja. */
(function () {
  "use strict";
  var INIT = window.EERR_INIT;
  var MESES = INIT.meses;
  var SIS_ESTILO = {
    nubox: { ini: "N", color: "#2F6FED", conexion: true },
    softland: { ini: "S", color: "#0E9488", conexion: false },
    defontana: { ini: "D", color: "#7A4FD0", conexion: false }
  };
  var CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  var S = {
    step: 1, sistema: "nubox", codigo: null, anio: null, desde: 1, hasta: 12,
    datos: null, conceptos: [], asig: {}, informe: null,
    filtro: "todas", q: "", verCuentas: true, abiertos: {}, cargando: false
  };

  var $ = function (s) { return document.querySelector(s); };
  var $$ = function (s) { return Array.prototype.slice.call(document.querySelectorAll(s)); };
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  var fmt = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
  function money(v) {
    if (!v || Math.round(v) === 0) return "";
    return v < 0 ? "(" + fmt.format(Math.round(-v)) + ")" : fmt.format(Math.round(v));
  }
  function pct(p) {
    if (p === null || p === undefined) return "";
    var s = Math.abs(p).toLocaleString("es-CL", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%";
    return p < 0 ? "(" + s + ")" : s;
  }
  function toast(t) {
    var el = $("#eerr-toast");
    el.textContent = t;
    el.classList.add("show");
    clearTimeout(toast.t);
    toast.t = setTimeout(function () { el.classList.remove("show"); }, 2200);
  }
  function empresasDe(sis) { return INIT.empresas[sis] || []; }
  function empresaActual() {
    return empresasDe(S.sistema).filter(function (e) { return e.codigo === S.codigo; })[0] || null;
  }
  function cod(c) { return c.codigo; }

  /* ---------------- navegación ---------------- */
  function puedeIr(n) {
    if (n >= 3 && !S.datos) {
      toast(S.codigo ? "Espera a que se carguen los datos de la empresa" : "Primero elige una empresa");
      return false;
    }
    return true;
  }
  function go(n) {
    if (!puedeIr(n)) { if (S.step !== 2 && n >= 3) go(2); return; }
    var antes = S.step;
    S.step = n;
    for (var i = 1; i <= 5; i++) $("#eerr-s" + i).hidden = i !== n;
    $$(".eerr-step").forEach(function (b) {
      var k = +b.dataset.step;
      if (k === n) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
      b.classList.toggle("done", k < n);
    });
    var e = empresaActual();
    $$(".eerr-empname").forEach(function (el) { el.textContent = e ? e.razon_social : ""; });
    if (n === 1) renderSistemas();
    if (n === 2) renderEmpresas();
    if (n === 3) renderConceptos();
    if (n === 4) renderCuentas();
    if (n === 5) pedirInforme(true);
    else if (antes === 3 && n === 4) guardar();
  }
  $$(".eerr-step").forEach(function (b) { b.addEventListener("click", function () { go(+b.dataset.step); }); });
  $$("[data-go]").forEach(function (b) {
    b.addEventListener("click", function () { go(+b.dataset.go); window.scrollTo({ top: 0 }); });
  });

  /* ---------------- paso 1: sistema ---------------- */
  function renderSistemas() {
    $("#eerr-sistemas").innerHTML = Object.keys(INIT.sistemas).map(function (k) {
      var s = SIS_ESTILO[k] || { ini: k[0].toUpperCase(), color: "#667085", conexion: false };
      var n = empresasDe(k).length;
      return '<button class="eerr-sis" type="button" data-s="' + k + '" aria-pressed="' + (S.sistema === k) + '">' +
        '<span class="mark" style="background:' + s.color + '">' + s.ini + "</span>" +
        '<span class="nm">' + esc(INIT.sistemas[k]) + "</span>" +
        '<span class="ct">' + n + " empresa" + (n === 1 ? "" : "s") + " asignada" + (n === 1 ? "" : "s") + "</span>" +
        '<span class="eerr-pill ' + (s.conexion ? "ok" : "pend") + '">' + (s.conexion ? "Conectado" : "Importación por definir") + "</span></button>";
    }).join("");
    $$(".eerr-sis").forEach(function (b) {
      b.addEventListener("click", function () {
        if (S.sistema !== b.dataset.s) { S.sistema = b.dataset.s; S.codigo = null; S.datos = null; }
        renderSistemas();
      });
    });
  }

  /* ---------------- paso 2: empresa y período ---------------- */
  function renderEmpresas() {
    var nombre = INIT.sistemas[S.sistema];
    var lista = empresasDe(S.sistema);
    var conexion = (SIS_ESTILO[S.sistema] || {}).conexion;
    $("#eerr-sisname").textContent = nombre;
    $("#eerr-empsub").textContent = conexion
      ? "Empresas seleccionadas en el conector de " + nombre + "."
      : "Empresas asignadas a " + nombre + " en Administrador → Sistemas contables. La importación de sus datos (libros mayores o balances) aún está por definir.";
    if (!lista.length) {
      $("#eerr-empresas").innerHTML = '<div class="eerr-empty"><b>No hay empresas para ' + esc(nombre) + ".</b><br>" +
        (conexion ? "Todavía no se importaron empresas desde el conector." : "Agrégalas en Administrador → Sistemas contables.") + "</div>";
      $("#eerr-periodo").hidden = true;
      return;
    }
    $("#eerr-empresas").innerHTML = lista.map(function (e) {
      var sinDatos = conexion && !e.anios.length;
      return '<button class="eerr-emp" type="button" data-c="' + esc(e.codigo) + '" aria-pressed="' + (e.codigo === S.codigo) + '">' +
        '<span class="alias">' + esc(e.codigo) + '</span><span class="rs">' + esc(e.razon_social) + "</span>" +
        (e.rut ? '<span class="rut">RUT ' + esc(e.rut) + "</span>" : "") +
        (sinDatos ? '<span class="nodata">Sin Estado de Resultados importado todavía</span>' : "") +
        (!conexion ? '<span class="nodata">Importación por definir</span>' : "") + "</button>";
    }).join("");
    $$(".eerr-emp").forEach(function (b) {
      b.addEventListener("click", function () { elegirEmpresa(b.dataset.c); });
    });
    renderPeriodo();
  }

  function elegirEmpresa(codigo) {
    var e = empresasDe(S.sistema).filter(function (x) { return x.codigo === codigo; })[0];
    if (!e) return;
    S.codigo = codigo;
    S.datos = null;
    S.anio = e.anios.length ? e.anios[0] : null;
    renderEmpresas();
    if (!(SIS_ESTILO[S.sistema] || {}).conexion) {
      toast("La importación desde " + INIT.sistemas[S.sistema] + " aún está por definir");
      return;
    }
    if (S.anio) cargarDatos();
  }

  function renderPeriodo() {
    var e = empresaActual();
    var box = $("#eerr-periodo");
    if (!e || !e.anios.length) { box.hidden = true; return; }
    box.hidden = false;
    $("#eerr-anio").innerHTML = e.anios.map(function (a) {
      return '<option value="' + a + '"' + (a === S.anio ? " selected" : "") + ">" + a + "</option>";
    }).join("");
    var conDatos = S.datos ? S.datos.meses_con_datos : [];
    function opts(sel) {
      return MESES.map(function (m, i) {
        var ok = conDatos.indexOf(i + 1) !== -1;
        return '<option value="' + (i + 1) + '"' + (ok ? "" : " disabled") + (i + 1 === sel ? " selected" : "") + ">" +
          m + (ok ? "" : " (sin datos)") + "</option>";
      }).join("");
    }
    $("#eerr-desde").innerHTML = opts(S.desde);
    $("#eerr-hasta").innerHTML = opts(S.hasta);
    $("#eerr-desde").disabled = $("#eerr-hasta").disabled = !S.datos;
    $("#eerr-estado-datos").textContent = S.cargando ? "Cargando datos…" : (S.datos ? S.datos.cuentas.length + " cuentas con movimiento en el año · " + S.datos.fuente : "");
  }

  $("#eerr-anio").addEventListener("change", function (e) { S.anio = +e.target.value; cargarDatos(); });
  $("#eerr-desde").addEventListener("change", function (e) {
    S.desde = +e.target.value; if (S.hasta < S.desde) S.hasta = S.desde; renderPeriodo();
  });
  $("#eerr-hasta").addEventListener("change", function (e) {
    S.hasta = +e.target.value; if (S.desde > S.hasta) S.desde = S.hasta; renderPeriodo();
  });

  function cargarDatos() {
    S.cargando = true;
    S.datos = null;
    renderPeriodo();
    var pedido = { codigo: S.codigo, anio: S.anio };
    var url = INIT.urls.datos + "?sistema=" + encodeURIComponent(S.sistema) +
      "&codigo=" + encodeURIComponent(S.codigo) + "&anio=" + encodeURIComponent(S.anio);
    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (pedido.codigo !== S.codigo || pedido.anio !== S.anio) return; // llegó tarde
        S.cargando = false;
        if (!res.ok) { toast(res.j.error || "No se pudieron cargar los datos"); renderPeriodo(); return; }
        S.datos = res.j;
        S.conceptos = res.j.conceptos;
        S.asig = res.j.asignaciones || {};
        var m = res.j.meses_con_datos;
        S.desde = m.length ? m[0] : 1;
        S.hasta = m.length ? m[m.length - 1] : 12;
        if (res.j.aviso) toast(res.j.aviso);
        renderPeriodo();
      })
      .catch(function () { S.cargando = false; toast("No se pudo conectar con el servidor"); renderPeriodo(); });
  }

  /* ---------------- paso 3: conceptos ---------------- */
  function nombreConcepto(id) {
    var c = S.conceptos.filter(function (x) { return x.id === id; })[0];
    return c ? c.n : id;
  }
  function describe(c) {
    if (c.tipo === "t") {
      var n = S.conceptos.filter(function (x) { return x.sec === c.id; }).length;
      return "Suma de " + n + " concepto" + (n === 1 ? "" : "s");
    }
    if (c.tipo === "f") return nombreConcepto(c.a) + " − " + nombreConcepto(c.b);
    var k = Object.keys(S.asig).filter(function (x) { return S.asig[x] === c.id; }).length;
    return k + " cuenta" + (k === 1 ? "" : "s") + " asignada" + (k === 1 ? "" : "s") + " · suma en " + INIT.secciones[c.sec];
  }
  function renderConceptos() {
    var badge = { g: '<span class="eerr-badge">Concepto</span>', t: '<span class="eerr-badge t">Total</span>', f: '<span class="eerr-badge f">Margen</span>' };
    $("#eerr-clist").innerHTML = S.conceptos.map(function (c) {
      var cls = c.tipo === "t" ? "total" : (c.tipo === "f" ? "formula" : "");
      return '<div class="eerr-crow ' + cls + (c.inc ? "" : " off") + '">' +
        '<div><span class="nm">' + esc(c.n) + "</span>" + badge[c.tipo] + (c.custom ? '<span class="eerr-badge new">Nuevo</span>' : "") +
        '<span class="sub">' + esc(describe(c)) + "</span></div>" +
        '<div class="eerr-seg" role="group" aria-label="Incluir ' + esc(c.n) + ' en el informe">' +
        '<button type="button" class="inc" data-id="' + esc(c.id) + '" data-v="1" aria-pressed="' + !!c.inc + '">Incluir</button>' +
        '<button type="button" class="exc" data-id="' + esc(c.id) + '" data-v="0" aria-pressed="' + !c.inc + '">No incluir</button></div>' +
        (c.custom ? '<button class="eerr-del" type="button" data-del="' + esc(c.id) + '">Quitar</button>' : "<span></span>") +
        "</div>";
    }).join("");
    $$("#eerr-clist .eerr-seg button").forEach(function (b) {
      b.addEventListener("click", function () {
        S.conceptos.forEach(function (c) { if (c.id === b.dataset.id) c.inc = b.dataset.v === "1"; });
        renderConceptos();
        guardarPronto();
      });
    });
    $$("#eerr-clist [data-del]").forEach(function (b) {
      b.addEventListener("click", function () {
        var id = b.dataset.del;
        S.conceptos = S.conceptos.filter(function (c) { return c.id !== id; });
        Object.keys(S.asig).forEach(function (k) { if (S.asig[k] === id) delete S.asig[k]; });
        renderConceptos();
        guardarPronto();
        toast("Concepto quitado; sus cuentas quedaron sin asignar");
      });
    });
  }
  $("#eerr-addform").addEventListener("submit", function (e) {
    e.preventDefault();
    var n = $("#eerr-newname").value.trim().replace(/\s+/g, " ").toUpperCase();
    if (!n) { $("#eerr-newname").focus(); toast("Escribe el nombre del concepto"); return; }
    if (S.conceptos.some(function (c) { return c.n.toUpperCase() === n; })) { toast("Ya existe un concepto con ese nombre"); return; }
    var sec = $("#eerr-newsec").value;
    var idx = S.conceptos.map(function (c) { return c.id; }).indexOf(sec);
    S.conceptos.splice(idx, 0, { id: "c" + Date.now(), n: n, tipo: "g", sec: sec, inc: true, custom: true });
    $("#eerr-newname").value = "";
    renderConceptos();
    guardarPronto();
    toast("“" + n + "” agregado a " + INIT.secciones[sec]);
  });

  /* ---------------- paso 4: asignar cuentas ---------------- */
  function enRango(c) {
    for (var i = S.desde - 1; i < S.hasta; i++) if (c.meses[i]) return true;
    return false;
  }
  function acumulado(c) {
    var s = 0;
    for (var i = S.desde - 1; i < S.hasta; i++) s += c.meses[i];
    return s;
  }
  function renderCuentas() {
    var lista = S.datos.cuentas.filter(enRango);
    $("#eerr-ncuentas").textContent = lista.length;
    var grupos = S.conceptos.filter(function (c) { return c.tipo === "g"; });
    var sin = lista.filter(function (c) { return !S.asig[cod(c)]; }).length;
    $("#eerr-nsin").textContent = sin;
    var q = S.q.toLowerCase();
    var filas = lista.filter(function (c) {
      return (S.filtro === "todas" || !S.asig[cod(c)]) && (!q || (c.codigo + " " + c.nombre).toLowerCase().indexOf(q) !== -1);
    });
    var opciones = Object.keys(INIT.secciones).map(function (sid) {
      return '<optgroup label="' + esc(INIT.secciones[sid]) + '">' + grupos.filter(function (g) { return g.sec === sid; }).map(function (g) {
        return '<option value="' + esc(g.id) + '">' + esc(g.n) + "</option>";
      }).join("") + "</optgroup>";
    }).join("");
    $("#eerr-tcu").innerHTML = filas.length ? filas.map(function (c) {
      var k = cod(c);
      return '<tr class="' + (S.asig[k] ? "" : "unassigned") + '"><td><b>' + esc(k) + "</b> " + esc(c.nombre) + "</td>" +
        '<td><span class="eerr-tipo ' + (c.tipo === 3 ? "g" : "p") + '">' + (c.tipo === 3 ? "Ganancia" : "Pérdida") + "</span></td>" +
        '<td class="num">' + (money(acumulado(c)) || "0") + "</td>" +
        '<td><select data-k="' + esc(k) + '" aria-label="Concepto para ' + esc(k) + '"><option value="">— Sin asignar —</option>' + opciones + "</select></td></tr>";
    }).join("") : '<tr><td colspan="4" class="muted" style="text-align:center;padding:18px">No hay cuentas que coincidan.</td></tr>';
    $$("#eerr-tcu select").forEach(function (s) {
      s.value = S.asig[s.dataset.k] || "";
      s.addEventListener("change", function () {
        if (s.value) S.asig[s.dataset.k] = s.value; else delete S.asig[s.dataset.k];
        renderCuentas();
        guardarPronto();
      });
    });
  }
  $("#eerr-buscar").addEventListener("input", function (e) { S.q = e.target.value; renderCuentas(); });
  $$(".eerr-chip").forEach(function (b) {
    b.addEventListener("click", function () {
      S.filtro = b.dataset.f;
      $$(".eerr-chip").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
      renderCuentas();
    });
  });

  /* ---------------- guardado + informe (servidor) ---------------- */
  function cuerpo(guardarConfig) {
    return {
      sistema: S.sistema, codigo: S.codigo, anio: S.anio, desde: S.desde, hasta: S.hasta,
      conceptos: S.conceptos, asignaciones: S.asig, guardar: !!guardarConfig
    };
  }
  function postInforme(guardarConfig) {
    return fetch(INIT.urls.informe, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": CSRF },
      body: JSON.stringify(cuerpo(guardarConfig))
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); });
  }
  function marcarGuardado(res) {
    var el = $("#eerr-saved");
    if (!res.ok) { el.textContent = ""; toast(res.j.error || "No se pudo guardar"); return; }
    if (res.j.aviso) { el.textContent = ""; toast(res.j.aviso); return; }
    el.textContent = "✓ Asignación guardada";
    S.conceptos = res.j.conceptos;
  }
  function guardar() {
    if (!S.datos) return Promise.resolve();
    return postInforme(true).then(marcarGuardado).catch(function () { toast("No se pudo guardar: sin conexión"); });
  }
  function guardarPronto() {
    $("#eerr-saved").textContent = "Guardando…";
    clearTimeout(guardarPronto.t);
    guardarPronto.t = setTimeout(guardar, 700);
  }

  function pedirInforme(guardarConfig) {
    clearTimeout(guardarPronto.t);
    $("#eerr-gb").innerHTML = '<tr><td class="muted" style="text-align:left;padding:18px">Calculando…</td></tr>';
    postInforme(guardarConfig).then(function (res) {
      if (!res.ok) { toast(res.j.error || "No se pudo calcular el informe"); return; }
      if (res.j.aviso) toast(res.j.aviso);
      S.informe = res.j.informe;
      S.conceptos = res.j.conceptos;
      renderInforme();
    }).catch(function () { toast("No se pudo conectar con el servidor"); });
  }

  /* ---------------- paso 5: informe ---------------- */
  function celdas(f) {
    var h = "";
    for (var j = 0; j < f.valores.length; j++) {
      var v = f.valores[j];
      h += '<td class="' + (v < 0 ? "neg" : "") + '">' + money(v) + '</td><td class="p">' + pct(f.pcts[j]) + "</td>";
    }
    return h + '<td class="acc ' + (f.acum < 0 ? "neg" : "") + '">' + money(f.acum) + '</td><td class="p acc">' + pct(f.acum_pct) + "</td>";
  }
  function renderInforme() {
    var I = S.informe, e = empresaActual();
    if (!I || !e) return;
    $("#eerr-rut").textContent = e.rut ? "RUT " + e.rut + " · " : "";
    var cols = I.columnas;
    $("#eerr-rango").textContent = cols.length === 1 ? cols[0] + " " + S.anio : cols[0] + " a " + cols[cols.length - 1] + " " + S.anio;
    $("#eerr-fuente").textContent = S.datos.fuente;
    var acumTit = cols.length === 1 ? cols[0].slice(0, 3) + " " + S.anio : cols[0].slice(0, 3) + " a " + cols[cols.length - 1].slice(0, 3) + " " + S.anio;
    $("#eerr-gh").innerHTML = "<tr><th>Concepto ↑</th>" + cols.map(function (m) {
      return "<th>" + esc(m) + " " + S.anio + '<span class="srt">⇅</span></th><th class="pct">%</th>';
    }).join("") + "<th>" + esc(acumTit) + '</th><th class="pct">%</th></tr>';

    var h = "";
    I.filas.forEach(function (f) {
      if (f.tipo === "cta") {
        var abierto = S.verCuentas && S.abiertos[f.padre] !== false;
        if (!abierto) return;
        h += '<tr class="cta"><td>' + esc(f.nombre) + "</td>" + celdas(f) + "</tr>";
        return;
      }
      if (f.tipo === "grupo") {
        var tiene = I.filas.some(function (x) { return x.tipo === "cta" && x.padre === f.id; });
        var open = S.verCuentas && S.abiertos[f.id] !== false;
        h += '<tr class="grupo"><td>' + (tiene
          ? '<button class="eerr-tog" type="button" data-t="' + esc(f.id) + '" aria-expanded="' + open + '" aria-label="Mostrar cuentas de ' + esc(f.nombre) + '">' + (open ? "▼" : "▶") + "</button>"
          : '<span class="eerr-tog"></span>') + esc(f.nombre) + "</td>" + celdas(f) + "</tr>";
        return;
      }
      h += '<tr class="' + f.tipo + '"><td>' + (f.tipo === "sinasig" ? "⚠ " : "") + esc(f.nombre) + "</td>" + celdas(f) + "</tr>";
    });
    $("#eerr-gb").innerHTML = h;
    $$(".eerr-tog[data-t]").forEach(function (b) {
      b.addEventListener("click", function () {
        S.abiertos[b.dataset.t] = b.getAttribute("aria-expanded") !== "true";
        renderInforme();
      });
    });
    var q = $("#eerr-cuadre"), cu = I.cuadre;
    if (cu.cuadra) { q.className = "eerr-cuadre ok"; q.textContent = "✓ Resultado cuadra con " + INIT.sistemas[S.sistema]; }
    else {
      var n = I.sin_asignar.length;
      q.className = "eerr-cuadre bad";
      q.textContent = "Diferencia con " + INIT.sistemas[S.sistema] + ": " + fmt.format(Math.round(cu.diferencia)) +
        (n ? " · asigna " + n + " cuenta" + (n === 1 ? "" : "s") : "");
    }
  }
  $("#eerr-vercuentas").addEventListener("change", function (e) { S.verCuentas = e.target.checked; S.abiertos = {}; renderInforme(); });

  $$("[data-exportar]").forEach(function (b) {
    b.addEventListener("click", function () {
      var f = $("#eerr-form-exportar");
      var c = cuerpo(false);
      ["sistema", "codigo", "anio", "desde", "hasta"].forEach(function (k) { f.elements[k].value = c[k]; });
      f.elements.conceptos.value = JSON.stringify(c.conceptos);
      f.elements.asignaciones.value = JSON.stringify(c.asignaciones);
      f.elements.formato.value = b.dataset.exportar;
      f.elements.con_cuentas.value = S.verCuentas ? "1" : "0";
      // submit() directo (sin evento "submit"): así no aparece el overlay
      // "Procesando…" de base.html, que en una descarga no se cerraría solo.
      f.submit();
      toast("Generando " + (b.dataset.exportar === "pdf" ? "PDF" : "Excel") + "…");
    });
  });

  go(1);
})();
