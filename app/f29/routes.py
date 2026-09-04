"""
"Generar CSV F29": puerto de `pagina_generar_csv_f29()` de la app de
Streamlit. Usa `f29_parser.py` sin cambios. Como Flask no re-ejecuta todo
el script en cada interacción (a diferencia de Streamlit), el flujo queda
en un solo formulario con dos botones (mismo <form>, distinto
`formaction`):

  - "Actualizar vista previa" -> POST /f29/preview  (recalcula y vuelve a
    mostrar la misma página con los totales actualizados).
  - "Descargar CSV"           -> POST /f29/descargar (misma lógica, pero
    entrega el archivo).

GET /f29/ solo pide el PDF; POST /f29/procesar lo parsea y muestra el
formulario ya precargado con los montos detectados.
"""

import io

from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for

from app.auth.decorators import login_required
from app.parsers.f29_parser import (
    parsear_f29, construir_filas, calcular_lineas_remanente,
    ultimo_dia_mes, nombre_mes, _clean_monto, MESES,
    CUENTA_CREDITO_FISCAL, CUENTA_REMANENTE_AUMENTA, CUENTA_REMANENTE_DISMINUYE,
)
from app.parsers.f29_export_writer import filas_a_xls_bytes
from app.parsers.config_manager import cargar_config

f29_bp = Blueprint("f29", __name__, url_prefix="/f29")


@f29_bp.route("/", methods=["GET"])
@login_required
def index():
    configs = cargar_config()
    if not configs:
        flash(
            "No hay ninguna cuenta configurada todavía. Ve a "
            "'Administrador' para agregar al menos una.", "error",
        )
    return render_template("f29.html", configs=configs, parsed=None, preview=None)


@f29_bp.route("/procesar", methods=["POST"])
@login_required
def procesar():
    configs = cargar_config()
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Sube un PDF del Formulario 29 para continuar.", "error")
        return redirect(url_for("f29.index"))

    try:
        data = parsear_f29(io.BytesIO(archivo.read()), configs=configs)
    except Exception as exc:  # noqa: BLE001
        flash(f"No se pudo leer el PDF: {exc}", "error")
        return redirect(url_for("f29.index"))

    filas_tabla = []
    for cfg in configs:
        raw = data.valores.get(cfg.codigo_f29)
        filas_tabla.append({
            "cuenta": cfg.cuenta,
            "codigo_f29": cfg.codigo_f29,
            "descripcion": cfg.descripcion,
            "tipo": cfg.tipo,
            "monto": _clean_monto(raw),
            "detectado": raw is not None,
        })

    mes_idx = (int(data.mes) - 1) if data.mes else 0

    return render_template(
        "f29.html",
        configs=configs,
        parsed={
            "mes_idx": mes_idx,
            "anio": data.anio or "",
            "rut": data.rut,
            "razon_social": data.razon_social,
            "advertencias": data.advertencias,
            "filas": filas_tabla,
            "remanente_504": data.remanente_504,
        },
        preview=None,
        meses=MESES,
    )


