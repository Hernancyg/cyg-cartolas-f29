"""
Genera el archivo de salida de "Empresas Caja": comprobantes contables
masivos de la caja de una empresa, en el mismo formato de plantilla que ya
usan "Generar F29" y "Conciliación" (17 columnas, hoja "Comprobantes").

No se reutiliza `app/conciliacion/export_writer.py` tal cual (aunque las
columnas/anchos/formatos son idénticos) — mismo criterio de "duplicar en
vez de refactorizar código ya en producción" que se usó entre F29 y
Conciliación.

## Diferencia clave con Conciliación: comprobantes de N líneas

Conciliación arma exactamente 2 líneas por comprobante (una cuenta contra
la otra). Aquí cada comprobante puede tener 2 a 4 líneas: una línea
agregada de la cuenta "Caja" (1101-01, fija) y una línea por cada cuenta
de detalle que tenga monto ese comprobante (por ejemplo, un mes de F29
con multas: línea F29 + línea Multas + línea Caja = 3 líneas; el mismo mes
sin multas: línea F29 + línea Caja = 2 líneas).

La regla de armado (confirmada con el usuario, generalizada desde el
patrón de 2 líneas de Conciliación/F29):

- Ingreso (dinero que entra a Caja: cobros a clientes, préstamo socio):
  Caja va al Debe; las cuentas de detalle van al Haber. Tipo = "I".
- Egreso (dinero que sale de Caja: pagos a proveedores/honorarios, F29,
  remuneraciones e imposiciones, créditos): las cuentas de detalle van al
  Debe; Caja va al Haber. Tipo = "E".
- La PRIMERA línea física del comprobante siempre lleva Número=0, Tipo,
  Fecha y Glosa; las líneas siguientes del mismo comprobante los dejan en
  blanco (mismo patrón ya verificado contra la plantilla real en
  Conciliación).
- En un egreso, las líneas de detalle van primero y Caja al final; en un
  ingreso, Caja va primero y las líneas de detalle después — así Caja
  siempre queda en la primera línea cuando es la que lleva el Debe (mismo
  orden que ya se comprobó contra la plantilla real en Conciliación: la
  primera línea es siempre la que lleva el Debe).
- "Centro Costo" = 100 en cada línea cuya cuenta tenga
  "Requiere Centro de Costo" = SI en el plan de cuentas; vacío si no.
- "Tipo Auxiliar" = "B" (+bloque bancario A/B/H) en cada línea cuya cuenta
  tenga "Atributo Bancario" = SI — en la práctica esto no debería aplicar
  nunca en Empresas Caja, ya que ni la cuenta Caja (1101-01) ni las cuentas
  de detalle configuradas llevan ese atributo en el plan de cuentas.
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

CUENTA_CAJA = {"codigo": "1101-01", "descripcion": "CUENTA CAJA", "es_banco": False, "requiere_centro_costo": False}


class FilaSinFecha(Exception):
    """Un comprobante no trae una fecha real (`datetime`) — no se puede
    escribir en el Excel de salida."""


class ComprobanteSinLineas(Exception):
    """Se intentó armar un comprobante sin ninguna línea de detalle (bug
    del llamador — no debería pasar si ya se validó que al menos un monto
    del mes/módulo es distinto de cero)."""


def _fila(cuenta_codigo, es_banco, glosa_detalle, centro_costo, debe, haber, es_primera, fecha, tipo, glosa):
    fila = ["", "", "", "", cuenta_codigo, glosa_detalle, centro_costo, "", debe or "", haber or "", "", "", "", "", "", "", ""]
    if es_primera:
        fila[0] = 0
        fila[1] = tipo
        fila[2] = fecha
        fila[3] = glosa
    if es_banco:
        fila[10] = "B"
        fila[12] = glosa_detalle
        fila[13] = 0
        fila[14] = 0
        fila[15] = debe or haber
        fila[16] = fecha
    return fila


def construir_filas_comprobante(fecha, glosa, lineas_detalle, ingreso):
    """`lineas_detalle`: lista de (cuenta_dict, monto) — una por cada
    ítem con monto distinto de cero en este comprobante (por ejemplo, un
    documento de Clientes/Proveedores/Honorarios, o los ítems de un mes de
    F29/Remuneraciones-Imposiciones/Créditos que no estén en cero).
    `ingreso`: True si es dinero que entra a Caja (Debe), False si sale
    (Haber). Devuelve la lista de filas (17 columnas) de ESTE comprobante,
    con Caja agregada (suma de todos los montos de detalle) y Número/Tipo/
    Fecha/Glosa solo en la primera línea física."""
    if not isinstance(fecha, datetime):
        raise FilaSinFecha(f"Comprobante sin fecha válida: {glosa!r}")
    if not lineas_detalle:
        raise ComprobanteSinLineas(f"Comprobante sin líneas de detalle: {glosa!r}")

    tipo = "I" if ingreso else "E"
    total_caja = sum(monto for _cuenta, monto in lineas_detalle)
    cc_caja = 100 if CUENTA_CAJA["requiere_centro_costo"] else ""

    filas = []
    primera_escrita = False

    def _marcar_primera():
        nonlocal primera_escrita
        es_primera = not primera_escrita
        primera_escrita = True
        return es_primera

    if ingreso:
        # Caja (Debe) primero, detalle (Haber) después — mismo orden que
        # Conciliación en un abono: la primera línea lleva el Debe.
        filas.append(_fila(CUENTA_CAJA["codigo"], CUENTA_CAJA["es_banco"], glosa, cc_caja, total_caja, "", _marcar_primera(), fecha, tipo, glosa))
        for cuenta, monto in lineas_detalle:
            cc = 100 if cuenta["requiere_centro_costo"] else ""
            filas.append(_fila(cuenta["codigo"], cuenta["es_banco"], glosa, cc, "", monto, _marcar_primera(), fecha, tipo, glosa))
    else:
        # Detalle (Debe) primero, Caja (Haber) al final — mismo orden que
        # Conciliación en un cargo: la primera línea lleva el Debe.
        for cuenta, monto in lineas_detalle:
            cc = 100 if cuenta["requiere_centro_costo"] else ""
            filas.append(_fila(cuenta["codigo"], cuenta["es_banco"], glosa, cc, monto, "", _marcar_primera(), fecha, tipo, glosa))
        filas.append(_fila(CUENTA_CAJA["codigo"], CUENTA_CAJA["es_banco"], glosa, cc_caja, "", total_caja, _marcar_primera(), fecha, tipo, glosa))

    return filas


def _int_o_none(valor):
    try:
        if valor in (None, ""):
            return None
        return int(round(float(valor)))
    except (TypeError, ValueError):
        return None


def comprobantes_a_xls_bytes(todas_las_filas) -> bytes:
    """`todas_las_filas`: lista ya aplanada de filas (17 columnas cada
    una), en el orden en que deben quedar en el archivo — normalmente la
    concatenación, en orden, de `construir_filas_comprobante(...)` de cada
    documento/mes de cada módulo."""
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

    for row_idx, fila in enumerate(todas_las_filas, start=1):
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
