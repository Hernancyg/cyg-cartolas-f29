"""
"Conciliación": pestaña nueva, por ahora solo para el rol admin, pedida
por el usuario para revisar/clasificar los movimientos de una cartola ya
convertida (el Excel que entrega "Subir Cartolas") contra el plan de
cuentas de la organización.

Primera etapa (esta), según lo que pidió el usuario ("creemos eso
primero y luego avanzamos con el archivo de salida"): solo cargar el
Excel convertido, mostrar cada movimiento (fecha, detalle, cargo, abono)
y permitir buscar y asignarle una cuenta del plan de cuentas ("Concepto")
por nombre. Todavía NO genera ningún archivo de salida — eso queda para
una siguiente ronda; por ahora el estado de la conciliación vive solo en
la página (recargar la pierde), igual que las vistas previas de "Subir
Cartolas" y "Generar F29".

El archivo de entrada es específicamente el que arma
`app/parsers/output_writer.py` (hoja "Banco", columnas B:E = FECHA
DIA/MES, DETALLE DE TRANSACCION, MONTO CHEQUES O CARGOS, MONTO DEPOSITOS
O ABONOS) — no un PDF ni la cartola original del banco.
"""

import io
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from openpyxl import load_workbook

from app.auth.decorators import admin_required
from app.conciliacion.plan_cuentas import PLAN_CUENTAS

conciliacion_bp = Blueprint("conciliacion", __name__, url_prefix="/conciliacion")

ALLOWED_EXT = (".xlsx", ".xlsm")


def _formatear_fecha(valor):
    """Las celdas de fecha del Excel convertido vienen como datetime de
    Python cuando `output_writer` pudo parsear la fecha original; si no
    pudo, quedó como texto tal cual — se muestra en ambos casos."""
    if isinstance(valor, datetime):
        return valor.strftime("%d-%m-%Y")
    if valor is None:
        return ""
    return str(valor).strip()


def _leer_excel_convertido(file_storage):
    """Devuelve (filas, error). `filas` es una lista de dicts con fecha
    (texto ya formateado), fecha_orden (datetime o None, para el rango de
    período), detalle, cargo y abono (float)."""
    try:
        wb = load_workbook(io.BytesIO(file_storage.read()), data_only=True)
    except Exception as exc:  # noqa: BLE001
        return None, f"No se pudo abrir el archivo: {exc}"

    ws = wb["Banco"] if "Banco" in wb.sheetnames else wb.active

    filas = []
    for fecha, detalle, cargo, abono in ws.iter_rows(min_row=2, min_col=2, max_col=5, values_only=True):
        if fecha is None and not detalle and not cargo and not abono:
            continue  # fila vacía (al final de la hoja, por ejemplo)
        filas.append({
            "fecha": _formatear_fecha(fecha),
            "fecha_orden": fecha if isinstance(fecha, datetime) else None,
            "detalle": (detalle or "").strip() if isinstance(detalle, str) else (detalle or ""),
            "cargo": float(cargo) if isinstance(cargo, (int, float)) else 0.0,
            "abono": float(abono) if isinstance(abono, (int, float)) else 0.0,
        })
    return filas, None


def _rango_periodo(filas):
    fechas = [f["fecha_orden"] for f in filas if f["fecha_orden"]]
    if not fechas:
        return None
    return f"{min(fechas).strftime('%d/%m/%Y')} - {max(fechas).strftime('%d/%m/%Y')}"


@conciliacion_bp.route("/", methods=["GET"])
@admin_required
def index():
    return render_template("conciliacion.html", filas=None, cuentas=PLAN_CUENTAS)


@conciliacion_bp.route("/procesar", methods=["POST"])
@admin_required
def procesar():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Sube el Excel convertido desde “Subir Cartolas” para continuar.", "error")
        return redirect(url_for("conciliacion.index"))

    nombre = archivo.filename
    if not nombre.lower().endswith(ALLOWED_EXT):
        flash("Formato no permitido. Sube el archivo .xlsx que descargaste desde “Subir Cartolas”.", "error")
        return redirect(url_for("conciliacion.index"))

    filas, error = _leer_excel_convertido(archivo)
    if error:
        flash(f"{error} ¿Es el Excel convertido desde “Subir Cartolas”?", "error")
        return redirect(url_for("conciliacion.index"))

    if not filas:
        flash("No se encontraron movimientos en el archivo. Verifica que sea el Excel convertido desde “Subir Cartolas”.", "error")
        return redirect(url_for("conciliacion.index"))

    return render_template(
        "conciliacion.html",
        filas=filas,
        periodo=_rango_periodo(filas),
        archivo_nombre=nombre,
        cuentas=PLAN_CUENTAS,
    )
