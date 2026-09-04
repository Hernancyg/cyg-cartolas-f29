"""
Genera el archivo de comprobantes de "Generar CSV F29" en formato .xls
(Excel binario, BIFF) — reemplaza el CSV anterior por pedido explícito del
usuario (04-09-2026), a partir de una plantilla real que entregó
(`plantillaCargaComprobantes_41.xls`, hoja "Comprobantes").

Columnas de la nueva plantilla, en este orden exacto (idéntico al archivo
entregado por el usuario, incluyendo espacios y mayúsculas/minúsculas):

  Número, Tipo, Fecha, Glosa, Cuenta Detalle, Glosa Detalle, Centro Costo,
  Sucursal, Debe, Haber, Tipo Auxiliar,
  A: Rut Cliente-Proveedor/H: Rut Prestador,
  A: Razon Social/B: Descripción Movimiento Bancario/ H: Nombre Prestador,
  A: Tipo De Documento/H: Tipo De Boleta Honorario,
  A: Folio /B: Numero Documento/H: Folio Boleta,
  A/B/H: Monto,
  A: Fecha Vencimiento /B: Fecha /H: Fecha Emisión  (DD/MM/AAAA)

Respecto de la plantilla anterior (CSV, 16 columnas — ver `f29_parser.
HEADER`/`filas_a_csv_bytes`, ya no usada por la ruta de descarga): cambia
el orden de "Tipo"/"Fecha"/"Glosa" (ahora Tipo va justo después de
Número), "Centro Costo" y "Sucursal" quedan intercambiados, y se agrega
una columna nueva "A: Tipo De Documento/H: Tipo De Boleta Honorario" que
esta app no completa (este parser no genera líneas de honorarios/
documentos, solo líneas de centralización de cuentas contables).

Este módulo NO recalcula nada — reutiliza tal cual las filas que ya arma
`f29_parser.construir_filas()` (16 columnas, mismo orden interno de
siempre, el que también usa la vista previa en pantalla de `f29.html`) y
solo las reordena/mapea a las columnas de la plantilla nueva al momento de
escribir el archivo. Así la vista previa HTML no se ve afectada por este
cambio de formato de exportación.

Usa `xlwt` (no `openpyxl`, que solo escribe .xlsx) porque el usuario pidió
explícitamente que el archivo salga con extensión .xls — la plantilla que
entregó es un binario BIFF real (Compound Document / OLE2), no un .xlsx
renombrado.
"""

from datetime import datetime
from io import BytesIO

import xlwt

HEADERS = [
    "Número",
    "Tipo",
    "Fecha",
    "Glosa",
    "Cuenta Detalle",
    "Glosa Detalle",
    "Centro Costo",
    "Sucursal",
    "Debe",
    "Haber",
    "Tipo Auxiliar",
    "A: Rut Cliente-Proveedor/H: Rut Prestador",
    "A: Razon Social/B: Descripción Movimiento Bancario/ H: Nombre Prestador",
    "A: Tipo De Documento/H: Tipo De Boleta Honorario",
    "A: Folio /B: Numero Documento/H: Folio Boleta",
    "A/B/H: Monto",
    "A: Fecha Vencimiento /B: Fecha /H: Fecha Emisión  (DD/MM/AAAA)",
]

# Ancho de columnas tomado literal de la plantilla del usuario (en
# caracteres del ancho estándar de Excel; xlwt espera 1/256 de esa
# unidad). Las columnas que no están aquí (Centro Costo, Sucursal, Haber,
# Tipo Auxiliar — índices 6, 7, 9, 10) se dejan con el ancho por defecto,
# igual que en la plantilla original.
COL_WIDTHS_CHARS = {
    0: 7.17,    # Número
    1: 9.99,    # Tipo
    2: 10.44,   # Fecha
    3: 28.17,   # Glosa
    4: 16.53,   # Cuenta Detalle
    5: 27.99,   # Glosa Detalle
    8: 14.26,   # Debe
    11: 30.26,  # A: Rut...
    12: 56.17,  # A: Razon Social...
    13: 34.81,  # A: Tipo De Documento...
    14: 21.26,  # A: Folio...
    15: 20.81,  # A/B/H: Monto
    16: 32.53,  # A: Fecha Vencimiento...
}