def _leer_formulario(form, prefix=""):
    """Reconstruye mes/año/filas/remanente desde los campos del
    formulario (posteados tanto por 'Actualizar vista previa' como por
    'Descargar Excel'), y calcula las líneas finales del comprobante.

    `prefix` permite reusar esta misma función para la carga masiva de
    varios períodos (04-09-2026): cada período de un lote postea sus
    campos con un prefijo propio ("p0_mes", "p0_f_cuenta", etc. para el
    período 0, "p1_..." para el 1, y así​). Con `prefix=""` (el default)
    se comporta exactamente igual que antes para el flujo de un solo
    período."""
    mes = form.get(prefix + "mes")
    anio = (form.get(prefix + "anio") or "").strip()

    cuentas = form.getlist(prefix + "f_cuenta")
    codigos = form.getlist(prefix + "f_codigo")
    tipos = form.getlist(prefix + "f_tipo")
    montos = form.getlist(prefix + "f_monto")
    incluidas = set(form.getlist(prefix + "f_incluir"))  # valores = codigo_f29 incluidos

    monto_por_codigo = {}
    tipo_por_codigo = {}
    cuenta_por_codigo = {}
    for i, codigo in enumerate(codigos):
        try:
            monto_por_codigo[codigo] = int(float(montos[i])) if montos[i] not in (None, "") else 0
        except (ValueError, IndexError):
            monto_por_codigo[codigo] = 0
        tipo_por_codigo[codigo] = tipos[i] if i < len(tipos) else "DEBE"
        cuenta_por_codigo[codigo] = cuentas[i] if i < len(cuentas) else ""

    monto_538 = monto_por_codigo.get("538")
    monto_537 = monto_por_codigo.get("537")
    topar_creditos = (
        "538" in monto_por_codigo and "537" in monto_por_codigo
        and (monto_538 - monto_537) < 0
    )

    lineas_base = []
    for codigo in codigos:
        if codigo not in incluidas:
            continue
        monto = monto_por_codigo[codigo]
        if topar_creditos and codigo == "537":
            monto = monto_538
        lineas_base.append({
            "cuenta": cuenta_por_codigo[codigo], "tipo": tipo_por_codigo[codigo],
            "monto": monto, "centro_costo": "",
        })

    remanente_504 = int(form.get(prefix + "remanente_504") or 0)
    remanente_anterior_raw = (form.get(prefix + "remanente_anterior") or "").strip()
    incluir_ajuste = form.get(prefix + "incluir_ajuste") == "on"
    lineas_remanente = []
    remanente_info = None
    if remanente_504 > 0 and remanente_anterior_raw:
        try:
            remanente_anterior = int(remanente_anterior_raw)
            diferencia_remanente = remanente_504 - remanente_anterior
            if diferencia_remanente != 0:
                remanente_info = {
                    "diferencia": diferencia_remanente,
                    "cuenta_debe": CUENTA_CREDITO_FISCAL if diferencia_remanente > 0 else CUENTA_REMANENTE_DISMINUYE,
                    "cuenta_haber": CUENTA_REMANENTE_AUMENTA if diferencia_remanente > 0 else CUENTA_CREDITO_FISCAL,
                }
                if incluir_ajuste:
                    lineas_remanente = calcular_lineas_remanente(remanente_504, remanente_anterior)
        except ValueError:
            pass

    return {
        "mes": mes, "anio": anio,
        "lineas_finales": lineas_base + lineas_remanente,
        "topar_creditos": topar_creditos,
        "monto_538": monto_538, "monto_537": monto_537,
        "remanente_info": remanente_info,
    }


@f29_bp.route("/preview", methods=["POST"])
@login_required
def preview():
    configs = cargar_config()
    ctx = _leer_formulario(request.form)

    if not ctx["mes"] or not ctx["anio"].isdigit() or len(ctx["anio"]) != 4:
        flash("Ingresa un mes y un año válido (4 dígitos) antes de continuar.", "error")
        return redirect(url_for("f29.index"))

    if not ctx["lineas_finales"]:
        flash("Selecciona al menos una cuenta para generar el comprobante.", "error")
        return redirect(url_for("f29.index"))

    filas_finales = construir_filas(ctx["mes"], ctx["anio"], ctx["lineas_finales"])
    total_debe = sum(l["monto"] for l in ctx["lineas_finales"] if l["tipo"] == "DEBE")
    total_haber = sum(l["monto"] for l in ctx["lineas_finales"] if l["tipo"] == "HABER")

    # Re-armar el estado del formulario (mes/año/filas/remanente) para que
    # la página se vuelva a mostrar igual, con la vista previa abajo.
    codigos = request.form.getlist("f_codigo")
    filas_tabla = []
    incluidas = set(request.form.getlist("f_incluir"))
    montos = request.form.getlist("f_monto")
    for cfg, monto_raw in zip(configs, montos):
        filas_tabla.append({
            "cuenta": cfg.cuenta, "codigo_f29": cfg.codigo_f29,
            "descripcion": cfg.descripcion, "tipo": cfg.tipo,
            "monto": monto_raw, "detectado": True,
            "incluida": cfg.codigo_f29 in incluidas,
        })

    mes_idx = MESES.index(nombre_mes(ctx["mes"])) if ctx["mes"] else 0

    return render_template(
        "f29.html",
        configs=configs,
        meses=MESES,
        parsed={
            "mes_idx": mes_idx, "anio": ctx["anio"],
            "filas": filas_tabla, "advertencias": [],
            "remanente_504": int(request.form.get("remanente_504") or 0),
            "remanente_anterior": request.form.get("remanente_anterior") or "",
            "incluir_ajuste": request.form.get("incluir_ajuste") == "on",
        },
        preview={
            "filas_finales": filas_finales,
            "total_debe": total_debe, "total_haber": total_haber,
            "diferencia": total_debe - total_haber,
            "topar_creditos": ctx["topar_creditos"],
            "monto_538": ctx["monto_538"], "monto_537": ctx["monto_537"],
            "remanente_info": ctx["remanente_info"],
            "nombre_archivo": f"centralizacion_f29_{nombre_mes(ctx['mes']).lower()}_{ctx['anio']}.xls",
        },
    )


