"""
"Calcular Global": nueva página que no existía en la app de Streamlit —
calculadora de Impuesto Global Complementario (IGC), año tributario 2026,
pedida por el usuario a partir de un Excel de referencia con las fórmulas
oficiales del Formulario 22 del SII. Un solo formulario con dos botones
(mismo <form>, distinto submit): "Calcular Global" recalcula y muestra
los resultados; "Limpiar" vuelve a la página en blanco.
"""

import re

from flask import Blueprint, render_template, request, send_file

from app.auth.decorators import login_required
from app.global_igc.calculator import EntradaGlobal, calcular_global
from app.global_igc.pdf_generator import generar_pdf_global

global_igc_bp = Blueprint("global_igc", __name__, url_prefix="/global")


@global_igc_bp.route("/", methods=["GET"])
@login_required
def index():
    return render_template("global_igc.html", entrada=None, resultado=None)


@global_igc_bp.route("/calcular", methods=["POST"])
@login_required
def calcular():
    entrada = EntradaGlobal.desde_formulario(request.form)
    resultado = calcular_global(entrada)
    return render_template("global_igc.html", entrada=entrada, resultado=resultado)


@global_igc_bp.route("/pdf", methods=["POST"])
@login_required
def pdf():
    """Descarga en PDF el mismo cálculo que se está mostrando en pantalla
    (mismo <form> del resultado, botón "Descargar PDF" con formaction a
    esta ruta) — pedido por el usuario el 03-09-2026 a partir de un
    mockup de referencia."""
    entrada = EntradaGlobal.desde_formulario(request.form)
    resultado = calcular_global(entrada)
    buffer = generar_pdf_global(entrada, resultado)

    base = entrada.rut_contribuyente or entrada.nombre_contribuyente or "contribuyente"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_") or "contribuyente"
    nombre_archivo = f"Global_Complementario_AT{entrada.anio_tributario}_{slug}.pdf"

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=nombre_archivo,
    )
