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
  - "Dar de baja" un activo (pérdida total o venta, ver `app/
    depreciacion/comprobantes_baja.py`): elige un mes/año (mismo
    mecanismo de extender el kardex que "Generar asiento"), calcula el
    valor libro a esa fecha y arma un comprobante aparte (no se
    consolida con nada) que limpia la cuenta de Activo Fijo (el código
    del Grupo Contable del activo mismo) y la Depreciación Acumulada del
    grupo, reconociendo la utilidad o pérdida contra las 3 cuentas que se
    configuran una vez por empresa (Caja/Cliente, Pérdida en Baja,
    Utilidad en Venta — ver `app/data/depreciacion_config_baja_repo.py`,
    en la misma pantalla de Grupos Contables).

El cálculo en sí (`app/depreciacion/calculo.py`) no toca Supabase — así se
puede testear con datos en memoria.
"""

import io
from datetime import date, datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for
from openpyxl import Workbook, load_workbook

from app.auth.decorators import pagina_required
from app.conciliacion.plan_cuentas import CUENTAS_POR_CODIGO, PLAN_CUENTAS
from app.data import (
    depreciacion_activos_repo, depreciacion_asientos_repo, depreciacion_bajas_repo, depreciacion_categorias_repo,
    depreciacion_config_baja_repo, depreciacion_empresas_repo, depreciacion_grupos_contables_repo,
    depreciacion_periodos_repo,
)
from app.depreciacion import comprobantes, comprobantes_baja
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


# ---------------------------------------------------------------------------
# Carga masiva de activos, POR EMPRESA (22-09-2026, pedido por el usuario: una
# opción de carga masiva junto a "Agregar activo") — a diferencia de la carga
# masiva de "años anteriores" más abajo (que reemplaza el kardex de activos
# YA creados, buscándolos por nombre en CUALQUIER empresa), esta SUMA activos
# nuevos a la empresa cuya ficha se está viendo — no hace falta columna
# "Empresa" en el Excel porque ya se sabe de cuál se trata por la URL.
# ---------------------------------------------------------------------------

DEPRECIACION_ACTIVOS_ALLOWED_EXT = (".xlsx", ".xlsm")
DEPRECIACION_ACTIVOS_ENCABEZADOS = [
    "Nombre Activo", "Categoría", "Fecha Adquisición", "Valor Adquisición", "Vida Útil (Años)", "Grupo Contable",
]

# Mismo criterio que `_mapear_columnas_depreciacion` (más abajo): las columnas
# se ubican por NOMBRE, no por posición.
DEPRECIACION_ACTIVOS_ROLES = {
    "nombre": ["NOMBRE ACTIVO", "NOMBRE DEL ACTIVO", "ACTIVO"],
    "categoria": ["CATEGORÍA", "CATEGORIA"],
    "fecha": ["FECHA ADQUISICIÓN", "FECHA ADQUISICION", "FECHA"],
    "valor": ["VALOR ADQUISICIÓN", "VALOR ADQUISICION", "VALOR"],
    "vida_util": ["VIDA ÚTIL (AÑOS)", "VIDA UTIL (AÑOS)", "VIDA ÚTIL", "VIDA UTIL"],
    "grupo_contable": ["GRUPO CONTABLE", "GRUPO_CONTABLE"],
}
DEPRECIACION_ACTIVOS_ROLES_OBLIGATORIOS = ("nombre", "fecha", "valor")
DEPRECIACION_ACTIVOS_ETIQUETAS = {
    "nombre": "Nombre Activo", "fecha": "Fecha Adquisición", "valor": "Valor Adquisición",
}


def _mapear_columnas_depreciacion_activos(fila_encabezado):
    indices = {}
    for idx, celda in enumerate(fila_encabezado):
        token = str(celda).strip().upper() if celda is not None else ""
        if not token:
            continue
        for rol, sinonimos in DEPRECIACION_ACTIVOS_ROLES.items():
            if rol not in indices and token in sinonimos:
                indices[rol] = idx
    faltan = [rol for rol in DEPRECIACION_ACTIVOS_ROLES_OBLIGATORIOS if rol not in indices]
    return indices, faltan


def _valor_adquisicion_de_celda(valor):
    """Acepta tanto un número real de Excel (celda con formato numérico)
    como texto con separador de miles chileno ("1.500.000")."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        return float(texto.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _leer_excel_depreciacion_activos(file_storage, empresa_id):
    """Devuelve (filas, errores) — `filas` son dicts listos para
    `depreciacion_activos_repo.crear_activos_masivo` (sin `empresa_id`
    todavía, se agrega en la ruta). Todo o nada: si `errores` no está
    vacía, `filas` es `None`, igual que `_leer_excel_depreciacion_periodos`."""
    try:
        wb = load_workbook(io.BytesIO(file_storage.read()), data_only=True)
    except Exception as exc:  # noqa: BLE001
        return None, [f"No se pudo abrir el archivo: {exc}"]
    ws = wb.active

    filas_todas = list(ws.iter_rows(values_only=True))
    if not filas_todas:
        return None, ["El archivo está vacío."]

    indices, faltan = _mapear_columnas_depreciacion_activos(filas_todas[0])
    if faltan:
        etiquetas = ", ".join(DEPRECIACION_ACTIVOS_ETIQUETAS[rol] for rol in faltan)
        return None, [
            f"Al archivo le faltan columnas obligatorias: {etiquetas}. Usa esos mismos nombres de columna."
        ]

    categorias = depreciacion_categorias_repo.listar_categorias()
    categorias_por_label = {f"{c['seccion']}: {c['descripcion']}".strip().lower(): c for c in categorias}
    grupos_por_codigo = {
        (g.get("codigo") or "").strip().lower(): g
        for g in depreciacion_grupos_contables_repo.listar_por_empresa(empresa_id)
    }

    def _valor(fila, rol):
        idx = indices.get(rol)
        return fila[idx] if idx is not None and idx < len(fila) else None

    filas_listas = []
    errores = []
    for numero_fila, fila_excel in enumerate(filas_todas[1:], start=2):
        if all(v is None or str(v).strip() == "" for v in fila_excel):
            continue  # fila vacía — se ignora sin avisar

        nombre_activo = str(_valor(fila_excel, "nombre") or "").strip()
        if not nombre_activo:
            errores.append(f"Fila {numero_fila}: falta el nombre del activo.")
            continue

        fecha_iso = _fecha_celda_a_iso(_valor(fila_excel, "fecha"))
        if not fecha_iso:
            errores.append(f"Fila {numero_fila}: 'Fecha Adquisición' no es una fecha válida.")
            continue

        valor_adquisicion = _valor_adquisicion_de_celda(_valor(fila_excel, "valor"))
        if valor_adquisicion is None or valor_adquisicion <= 0:
            errores.append(f"Fila {numero_fila}: 'Valor Adquisición' debe ser un número mayor a 0.")
            continue

        categoria_id = None
        categoria_vida_util = None
        categoria_texto = str(_valor(fila_excel, "categoria") or "").strip()
        if categoria_texto:
            categoria = categorias_por_label.get(categoria_texto.lower())
            if not categoria:
                errores.append(
                    f"Fila {numero_fila}: la categoría '{categoria_texto}' no existe — usa el mismo texto "
                    "que aparece en el desplegable de 'Agregar activo' (o la hoja 'Categorías' de la plantilla)."
                )
                continue
            # `.get("id")`, no `["id"]`: si `depreciacion_categorias` está
            # vacía en Supabase, `listar_categorias()` cae de vuelta a
            # `DEFAULTS`, que no trae "id" (igual que en la plantilla del
            # formulario "Agregar activo", `c.id` — ahí Jinja lo resuelve
            # silencioso a "", acá hay que hacerlo a mano para no reventar).
            categoria_id = categoria.get("id")
            categoria_vida_util = categoria.get("vida_util_anios")

        vida_util_celda = _valor(fila_excel, "vida_util")
        if vida_util_celda is None or str(vida_util_celda).strip() == "":
            vida_util_anios = categoria_vida_util
        else:
            try:
                vida_util_anios = int(vida_util_celda)
            except (TypeError, ValueError):
                errores.append(f"Fila {numero_fila}: 'Vida Útil (Años)' no es un número entero válido.")
                continue
        if not vida_util_anios or vida_util_anios <= 0:
            errores.append(
                f"Fila {numero_fila}: falta la vida útil — elige una 'Categoría' con vida útil fija o "
                "complétala a mano en 'Vida Útil (Años)'."
            )
            continue

        grupo_contable_codigo = None
        grupo_texto = str(_valor(fila_excel, "grupo_contable") or "").strip()
        if grupo_texto:
            grupo_codigo_solo = grupo_texto.split(" ", 1)[0]  # por si viene "1204-01 VEHICULOS"
            grupo = grupos_por_codigo.get(grupo_codigo_solo.lower())
            if not grupo:
                errores.append(
                    f"Fila {numero_fila}: el grupo contable '{grupo_texto}' no está configurado para esta "
                    "empresa — configúralo primero en Grupos Contables."
                )
                continue
            grupo_contable_codigo = grupo["codigo"]

        filas_listas.append({
            "nombre_activo": nombre_activo,
            "categoria_id": categoria_id,
            "fecha_adquisicion": fecha_iso,
            "valor_adquisicion": valor_adquisicion,
            "vida_util_anios": vida_util_anios,
            "grupo_contable_codigo": grupo_contable_codigo,
        })

    if errores:
        return None, errores
    return filas_listas, []


