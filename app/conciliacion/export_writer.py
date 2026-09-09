"""
Genera el archivo de salida de "Conciliación" (segunda ronda, 09-09-2026):
un .xls de comprobantes contables, uno por cada movimiento de la cartola ya
clasificado, en el mismo formato de plantilla que ya usa "Generar F29"
(`plantillaCargaComprobantes_41.xls` / `_42.xls`, hoja "Comprobantes") — el
usuario entregó una muestra de esa plantilla ya llena
(`plantillaCargaComprobantes_42.xls`) junto con la cartola convertida que la
generó, para que el mapeo de columnas se dedujera de ahí.

No se reutiliza `app/parsers/f29_export_writer.py` tal cual (aunque las
columnas/anchos/formatos son idénticos) para no arriesgar ese módulo, ya en
producción — se duplican aquí las constantes de la plantilla, igual que se
hizo en su momento entre F29 de un período y F29 masivo.

## Regla de armado de cada comprobante (2 líneas por movimiento)

Cada movimiento de la cartola se concilia contra DOS cuentas:

- La **cuenta bancaria fija** que el admin elige arriba de la tabla (por
  ejemplo "1101-29 — BANCO BCI") — la misma para todos los movimientos del
  archivo, porque todos vienen de la cartola de ese banco.
- La **cuenta "Concepto"** que el admin elige por cada fila (el buscador ya
  existente) — la contra-cuenta de ese movimiento en particular.

Según confirmó el usuario con su propia plantilla de ejemplo:

- Si el movimiento es un **cargo** (dinero que sale del banco): la cuenta
  bancaria va al **Haber** y la cuenta Concepto al **Debe**. Tipo = "E".
- Si el movimiento es un **abono** (dinero que entra al banco): la cuenta
  bancaria va al **Debe** y la cuenta Concepto al **Haber**. Tipo = "I".
- La primera línea del comprobante es siempre la que lleva el **Debe**
  (con Número=0, Tipo, Fecha y Glosa); la segunda línea es siempre la que
  lleva el **Haber** (sin esos 4 campos) — confirmado contra las 7
  muestras de la plantilla: en los abonos la primera línea es el banco, en
  los cargos la primera línea es la cuenta Concepto.
- "Glosa Detalle" repite el texto del movimiento (editable en pantalla,
  toma el detalle de la cartola por defecto) en AMBAS líneas.
- "Centro Costo" = 100 en la línea de la cuenta que tenga
  "Requiere Centro de Costo" = SI en el plan de cuentas (columna del mismo
  nombre); vacío si no.
- "Tipo Auxiliar" = "B" en la línea de la cuenta que tenga
  "Atributo Bancario" = SI en el plan de cuentas; y en ese caso también se
  llena el bloque "A/B/H" de detalle bancario: Razon Social/Descripción =
  el texto del movimiento, Tipo De Documento = 0, Folio = 0, Monto = el
  mismo monto de esa línea, Fecha = la misma fecha del movimiento.
- "Número" = 0 en la primera línea, vacío en la segunda (así también
  "Sucursal", que esta ronda no se implementa — la plantilla del usuario
  la deja vacía en las 7 muestras, y no pidió usar el atributo
  "Requiere Sucursal" del plan de cuentas).
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

# Mismos anchos/formatos que `f29_export_writer.py` — misma plantilla del
# usuario, ver ese módulo para más detalle de cómo se midieron.
COL_WIDTHS_CHARS = {
    0: 7.17,
    1: 9.99,
    2: 10.44,
    3: 28.17,
    4: 16.53,
    5: 27.99,
    8: 14.26,
    11: 30.26,
    12: 56.17,
    13: 34.81,
    14: 21.26,
    15: 20.81,
    16: 32.53,
}

CURRENCY_FMT = "[$-340A]\\ #,##0"
DATE_FMT = "DD/MM/YYYY"


class FilaSinFecha(Exception):
    """La fila no trae una fecha real (`datetime`) — no se puede escribir
    en el Excel de salida. No debería ocurrir con cartolas normales; el
    llamador decide si abortar o avisar al usuario."""


def _fila_debe(fecha, tipo, glosa, cuenta, glosa_detalle, centro_costo, monto, es_banco):
    fila = ["", "", "", "", cuenta, glosa_detalle, centro_costo, "", monto, "", "", "", "", "", "", "", ""]
    fila[0] = 0
    fila[1] = tipo
    fila[2] = fecha
    fila[3] = glosa
    if es_banco:
        fila[10] = "B"
        fila[12] = glosa_detalle
        fila[13] = 0
        fila[14] = 0
        fila[15] = monto
        fila[16] = fecha
    return fila


def _fila_haber(fecha, cuenta, glosa_detalle, centro_costo, monto, es_banco):
    fila = ["", "", "", "", cuenta, glosa_detalle, centro_costo, "", "", monto, "", "", "", "", "", "", ""]
    if es_banco:
        fila[10] = "B"
        fila[12] = glosa_detalle
        fila[13] = 0
        fila[14] = 0
        fila[15] = monto
        fila[16] = fecha
    return fila


def construir_filas_comprobantes(movimientos, cuenta_banco):
    """`movimientos`: lista de dicts con `fecha` (datetime), `detalle`
    (texto ya editado, se usa como Glosa/Glosa Detalle), `cargo`/`abono`
    (float, exactamente uno de los dos > 0), `concepto` (dict con
    `codigo`/`descripcion`/`es_banco`/`requiere_centro_costo`).
    `cuenta_banco`: dict con los mismos 4 campos, para la cuenta bancaria
    fija elegida arriba. Devuelve la lista de filas (17 columnas cada una,
    2 filas por movimiento) lista para escribir en el .xls."""
    filas = []
    for mov in movimientos:
        fecha = mov["fecha"]
        if not isinstance(fecha, datetime):
            raise FilaSinFecha(f"Movimiento sin fecha válida: {mov!r}")
        detalle = mov["detalle"]
        concepto = mov["concepto"]
        es_cargo = mov["cargo"] > 0
        monto = mov["cargo"] if es_cargo else mov["abono"]
        tipo = "E" if es_cargo else "I"

        if es_cargo:
            cuenta_debe, cuenta_haber = concepto, cuenta_banco
        else:
            cuenta_debe, cuenta_haber = cuenta_banco, concepto

        cc_debe = 100 if cuenta_debe["requiere_centro_costo"] else ""
        cc_haber = 100 if cuenta_haber["requiere_centro_costo"] else ""

        filas.append(_fila_debe(
            fecha, tipo, detalle, cuenta_debe["codigo"], detalle, cc_debe, monto, cuenta_debe["es_banco"],
        ))
        filas.append(_fila_haber(
            fecha, cuenta_haber["codigo"], detalle, cc_haber, monto, cuenta_haber["es_banco"],
        ))
    return filas


def _int_o_none(valor):
    try:
        if valor in (None, ""):
            return None
        return int(round(float(valor)))
    except (TypeError, ValueError):
        return None


def comprobantes_a_xls_bytes(movimientos, cuenta_banco) -> bytes:
    """Devuelve los bytes de un .xls (BIFF) con la hoja "Comprobantes",
    misma plantilla que usa "Generar F29" — ver `construir_filas_
    comprobantes()` para la lógica de armado de cada línea."""
    filas = construir_filas_comprobantes(movimientos, cuenta_banco)

    wb = xlwt.Workbook(encoding="utf-8")
    ws = wb.add_sheet("Comprobantes")

    header_style = xlwt.easyxf("font: name Calibri, height 200, bold on;")
    header_left = xlwt.easyxf("font: name Calibri, height 200, bold on; align: horiz left;")
    header_right = xlwt.easyxf("font: name Calibri, height 200, bold on; align: horiz right;")
    body_style = xlwt.easyxf("font: name Calibri, height 200;")
    currency_style = xlwt.easyxf("font: name Calibri, height 200;", num_format_str=CURRENCY_FMT)
    date_style = xlwt.easyxf("font: name Calibri, height 200;", num_format_str=DATE_FMT)

    header_styles = {10: header_left, 11: header_left, 14: header_left, 15: header_right}
    for col, texto in enumerate(HEADERS):
        ws.write(0, col, texto, header_styles.get(col, header_style))

    for col, chars in COL_WIDTHS_CHARS.items():
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
