"""
Genera el Excel del kardex de depreciación (ver
`app/depreciacion/calculo.calcular_kardex`) — de UN activo
(`build_kardex_workbook`) o de TODOS los activos de una empresa, uno
debajo del otro en la MISMA hoja (`build_empresa_kardex_workbook`, usado
por "Tabla de depreciación → Descargar Excel": el usuario pidió que el
archivo de salida muestre lo mismo que el kardex de cada activo, todos
juntos en una sola hoja, con encabezado con color — 11-09-2026).
Mismo estilo simple (Arial, bordes finos) que `app/parsers/output_writer.py`.
"""

from datetime import datetime
from io import BytesIO

import xlwt
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

NUMFMT_MONTO = "#,##0"
NUMFMT_FECHA = "dd-mm-yyyy"
NUMFMT_FACTOR = "0.0000"

THIN = Side(style="thin")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

HEADER_FILL = PatternFill(start_color="1F3864", end_color="1F3864", fill_type="solid")
HEADER_FONT = Font(name="Arial", size=8, bold=True, color="FFFFFF")

KARDEX_HEADERS = [
    "Fecha", "Meses Utilizados", "Costo Total", "Factor CCMM", "Valor Actualizado",
    "Vida Útil Antes (meses)", "Depreciación del Ejercicio",
    "Deprec. Acum. (apertura)", "Factor CCMM", "Deprec. Acum. (Actualizado)",
    "Deprec. Acum. (cierre)", "Valor Libro",
]
KARDEX_COL_WIDTHS = {
    "A": 13, "B": 15, "C": 15, "D": 12, "E": 16, "F": 16, "G": 18,
    "H": 18, "I": 12, "J": 20, "K": 16, "L": 14,
}
_MONTO_COLS = {"C", "E", "G", "H", "J", "K", "L"}
_FACTOR_COLS = {"D", "I"}


