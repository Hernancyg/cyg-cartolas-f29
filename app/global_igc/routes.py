"""
"Calcular Global": nueva página que no existía en la app de Streamlit —
calculadora de Impuesto Global Complementario (IGC), año tributario 2026,
pedida por el usuario a partir de un Excel de referencia con las fórmulas
oficiales del Formulario 22 del SII. Un solo formulario con dos botones
(mismo <form>, distinto submit): "Calcular Global" recalcula y muestra
los resultados; "Limpiar" vuelve a la página en blanco.
"""

from flask import Blueprint, render_template, request

from app.auth.decorators import login_required
from app.global_igc.calculator import EntradaGlobal, calcular_global

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
