"""
"Conciliación": pestaña nueva, por ahora solo para el rol admin, pedida
por el usuario para revisar/clasificar los movimientos de una cartola ya
convertida (el Excel que entrega "Subir Cartolas") contra el plan de
cuentas de la organización.

Primera ronda (09-09-2026): cargar el Excel convertido, mostrar cada
movimiento (fecha, detalle, cargo, abono) y permitir buscar y asignarle
una cuenta del plan de cuentas ("Concepto") por nombre — sin archivo de
salida todavía.

Segunda ronda (09-09-2026, esta): agrega el archivo de salida. El admin
elige además una **cuenta bancaria fija** (arriba de la tabla, misma para
todos los movimientos del archivo — es la cuenta del banco de la cartola
que se está conciliando) y puede editar el texto de "Detalle de
transacción" antes de descargar. Con eso, `/conciliacion/descargar` genera
un .xls de comprobantes (2 líneas por movimiento: la cuenta bancaria y la
cuenta "Concepto" de esa fila, una en el Debe y la otra en el Haber según
si el movimiento es cargo o abono) — ver `app/conciliacion/export_writer.
py` para el detalle exacto de esa regla, deducida de una muestra real de
la plantilla de salida que entregó el usuario.

Tercera ronda (14-09-2026, esta): conciliación asistida contra documentos
auxiliares — el admin puede cargar los mismos 3 Excel de "Empresas Caja"
(Clientes/Proveedores/Honorarios, ver `app/conciliacion/documentos.py`) y
cada movimiento se propone automáticamente contra un documento pendiente
si su monto Y el RUT que se alcance a extraer del texto del movimiento
calzan EXACTO con un documento todavía no usado (si el texto de la
cartola no trae un RUT reconocible, no hay propuesta automática — el
admin busca a mano, igual que hoy). Toda esta lógica de emparejamiento
vive en el cliente (`app/static/js/conciliacion.js`): el servidor solo
sube/parsea los 3 Excel (`/conciliacion/cargar-auxiliar/<modulo>`, mismo
patrón AJAX que `caja_empresas.js:cargarModulo`) y arma el bloque de Tipo
Auxiliar "A"/"H" de la línea Concepto cuando el movimiento llega resuelto
contra un documento (en vez de una cuenta suelta) — ver `_leer_filas_del_
formulario` y `construir_filas_comprobantes`.

El estado de la conciliación sigue viviendo solo en la página (recargar
la pierde, igual que las vistas previas de "Subir Cartolas" y "Generar
F29") — el archivo final se reconstruye en el servidor a partir de los
campos ocultos que la propia página va llenando con JavaScript conforme
el admin clasifica cada fila, no de una sesión guardada.

El archivo de entrada es específicamente el que arma
`app/parsers/output_writer.py` (hoja "Banco", columnas B:E = FECHA
DIA/MES, DETALLE DE TRANSACCION, MONTO CHEQUES O CARGOS, MONTO DEPOSITOS
O ABONOS) — no un PDF ni la cartola original del banco.
"""

import io
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from app.auth.decorators import pagina_required
from app.conciliacion.documentos import AUXILIAR_MODULOS
from app.conciliacion.export_writer import FilaSinFecha, comprobantes_a_xls_bytes
from app.conciliacion.plan_cuentas import CUENTAS_POR_CODIGO, PLAN_CUENTAS
from app.data import tipos_documento_repo
from openpyxl import load_workbook

conciliacion_bp = Blueprint("conciliacion", __name__, url_prefix="/conciliacion")

ALLOWED_EXT = (".xlsx", ".xlsm")

