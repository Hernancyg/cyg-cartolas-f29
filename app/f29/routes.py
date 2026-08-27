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
    parsear_f29, construir_filas, filas_a_csv_bytes, calcular_lineas_remanente,
    ultimo_dia_mes, nombre_mes, _clean_monto, MESES,
    CUENTA_CREDITO_FISCAL, CUENTA_REMANENTE_AUMENTA, CUENTA_REMANENTE_DISMINUYE,
)
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


def _leer_formulario(form):
    """Reconstruye mes/año/filas/remanente desde los campos del
    formulario (posteados tanto por 'Actualizar vista previa' como por
    'Descargar CSV'), y calcula las líneas finales del comprobante."""
    mes = form.get("mes")
    anio = (form.get("anio") or "").strip()

    cuentas = form.getlist("f_cuenta")
    codigos = form.getlist("f_codigo")
    tipos = form.getlist("f_tipo")
    montos = form.getlist("f_monto")
    incluidas = set(form.getlist("f_incluir"))  # valores = codigo_f29 incluidos

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

    remanente_504 = int(form.get("remanente_504") or 0)
    remanente_anterior_raw = (form.get("remanente_anterior") or "").strip()
    incluir_ajuste = form.get("incluir_ajuste") == "on"
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
            "nombre_archivo": f"centralizacion_f29_{nombre_mes(ctx['mes']).lower()}_{ctx['anio']}.csv",
        },
    )


@f29_bp.route("/descargar", methods=["POST"])
@login_required
def descargar():
    ctx = _leer_formulario(request.form)
    if not ctx["mes"] or not ctx["anio"].isdigit() or len(ctx["anio"]) != 4 or not ctx["lineas_finales"]:
        flash("Faltan datos para generar el CSV (período o cuentas a incluir).", "error")
        return redirect(url_for("f29.index"))

    filas_finales = construir_filas(ctx["mes"], ctx["anio"], ctx["lineas_finales"])
    csv_bytes = filas_a_csv_bytes(filas_finales)
    nombre_archivo = f"centralizacion_f29_{nombre_mes(ctx['mes']).lower()}_{ctx['anio']}.csv"

    return send_file(
        io.BytesIO(csv_bytes),
        as_attachment=True,
        download_name=nombre_archivo,
        mimetype="text/csv",
    )