@f29_bp.route("/descargar", methods=["POST"])
@login_required
def descargar():
    ctx = _leer_formulario(request.form)
    if not ctx["mes"] or not ctx["anio"].isdigit() or len(ctx["anio"]) != 4 or not ctx["lineas_finales"]:
        flash("Faltan datos para generar el archivo (período o cuentas a incluir).", "error")
        return redirect(url_for("f29.index"))

    filas_finales = construir_filas(ctx["mes"], ctx["anio"], ctx["lineas_finales"])
    xls_bytes = filas_a_xls_bytes(filas_finales)
    nombre_archivo = f"centralizacion_f29_{nombre_mes(ctx['mes']).lower()}_{ctx['anio']}.xls"

    return send_file(
        io.BytesIO(xls_bytes),
        as_attachment=True,
        download_name=nombre_archivo,
        mimetype="application/vnd.ms-excel",
    )


# ---------------------------------------------------------------------------
# Carga masiva de varios períodos (04-09-2026): sube varios PDF de F29 de
# meses distintos de una vez y descarga UN solo .xls con los comprobantes
# de todos los períodos, uno detrás de otro (mismo formato/orden de
# columnas que "Generar F29" de un período).
#
# El remanente de crédito fiscal (código 504) se encadena automáticamente
# entre períodos consecutivos del mismo lote: el remanente que el F29 de
# un mes declara que traspasa "para el período siguiente" (código 77) se
# usa como sugerencia de "remanente anterior" del período que le sigue
# cronológicamente en el lote. Para el PRIMER período del lote no hay F29
# anterior del cual encadenar, así que ese campo queda vacío y el usuario
# lo ingresa a mano (igual que en el flujo de un solo período) si ese
# primer período efectivamente trae remanente (código 504 > 0).
#
# Reusa sin cambios: `parsear_f29`, `construir_filas`, `calcular_lineas_
# remanente`, `filas_a_xls_bytes` y `_leer_formulario` (ahora con soporte
# de prefijo por período). El flujo de un solo período ("/", "/procesar",
# "/preview", "/descargar") no se tocó.
# ---------------------------------------------------------------------------

def _filas_tabla_desde_data(configs, data):
    filas_tabla = []
    for cfg in configs:
        raw = data.valores.get(cfg.codigo_f29)
        filas_tabla.append({
            "cuenta": cfg.cuenta,
            "codigo_f29": cfg.codigo_f29,
            "descripcion": cfg.descripcion,
            "tipo": cfg.tipo,
            "monto": _clean_monto(raw),
            "detectado": raw is not None,
        })
    return filas_tabla


@f29_bp.route("/masivo", methods=["GET"])
@login_required
def masivo():
    configs = cargar_config()
    if not configs:
        flash(
            "No hay ninguna cuenta configurada todavía. Ve a "
            "'Administrador' para agregar al menos una.", "error",
        )
    return render_template("f29_masivo.html", periodos=None, preview=None)


