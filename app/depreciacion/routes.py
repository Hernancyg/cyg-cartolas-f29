"""
"Depreciación": pestaña nueva para generar la tabla de depreciación lineal
normal (según vida útil del SII, ver `app/data/depreciacion_categorias_
repo.py`) de los activos fijos de cada empresa cliente.

  - "Empresas": alta/baja de las empresas (registro propio, sin relación
    con "Empresas SII" de la pestaña "Consulta SII").
  - Detalle de una empresa: alta/baja de sus activos fijos (persisten en
    Supabase, ver `app/data/depreciacion_activos_repo.py`) y la tabla de
    depreciación calculada para el período elegido (mes/año, todos los
    activos juntos), con descarga a Excel.
  - Ficha de un activo: su KARDEX de depreciación (una fila por período,
    normalmente un año, con los meses utilizados editables a mano — ver
    `app/data/depreciacion_periodos_repo.py` y `calculo.calcular_kardex`),
    igual a la planilla de referencia que entregó el usuario (11-09-2026):
    Fecha/Costo/Adiciones/Vida útil restante/Depreciación del ejercicio/
    Acumulada/Valor libro encadenados fila a fila.
  - "Categorías SII": el catálogo editable de "tipo de bien -> vida útil
    normal" que sugiere la vida útil al agregar un activo nuevo.
  - "Grupos Contables": las 3 cuentas de depreciación (Gasto/Acumulada/
    Corrección Monetaria) de cada "cuenta del activo fijo" (ej.
    "1204-01 VEHICULOS") — se configuran UNA vez por grupo, no por cada
    activo individual (rediseño 11-09-2026, ver `app/data/depreciacion_
    grupos_contables_repo.py`). Cada activo solo elige a qué grupo
    pertenece al crearlo.
  - "Generar asiento": elige un mes/año a gestionar y arma el comprobante
    contable (mismo formato de 17 columnas que F29/Conciliación/Caja
    Empresas) CONSOLIDADO por grupo contable (todos los activos de un
    mismo grupo suman en una sola línea) — solo con los períodos del
    kardex que todavía no se hayan asentado antes (ver `app/data/
    depreciacion_asientos_repo.py`, la "memoria" de lo ya generado, y
    `app/depreciacion/comprobantes.py` para el armado de cada línea). Si
    el kardex de un activo todavía no llega hasta el mes elegido, se le
    agrega automáticamente una fila nueva que cubra los meses que faltan
    (factor CCMM 1, editable después a mano en su kardex si hace falta
    corregirlo) — así no hay que ir período por período a cada activo
    antes de poder generar.

El cálculo en sí (`app/depreciacion/calculo.py`) no toca Supabase — así se
puede testear con datos en memoria.
"""

import io
from datetime import date

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for

from app.auth.decorators import pagina_required
from app.conciliacion.plan_cuentas import CUENTAS_POR_CODIGO, PLAN_CUENTAS
from app.data import (
    depreciacion_activos_repo, depreciacion_asientos_repo, depreciacion_categorias_repo,
    depreciacion_empresas_repo, depreciacion_grupos_contables_repo, depreciacion_periodos_repo,
)
from app.depreciacion import comprobantes
from app.depreciacion.calculo import (
    calcular_kardex, calcular_tabla, fusionar_kardex_por_anio, meses_faltantes, parse_fecha, ultimo_dia_mes,
)
from app.depreciacion.export_writer import build_comprobantes_workbook, build_empresa_kardex_workbook, build_kardex_workbook

depreciacion_bp = Blueprint("depreciacion", __name__, url_prefix="/depreciacion")

MESES_LABEL = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
# [("01", "Enero"), ..., ("12", "Diciembre")] — para los <select> de mes de
# "Tabla de depreciación" y "Generar asiento" (el <input type="month">
# nativo no se puede re-estilar; ver esos templates).
MESES_OPCIONES = [(f"{i + 1:02d}", nombre) for i, nombre in enumerate(MESES_LABEL)]


