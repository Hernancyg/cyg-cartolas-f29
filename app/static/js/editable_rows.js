// Agregar/quitar filas en las tablas editables (movimientos de cartola,
// montos F29, cuentas de administrador). Vainilla JS, sin dependencias —
// reemplaza el num_rows="dynamic" de st.data_editor.
(function () {
  document.addEventListener("click", function (ev) {
    var removeBtn = ev.target.closest(".row-remove");
    if (removeBtn) {
      var row = removeBtn.closest("tr");
      var tbody = row && row.parentElement;
      // No permitir vaciar completamente una tabla que requiere al menos 1
      // fila: clona la fila ANTES de quitarla (17-09-2026, corregido — antes
      // clonaba después de `row.remove()`, así que `tbody.querySelector("tr")`
      // ya no encontraba ninguna fila y la reposición quedaba muerta en
      // silencio; solo no se había notado porque ninguna tabla con
      // data-min-rows había llegado a este caso).
      var repuesto = (tbody && tbody.dataset.minRows && tbody.rows.length === 1) ? limpiarClon(row) : null;
      if (row) row.remove();
      if (repuesto) tbody.appendChild(repuesto);
      return;
    }
  });

  document.querySelectorAll("[id^='btn-add-row']").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var tableId = btn.getAttribute("data-table") || "tabla-movimientos";
      var table = document.getElementById(tableId);
      if (!table) {
        // fallback: la tabla más cercana en el mismo form
        var form = btn.closest("form");
        table = form && form.querySelector("table.data-table");
      }
      var tbody = table && table.querySelector("tbody");
      if (tbody) addRowFromTemplate(tbody);
    });
  });

  function limpiarClon(row) {
    var clon = row.cloneNode(true);
    clon.querySelectorAll("input").forEach(function (inp) { inp.value = ""; });
    clon.querySelectorAll("select").forEach(function (sel) { sel.selectedIndex = 0; });
    return clon;
  }

  function addRowFromTemplate(tbody) {
    var lastRow = tbody.querySelector("tr");
    if (!lastRow) return; // sin ninguna fila que clonar — el template debe renderizar al menos una (ver data-min-rows)
    tbody.appendChild(limpiarClon(lastRow));
  }
})();