@f29_bp.route("/masivo/procesar", methods=["POST"])
@login_required
def masivo_procesar():
    configs = cargar_config()
    archivos = [a for a in request.files.getlist("archivos") if a and a.filename]

    if not archivos:
        flash("Sube al menos dos PDF del Formulario 29 para continuar.", "error")
        return redirect(url_for("f29.masivo"))
    if len(archivos) < 2:
        flash(
            "Para un solo período usa 'Generar F29'. La carga masiva es para "
            "2 o más períodos a la vez.", "error",
        )
        return redirect(url_for("f29.masivo"))

    datas = []
    for archivo in archivos:
        try:
            data = parsear_f29(io.BytesIO(archivo.read()), configs=configs)
        except Exception as exc:  # noqa: BLE001
            flash(f"No se pudo leer '{archivo.filename}': {exc}", "error")
            return redirect(url_for("f29.masivo"))
        if not data.mes or not data.anio:
            flash(
                f"No se pudo detectar el período (mes/año) de '{archivo.filename}'. "
                f"Súbelo por separado en 'Generar F29' e ingresa el período a mano.",
                "error",
            )
            return redirect(url_for("f29.masivo"))
        datas.append(data)

    # Orden cronológico (no el orden en que se subieron los archivos) — así
    # el encadenamiento de remanente sigue el orden real de los períodos.
    datas.sort(key=lambda d: (d.anio, d.mes))

    periodos = []
    for i, data in enumerate(datas):
        remanente_anterior_sugerido = None
        anterior_encadenable = False
        if i > 0:
            anterior = datas[i - 1]
            if anterior.remanente_periodo_siguiente_encontrado:
                remanente_anterior_sugerido = anterior.remanente_periodo_siguiente
                anterior_encadenable = True
            elif data.remanente_504 > 0:
                data.advertencias.append(
                    "No se pudo detectar automáticamente el remanente que el "
                    "período anterior de este lote traspasa (código 77 de su "
                    "F29). Ingresa el remanente del mes anterior a mano abajo."
                )
        periodos.append({
            "idx": i,
            "mes": data.mes,
            "mes_idx": int(data.mes) - 1,
            "anio": data.anio,
            "rut": data.rut,
            "razon_social": data.razon_social,
            "advertencias": data.advertencias,
            "filas": _filas_tabla_desde_data(configs, data),
            "remanente_504": data.remanente_504,
            "remanente_anterior": remanente_anterior_sugerido,
            "remanente_encadenado": anterior_encadenable,
        })

    return render_template(
        "f29_masivo.html",
        configs=configs,
        meses=MESES,
        periodos=periodos,
        preview=None,
    )


