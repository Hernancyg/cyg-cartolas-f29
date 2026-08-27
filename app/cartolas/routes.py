"""
"Subir Cartolas": convierte cartolas bancarias (PDF o Excel) al formato
estándar de la planilla "Banco". Puerto de `pagina_subir_cartolas()` de la
app de Streamlit, con la misma lógica de `bank_parsers.py` /
`output_writer.py` (sin cambios), adaptada al ciclo request/response de
Flask:

  1. GET  /            -> grilla de bancos + zona de carga (banco por ?banco=).
  2. POST /procesar     -> parsea el archivo subido y muestra la vista
                            previa editable (misma página).
  3. POST /descargar    -> reconstruye el Excel a partir de las filas ya
                            editadas en el formulario y lo entrega como
                            descarga.
"""

import io

from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for

from app.auth.decorators import login_required
from app.cartolas.banks import BANKS, BANK_DISPLAY_TO_DETECTED, bank_by_key
from app.parsers.bank_parsers import parse_pdf, parse_excel, Transaction
from app.parsers.output_writer import build_output_workbook

cartolas_bp = Blueprint("cartolas", __name__, url_prefix="/cartolas")

ALLOWED_EXT = (".pdf", ".xlsx", ".xlsm", ".xls")


@cartolas_bp.route("/", methods=["GET"])
@login_required
def index():
    banco_key = request.args.get("banco")
    banco = bank_by_key(banco_key) if banco_key else None
    return render_template(
        "cartolas.html",
        banks=BANKS,
        banco_elegido=banco_key,
        banco_elegido_name=banco["name"] if banco else None,
        resultado=None,
    )


@cartolas_bp.route("/procesar", methods=["POST"])
@login_required
def procesar():
    banco_key = request.form.get("banco")
    banco = bank_by_key(banco_key) if banco_key else None
    archivo = request.files.get("archivo")

    if not banco:
        flash("Selecciona un banco antes de subir el archivo.", "error")
        return redirect(url_for("cartolas.index"))

    if not archivo or not archivo.filename:
        flash("Sube un archivo PDF o Excel para continuar.", "error")
        return redirect(url_for("cartolas.index", banco=banco_key))

    nombre = archivo.filename
    if not nombre.lower().endswith(ALLOWED_EXT):
        flash("Formato no permitido. Sube un PDF, XLSX o XLS.", "error")
        return redirect(url_for("cartolas.index", banco=banco_key))

    buffer = io.BytesIO(archivo.read())
    try:
        if nombre.lower().endswith(".pdf"):
            result = parse_pdf(buffer)
        else:
            result = parse_excel(buffer)
    except Exception as exc:  # noqa: BLE001
        flash(f"No se pudo procesar el archivo: {exc}", "error")
        return redirect(url_for("cartolas.index", banco=banco_key))

    esperado = BANK_DISPLAY_TO_DETECTED.get(banco["name"])
    aviso_banco = None
    if esperado and result.banco_detectado not in ("Desconocido", esperado):
        aviso_banco = (
            f"Seleccionaste <strong>{banco['name']}</strong>, pero el contenido del "
            f"archivo parece ser de <strong>{result.banco_detectado}</strong>. "
            "Verifica que subiste el archivo correcto."
        )

    total_cargo = sum(tx.cargo for tx in result.transacciones)
    total_abono = sum(tx.abono for tx in result.transacciones)
    base_name = nombre.rsplit(".", 1)[0]

    return render_template(
        "cartolas.html",
        banks=BANKS,
        banco_elegido=banco_key,
        banco_elegido_name=banco["name"],
        resultado={
            "transacciones": result.transacciones,
            "advertencias": result.advertencias,
            "aviso_banco": aviso_banco,
            "total_cargo": total_cargo,
            "total_abono": total_abono,
            "archivo_nombre": nombre,
            "base_name": base_name,
        },
    )


@cartolas_bp.route("/descargar", methods=["POST"])
@login_required
def descargar():
    fechas = request.form.getlist("fecha")
    detalles = request.form.getlist("detalle")
    cargos = request.form.getlist("cargo")
    abonos = request.form.getlist("abono")
    base_name = request.form.get("base_name") or "cartola"

    def to_float(v):
        try:
            return float(v) if v else 0.0
        except ValueError:
            return 0.0

    transacciones = [
        Transaction(
            fecha=fechas[i] if i < len(fechas) else "",
            descripcion=detalles[i] if i < len(detalles) else "",
            cargo=to_float(cargos[i]) if i < len(cargos) else 0.0,
            abono=to_float(abonos[i]) if i < len(abonos) else 0.0,
        )
        for i in range(len(fechas))
    ]

    wb = build_output_workbook(transacciones)
    output_buffer = io.BytesIO()
    wb.save(output_buffer)
    output_buffer.seek(0)

    return send_file(
        output_buffer,
        as_attachment=True,
        download_name=f"{base_name}_convertido.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
