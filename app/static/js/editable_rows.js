// Agregar/quitar filas en las tablas editables (movimientos de cartola,
// montos F29, cuentas de administrador). Vainilla JS, sin dependencias —
// reemplaza el num_rows="dynamic" de st.data_editor.
(function () {
  document.addEventListener("click", function (ev) {
    var removeBtn = ev.target.closest(".row-remove");
    if (removeBtn) {
      var row = removeBtn.closest("tr");
      var tbody = row && row.parentElement;
      if (row) row.remove();
      // no permitir vaciar completamente una tabla que requiere al menos 1 fila
      if (tbody && tbody.dataset.minRows && tbody.rows.length === 0) {
        addRowFromTemplate(tbody);
      }
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

  function addRowFromTemplate(tbody) {
    var lastRow = tbody.querySelector("tr");
    var newRow;
    if (lastRow) {
      newRow = lastRow.cloneNode(true);
      newRow.querySelectorAll("input").forEach(function (inp) { inp.value = ""; });
      newRow.querySelectorAll("select").forEach(function (sel) { sel.selectedIndex = 0; });
    } else {
      return;
    }
    tbody.appendChild(newRow);
  }
})();