@depreciacion_bp.route("/empresas/<empresa_id>/activos/plantilla", methods=["GET"])
@pagina_required("depreciacion.empresas")
def activos_plantilla(empresa_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    if not empresa:
        flash("Esa empresa ya no existe.", "error")
        return redirect(url_for("depreciacion.empresas"))

    wb = Workbook()
    ws = wb.active
    ws.title = "Activos"
    ws.append(DEPRECIACION_ACTIVOS_ENCABEZADOS)

    ws_cat = wb.create_sheet("Categorías (referencia)")
    ws_cat.append(["Texto a copiar en 'Categoría'", "Vida útil (años)"])
    for c in depreciacion_categorias_repo.listar_categorias():
        ws_cat.append([f"{c['seccion']}: {c['descripcion']}", c.get("vida_util_anios")])

    ws_grp = wb.create_sheet("Grupos contables (referencia)")
    ws_grp.append(["Código a copiar en 'Grupo Contable'", "Cuenta de gasto", "Cuenta acumulada"])
    for g in depreciacion_grupos_contables_repo.listar_por_empresa(empresa_id):
        ws_grp.append([g.get("codigo"), g.get("cuenta_gasto_codigo"), g.get("cuenta_acumulada_codigo")])

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer, as_attachment=True,
        download_name=f"activos_{(empresa['nombre'] or 'empresa').strip().replace(' ', '_')}_plantilla.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@depreciacion_bp.route("/empresas/<empresa_id>/activos/cargar", methods=["POST"])
@pagina_required("depreciacion.empresas")
def activos_cargar(empresa_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    if not empresa:
        flash("Esa empresa ya no existe.", "error")
        return redirect(url_for("depreciacion.empresas"))

    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Sube un archivo Excel para continuar.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))
    if not archivo.filename.lower().endswith(DEPRECIACION_ACTIVOS_ALLOWED_EXT):
        flash("Formato no permitido. Sube un archivo .xlsx o .xlsm.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))

    filas, errores = _leer_excel_depreciacion_activos(archivo, empresa_id)
    if errores:
        for mensaje in errores:
            flash(mensaje, "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))
    if not filas:
        flash("El archivo no trae ninguna fila con datos.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))

    for f in filas:
        f["empresa_id"] = empresa_id
    try:
        creados = depreciacion_activos_repo.crear_activos_masivo(filas)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("No se pudo guardar activos (carga masiva): %s", exc)
        flash("No se pudo guardar: hubo un problema de conexión con la base de datos.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))

    flash(f"{len(creados)} activo(s) agregado(s) desde el Excel.", "success")
    return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))


@depreciacion_bp.route("/empresas/<empresa_id>/activos/<activo_id>/dar_de_baja", methods=["GET"])
@pagina_required("depreciacion.empresas")
def activo_baja_form(empresa_id, activo_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    activo = depreciacion_activos_repo.obtener_activo(activo_id)
    if not empresa or not activo or activo["empresa_id"] != empresa_id:
        flash("Ese activo ya no existe.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))
    if not activo.get("activo", True):
        flash("Ese activo ya está dado de baja.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))

    hoy = date.today()
    return render_template(
        "depreciacion/activo_baja.html", empresa=empresa, activo=activo,
        MESES_OPCIONES=MESES_OPCIONES, anios_disponibles=_anios_disponibles(),
        periodo=f"{hoy.year:04d}-{hoy.month:02d}",
    )


@depreciacion_bp.route("/empresas/<empresa_id>/activos/<activo_id>/dar_de_baja/calcular", methods=["POST"])
@pagina_required("depreciacion.empresas")
def activo_baja_calcular(empresa_id, activo_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    activo = depreciacion_activos_repo.obtener_activo(activo_id)
    if not empresa or not activo or activo["empresa_id"] != empresa_id:
        flash("Ese activo ya no existe.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))

    anio, mes = _parsear_mes_anio(request.form.get("periodo"))
    tipo_baja = request.form.get("tipo_baja") or ""
    modalidad_venta = request.form.get("modalidad_venta") or None
    monto_venta_raw = (request.form.get("monto_venta") or "0").strip().replace(".", "").replace(",", ".")

    errores = []
    if tipo_baja not in ("perdida_total", "venta"):
        errores.append("Elige el tipo de baja: pérdida total o venta.")
    if tipo_baja == "venta" and modalidad_venta not in ("factura", "contrato"):
        errores.append("Elige la modalidad de venta: con factura o por contrato de compraventa.")
    monto_venta = 0.0
    if tipo_baja == "venta":
        try:
            monto_venta = float(monto_venta_raw or 0)
            if monto_venta <= 0:
                errores.append("Ingresa el monto de la venta.")
        except ValueError:
            errores.append("El monto de venta no es un número válido.")

    if errores:
        for e in errores:
            flash(e, "error")
        return redirect(url_for("depreciacion.activo_baja_form", empresa_id=empresa_id, activo_id=activo_id))

    fila = _valor_libro_en(activo, anio, mes, persistir=False)
    valor_actualizado = fila["valor_actualizado"] if fila else round(float(activo["valor_adquisicion"]))
    deprec_acumulada = fila["deprec_acum_cierre"] if fila else 0
    valor_libro = fila["valor_libro"] if fila else valor_actualizado
    resultado = comprobantes_baja.calcular_resultado(tipo_baja, monto_venta, valor_libro)

    grupo_contable = None
    if activo.get("grupo_contable_codigo"):
        grupo_contable = depreciacion_grupos_contables_repo.obtener(empresa_id, activo["grupo_contable_codigo"])
    config_baja = depreciacion_config_baja_repo.obtener(empresa_id)

    error_cuentas = None
    try:
        comprobantes_baja.validar_cuentas(activo, grupo_contable, config_baja, tipo_baja, modalidad_venta, resultado)
    except comprobantes_baja.CuentaBajaFaltante as exc:
        error_cuentas = str(exc)

    return render_template(
        "depreciacion/activo_baja_confirmar.html", empresa=empresa, activo=activo,
        periodo=f"{anio:04d}-{mes:02d}", periodo_label=f"{MESES_LABEL[mes - 1]} {anio}",
        tipo_baja=tipo_baja, modalidad_venta=modalidad_venta, monto_venta=monto_venta,
        valor_actualizado=valor_actualizado, deprec_acumulada=deprec_acumulada,
        valor_libro=valor_libro, resultado=resultado, error_cuentas=error_cuentas,
    )


@depreciacion_bp.route("/empresas/<empresa_id>/activos/<activo_id>/dar_de_baja/confirmar", methods=["POST"])
@pagina_required("depreciacion.empresas")
def activo_baja_confirmar(empresa_id, activo_id):
    empresa = depreciacion_empresas_repo.obtener_empresa(empresa_id)
    activo = depreciacion_activos_repo.obtener_activo(activo_id)
    if not empresa or not activo or activo["empresa_id"] != empresa_id:
        flash("Ese activo ya no existe.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))
    if not activo.get("activo", True):
        flash("Ese activo ya está dado de baja.", "error")
        return redirect(url_for("depreciacion.empresa_detalle", empresa_id=empresa_id))

    anio, mes = _parsear_mes_anio(request.form.get("periodo"))
    tipo_baja = request.form.get("tipo_baja") or ""
    modalidad_venta = request.form.get("modalidad_venta") or None
    try:
        monto_venta = float(request.form.get("monto_venta") or 0)
    except ValueError:
        monto_venta = 0.0

    fila = _valor_libro_en(activo, anio, mes, persistir=True)
    valor_actualizado = fila["valor_actualizado"] if fila else round(float(activo["valor_adquisicion"]))
    deprec_acumulada = fila["deprec_acum_cierre"] if fila else 0
    valor_libro = fila["valor_libro"] if fila else valor_actualizado
    resultado = comprobantes_baja.calcular_resultado(tipo_baja, monto_venta, valor_libro)

    grupo_contable = depreciacion_grupos_contables_repo.obtener(empresa_id, activo.get("grupo_contable_codigo") or "")
    config_baja = depreciacion_config_baja_repo.obtener(empresa_id)

    try:
        comprobantes_baja.validar_cuentas(activo, grupo_contable, config_baja, tipo_baja, modalidad_venta, resultado)
    except comprobantes_baja.CuentaBajaFaltante as exc:
        flash(f"No se pudo generar el asiento de baja: {exc}", "error")
        return redirect(url_for("depreciacion.activo_baja_form", empresa_id=empresa_id, activo_id=activo_id))

    fecha_baja = ultimo_dia_mes(anio, mes)
    fecha_dt = datetime.combine(fecha_baja, datetime.min.time())
    filas_comprobante = comprobantes_baja.construir_filas(
        activo, grupo_contable, config_baja, tipo_baja, modalidad_venta,
        monto_venta, valor_actualizado, deprec_acumulada, resultado, fecha_dt,
    )

    depreciacion_bajas_repo.crear(
        activo_id, fecha_baja.isoformat(), tipo_baja, modalidad_venta,
        monto_venta, valor_actualizado, deprec_acumulada, valor_libro, resultado,
    )
    depreciacion_activos_repo.dar_de_baja(activo_id)

    contenido = build_comprobantes_workbook(filas_comprobante)
    nombre_archivo = f"baja_{activo['nombre_activo'].strip().replace(' ', '_')}.xls"
    return send_file(
        io.BytesIO(contenido), as_attachment=True, download_name=nombre_archivo,
        mimetype="application/vnd.ms-excel",
    )


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
    anio-mes inclusive])] para cada activo ACTIVO de la empresa — un
    activo ya dado de baja (ver `activo_baja_confirmar`) no vuelve a
    depreciar hacia adelante, así que no entra a "Generar asiento"."""
    objetivo_ordinal = anio * 12 + mes
    resultado = []
    for activo in depreciacion_activos_repo.listar_por_empresa(empresa_id):
        if not activo.get("activo", True):
            continue
        asentadas = depreciacion_asientos_repo.fechas_ya_generadas(activo["id"])
        periodos = depreciacion_periodos_repo.listar_por_activo(activo["id"])
        periodos = [p for p in periodos if _ordinal(parse_fecha(p["fecha"])) <= objetivo_ordinal]
        periodos = _extender_periodos(activo, periodos, anio, mes, persistir, asentadas)
        kardex = calcular_kardex(activo, periodos)
        pendientes = [k for k in kardex if k["fecha"] not in asentadas]
        resultado.append((activo, pendientes))
    return resultado


def _valor_libro_en(activo, anio, mes, persistir):
    """Extiende el kardex de `activo` (mismo mecanismo que "Generar
    asiento" — ver `_extender_periodos`) hasta el cierre de anio-mes y
    devuelve la última fila de `calcular_kardex` a esa fecha (con
    valor_actualizado/deprec_acum_cierre/valor_libro) — lo usa "Dar de
    baja" para saber cuánto vale el activo en libros al momento de
    venderlo o perderlo. `None` si el activo no tiene ninguna fila
    (nunca se cargó ningún período ni se pudo extender, ej. fecha de
    baja anterior a la de adquisición)."""
    objetivo_ordinal = anio * 12 + mes
    asentadas = depreciacion_asientos_repo.fechas_ya_generadas(activo["id"])
    periodos = depreciacion_periodos_repo.listar_por_activo(activo["id"])
    periodos = [p for p in periodos if _ordinal(parse_fecha(p["fecha"])) <= objetivo_ordinal]
    periodos = _extender_periodos(activo, periodos, anio, mes, persistir, asentadas)
    kardex = calcular_kardex(activo, periodos)
    return kardex[-1] if kardex else None


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

    # datetime, no date: el escritor del .xls (xlwt) solo escribe la celda
    # de fecha si es un datetime.datetime — un date "pelado" queda en
    # blanco silenciosamente (ver app/depreciacion/export_writer.py).
    fecha_comprobante = datetime.combine(ultimo_dia_mes(anio, mes), datetime.min.time())
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
    config_baja = depreciacion_config_baja_repo.obtener(empresa_id) or {}
    config_baja_desc = {
        campo: CUENTAS_POR_CODIGO.get(config_baja.get(campo) or "", {}).get("descripcion", "")
        for campo in (
            "cuenta_caja_cliente_codigo", "cuenta_perdida_codigo", "cuenta_utilidad_codigo",
            "cuenta_costo_venta_codigo",
        )
    }
    return render_template(
        "depreciacion/grupos_contables.html", empresa=empresa, grupos=grupos, cuentas=PLAN_CUENTAS,
        config_baja=config_baja, config_baja_desc=config_baja_desc,
    )


@depreciacion_bp.route("/empresas/<empresa_id>/config-baja/guardar", methods=["POST"])
@pagina_required("depreciacion.empresas")
def config_baja_guardar(empresa_id):
    cuenta_caja = request.form.get("cuenta_caja_cliente_codigo") or None
    cuenta_perdida = request.form.get("cuenta_perdida_codigo") or None
    cuenta_utilidad = request.form.get("cuenta_utilidad_codigo") or None
    cuenta_costo_venta = request.form.get("cuenta_costo_venta_codigo") or None

    for codigo in (cuenta_caja, cuenta_perdida, cuenta_utilidad, cuenta_costo_venta):
        if codigo and codigo not in CUENTAS_POR_CODIGO:
            flash("Una de las cuentas elegidas no existe en el plan de cuentas — vuelve a buscarla.", "error")
            return redirect(url_for("depreciacion.grupos_contables", empresa_id=empresa_id))

    depreciacion_config_baja_repo.guardar(empresa_id, cuenta_caja, cuenta_perdida, cuenta_utilidad, cuenta_costo_venta)
    flash("Cuentas para dar de baja guardadas.", "success")
    return redirect(url_for("depreciacion.grupos_contables", empresa_id=empresa_id))


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


# ---------------------------------------------------------------------------
# Carga masiva de "años anteriores" (21-09-2026, pedido por el usuario) —
# reemplaza, POR ACTIVO, todo su kardex de períodos (`depreciacion_periodos`)
# con lo que traiga el Excel, usando la misma `depreciacion_periodos_repo.
# guardar_todos` que ya respalda la edición manual del kardex en la ficha
# del activo (ver `periodos_guardar` más arriba). No crea empresas ni
# activos nuevos: cada fila debe calzar por nombre (sin distinguir
# mayúsculas) con una empresa y un activo YA creados en esta pestaña — si
# no calzan, se avisa fila por fila y no se guarda nada ("todo o nada").
# Vivió primero como página de Administrador (admin_required); se movió
# acá para que quede accesible directo desde la propia pestaña
# Depreciación, con el mismo acceso que "Empresas"/"Categorías SII"
# (pagina_required — admin por defecto, pero configurable en Pestañas).
# ---------------------------------------------------------------------------

DEPRECIACION_PERIODOS_ALLOWED_EXT = (".xlsx", ".xlsm")
DEPRECIACION_PERIODOS_ENCABEZADOS = ["Empresa", "Activo", "Fecha período", "Meses utilizados", "Factor CCMM"]

# Sinónimos de encabezado por rol: se ubica cada columna por NOMBRE, no por
# posición, para aceptar tanto la plantilla simple de 5 columnas como una
# exportación más ancha del kardex completo (Costo Total/Valor Actualizado/
# Vida Útil Antes/Depreciación del Ejercicio/Deprec. Acum. .../Valor Libro,
# tal cual se ve en la ficha del activo) — esas columnas de más se IGNORAN,
# `calcular_kardex` las vuelve a derivar solas a partir de fecha/meses/
# factor, así que no hace falta borrarlas antes de subir el archivo. Si
# "Factor CCMM" aparece dos veces (la ficha del activo la muestra dos
# veces, una por cada multiplicación en que interviene), se usa la primera
# — ambas traen siempre el mismo valor.
DEPRECIACION_PERIODOS_ROLES = {
    "empresa": ["EMPRESA"],
    "activo": ["ACTIVO"],
    "fecha": ["FECHA PERÍODO", "FECHA PERIODO", "FECHA"],
    "meses_utilizados": ["MESES UTILIZADOS", "MESES_UTILIZADOS"],
    "factor_ccmm": ["FACTOR CCMM", "FACTOR_CCMM"],
}
DEPRECIACION_PERIODOS_ROLES_OBLIGATORIOS = ("empresa", "activo", "fecha", "meses_utilizados")
DEPRECIACION_PERIODOS_ETIQUETAS = {
    "empresa": "Empresa", "activo": "Activo", "fecha": "Fecha (período)", "meses_utilizados": "Meses utilizados",
}


def _mapear_columnas_depreciacion(fila_encabezado):
    """Devuelve (indices, faltan): `indices` es {rol: posición_columna}
    para los roles que se encontraron en la fila de encabezado; `faltan`
    es la lista de roles obligatorios que no se encontraron."""
    indices = {}
    for idx, celda in enumerate(fila_encabezado):
        token = str(celda).strip().upper() if celda is not None else ""
        if not token:
            continue
        for rol, sinonimos in DEPRECIACION_PERIODOS_ROLES.items():
            if rol not in indices and token in sinonimos:
                indices[rol] = idx
    faltan = [rol for rol in DEPRECIACION_PERIODOS_ROLES_OBLIGATORIOS if rol not in indices]
    return indices, faltan


def _fecha_celda_a_iso(valor):
    """Convierte el valor de una celda de fecha (datetime/date que entrega
    openpyxl para una celda con formato de fecha, o texto en
    aaaa-mm-dd/dd-mm-aaaa/dd/mm/aaaa) a 'YYYY-MM-DD'. Devuelve None si no
    se pudo interpretar."""
    if valor is None or str(valor).strip() == "":
        return None
    if hasattr(valor, "strftime"):
        return valor.strftime("%Y-%m-%d")
    texto = str(valor).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _leer_excel_depreciacion_periodos(file_storage):
    """Devuelve (grupos, errores). `grupos` es
    `{activo_id: {"nombre": ..., "empresa": ..., "filas": [...]}}` — cada
    fila ya lista para `depreciacion_periodos_repo.guardar_todos`
    (`{"fecha": "YYYY-MM-DD", "meses_utilizados": int, "factor_ccmm": float}`).
    Si `errores` no está vacía, `grupos` es `None` (todo o nada, mismo
    criterio que `admin/routes.py:_leer_excel_planificacion`)."""
    try:
        wb = load_workbook(io.BytesIO(file_storage.read()), data_only=True)
    except Exception as exc:  # noqa: BLE001
        return None, [f"No se pudo abrir el archivo: {exc}"]
    ws = wb.active

    filas_todas = list(ws.iter_rows(values_only=True))
    if not filas_todas:
        return None, ["El archivo está vacío."]

    indices, faltan = _mapear_columnas_depreciacion(filas_todas[0])
    if faltan:
        etiquetas = ", ".join(DEPRECIACION_PERIODOS_ETIQUETAS[rol] for rol in faltan)
        return None, [
            f"Al archivo le faltan columnas obligatorias: {etiquetas}. Usa esos mismos nombres de "
            "columna (puedes agregar columnas de más, como Costo Total o Valor Libro — se ignoran)."
        ]

    empresas = depreciacion_empresas_repo.listar_empresas()
    empresas_por_nombre = {(e.get("nombre") or "").strip().lower(): e for e in empresas}
    activos_por_empresa = {
        e["id"]: {
            (a.get("nombre_activo") or "").strip().lower(): a
            for a in depreciacion_activos_repo.listar_por_empresa(e["id"])
        }
        for e in empresas
    }

    def _valor(fila, rol):
        idx = indices.get(rol)
        return fila[idx] if idx is not None and idx < len(fila) else None

    grupos = {}
    errores = []
    for numero_fila, fila_excel in enumerate(filas_todas[1:], start=2):
        if all(v is None or str(v).strip() == "" for v in fila_excel):
            continue  # fila vacía (ej. sobrante de la plantilla) — se ignora sin avisar

        empresa_nombre = str(_valor(fila_excel, "empresa")).strip() if _valor(fila_excel, "empresa") is not None else ""
        activo_nombre = str(_valor(fila_excel, "activo")).strip() if _valor(fila_excel, "activo") is not None else ""

        empresa = empresas_por_nombre.get(empresa_nombre.lower())
        if not empresa_nombre or not empresa:
            errores.append(
                f"Fila {numero_fila}: la empresa '{empresa_nombre}' no existe en Depreciación → Empresas."
            )
            continue

        activo = activos_por_empresa.get(empresa["id"], {}).get(activo_nombre.lower())
        if not activo_nombre or not activo:
            errores.append(
                f"Fila {numero_fila}: el activo '{activo_nombre}' no existe en la empresa "
                f"'{empresa['nombre']}' — créalo primero en su ficha."
            )
            continue

        fecha_iso = _fecha_celda_a_iso(_valor(fila_excel, "fecha"))
        if not fecha_iso:
            errores.append(f"Fila {numero_fila}: 'Fecha' no es una fecha válida.")
            continue

        try:
            meses_int = int(_valor(fila_excel, "meses_utilizados"))
            if meses_int <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errores.append(f"Fila {numero_fila}: 'Meses utilizados' debe ser un número entero mayor a 0.")
            continue

        factor_raw = _valor(fila_excel, "factor_ccmm")
        try:
            factor_float = float(str(factor_raw).replace(",", ".")) if factor_raw not in (None, "") else 1.0
            if factor_float <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errores.append(
                f"Fila {numero_fila}: 'Factor CCMM' debe ser un número mayor a 0 (déjalo vacío para 1)."
            )
            continue

        grupo = grupos.setdefault(
            activo["id"], {"nombre": activo["nombre_activo"], "empresa": empresa["nombre"], "filas": []},
        )
        grupo["filas"].append({"fecha": fecha_iso, "meses_utilizados": meses_int, "factor_ccmm": factor_float})

    if errores:
        return None, errores
    return grupos, []


@depreciacion_bp.route("/periodos", methods=["GET"])
@pagina_required("depreciacion.empresas")
def periodos_carga_masiva():
    return render_template("depreciacion/periodos_carga_masiva.html")


@depreciacion_bp.route("/periodos/plantilla", methods=["GET"])
@pagina_required("depreciacion.empresas")
def periodos_plantilla():
    wb = Workbook()
    ws = wb.active
    ws.title = "Depreciación años anteriores"
    ws.append(DEPRECIACION_PERIODOS_ENCABEZADOS)
    for empresa in depreciacion_empresas_repo.listar_empresas():
        for activo in depreciacion_activos_repo.listar_por_empresa(empresa["id"]):
            ws.append([empresa["nombre"], activo["nombre_activo"], None, None, None])

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer, as_attachment=True, download_name="depreciacion_anos_anteriores_plantilla.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@depreciacion_bp.route("/periodos/cargar", methods=["POST"])
@pagina_required("depreciacion.empresas")
def periodos_cargar():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Sube un archivo Excel para continuar.", "error")
        return redirect(url_for("depreciacion.periodos_carga_masiva"))
    if not archivo.filename.lower().endswith(DEPRECIACION_PERIODOS_ALLOWED_EXT):
        flash("Formato no permitido. Sube un archivo .xlsx o .xlsm.", "error")
        return redirect(url_for("depreciacion.periodos_carga_masiva"))

    grupos, errores = _leer_excel_depreciacion_periodos(archivo)
    if errores:
        for mensaje in errores:
            flash(mensaje, "error")
        return redirect(url_for("depreciacion.periodos_carga_masiva"))
    if not grupos:
        flash("El archivo no trae ninguna fila con datos.", "error")
        return redirect(url_for("depreciacion.periodos_carga_masiva"))

    total_periodos = 0
    try:
        for activo_id, grupo in grupos.items():
            filas = sorted(grupo["filas"], key=lambda f: f["fecha"])
            depreciacion_periodos_repo.guardar_todos(activo_id, filas)
            total_periodos += len(filas)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("No se pudo guardar depreciacion_periodos (carga masiva): %s", exc)
        flash("No se pudo guardar: hubo un problema de conexión con la base de datos.", "error")
        return redirect(url_for("depreciacion.periodos_carga_masiva"))

    flash(
        f"Depreciación cargada: {total_periodos} período(s) en {len(grupos)} activo(s). "
        "Esto reemplazó todo el kardex previo de cada uno de esos activos.",
        "success",
    )
    return redirect(url_for("depreciacion.periodos_carga_masiva"))