def _escribir_kardex(ws, titulo: str, filas: list, start_row: int = 1) -> int:
    """Escribe un bloque título + encabezado (con color) + filas,
    empezando en `start_row`. Devuelve la fila libre siguiente (con un
    espacio de separación), para poder encadenar varios activos en la
    misma hoja."""
    if start_row == 1:
        for col, width in KARDEX_COL_WIDTHS.items():
            ws.column_dimensions[col].width = width

    titulo_row = start_row
    ws.cell(row=titulo_row, column=1, value=titulo).font = Font(name="Arial", size=10, bold=True)
    ws.merge_cells(start_row=titulo_row, start_column=1, end_row=titulo_row, end_column=len(KARDEX_HEADERS))

    header_row = titulo_row + 1
    for i, header in enumerate(KARDEX_HEADERS, start=1):
        cell = ws.cell(row=header_row, column=i, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER

    row = header_row + 1
    for fila in filas:
        valores = [
            fila["fecha"], fila["meses_utilizados"], fila["costo_total"], fila["factor_ccmm"],
            fila["valor_actualizado"], fila["vida_util_antes_meses"], fila["depreciacion_ejercicio"],
            fila["deprec_acum_apertura"], fila["factor_ccmm"], fila["deprec_acum_actualizado"],
            fila["deprec_acum_cierre"], fila["valor_libro"],
        ]
        for col_idx, valor in enumerate(valores, start=1):
            cell = ws.cell(row=row, column=col_idx, value=valor)
            cell.font = Font(name="Arial", size=8)
            cell.border = BORDER
            col_letter = get_column_letter(col_idx)
            if col_letter == "A":
                cell.number_format = NUMFMT_FECHA
                cell.alignment = Alignment(horizontal="center")
            elif col_letter in _MONTO_COLS:
                cell.number_format = NUMFMT_MONTO
                cell.alignment = Alignment(horizontal="right")
            elif col_letter in _FACTOR_COLS:
                cell.number_format = NUMFMT_FACTOR
                cell.alignment = Alignment(horizontal="right")
            else:
                cell.alignment = Alignment(horizontal="center")
        row += 1

    return row + 1


def build_kardex_workbook(empresa_nombre: str, activo: dict, filas: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Kardex"
    _escribir_kardex(ws, f"{empresa_nombre} — {activo['nombre_activo']} — Kardex de depreciación", filas)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_empresa_kardex_workbook(empresa_nombre: str, activos_con_kardex: list) -> bytes:
    """`activos_con_kardex`: lista de (activo, filas_kardex) — todos en
    UNA sola hoja, uno debajo del otro (título + encabezado + filas de
    cada activo, separados por una fila en blanco). Si la empresa no
    tiene ningún activo, la hoja queda con un solo aviso en vez de
    fallar."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Depreciación"

    if not activos_con_kardex:
        ws["A1"] = f"{empresa_nombre} — sin activos cargados"
        ws["A1"].font = Font(name="Arial", size=10, bold=True)
    else:
        row = 1
        for activo, filas in activos_con_kardex:
            titulo = f"{empresa_nombre} — {activo['nombre_activo']} — Kardex de depreciación"
            if not activo.get("activo", True):
                titulo += " (dado de baja)"
            row = _escribir_kardex(ws, titulo, filas, start_row=row)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Comprobantes contables de "Generar asiento" — mismas 17 columnas/estilos
# que app/conciliacion/export_writer.py (duplicado a propósito).
# ---------------------------------------------------------------------------

COMPROBANTE_HEADERS = [
    "Número", "Tipo", "Fecha", "Glosa", "Cuenta Detalle", "Glosa Detalle",
    "Centro Costo", "Sucursal", "Debe", "Haber", "Tipo Auxiliar",
    "A: Rut Cliente-Proveedor/H: Rut Prestador",
    "A: Razon Social/B: Descripción Movimiento Bancario/ H: Nombre Prestador",
    "A: Tipo De Documento/H: Tipo De Boleta Honorario",
    "A: Folio /B: Numero Documento/H: Folio Boleta",
    "A/B/H: Monto",
    "A: Fecha Vencimiento /B: Fecha /H: Fecha Emisión  (DD/MM/AAAA)",
]
COMPROBANTE_COL_WIDTHS_CHARS = {
    0: 7.17, 1: 9.99, 2: 10.44, 3: 28.17, 4: 16.53, 5: 27.99, 8: 14.26,
    11: 30.26, 12: 56.17, 13: 34.81, 14: 21.26, 15: 20.81, 16: 32.53,
}
COMPROBANTE_CURRENCY_FMT = "[$-340A]\\ #,##0"
COMPROBANTE_DATE_FMT = "DD/MM/YYYY"


def _int_o_none(valor):
    try:
        if valor in (None, ""):
            return None
        return int(round(float(valor)))
    except (TypeError, ValueError):
        return None


def build_comprobantes_workbook(filas: list) -> bytes:
    """`filas`: lista de filas de 17 columnas (ver
    `app/depreciacion/comprobantes.construir_filas`). Mismo estilo/anchos
    que la hoja "Comprobantes" de Conciliación/F29/Empresas Caja, para que
    se importe igual al sistema contable."""
    wb = xlwt.Workbook(encoding="utf-8")
    ws = wb.add_sheet("Comprobantes")

    header_style = xlwt.easyxf("font: name Calibri, height 200, bold on;")
    header_left = xlwt.easyxf("font: name Calibri, height 200, bold on; align: horiz left;")
    header_right = xlwt.easyxf("font: name Calibri, height 200, bold on; align: horiz right;")
    body_style = xlwt.easyxf("font: name Calibri, height 200;")
    currency_style = xlwt.easyxf("font: name Calibri, height 200;", num_format_str=COMPROBANTE_CURRENCY_FMT)
    date_style = xlwt.easyxf("font: name Calibri, height 200;", num_format_str=COMPROBANTE_DATE_FMT)

    header_styles = {10: header_left, 11: header_left, 14: header_left, 15: header_right}
    for col, texto in enumerate(COMPROBANTE_HEADERS):
        ws.write(0, col, texto, header_styles.get(col, header_style))
    for col, chars in COMPROBANTE_COL_WIDTHS_CHARS.items():
        ws.col(col).width = int(chars * 256)

    for row_idx, fila in enumerate(filas, start=1):
        (numero, tipo, fecha, glosa, cuenta, glosa_detalle, centro_costo,
         sucursal, debe, haber, tipo_aux, rut, razon_social, tipo_doc,
         numero_documento, valor, fecha_vencimiento) = fila

        numero_val = _int_o_none(numero)
        if numero_val is not None:
            ws.write(row_idx, 0, numero_val, body_style)
        if tipo:
            ws.write(row_idx, 1, tipo, body_style)
        if isinstance(fecha, datetime):
            ws.write(row_idx, 2, fecha, date_style)
        if glosa:
            ws.write(row_idx, 3, glosa, body_style)
        ws.write(row_idx, 4, cuenta or "", body_style)
        ws.write(row_idx, 5, glosa_detalle or "", body_style)
        if centro_costo:
            ws.write(row_idx, 6, centro_costo, body_style)
        if sucursal:
            ws.write(row_idx, 7, sucursal, body_style)
        debe_val = _int_o_none(debe)
        if debe_val:
            ws.write(row_idx, 8, debe_val, currency_style)
        haber_val = _int_o_none(haber)
        if haber_val:
            ws.write(row_idx, 9, haber_val, currency_style)
        if tipo_aux:
            ws.write(row_idx, 10, tipo_aux, body_style)
        if rut:
            ws.write(row_idx, 11, rut, body_style)
        if razon_social:
            ws.write(row_idx, 12, razon_social, body_style)
        tipo_doc_val = _int_o_none(tipo_doc)
        if tipo_doc_val is not None:
            ws.write(row_idx, 13, tipo_doc_val, body_style)
        numero_documento_val = _int_o_none(numero_documento)
        if numero_documento_val is not None:
            ws.write(row_idx, 14, numero_documento_val, body_style)
        valor_val = _int_o_none(valor)
        if valor_val:
            ws.write(row_idx, 15, valor_val, currency_style)
        if isinstance(fecha_vencimiento, datetime):
            ws.write(row_idx, 16, fecha_vencimiento, date_style)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