def _anios_disponibles():
    """Rango razonable para el <select> de año: 15 años atrás (activos
    antiguos) hasta el año que viene."""
    hoy = date.today()
    return list(range(hoy.year - 15, hoy.year + 2))


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
        empresa=empresa, activos=activos, categorias=categorias, tabla=tabla, cuentas=PLAN_CUENTAS,
        periodo=f"{year:04d}-{month:02d}", periodo_label=f"{MESES_LABEL[month - 1]} {year}",
        MESES_OPCIONES=MESES_OPCIONES, anios_disponibles=_anios_disponibles(),
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
    grupo_contable_codigo = request.form.get("grupo_contable_codigo") or None

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
        grupo_contable_codigo,
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
    """Descarga el kardex COMPLETO (todos los períodos cargados) de CADA
    activo de la empresa, una hoja por activo — mismo formato que
    "Kardex" de la ficha de un activo (el usuario pidió que la descarga
    de "Tabla de depreciación" muestre lo mismo que el kardex pero con
    todos los activos juntos, 11-09-2026), no la foto de un solo mes."""
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    if not empresa:
        flash("Esa empresa ya no existe.", "error")
        return redirect(url_for("depreciacion.empresas"))

    activos = depreciacion_activos_repo.listar_por_empresa(empresa_id)
    activos_con_kardex = [
        (activo, fusionar_kardex_por_anio(calcular_kardex(activo, depreciacion_periodos_repo.listar_por_activo(activo["id"]))))
        for activo in activos
    ]

    contenido = build_empresa_kardex_workbook(empresa["nombre"], activos_con_kardex)
    nombre_archivo = f"depreciacion_{empresa['nombre'].strip().replace(' ', '_')}.xlsx"
    return send_file(
        io.BytesIO(contenido), as_attachment=True, download_name=nombre_archivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Ficha de un activo: kardex de depreciación por período
# ---------------------------------------------------------------------------

@depreciacion_bp.route("/empresas/<empresa_id>/activos/<activo_id>", methods=["GET"])
@pagina_required("depreciacion.empresas")
def activo_detalle(empresa_id, activo_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    activo = depreciacion_activos_repo.obtener_activo(activo_id)
    if not empresa or not activo or activo["empresa_id"] != empresa_id:
        flash("Ese activo ya no existe.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))

    periodos = depreciacion_periodos_repo.listar_por_activo(activo_id)
    kardex = calcular_kardex(activo, periodos)
    fechas_asentadas = depreciacion_asientos_repo.fechas_ya_generadas(activo_id)
    grupo_actual_descripcion = CUENTAS_POR_CODIGO.get(activo.get("grupo_contable_codigo") or "", {}).get("descripcion", "")

    return render_template(
        "depreciacion/activo_detalle.html", empresa=empresa, activo=activo, filas=list(zip(periodos, kardex)),
        cuentas=PLAN_CUENTAS, fechas_asentadas=fechas_asentadas, grupo_actual_descripcion=grupo_actual_descripcion,
    )


@depreciacion_bp.route("/empresas/<empresa_id>/activos/<activo_id>/grupo/guardar", methods=["POST"])
@pagina_required("depreciacion.empresas")
def activo_grupo_guardar(empresa_id, activo_id):
    activo = depreciacion_activos_repo.obtener_activo(activo_id)
    if not activo or activo["empresa_id"] != empresa_id:
        flash("Ese activo ya no existe.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))

    codigo = request.form.get("grupo_contable_codigo") or None
    if codigo and codigo not in CUENTAS_POR_CODIGO:
        flash("Ese grupo contable no existe en el plan de cuentas — vuelve a buscarlo.", "error")
        return redirect(url_for("depreciacion.activo_detalle", empresa_id=empresa_id, activo_id=activo_id))

    depreciacion_activos_repo.actualizar_grupo_contable(activo_id, codigo)
    flash("Grupo contable guardado.", "success")
    return redirect(url_for("depreciacion.activo_detalle", empresa_id=empresa_id, activo_id=activo_id))


@depreciacion_bp.route("/empresas/<empresa_id>/activos/<activo_id>/periodos/guardar", methods=["POST"])
@pagina_required("depreciacion.empresas")
def periodos_guardar(empresa_id, activo_id):
    activo = depreciacion_activos_repo.obtener_activo(activo_id)
    if not activo or activo["empresa_id"] != empresa_id:
        flash("Ese activo ya no existe.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))

    fechas = request.form.getlist("p_fecha")
    meses = request.form.getlist("p_meses")
    factores = request.form.getlist("p_factor_ccmm")

    filas = []
    errores = []
    for i in range(len(fechas)):
        fecha = (fechas[i] or "").strip()
        meses_raw = (meses[i] if i < len(meses) else "").strip()
        factor_raw = (factores[i] if i < len(factores) else "1").strip() or "1"
        if not fecha and not meses_raw:
            continue  # fila vacía (ej. se agregó y se dejó sin llenar) -> se ignora, no error
        if not fecha or not meses_raw:
            errores.append(f"Fila {i + 1}: falta la fecha o los meses utilizados.")
            continue
        try:
            meses_int = int(meses_raw)
            if meses_int <= 0:
                raise ValueError
        except ValueError:
            errores.append(f"Fila {i + 1}: los meses utilizados deben ser un número entero mayor a 0.")
            continue
        try:
            factor_float = float(factor_raw.replace(",", "."))
            if factor_float <= 0:
                raise ValueError
        except ValueError:
            errores.append(f"Fila {i + 1}: el Factor CCMM debe ser un número mayor a 0 (1 = sin corrección).")
            continue
        filas.append({"fecha": fecha, "meses_utilizados": meses_int, "factor_ccmm": factor_float})

    if errores:
        for e in errores:
            flash(e, "error")
        return redirect(url_for("depreciacion.activo_detalle", empresa_id=empresa_id, activo_id=activo_id))

    filas.sort(key=lambda f: f["fecha"])
    depreciacion_periodos_repo.guardar_todos(activo_id, filas)
    flash("Kardex guardado.", "success")
    return redirect(url_for("depreciacion.activo_detalle", empresa_id=empresa_id, activo_id=activo_id))


@depreciacion_bp.route("/empresas/<empresa_id>/activos/<activo_id>/descargar", methods=["GET"])
@pagina_required("depreciacion.empresas")
def kardex_descargar(empresa_id, activo_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    activo = depreciacion_activos_repo.obtener_activo(activo_id)
    if not empresa or not activo or activo["empresa_id"] != empresa_id:
        flash("Ese activo ya no existe.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))

    periodos = depreciacion_periodos_repo.listar_por_activo(activo_id)
    kardex = fusionar_kardex_por_anio(calcular_kardex(activo, periodos))

    contenido = build_kardex_workbook(empresa["nombre"], activo, kardex)
    nombre_archivo = f"kardex_{activo['nombre_activo'].strip().replace(' ', '_')}.xlsx"
    return send_file(
        io.BytesIO(contenido), as_attachment=True, download_name=nombre_archivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Generar asiento contable (comprobante) — consolidado por grupo contable,
# para un mes/año elegido
# ---------------------------------------------------------------------------

def _parsear_mes_anio(valor):
    """'YYYY-MM' -> (year, month); el mes actual si falta o viene mal
    formado."""
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


def _extender_periodos(activo, periodos, anio, mes, persistir, asentadas):
    """Si el kardex de `activo` (ya filtrado a los períodos <= anio-mes)
    no llega todavía hasta el cierre de anio-mes, agrega los meses que
    faltan (factor CCMM 1, editable después a mano):

      - Si la última fila cae en el MISMO año calendario que `anio` y
        todavía no tiene un asiento generado, se le SUMAN los meses que
        faltan a esa misma fila (y su fecha avanza hasta el cierre de
        anio-mes) en vez de crear una fila aparte — así el kardex agrupa
        naturalmente un año por fila, en vez de ir quedando con muchas
        filas de 1 mes cada vez que se gestiona un mes nuevo.
      - Si la última fila YA tiene un asiento generado (fusionarla
        correría el riesgo de contar de nuevo lo que ya se asentó, porque
        la "memoria" de lo asentado se guarda por fecha — ver
        `app/data/depreciacion_asientos_repo.py` — y cambiarle la fecha a
        una fila ya asentada la dejaría fuera de esa memoria) o cae en un
        año distinto, se agrega una fila nueva en vez de tocar la
        anterior.

    Con `persistir=False` los cambios se arman solo en memoria (para la
    vista previa de "Generar asiento", que es un GET y no debería
    escribir nada); con `persistir=True` (al generar de verdad) quedan
    guardados en Supabase."""
    fecha_ultima = parse_fecha(periodos[-1]["fecha"]) if periodos else None
    fecha_adq = parse_fecha(activo["fecha_adquisicion"])
    faltan = meses_faltantes(fecha_ultima, fecha_adq, anio, mes)
    if faltan <= 0:
        return periodos

    fecha_nueva = ultimo_dia_mes(anio, mes).isoformat()
    ultima_fila = periodos[-1] if periodos else None
    puede_fusionar = ultima_fila is not None and fecha_ultima.year == anio and ultima_fila["fecha"] not in asentadas

    if puede_fusionar:
        meses_nuevos = int(ultima_fila["meses_utilizados"]) + faltan
        if persistir:
            depreciacion_periodos_repo.actualizar_periodo(ultima_fila["id"], fecha_nueva, meses_nuevos)
        fila_actualizada = {**ultima_fila, "fecha": fecha_nueva, "meses_utilizados": meses_nuevos}
        return periodos[:-1] + [fila_actualizada]

    if persistir:
        nueva = depreciacion_periodos_repo.agregar_periodo(activo["id"], fecha_nueva, faltan, 1.0)
    else:
        nueva = {"fecha": fecha_nueva, "meses_utilizados": faltan, "factor_ccmm": 1.0}
    return periodos + [nueva]


def _ordinal(fecha) -> int:
    return fecha.year * 12 + fecha.month


def _pendientes_por_activo(empresa_id, anio, mes, persistir=False):
    """[(activo, [filas de calcular_kardex sin asiento todavía, hasta
    anio-mes inclusive])] para cada activo de la empresa."""
    objetivo_ordinal = anio * 12 + mes
    resultado = []
    for activo in depreciacion_activos_repo.listar_por_empresa(empresa_id):
        asentadas = depreciacion_asientos_repo.fechas_ya_generadas(activo["id"])
        periodos = depreciacion_periodos_repo.listar_por_activo(activo["id"])
        periodos = [p for p in periodos if _ordinal(parse_fecha(p["fecha"])) <= objetivo_ordinal]
        periodos = _extender_periodos(activo, periodos, anio, mes, persistir, asentadas)
        kardex = calcular_kardex(activo, periodos)
        pendientes = [k for k in kardex if k["fecha"] not in asentadas]
        resultado.append((activo, pendientes))
    return resultado


@depreciacion_bp.route("/empresas/<empresa_id>/asientos", methods=["GET"])
@pagina_required("depreciacion.empresas")
def asientos(empresa_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    if not empresa:
        flash("Esa empresa ya no existe.", "error")
        return redirect(url_for("depreciacion.empresas"))

    anio, mes = _parsear_mes_anio(request.args.get("periodo"))
    activos_con_pendientes = _pendientes_por_activo(empresa_id, anio, mes, persistir=False)
    grupos, activos_sin_grupo = comprobantes.agrupar_pendientes(activos_con_pendientes)
    grupos_contables = {g["codigo"]: g for g in depreciacion_grupos_contables_repo.listar_por_empresa(empresa_id)}

    filas = []
    for codigo, datos in grupos.items():
        try:
            comprobantes.validar_grupos({codigo: datos}, grupos_contables)
            error = None
        except comprobantes.GrupoFaltante as exc:
            error = str(exc)
        filas.append({
            "codigo": codigo, "descripcion": CUENTAS_POR_CODIGO.get(codigo, {}).get("descripcion", codigo),
            "datos": datos, "error": error,
        })

    return render_template(
        "depreciacion/asientos.html", empresa=empresa, filas=filas, activos_sin_grupo=activos_sin_grupo,
        periodo=f"{anio:04d}-{mes:02d}", periodo_label=f"{MESES_LABEL[mes - 1]} {anio}",
        MESES_OPCIONES=MESES_OPCIONES, anios_disponibles=_anios_disponibles(),
    )


@depreciacion_bp.route("/empresas/<empresa_id>/asientos/generar", methods=["POST"])
@pagina_required("depreciacion.empresas")
def asientos_generar(empresa_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    if not empresa:
        flash("Esa empresa ya no existe.", "error")
        return redirect(url_for("depreciacion.empresas"))

    anio, mes = _parsear_mes_anio(request.form.get("periodo"))
    periodo_label = f"{MESES_LABEL[mes - 1]} {anio}"

    activos_con_pendientes = _pendientes_por_activo(empresa_id, anio, mes, persistir=True)
    grupos, activos_sin_grupo = comprobantes.agrupar_pendientes(activos_con_pendientes)
    grupos_contables = {g["codigo"]: g for g in depreciacion_grupos_contables_repo.listar_por_empresa(empresa_id)}

    if activos_sin_grupo:
        flash("No se incluyeron (sin grupo contable asignado): " + ", ".join(activos_sin_grupo), "error")

    grupos_ok = {}
    for codigo, datos in grupos.items():
        try:
            comprobantes.validar_grupos({codigo: datos}, grupos_contables)
            grupos_ok[codigo] = datos
        except comprobantes.GrupoFaltante as exc:
            flash(str(exc), "error")

    if not grupos_ok:
        flash("No había ningún período pendiente de asentar hasta ese mes.", "info" if not activos_sin_grupo else "error")
        return redirect(url_for("depreciacion.asientos", empresa_id=empresa_id, periodo=f"{anio:04d}-{mes:02d}"))

    fecha_comprobante = ultimo_dia_mes(anio, mes)
    filas_comprobante = comprobantes.construir_filas(grupos_ok, grupos_contables, fecha_comprobante, periodo_label)

    nuevos_asientos = []
    for activo, pendientes in activos_con_pendientes:
        codigo = activo.get("grupo_contable_codigo")
        if codigo not in grupos_ok:
            continue
        for p in pendientes:
            nuevos_asientos.append({
                "activo_id": activo["id"], "fecha": p["fecha"],
                "monto_ejercicio": p["depreciacion_ejercicio"], "monto_correccion": p["correccion_monetaria"],
            })
    depreciacion_asientos_repo.crear_muchos(nuevos_asientos)

    contenido = build_comprobantes_workbook(filas_comprobante)
    nombre_archivo = f"asiento_depreciacion_{empresa['nombre'].strip().replace(' ', '_')}_{anio:04d}-{mes:02d}.xls"
    return send_file(
        io.BytesIO(contenido), as_attachment=True, download_name=nombre_archivo,
        mimetype="application/vnd.ms-excel",
    )


@depreciacion_bp.route("/empresas/<empresa_id>/activos/<activo_id>/asientos/<fecha>/deshacer", methods=["POST"])
@pagina_required("depreciacion.empresas")
def asiento_deshacer(empresa_id, activo_id, fecha):
    depreciacion_asientos_repo.eliminar_por_activo_y_fecha(activo_id, fecha)
    flash("Asiento deshecho — ese período vuelve a quedar pendiente.", "success")
    return redirect(url_for("depreciacion.activo_detalle", empresa_id=empresa_id, activo_id=activo_id))


# ---------------------------------------------------------------------------
# Grupos Contables (cuentas de depreciación por "cuenta del activo fijo",
# propios de cada empresa — dos empresas pueden compartir un mismo código
# de grupo y necesitar cuentas de depreciación distintas)
# ---------------------------------------------------------------------------

@depreciacion_bp.route("/empresas/<empresa_id>/grupos-contables", methods=["GET"])
@pagina_required("depreciacion.empresas")
def grupos_contables(empresa_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    if not empresa:
        flash("Esa empresa ya no existe.", "error")
        return redirect(url_for("depreciacion.empresas"))

    grupos = depreciacion_grupos_contables_repo.listar_por_empresa(empresa_id)
    for g in grupos:
        g["descripcion"] = CUENTAS_POR_CODIGO.get(g["codigo"], {}).get("descripcion", "")
    return render_template("depreciacion/grupos_contables.html", empresa=empresa, grupos=grupos, cuentas=PLAN_CUENTAS)


@depreciacion_bp.route("/empresas/<empresa_id>/grupos-contables/guardar", methods=["POST"])
@pagina_required("depreciacion.empresas")
def grupos_contables_guardar(empresa_id):
    codigo = request.form.get("grupo_codigo") or None
    cuenta_gasto = request.form.get("cuenta_gasto_codigo") or None
    cuenta_acumulada = request.form.get("cuenta_acumulada_codigo") or None
    cuenta_correccion = request.form.get("cuenta_correccion_codigo") or None

    errores = []
    if not codigo or codigo not in CUENTAS_POR_CODIGO:
        errores.append("Elige el grupo (la cuenta del activo fijo) desde el buscador.")
    if not cuenta_gasto or cuenta_gasto not in CUENTAS_POR_CODIGO:
        errores.append("Elige la cuenta de Gasto por Depreciación.")
    if not cuenta_acumulada or cuenta_acumulada not in CUENTAS_POR_CODIGO:
        errores.append("Elige la cuenta de Depreciación Acumulada.")
    if cuenta_correccion and cuenta_correccion not in CUENTAS_POR_CODIGO:
        errores.append("La cuenta de Corrección Monetaria elegida no existe en el plan de cuentas.")

    if errores:
        for e in errores:
            flash(e, "error")
        return redirect(url_for("depreciacion.grupos_contables", empresa_id=empresa_id))

    depreciacion_grupos_contables_repo.guardar(empresa_id, codigo, cuenta_gasto, cuenta_acumulada, cuenta_correccion)
    flash(f"Grupo contable '{codigo}' guardado.", "success")
    return redirect(url_for("depreciacion.grupos_contables", empresa_id=empresa_id))


@depreciacion_bp.route("/empresas/<empresa_id>/grupos-contables/<codigo>/eliminar", methods=["POST"])
@pagina_required("depreciacion.empresas")
def grupos_contables_eliminar(empresa_id, codigo):
    depreciacion_grupos_contables_repo.eliminar(empresa_id, codigo)
    flash("Grupo contable eliminado.", "success")
    return redirect(url_for("depreciacion.grupos_contables", empresa_id=empresa_id))


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
