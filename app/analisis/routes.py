"""
"Análisis": genera el Excel de análisis mensual (Estado de Situación
Financiera Clasificado, ver `app/analisis/generador.py`) a partir de los
CSV que deja el puente Nubox -> repo en `nubox_importado/`
(`app/data/nubox_importado_repo.py`).
"""

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from app.auth.decorators import pagina_required
from app.data import nubox_importado_repo
from app.analisis.generador import generar_excel_analisis, periodo_legible

analisis_bp = Blueprint("analisis", __name__, url_prefix="/analisis")


@analisis_bp.route("/", methods=["GET"])
@pagina_required("analisis.index")
def index():
    disponibles = nubox_importado_repo.listar_disponibles()
    for item in disponibles:
        item["periodo_label"] = periodo_legible(item["periodo"])
    return render_template("analisis/index.html", disponibles=disponibles)


@analisis_bp.route("/generar", methods=["POST"])
@pagina_required("analisis.index")
def generar():
    alias = (request.form.get("alias") or "").strip()
    periodo = (request.form.get("periodo") or "").strip()
    empresa_nombre = (request.form.get("empresa_nombre") or "").strip()
    empresa_rut = (request.form.get("empresa_rut") or "").strip()

    if not empresa_nombre:
        flash("Ingresa el nombre de la empresa para completar la portada.", "error")
        return redirect(url_for("analisis.index"))

    rutas = nubox_importado_repo.rutas_de(alias, periodo)
    if not rutas:
        flash(f"No se encontraron los archivos de Nubox para '{alias}' / {periodo}.", "error")
        return redirect(url_for("analisis.index"))
    ruta_balance, ruta_mayor = rutas

    resultado = generar_excel_analisis(ruta_balance, ruta_mayor, empresa_nombre, empresa_rut, periodo)

    if resultado.cuentas_sin_clasificar:
        cuentas = ", ".join(resultado.cuentas_sin_clasificar[:10])
        extra = f" (y {len(resultado.cuentas_sin_clasificar) - 10} más)" if len(resultado.cuentas_sin_clasificar) > 10 else ""
        flash(
            f"{len(resultado.cuentas_sin_clasificar)} cuenta(s) no tienen clasificación conocida y "
            f"quedaron fuera del Estado de Situación Financiera: {cuentas}{extra}. Hay que agregarlas "
            "a app/analisis/clasificacion_cuentas.json.",
            "error",
        )

    return send_file(
        resultado.archivo, as_attachment=True,
        download_name=f"Analisis_{alias}_{periodo}.xlsm",
        mimetype="application/vnd.ms-excel.sheet.macroEnabled.12",
    )
