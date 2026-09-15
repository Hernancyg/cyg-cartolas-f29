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

## Regla de armado de cada comprobante (banco + N líneas por movimiento)

Cada movimiento de la cartola se concilia contra la **cuenta bancaria
fija** que el admin elige arriba de la tabla (por ejemplo "1101-29 —
BANCO BCI", la misma para todos los movimientos del archivo) y una o más
**líneas de detalle** que arma en el modal "Crear comprobante" (14-09-2026,
segunda ronda de la conciliación asistida — reemplaza la única cuenta
"Concepto" por fila de las rondas anteriores):

- Cada línea de detalle es una cuenta del plan de cuentas con un monto —
  si es una de las 3 cuentas con documentos auxiliares (Clientes/
  Proveedores/Honorarios, ver `app/conciliacion/documentos.py`), la línea
  puede llevar VARIOS documentos adjuntos en vez de un monto suelto: cada
  documento se escribe como su PROPIA fila (mismo código de cuenta,
  repetido), con su propio bloque de Tipo Auxiliar "A"/"H" — el monto de
  la línea que se ve en pantalla es la suma de sus documentos, pero en el
  archivo de salida no hay una sola fila con el total, sino una por
  documento (igual criterio que "Empresas Caja" cuando se tildan varios
  documentos pendientes del mismo módulo).
- Si el movimiento es un **cargo** (dinero que sale del banco): la cuenta
  bancaria va al **Haber** y las líneas de detalle al **Debe**. Tipo = "E".
- Si el movimiento es un **abono** (dinero que entra al banco): la cuenta
  bancaria va al **Debe** y las líneas de detalle al **Haber**. Tipo = "I".
- La PRIMERA fila del comprobante es siempre la que lleva el **Debe**
  (con Número=0, Tipo, Fecha y Glosa); el resto no lleva esos 4 campos —
  mismo criterio que las rondas anteriores (en los abonos la primera fila
  es el banco, en los cargos la primera fila es la primera línea de
  detalle).
- "Glosa Detalle" repite el texto del movimiento (editable en pantalla,
  toma el detalle de la cartola por defecto) en TODAS las filas.
- "Centro Costo" = 100 en la fila de la cuenta que tenga "Requiere Centro
  de Costo" = SI en el plan de cuentas; vacío si no.
- "Tipo Auxiliar" = "B" en la fila del banco (con el bloque de detalle
  bancario: Razón Social/Descripción = texto del movimiento, Tipo De
  Documento = 0, Folio = 0, Monto = el monto de esa fila, Fecha = la
  fecha del movimiento); "A"/"H" en cada fila de un documento auxiliar
  (con el bloque real del documento — Rut, Razón Social, Tipo/Folio,
  Monto, Fecha); vacío en una línea de detalle sin documentos (cuenta
  suelta del plan de cuentas).
- El comprobante siempre queda balanceado (Debe == Haber == el monto del
  movimiento) — se valida server-side antes de armar el archivo, ver
  `app/conciliacion/routes.py:descargar`.
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


def _fila(numero, tipo, fecha, glosa, cuenta, glosa_detalle, centro_costo, debe, haber, auxiliar):
    """Una fila (17 columnas). `auxiliar`: `None` o un dict `{tipo, rut,
    nombre, tipo_documento_codigo, numero_documento, fecha, monto}` —
    `tipo` es "B" (banco), "A" (Clientes/Proveedores) o "H" (Honorarios).
    `debe`/`haber` son el monto CONTABLE de esta fila (14-09-2026: puede
    venir vacío a propósito — ver `construir_filas_comprobantes`, cuando
    una línea agrupa varios documentos solo la primera fila postea el
    total, las demás solo llevan su propio detalle auxiliar) — el monto
    del bloque auxiliar (columna "A/B/H: Monto") es SIEMPRE el de `auxiliar
    ["monto"]` (el valor propio de ESE documento), sin importar si esta
    fila posteó algo en Debe/Haber o no."""
    fila = [numero, tipo, fecha, glosa, cuenta, glosa_detalle, centro_costo, "", debe or "", haber or "", "", "", "", "", "", "", ""]
    if auxiliar:
        fila[10] = auxiliar["tipo"]
        fila[11] = auxiliar.get("rut") or ""
        fila[12] = auxiliar["nombre"]
        tipo_documento_codigo = auxiliar.get("tipo_documento_codigo")
        fila[13] = tipo_documento_codigo if tipo_documento_codigo is not None else ""
        fila[14] = auxiliar.get("numero_documento") or ""
        fila[15] = auxiliar.get("monto")
        fila[16] = auxiliar["fecha"]
    return fila


def construir_filas_comprobantes(movimientos, cuenta_banco):
    """`movimientos`: lista de dicts con `fecha` (datetime), `detalle`
    (texto ya editado, se usa como Glosa/Glosa Detalle), `cargo`/`abono`
    (float, exactamente uno de los dos > 0), y `lineas` — lista de UNA O
    MÁS líneas de detalle (14-09-2026, modal "Crear comprobante"), cada
    una un dict `{cuenta, monto, documentos}`:

    - `cuenta`: dict con `codigo`/`descripcion`/`es_banco`/`requiere_
      centro_costo` (del plan de cuentas).
    - `monto`: el monto de la línea SI `documentos` está vacío (cuenta
      suelta, sin documento auxiliar).
    - `documentos`: lista de dicts `{tipo, rut, nombre, tipo_documento_
      codigo, numero_documento, fecha, monto}` (uno por documento
      Cliente/Proveedor/Honorario adjunto a esta línea) — si no está
      vacía, la línea se expande en UNA FILA POR DOCUMENTO (mismo código
      de cuenta, cada una con su propio bloque de Tipo Auxiliar "A"/"H"
      y el monto de ESE documento) en vez de una sola fila con el total.

    La suma de todas las líneas (o de los montos de sus documentos) debe
    calzar con `cargo`/`abono` del movimiento — se valida antes de llegar
    acá (ver `app/conciliacion/routes.py:descargar`), así que esta
    función no vuelve a revisarlo. `cuenta_banco`: dict con los mismos 4
    campos, para la cuenta bancaria fija elegida arriba — siempre aporta
    exactamente UNA fila, con el bloque "B" (Tipo Auxiliar bancario).
    Devuelve la lista de filas (17 columnas cada una) lista para escribir
    en el .xls."""
    filas = []
    for mov in movimientos:
        fecha = mov["fecha"]
        if not isinstance(fecha, datetime):
            raise FilaSinFecha(f"Movimiento sin fecha válida: {mov!r}")
        detalle = mov["detalle"]
        es_cargo = mov["cargo"] > 0
        monto_total = mov["cargo"] if es_cargo else mov["abono"]
        tipo = "E" if es_cargo else "I"

        cc_banco = 100 if cuenta_banco["requiere_centro_costo"] else ""
        aux_banco = {
            "tipo": "B", "rut": "", "nombre": detalle, "tipo_documento_codigo": 0,
            "numero_documento": 0, "fecha": fecha, "monto": monto_total,
        } if cuenta_banco["es_banco"] else None

        # Cada línea de detalle sin documentos aporta UNA fila. Una línea
        # CON documentos aporta una fila POR documento (para no perder el
        # detalle de Rut/Folio/Monto de cada uno) — pero el monto CONTABLE
        # (Debe/Haber) de esa cuenta se postea UNA sola vez, en la primera
        # de esas filas, por el TOTAL de la línea; las demás quedan con
        # Debe/Haber vacío (14-09-2026, confirmado por el usuario contra un
        # ejemplo real: varias facturas del mismo cliente en una línea
        # postean el monto sumado una sola vez, cada una con su propio
        # detalle auxiliar aparte).
        detalle_datos = []  # [(cuenta, monto_a_postear_o_None, auxiliar_or_None)]
        for linea in mov["lineas"]:
            cuenta = linea["cuenta"]
            if linea["documentos"]:
                total_linea = sum(doc["monto"] for doc in linea["documentos"])
                for i, doc in enumerate(linea["documentos"]):
                    detalle_datos.append((cuenta, total_linea if i == 0 else None, doc))
            else:
                detalle_datos.append((cuenta, linea["monto"], None))

        filas_detalle = []
        for cuenta, monto, auxiliar in detalle_datos:
            if monto is None:
                debe, haber, cc = None, None, ""
            else:
                debe, haber = (monto, None) if es_cargo else (None, monto)
                cc = 100 if cuenta["requiere_centro_costo"] else ""
            filas_detalle.append(_fila("", "", "", "", cuenta["codigo"], detalle, cc, debe, haber, auxiliar))

        debe_banco, haber_banco = (None, monto_total) if es_cargo else (monto_total, None)
        fila_banco = _fila("", "", "", "", cuenta_banco["codigo"], detalle, cc_banco, debe_banco, haber_banco, aux_banco)

        if es_cargo:
            # Banco al Haber: la primera fila es la primera línea de detalle (Debe).
            primeros_campos = [0, tipo, fecha, detalle]
            for i, campo in enumerate(primeros_campos):
                filas_detalle[0][i] = campo
            filas.extend(filas_detalle)
            filas.append(fila_banco)
        else:
            # Banco al Debe: la primera fila es el banco.
            fila_banco[0], fila_banco[1], fila_banco[2], fila_banco[3] = 0, tipo, fecha, detalle
            filas.append(fila_banco)
            filas.extend(filas_detalle)
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