# Subconjunto de AUXILIAR_MODULOS que necesita el matching en el cliente
# (`app/static/js/conciliacion.js`) — cuenta fija a la que se concilia
# cada módulo y el tipo de bloque auxiliar ("A"/"H") que le corresponde en
# el archivo de salida. Se inyecta en la página como `window.CYG_AUX_
# MODULOS` (ver `conciliacion.html`).
AUX_MODULOS_JS = {
    modulo: {
        "cuenta_codigo": info["cuenta_codigo"], "tipo_auxiliar": info["tipo_auxiliar"],
        "titulo": info["titulo"], "direccion": info["direccion"],
    }
    for modulo, info in AUXILIAR_MODULOS.items()
}


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
    (texto ya formateado), fecha_iso (yyyy-mm-dd, para llevar la fecha real
    de ida y vuelta por campos ocultos del formulario sin ambigüedad de
    formato), detalle, cargo y abono (float), y `concepto_codigo`/
    `concepto_descripcion` vacíos (se llenan en pantalla con el buscador,
    o al reconstruir el estado tras un error de validación al descargar)."""
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
            "fecha_iso": fecha.strftime("%Y-%m-%d") if isinstance(fecha, datetime) else "",
            "detalle": (detalle or "").strip() if isinstance(detalle, str) else (detalle or ""),
            "cargo": float(cargo) if isinstance(cargo, (int, float)) else 0.0,
            "abono": float(abono) if isinstance(abono, (int, float)) else 0.0,
            "concepto_codigo": "",
            "concepto_descripcion": "",
            "aux_tipo": "",
            "aux_modulo": "",
            "aux_doc_idx": "",
            "aux_rut": "",
            "aux_nombre": "",
            "aux_tipo_doc": "",
            "aux_numero_doc": "",
            "aux_fecha_iso": "",
        })
    return filas, None


def _rango_periodo_iso(filas):
    fechas = [f["fecha_iso"] for f in filas if f["fecha_iso"]]
    if not fechas:
        return None
    fechas_dt = sorted(datetime.strptime(f, "%Y-%m-%d") for f in fechas)
    return f"{fechas_dt[0].strftime('%d/%m/%Y')} - {fechas_dt[-1].strftime('%d/%m/%Y')}"


def _leer_auxiliares_del_formulario(form):
    """Reconstruye los 3 pools de documentos auxiliares (Clientes/
    Proveedores/Honorarios) ya cargados en pantalla, a partir de los
    campos ocultos `aux_{modulo}_*_{i}` — igual criterio que `_leer_filas_
    del_formulario` para los movimientos: se usa para volver a mostrar la
    página si `/descargar` encuentra un error de validación, sin que el
    admin tenga que volver a subir los 3 Excel de auxiliares."""
    auxiliares = {}
    for modulo in AUXILIAR_MODULOS:
        total = int(form.get(f"aux_{modulo}_total") or 0)
        docs = []
        for i in range(total):
            docs.append({
                "nombre": form.get(f"aux_{modulo}_nombre_{i}", ""),
                "rut": form.get(f"aux_{modulo}_rut_{i}", ""),
                "fecha": form.get(f"aux_{modulo}_fecha_{i}", ""),
                "fecha_iso": form.get(f"aux_{modulo}_fecha_iso_{i}", ""),
                "tipo_documento": form.get(f"aux_{modulo}_tipo_documento_{i}", ""),
                "numero_documento": form.get(f"aux_{modulo}_numero_documento_{i}", ""),
                "monto": float(form.get(f"aux_{modulo}_monto_{i}") or 0),
            })
        auxiliares[modulo] = docs
    return auxiliares


@conciliacion_bp.route("/", methods=["GET"])
@pagina_required("conciliacion.index")
def index():
    return render_template("conciliacion.html", filas=None, cuentas=PLAN_CUENTAS, auxiliares={}, aux_modulos=AUX_MODULOS_JS)


@conciliacion_bp.route("/cargar-auxiliar/<modulo>", methods=["POST"])
@pagina_required("conciliacion.index")
def cargar_auxiliar(modulo):
    """Carga AJAX de uno de los 3 Excel de documentos pendientes (mismo
    parser que "Empresas Caja") — devuelve el fragmento con la tabla de
    documentos + los campos ocultos que la reconstruyen en el POST final
    de `/descargar`, para inyectar en `#wrap-aux-<modulo>` sin recargar la
    página (mismo patrón que `caja_empresas.js:cargarModulo`)."""
    info = AUXILIAR_MODULOS.get(modulo)
    if not info:
        return "Módulo desconocido", 404

    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        return render_template("conciliacion/_fragmento_auxiliares.html", modulo=modulo, docs=[]), 400

    docs, error = info["parser"](archivo)
    if error:
        return f"<div class=\"alert alert-error\">{error} {info['error_archivo']}</div>", 400
    if not docs:
        return (
            f"<div class=\"alert alert-error\">No se encontraron documentos en el archivo. "
            f"{info['error_archivo']}</div>",
            400,
        )

    return render_template("conciliacion/_fragmento_auxiliares.html", modulo=modulo, docs=docs)


@conciliacion_bp.route("/procesar", methods=["POST"])
@pagina_required("conciliacion.index")
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
        periodo=_rango_periodo_iso(filas),
        archivo_nombre=nombre,
        cuentas=PLAN_CUENTAS,
        cuenta_banco_codigo="",
        cuenta_banco_descripcion="",
        auxiliares={},
        aux_modulos=AUX_MODULOS_JS,
    )


def _leer_filas_del_formulario(form):
    """Reconstruye la lista de movimientos (con la clasificación que el
    admin ya haya hecho en pantalla) a partir de los campos ocultos que
    llegan en el POST de `/descargar` — tanto para armar el archivo de
    salida como para volver a mostrar la tabla si algo falta y hay que
    pedirle al admin que la complete, sin que pierda lo ya clasificado.

    `aux_*` (14-09-2026): cuando el movimiento se resolvió contra un
    documento auxiliar (Clientes/Proveedores/Honorarios) en vez de una
    cuenta suelta del plan de cuentas — `aux_tipo` es "A"/"H" (el mismo
    Tipo Auxiliar que usa "Empresas Caja") o "" si se resolvió a mano con
    el buscador de "Concepto" de siempre. `aux_modulo`/`aux_doc_idx`
    identifican EXACTAMENTE qué documento del pool se usó (para que el JS
    no vuelva a proponerlo en otro movimiento al recargar la página tras
    un error de validación) — no se usan para armar el comprobante."""
    total = int(form.get("total_filas") or 0)
    filas = []
    for i in range(total):
        filas.append({
            "fecha": form.get(f"fecha_{i}", ""),
            "fecha_iso": form.get(f"fecha_iso_{i}", ""),
            "detalle": form.get(f"detalle_{i}", ""),
            "cargo": float(form.get(f"cargo_{i}") or 0),
            "abono": float(form.get(f"abono_{i}") or 0),
            "concepto_codigo": form.get(f"concepto_codigo_{i}", ""),
            "concepto_descripcion": form.get(f"concepto_descripcion_{i}", ""),
            "aux_tipo": form.get(f"aux_tipo_{i}", ""),
            "aux_modulo": form.get(f"aux_modulo_{i}", ""),
            "aux_doc_idx": form.get(f"aux_doc_idx_{i}", ""),
            "aux_rut": form.get(f"aux_rut_{i}", ""),
            "aux_nombre": form.get(f"aux_nombre_{i}", ""),
            "aux_tipo_doc": form.get(f"aux_tipo_doc_{i}", ""),
            "aux_numero_doc": form.get(f"aux_numero_doc_{i}", ""),
            "aux_fecha_iso": form.get(f"aux_fecha_iso_{i}", ""),
        })
    return filas


@conciliacion_bp.route("/descargar", methods=["POST"])
@pagina_required("conciliacion.index")
def descargar():
    archivo_nombre = request.form.get("archivo_nombre", "")
    cuenta_banco_codigo = request.form.get("cuenta_banco_codigo", "").strip()
    cuenta_banco_descripcion = request.form.get("cuenta_banco_descripcion", "").strip()
    filas = _leer_filas_del_formulario(request.form)
    auxiliares = _leer_auxiliares_del_formulario(request.form)

    errores = []
    cuenta_banco = CUENTAS_POR_CODIGO.get(cuenta_banco_codigo)
    if not cuenta_banco_codigo or not cuenta_banco:
        errores.append("Selecciona arriba la cuenta bancaria con la que se está conciliando esta cartola.")

    filas_sin_concepto = [
        str(i + 1) for i, f in enumerate(filas)
        if not f["concepto_codigo"] or f["concepto_codigo"] not in CUENTAS_POR_CODIGO
    ]
    if filas_sin_concepto:
        etiqueta = "movimiento" if len(filas_sin_concepto) == 1 else "movimientos"
        errores.append(
            f"Clasifica el {etiqueta} de la fila {', '.join(filas_sin_concepto)} antes de descargar."
            if len(filas_sin_concepto) == 1
            else f"Clasifica los {etiqueta} de las filas {', '.join(filas_sin_concepto)} antes de descargar."
        )

    filas_sin_fecha = [str(i + 1) for i, f in enumerate(filas) if not f["fecha_iso"]]
    if filas_sin_fecha:
        errores.append(
            "La fila "
            + ", ".join(filas_sin_fecha)
            + " no trae una fecha reconocible — revisa el Excel convertido de origen."
        )

    if errores:
        for mensaje in errores:
            flash(mensaje, "error")
        return render_template(
            "conciliacion.html",
            filas=filas,
            periodo=_rango_periodo_iso(filas),
            archivo_nombre=archivo_nombre,
            cuentas=PLAN_CUENTAS,
            cuenta_banco_codigo=cuenta_banco_codigo,
            cuenta_banco_descripcion=cuenta_banco_descripcion,
            auxiliares=auxiliares,
            aux_modulos=AUX_MODULOS_JS,
        )

    movimientos = []
    for f in filas:
        concepto = CUENTAS_POR_CODIGO[f["concepto_codigo"]]
        auxiliar = None
        if f["aux_tipo"]:
            fecha_aux_iso = f["aux_fecha_iso"] or f["fecha_iso"]
            auxiliar = {
                "tipo": f["aux_tipo"],
                "rut": f["aux_rut"],
                "nombre": f["aux_nombre"],
                "tipo_documento_codigo": tipos_documento_repo.codigo_de(f["aux_tipo_doc"]),
                "numero_documento": f["aux_numero_doc"],
                "fecha": datetime.strptime(fecha_aux_iso, "%Y-%m-%d"),
            }
        movimientos.append({
            "fecha": datetime.strptime(f["fecha_iso"], "%Y-%m-%d"),
            "detalle": f["detalle"],
            "cargo": f["cargo"],
            "abono": f["abono"],
            "concepto": concepto,
            "auxiliar": auxiliar,
        })

    try:
        contenido = comprobantes_a_xls_bytes(movimientos, cuenta_banco)
    except FilaSinFecha:
        flash("Alguna fila no trae una fecha reconocible — revisa el Excel convertido de origen.", "error")
        return render_template(
            "conciliacion.html",
            filas=filas,
            periodo=_rango_periodo_iso(filas),
            archivo_nombre=archivo_nombre,
            cuentas=PLAN_CUENTAS,
            cuenta_banco_codigo=cuenta_banco_codigo,
            cuenta_banco_descripcion=cuenta_banco_descripcion,
            auxiliares=auxiliares,
            aux_modulos=AUX_MODULOS_JS,
        )

    base = (archivo_nombre or "conciliacion").rsplit(".", 1)[0]
    nombre_salida = f"Comprobantes_Conciliacion_{base}.xls"
    return send_file(
        io.BytesIO(contenido),
        as_attachment=True,
        download_name=nombre_salida,
        mimetype="application/vnd.ms-excel",
    )