CURRENCY_FMT = "[$-340A]\\ #,##0"
DATE_FMT = "DD/MM/YYYY"


def _parse_fecha(fecha_str):
    """Convierte 'dd-mm-aaaa' (formato que entrega `construir_filas()`) u
    otros formatos comunes a datetime; None si viene vacío o no calza."""
    if not fecha_str:
        return None
    fecha_str = str(fecha_str).strip()
    if not fecha_str:
        return None
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            return datetime.strptime(fecha_str, fmt)
        except ValueError:
            continue
    return None


def _int_o_none(valor):
    try:
        if valor in (None, ""):
            return None
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def construir_filas_xls(filas):
    """Reordena las filas de `f29_parser.construir_filas()` (16 columnas,
    orden interno de siempre) al orden de columnas de la plantilla nueva
    (17 columnas). No cambia ningún valor, solo la posición — y agrega la
    columna nueva "Tipo De Documento" vacía."""
    filas_xls = []
    for fila in filas:
        (numero, fecha, glosa, tipo, cuenta, glosa_detalle, sucursal,
         centro_costo, debe, haber, tipo_aux, rut, razon_social,
         numero_documento, valor, fecha_vencimiento) = fila
        filas_xls.append([
            numero, tipo, fecha, glosa, cuenta, glosa_detalle, centro_costo,
            sucursal, debe, haber, tipo_aux, rut, razon_social,
            "",  # A: Tipo De Documento/H: Tipo De Boleta Honorario (nuevo, sin dato)
            numero_documento, valor, fecha_vencimiento,
        ])
    return filas_xls


def filas_a_xls_bytes(filas) -> bytes:
    """`filas`: salida de `f29_parser.construir_filas()`. Devuelve los
    bytes de un .xls (BIFF) con la hoja "Comprobantes", según la
    plantilla `plantillaCargaComprobantes_41.xls` entregada por el
    usuario (mismos encabezados, formato de moneda y de fecha, y anchos
    de columna)."""
    filas_xls = construir_filas_xls(filas)

    wb = xlwt.Workbook(encoding="utf-8")
    ws = wb.add_sheet("Comprobantes")

    header_style = xlwt.easyxf("font: name Calibri, height 200, bold on;")
    header_left = xlwt.easyxf("font: name Calibri, height 200, bold on; align: horiz left;")
    header_right = xlwt.easyxf("font: name Calibri, height 200, bold on; align: horiz right;")
    body_style = xlwt.easyxf("font: name Calibri, height 200;")
    currency_style = xlwt.easyxf("font: name Calibri, height 200;", num_format_str=CURRENCY_FMT)
    date_style = xlwt.easyxf("font: name Calibri, height 200;", num_format_str=DATE_FMT)

    # Alineación de encabezado tal como viene en la plantilla del usuario
    # (Tipo Auxiliar / RUT / Folio a la izquierda, Monto a la derecha).
    header_styles = {10: header_left, 11: header_left, 14: header_left, 15: header_right}
    for col, texto in enumerate(HEADERS):
        ws.write(0, col, texto, header_styles.get(col, header_style))

    for col, chars in COL_WIDTHS_CHARS.items():
        ws.col(col).width = int(chars * 256)

    for row_idx, fila in enumerate(filas_xls, start=1):
        (numero, tipo, fecha, glosa, cuenta, glosa_detalle, centro_costo,
         sucursal, debe, haber, tipo_aux, rut, razon_social, tipo_doc,
         numero_documento, valor, fecha_vencimiento) = fila

        numero_val = _int_o_none(numero)
        if numero_val is not None:
            ws.write(row_idx, 0, numero_val, body_style)
        if tipo:
            ws.write(row_idx, 1, tipo, body_style)
        fecha_val = _parse_fecha(fecha)
        if fecha_val is not None:
            ws.write(row_idx, 2, fecha_val, date_style)
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
        if tipo_doc:
            ws.write(row_idx, 13, tipo_doc, body_style)
        if numero_documento:
            ws.write(row_idx, 14, numero_documento, body_style)
        valor_val = _int_o_none(valor)
        if valor_val:
            ws.write(row_idx, 15, valor_val, currency_style)
        fecha_venc_val = _parse_fecha(fecha_vencimiento)
        if fecha_venc_val is not None:
            ws.write(row_idx, 16, fecha_venc_val, date_style)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
