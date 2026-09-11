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

from io import BytesIO

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
