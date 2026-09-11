"""
"Depreciación": pestaña nueva para generar la tabla de depreciación lineal
normal (según vida útil del SII, ver `app/data/depreciacion_categorias_
repo.py`) de los activos fijos de cada empresa cliente.

  - "Empresas": alta/baja de las empresas (registro propio, sin relación
    con "Empresas SII" de la pestaña "Consulta SII").
  - Detalle de una empresa: alta/baja de sus activos fijos (persisten en
    Supabase, ver `app/data/depreciacion_activos_repo.py`) y la tabla de
    depreciación calculada para el período elegido (mes/año), con
    descarga a Excel.
  - "Categorías SII": el catálogo editable de "tipo de bien -> vida útil
    normal" que sugiere la vida útil al agregar un activo nuevo.

El cálculo en sí (`app/depreciacion/calculo.py`) no toca Supabase — así se
puede testear con datos en memoria.
"""

import io
from datetime import date

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for

from app.auth.decorators import pagina_required
from app.data import depreciacion_activos_repo, depreciacion_categorias_repo, depreciacion_empresas_repo
from app.depreciacion.calculo import calcular_tabla
from app.depreciacion.export_writer import build_tabla_workbook

depreciacion_bp = Blueprint("depreciacion", __name__, url_prefix="/depreciacion")

MESES_LABEL = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def _parsear_periodo(valor):
    """'YYYY-MM' -> (year, month); el mes actual si falta o viene mal
    formado, para que la página siempre tenga algo razonable que mostrar."""
    if valor:
        try:
            year_str, month_str = valor.split("-")
            year, month = int(year_str), int(month_str)
            if 1 <= month <= 12:
                return year, month
        except (ValueError, AttributeError):
            pass
    hoy = date.today()
    return hoy.year, hoy.month


@depreciacion_bp.route("/", methods=["GET"])
@pagina_required("depreciacion.empresas")
def index():
    return redirect(url_for("depreciacion.empresas"))


# ---------------------------------------------------------------------------
# Empresas
# ---------------------------------------------------------------------------

@depreciacion_bp.route("/empresas", methods=["GET"])
@pagina_required("depreciacion.empresas")
def empresas():
    return render_template("depreciacion/empresas.html", empresas=depreciacion_empresas_repo.listar_empresas())


@depreciacion_bp.route("/empresas/crear", methods=["POST"])
@pagina_required("depreciacion.empresas")
def empresas_crear():
    rut = (request.form.get("rut") or "").strip()
    nombre = (request.form.get("nombre") or "").strip()
    if not nombre:
        flash("El nombre de la empresa es obligatorio.", "error")
        return redirect(url_for("depreciacion.empresas"))
    empresa = depreciacion_empresas_repo.crear_empresa(rut, nombre)
    flash(f"Empresa '{nombre}' agregada.", "success")
    return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa["id"]))


@depreciacion_bp.route("/empresas/<empresa_id>/eliminar", methods=["POST"])
@pagina_required("depreciacion.empresas")
def empresas_eliminar(empresa_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    depreciacion_empresas_repo.eliminar_empresa(empresa_id)
    if empresa:
        flash(f"Empresa '{empresa['nombre']}' eliminada (junto con todos sus activos).", "success")
    return redirect(url_for("depreciacion.empresas"))


# ---------------------------------------------------------------------------
# Detalle de una empresa: activos + tabla de depreciación
# ---------------------------------------------------------------------------

@depreciacion_bp.route("/empresas/<empresa_id>", methods=["GET"])
@pagina_required("depreciacion.empresas")
def empresa_detalle(empresa_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    if not empresa:
        flash("Esa empresa ya no existe.", "error")
        return redirect(url_for("depreciacion.empresas"))

    year, month = _parsear_periodo(request.args.get("periodo"))
    activos = depreciacion_activos_repo.listar_por_empresa(empresa_id)
    tabla = calcular_tabla(activos, year, month)
    categorias = depreciacion_categorias_repo.listar_categorias()

    return render_template(
        "depreciacion/empresa_detalle.html",
        empresa=empresa, activos=activos, categorias=categorias, tabla=tabla,
        periodo=f"{year:04d}-{month:02d}", periodo_label=f"{MESES_LABEL[month - 1]} {year}",
    )


@depreciacion_bp.route("/empresas/<empresa_id>/activos/crear", methods=["POST"])
@pagina_required("depreciacion.empresas")
def activos_crear(empresa_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    if not empresa:
        flash("Esa empresa ya no existe.", "error")
        return redirect(url_for("depreciacion.empresas"))

    nombre_activo = (request.form.get("nombre_activo") or "").strip()
    fecha_adquisicion = request.form.get("fecha_adquisicion") or ""
    valor_adquisicion_raw = (request.form.get("valor_adquisicion") or "").replace(".", "").replace(",", ".")
    vida_util_raw = (request.form.get("vida_util_anios") or "").strip()
    categoria_id = request.form.get("categoria_id") or None

    errores = []
    if not nombre_activo:
        errores.append("Falta el nombre del activo.")
    if not fecha_adquisicion:
        errores.append("Falta la fecha de adquisición.")
    try:
        valor_adquisicion = float(valor_adquisicion_raw)
        if valor_adquisicion <= 0:
            errores.append("El valor de adquisición debe ser mayor a 0.")
    except ValueError:
        errores.append("El valor de adquisición no es un número válido.")
        valor_adquisicion = None
    try:
        vida_util_anios = int(vida_util_raw)
        if vida_util_anios <= 0:
            errores.append("La vida útil debe ser mayor a 0 años.")
    except ValueError:
        errores.append("La vida útil (años) no es un número válido — elige una categoría o ingrésala a mano.")
        vida_util_anios = None

    if errores:
        for e in errores:
            flash(e, "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))

    depreciacion_activos_repo.crear_activo(
        empresa_id, categoria_id, nombre_activo, fecha_adquisicion, valor_adquisicion, vida_util_anios,
    )
    flash(f"Activo '{nombre_activo}' agregado.", "success")
    return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))


@depreciacion_bp.route("/empresas/<empresa_id>/activos/<activo_id>/baja", methods=["POST"])
@pagina_required("depreciacion.empresas")
def activos_baja(empresa_id, activo_id):
    depreciacion_activos_repo.dar_de_baja(activo_id)
    flash("Activo dado de baja (sigue apareciendo en los períodos ya pasados).", "success")
    return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))