@f29_bp.route("/masivo/preview", methods=["POST"])
@login_required
def masivo_preview():
    configs = cargar_config()
    num_periodos = int(request.form.get("num_periodos") or 0)
    if num_periodos < 2:
        flash("Faltan períodos para procesar la carga masiva.", "error")
        return redirect(url_for("f29.masivo"))

    periodos = []
    filas_totales = []
    total_debe = 0
    total_haber = 0

    for i in range(num_periodos):
        prefix = f"p{i}_"
        ctx = _leer_formulario(request.form, prefix=prefix)

        if not ctx["mes"] or not ctx["anio"].isdigit() or len(ctx["anio"]) != 4:
            flash(f"Período #{i + 1}: ingresa un mes y un año válido (4 dígitos).", "error")
            return redirect(url_for("f29.masivo"))
        if not ctx["lineas_finales"]:
            flash(f"Período #{i + 1}: selecciona al menos una cuenta para incluir.", "error")
            return redirect(url_for("f29.masivo"))

        filas_totales.extend(construir_filas(ctx["mes"], ctx["anio"], ctx["lineas_finales"]))
        total_debe += sum(l["monto"] for l in ctx["lineas_finales"] if l["tipo"] == "DEBE")
        total_haber += sum(l["monto"] for l in ctx["lineas_finales"] if l["tipo"] == "HABER")

        codigos = request.form.getlist(prefix + "f_codigo")
        incluidas = set(request.form.getlist(prefix + "f_incluir"))
        montos = request.form.getlist(prefix + "f_monto")
        filas_tabla = []
        for cfg, monto_raw in zip(configs, montos):
            filas_tabla.append({
                "cuenta": cfg.cuenta, "codigo_f29": cfg.codigo_f29,
                "descripcion": cfg.descripcion, "tipo": cfg.tipo,
                "monto": monto_raw, "detectado": True,
                "incluida": cfg.codigo_f29 in incluidas,
            })

        periodos.append({
            "idx": i,
            "mes": ctx["mes"],
            "mes_idx": MESES.index(nombre_mes(ctx["mes"])),
            "anio": ctx["anio"],
            "advertencias": [],
            "filas": filas_tabla,
            "remanente_504": int(request.form.get(prefix + "remanente_504") or 0),
            "remanente_anterior": request.form.get(prefix + "remanente_anterior") or "",
            "remanente_encadenado": request.form.get(prefix + "remanente_encadenado") == "on",
            "topar_creditos": ctx["topar_creditos"],
            "monto_538": ctx["monto_538"], "monto_537": ctx["monto_537"],
            "remanente_info": ctx["remanente_info"],
        })

    primer_mes, ultimo_mes = periodos[0]["mes"], periodos[-1]["mes"]
    primer_anio, ultimo_anio = periodos[0]["anio"], periodos[-1]["anio"]
    if primer_anio == ultimo_anio:
        nombre_archivo = (
            f"centralizacion_f29_{nombre_mes(primer_mes).lower()}"
            f"_a_{nombre_mes(ultimo_mes).lower()}_{primer_anio}.xls"
        )
    else:
        nombre_archivo = (
            f"centralizacion_f29_{nombre_mes(primer_mes).lower()}_{primer_anio}"
            f"_a_{nombre_mes(ultimo_mes).lower()}_{ultimo_anio}.xls"
        )

    return render_template(
        "f29_masivo.html",
        configs=configs,
        meses=MESES,
        periodos=periodos,
        preview={
            "filas_finales": filas_totales,
            "total_debe": total_debe,
            "total_haber": total_haber,
            "diferencia": total_debe - total_haber,
            "nombre_archivo": nombre_archivo,
        },
    )


@f29_bp.route("/masivo/descargar", methods=["POST"])
@login_required
def masivo_descargar():
    num_periodos = int(request.form.get("num_periodos") or 0)
    if num_periodos < 2:
        flash("Faltan períodos para procesar la carga masiva.", "error")
        return redirect(url_for("f29.masivo"))

    filas_totales = []
    meses_anios = []
    for i in range(num_periodos):
        prefix = f"p{i}_"
        ctx = _leer_formulario(request.form, prefix=prefix)
        if not ctx["mes"] or not ctx["anio"].isdigit() or len(ctx["anio"]) != 4 or not ctx["lineas_finales"]:
            flash(
                f"Período #{i + 1}: faltan datos para generar el archivo "
                f"(período o cuentas a incluir).", "error",
            )
            return redirect(url_for("f29.masivo"))
        filas_totales.extend(construir_filas(ctx["mes"], ctx["anio"], ctx["lineas_finales"]))
        meses_anios.append((ctx["mes"], ctx["anio"]))

    xls_bytes = filas_a_xls_bytes(filas_totales)
    primer_mes, primer_anio = meses_anios[0]
    ultimo_mes, ultimo_anio = meses_anios[-1]
    if primer_anio == ultimo_anio:
        nombre_archivo = (
            f"centralizacion_f29_{nombre_mes(primer_mes).lower()}"
            f"_a_{nombre_mes(ultimo_mes).lower()}_{primer_anio}.xls"
        )
    else:
        nombre_archivo = (
            f"centralizacion_f29_{nombre_mes(primer_mes).lower()}_{primer_anio}"
            f"_a_{nombre_mes(ultimo_mes).lower()}_{ultimo_anio}.xls"
        )

    return send_file(
        io.BytesIO(xls_bytes),
        as_attachment=True,
        download_name=nombre_archivo,
        mimetype="application/vnd.ms-excel",
    )