@depreciacion_bp.route("/empresas/<empresa_id>/activos/<activo_id>/eliminar", methods=["POST"])
@pagina_required("depreciacion.empresas")
def activos_eliminar(empresa_id, activo_id):
    depreciacion_activos_repo.eliminar_activo(activo_id)
    flash("Activo eliminado.", "success")
    return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))


@depreciacion_bp.route("/empresas/<empresa_id>/descargar", methods=["GET"])
@pagina_required("depreciacion.empresas")
def descargar(empresa_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    if not empresa:
        flash("Esa empresa ya no existe.", "error")
        return redirect(url_for("depreciacion.empresas"))

    year, month = _parsear_periodo(request.args.get("periodo"))
    activos = depreciacion_activos_repo.listar_por_empresa(empresa_id)
    tabla = calcular_tabla(activos, year, month)
    periodo_label = f"{MESES_LABEL[month - 1]} {year}"

    contenido = build_tabla_workbook(empresa["nombre"], periodo_label, tabla)
    nombre_archivo = f"depreciacion_{empresa['nombre'].strip().replace(' ', '_')}_{year:04d}-{month:02d}.xlsx"
    return send_file(
        io.BytesIO(contenido), as_attachment=True, download_name=nombre_archivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Categorías SII (catálogo de vida útil)
# ---------------------------------------------------------------------------

@depreciacion_bp.route("/categorias", methods=["GET"])
@pagina_required("depreciacion.empresas")
def categorias():
    return render_template("depreciacion/categorias.html", categorias=depreciacion_categorias_repo.listar_categorias())


@depreciacion_bp.route("/categorias/guardar", methods=["POST"])
@pagina_required("depreciacion.empresas")
def categorias_guardar():
    secciones = request.form.getlist("c_seccion")
    descripciones = request.form.getlist("c_descripcion")
    vidas_utiles = request.form.getlist("c_vida_util")
    notas = request.form.getlist("c_nota")

    filas = []
    for i in range(len(secciones)):
        seccion = secciones[i].strip() if i < len(secciones) else ""
        descripcion = descripciones[i].strip() if i < len(descripciones) else ""
        if not seccion or not descripcion:
            continue
        vida_util_raw = (vidas_utiles[i] if i < len(vidas_utiles) else "").strip()
        vida_util_anios = int(vida_util_raw) if vida_util_raw.isdigit() else None
        nota = notas[i].strip() if i < len(notas) else ""
        filas.append({"seccion": seccion, "descripcion": descripcion, "vida_util_anios": vida_util_anios, "nota": nota})

    try:
        depreciacion_categorias_repo.guardar_todas(filas)
        flash("Categorías guardadas.", "success")
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("No se pudo guardar depreciacion_categorias: %s", exc)
        flash(
            "No se pudo guardar (¿falta ejecutar migration/006_depreciacion.sql en Supabase?).", "error",
        )
    return redirect(url_for("depreciacion.categorias"))
