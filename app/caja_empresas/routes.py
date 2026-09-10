"""
"Empresas Caja": pestaña nueva pedida por el usuario para generar
comprobantes contables masivos de la caja de una empresa, en un solo lote
que puede cubrir varios meses a la vez (mismo espíritu que "Generar F29 →
Carga masiva").

Seis módulos, en orden (cada uno sube o baja el saldo corrido que arrastra
del anterior, empezando por el saldo inicial digitado):

1. Clientes  (cobros — sube el saldo): se sube un Excel con los documentos
   pendientes de cobro (ver `app/caja_empresas/parsers.py` para el mapeo de
   columnas), se destildan los que no correspondan a esta cobranza, y se
   elige una cuenta del plan de cuentas por documento (buscador, igual que
   Conciliación) — el archivo no trae una cuenta contable, así que no hay
   forma de adivinarla.
2. Proveedores (pagos — baja el saldo): mismo mecanismo que Clientes.
3. Honorarios  (pagos — baja el saldo): mismo mecanismo, con la
   particularidad de que "Tipo Documento"/"N° Documento" se separan de la
   columna "Boleta" del archivo (por ejemplo "BOL-HE 2").
4. F29 (baja el saldo): grilla de 12 meses, fecha digitada a mano por mes,
   monto F29 (cuenta fija 2108-05) y monto Multas (cuenta fija 4201-11).
5. Remuneraciones e Imposiciones (baja el saldo): misma grilla, montos de
   Remuneraciones (2108-15) e Imposiciones (2108-25).
6. Créditos (baja el saldo): misma grilla, Amortización (cuenta elegida por
   buscador, una sola vez para todo el lote — no cambia mes a mes),
   Intereses (4401-01) y Comisiones (4301-07).

Si el saldo final queda negativo, se puede agregar un asiento extra
"Préstamo Socio" (cuenta 2106-04, monto y fecha a elección) que sube el
saldo para poder emitir el archivo.

La cuenta "Caja" (1101-01) es fija para todo el lote y mueve siempre al
resto — ver `app/caja_empresas/export_writer.py` para el detalle exacto de
cómo se arma cada comprobante (2 a 4 líneas según cuántos ítems traiga ese
mes/documento).

Mismo patrón de estado que el resto de la app (Conciliación, F29 masivo):
nada se guarda en el servidor entre requests — todo viaja en campos
ocultos del formulario. La única particularidad de esta pestaña es que
subir cada uno de los 3 archivos de documentos es una llamada AJAX propia
(`/cargar/<modulo>`) que devuelve solo el fragmento de esa tabla — así se
puede cargar Clientes, después Proveedores, después Honorarios (u otro
orden) sin perder lo ya cargado ni tener que repetir los 3 archivos cada
vez que se ajusta algo.
"""

import io
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from app.auth.decorators import pagina_required
from app.caja_empresas import parsers
from app.caja_empresas.export_writer import comprobantes_a_xls_bytes, construir_filas_comprobante
from app.conciliacion.plan_cuentas import CUENTAS_POR_CODIGO, PLAN_CUENTAS

caja_empresas_bp = Blueprint("caja_empresas", __name__, url_prefix="/caja_empresas")

MESES_LABEL = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

DOCUMENTO_MODULOS = {
    "clientes": {
        "parser": parsers.parsear_clientes,
        "titulo": "Clientes",
        "glosa": "Cobro",
        "ingreso": True,
        "error_archivo": "¿Es el Excel de “Estado de Cuentas - Pendientes” de Clientes?",
    },
    "proveedores": {
        "parser": parsers.parsear_proveedores,
        "titulo": "Proveedores",
        "glosa": "Pago proveedor",
        "ingreso": False,
        "error_archivo": "¿Es el Excel de “Estado de Cuentas - Pendientes” de Proveedores?",
    },
    "honorarios": {
        "parser": parsers.parsear_honorarios,
        "titulo": "Honorarios",
        "glosa": "Pago honorarios",
        "ingreso": False,
        "error_archivo": "¿Es el Excel de “Estado de Cuentas de Honorario - Pendientes”?",
    },
}

# Cada entrada: (prefijo, título, [(campo, etiqueta, código_cuenta_fijo_o_None)])
# La cuenta de "amortizacion" es None porque se elige con un buscador
# (una sola vez para todo el lote), no es fija como las demás.
GRILLAS_MENSUALES = [
    ("f29", "F29", [("monto", "Monto F29", "2108-05"), ("multas", "Multas", "4201-11")]),
    ("remimp", "Remuneraciones e Imposiciones", [
        ("remuneraciones", "Remuneraciones", "2108-15"),
        ("imposiciones", "Imposiciones", "2108-25"),
    ]),
    ("credito", "Créditos", [
        ("amortizacion", "Amortización", None),
        ("intereses", "Intereses", "4401-01"),
        ("comisiones", "Comisiones", "4301-07"),
    ]),
]

CUENTA_PRESTAMO_SOCIO = "2106-04"


def _grilla_vacia(campos):
    return [dict({"fecha_iso": ""}, **{campo: 0 for campo, _label, _cuenta in campos}) for _ in range(12)]


def _leer_filas_documentos(form, modulo):
    total = int(form.get(f"{modulo}_total_filas") or 0)
    filas = []
    for i in range(total):
        try:
            monto = float(form.get(f"{modulo}_monto_{i}") or 0)
        except ValueError:
            monto = 0.0
        filas.append({
            "nombre": form.get(f"{modulo}_nombre_{i}", ""),
            "fecha": form.get(f"{modulo}_fecha_{i}", ""),
            "fecha_iso": form.get(f"{modulo}_fecha_iso_{i}", ""),
            "tipo_documento": form.get(f"{modulo}_tipo_documento_{i}", ""),
            "numero_documento": form.get(f"{modulo}_numero_documento_{i}", ""),
            "monto": monto,
            "cuenta_codigo": form.get(f"{modulo}_cuenta_codigo_{i}", "").strip(),
            "cuenta_descripcion": form.get(f"{modulo}_cuenta_descripcion_{i}", "").strip(),
            "seleccionado": form.get(f"{modulo}_check_{i}") == "on",
        })
    return filas


def _leer_grilla_mensual(form, prefijo, campos):
    meses = []
    for m in range(12):
        fila = {"fecha_iso": form.get(f"{prefijo}_fecha_{m}", "")}
        for campo, _label, _cuenta in campos:
            try:
                fila[campo] = float(form.get(f"{prefijo}_{campo}_{m}") or 0)
            except ValueError:
                fila[campo] = 0.0
        meses.append(fila)
    return meses


def _contexto_vacio():
    return {
        "cuentas": PLAN_CUENTAS,
        "meses_label": MESES_LABEL,
        "grillas": GRILLAS_MENSUALES,
        "clientes_filas": [],
        "proveedores_filas": [],
        "honorarios_filas": [],
        "f29_meses": _grilla_vacia(GRILLAS_MENSUALES[0][2]),
        "remimp_meses": _grilla_vacia(GRILLAS_MENSUALES[1][2]),
        "credito_meses": _grilla_vacia(GRILLAS_MENSUALES[2][2]),
        "credito_cuenta_amortizacion_codigo": "",
        "credito_cuenta_amortizacion_descripcion": "",
        "saldo_inicial": "",
        "prestamo_socio_check": False,
        "prestamo_socio_monto": "",
        "prestamo_socio_fecha": "",
    }


@caja_empresas_bp.route("/", methods=["GET"])
@pagina_required("caja_empresas.index")
def index():
    return render_template("caja_empresas.html", **_contexto_vacio())


@caja_empresas_bp.route("/cargar/<modulo>", methods=["POST"])
@pagina_required("caja_empresas.index")
def cargar(modulo):
    info = DOCUMENTO_MODULOS.get(modulo)
    if not info:
        return "Módulo desconocido", 404

    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        return render_template("caja_empresas/_fragmento_documentos.html", modulo=modulo, filas=[]), 400

    filas, error = info["parser"](archivo)
    if error:
        return f"<div class=\"alert alert-error\">{error} {info['error_archivo']}</div>", 400
    if not filas:
        return (
            f"<div class=\"alert alert-error\">No se encontraron documentos en el archivo. "
            f"{info['error_archivo']}</div>",
            400,
        )

    return render_template("caja_empresas/_fragmento_documentos.html", modulo=modulo, filas=filas)


def _comprobantes_documentos(filas, ingreso, glosa_prefix, errores, etiqueta_modulo):
    """Arma un comprobante por cada documento SELECCIONADO. Agrega a
    `errores` (in-place) un mensaje por cada fila seleccionada sin cuenta
    válida, en vez de fallar silenciosamente. Devuelve (filas_planas,
    total_monto_seleccionado)."""
    todas = []
    total = 0.0
    faltantes = []
    for i, f in enumerate(filas):
        if not f["seleccionado"]:
            continue
        cuenta = CUENTAS_POR_CODIGO.get(f["cuenta_codigo"])
        if not cuenta:
            faltantes.append(str(i + 1))
            continue
        try:
            fecha = datetime.strptime(f["fecha_iso"], "%Y-%m-%d")
        except ValueError:
            errores.append(
                f"{etiqueta_modulo}: el documento de la fila {i + 1} no trae una fecha reconocible."
            )
            continue
        glosa = f"{glosa_prefix} {f['nombre']} - {f['tipo_documento']} {f['numero_documento']}".strip()
        todas.extend(construir_filas_comprobante(fecha, glosa, [(cuenta, f["monto"])], ingreso=ingreso))
        total += f["monto"]

    if faltantes:
        etiqueta = "el documento de la fila" if len(faltantes) == 1 else "los documentos de las filas"
        errores.append(f"{etiqueta_modulo}: asigna una cuenta a {etiqueta} {', '.join(faltantes)} antes de generar.")

    return todas, total


def _comprobantes_mensuales(meses, campos, glosa_prefix, errores, etiqueta_modulo, cuenta_amortizacion=None):
    """`campos`: la lista de (campo, etiqueta, codigo_cuenta_fijo_o_None)
    de `GRILLAS_MENSUALES`. `cuenta_amortizacion`: dict de la cuenta
    elegida por buscador para el campo cuyo código fijo es None (hoy solo
    ocurre en Créditos/Amortización) — puede ser None si ese campo no se
    usa este lote."""
    todas = []
    total = 0.0
    for idx, mes in enumerate(meses):
        lineas = []
        campo_sin_cuenta = False
        for campo, _label, codigo_fijo in campos:
            monto = mes.get(campo, 0)
            if not monto or monto <= 0:
                continue
            cuenta = CUENTAS_POR_CODIGO.get(codigo_fijo) if codigo_fijo else cuenta_amortizacion
            if not cuenta:
                campo_sin_cuenta = True
                continue
            lineas.append((cuenta, monto))

        if campo_sin_cuenta:
            errores.append(
                f"{etiqueta_modulo}: selecciona la cuenta de Amortización arriba de la grilla — "
                f"{MESES_LABEL[idx]} trae un monto de amortización."
            )
        if not lineas:
            continue
        if not mes["fecha_iso"]:
            errores.append(f"{etiqueta_modulo}: falta la fecha de {MESES_LABEL[idx]}.")
            continue

        fecha = datetime.strptime(mes["fecha_iso"], "%Y-%m-%d")
        glosa = f"{glosa_prefix} {MESES_LABEL[idx]}"
        todas.extend(construir_filas_comprobante(fecha, glosa, lineas, ingreso=False))
        total += sum(m for _c, m in lineas)

    return todas, total


@caja_empresas_bp.route("/generar", methods=["POST"])
@pagina_required("caja_empresas.index")
def generar():
    form = request.form
    errores = []

    try:
        saldo_inicial = float(form.get("saldo_inicial") or 0)
    except ValueError:
        saldo_inicial = 0.0
        errores.append("El saldo inicial no es un número válido.")

    clientes_filas = _leer_filas_documentos(form, "clientes")
    proveedores_filas = _leer_filas_documentos(form, "proveedores")
    honorarios_filas = _leer_filas_documentos(form, "honorarios")

    f29_meses = _leer_grilla_mensual(form, "f29", GRILLAS_MENSUALES[0][2])
    remimp_meses = _leer_grilla_mensual(form, "remimp", GRILLAS_MENSUALES[1][2])
    credito_meses = _leer_grilla_mensual(form, "credito", GRILLAS_MENSUALES[2][2])

    credito_cuenta_codigo = form.get("credito_cuenta_amortizacion_codigo", "").strip()
    credito_cuenta_descripcion = form.get("credito_cuenta_amortizacion_descripcion", "").strip()
    cuenta_amortizacion = CUENTAS_POR_CODIGO.get(credito_cuenta_codigo)

    prestamo_socio_check = form.get("prestamo_socio_check") == "on"
    try:
        prestamo_socio_monto = float(form.get("prestamo_socio_monto") or 0)
    except ValueError:
        prestamo_socio_monto = 0.0
    prestamo_socio_fecha_iso = form.get("prestamo_socio_fecha", "")

    filas_clientes, total_clientes = _comprobantes_documentos(
        clientes_filas, True, "Cobro", errores, "Clientes",
    )
    filas_proveedores, total_proveedores = _comprobantes_documentos(
        proveedores_filas, False, "Pago proveedor", errores, "Proveedores",
    )
    filas_honorarios, total_honorarios = _comprobantes_documentos(
        honorarios_filas, False, "Pago honorarios", errores, "Honorarios",
    )
    filas_f29, total_f29 = _comprobantes_mensuales(
        f29_meses, GRILLAS_MENSUALES[0][2], "Pago F29", errores, "F29",
    )
    filas_remimp, total_remimp = _comprobantes_mensuales(
        remimp_meses, GRILLAS_MENSUALES[1][2], "Pago remuneraciones e imposiciones", errores,
        "Remuneraciones e Imposiciones",
    )
    filas_credito, total_credito = _comprobantes_mensuales(
        credito_meses, GRILLAS_MENSUALES[2][2], "Pago crédito", errores, "Créditos",
        cuenta_amortizacion=cuenta_amortizacion,
    )

    saldo_antes_prestamo = (
        saldo_inicial + total_clientes - total_proveedores - total_honorarios
        - total_f29 - total_remimp - total_credito
    )

    filas_prestamo = []
    if prestamo_socio_check:
        if prestamo_socio_monto <= 0:
            errores.append("Préstamo Socio: ingresa un monto mayor a cero.")
        if not prestamo_socio_fecha_iso:
            errores.append("Préstamo Socio: falta la fecha del asiento.")
        if prestamo_socio_monto > 0 and prestamo_socio_fecha_iso:
            fecha_prestamo = datetime.strptime(prestamo_socio_fecha_iso, "%Y-%m-%d")
            cuenta_prestamo = CUENTAS_POR_CODIGO[CUENTA_PRESTAMO_SOCIO]
            filas_prestamo = construir_filas_comprobante(
                fecha_prestamo, "Préstamo socio", [(cuenta_prestamo, prestamo_socio_monto)], ingreso=True,
            )

    saldo_final = saldo_antes_prestamo + (prestamo_socio_monto if prestamo_socio_check else 0)

    if saldo_antes_prestamo < 0 and not prestamo_socio_check:
        errores.append(
            f"El saldo final queda negativo (${round(saldo_antes_prestamo):,.0f}".replace(",", ".")
            + "). Marca la opción “Préstamo Socio” y agrega el monto para poder generar el archivo."
        )
    elif prestamo_socio_check and prestamo_socio_monto > 0 and saldo_final < 0:
        errores.append(
            "El préstamo socio ingresado no alcanza para cubrir el saldo negativo "
            f"(falta ${round(-saldo_final):,.0f}".replace(",", ".") + ")."
        )

    if errores:
        for mensaje in errores:
            flash(mensaje, "error")
        return render_template(
            "caja_empresas.html",
            cuentas=PLAN_CUENTAS,
            meses_label=MESES_LABEL,
            grillas=GRILLAS_MENSUALES,
            clientes_filas=clientes_filas,
            proveedores_filas=proveedores_filas,
            honorarios_filas=honorarios_filas,
            f29_meses=f29_meses,
            remimp_meses=remimp_meses,
            credito_meses=credito_meses,
            credito_cuenta_amortizacion_codigo=credito_cuenta_codigo,
            credito_cuenta_amortizacion_descripcion=credito_cuenta_descripcion,
            saldo_inicial=form.get("saldo_inicial", ""),
            prestamo_socio_check=prestamo_socio_check,
            prestamo_socio_monto=form.get("prestamo_socio_monto", ""),
            prestamo_socio_fecha=prestamo_socio_fecha_iso,
        )

    todas_las_filas = (
        filas_clientes + filas_proveedores + filas_honorarios
        + filas_f29 + filas_remimp + filas_credito + filas_prestamo
    )

    if not todas_las_filas:
        flash("No hay ningún documento ni monto para generar comprobantes.", "error")
        return redirect(url_for("caja_empresas.index"))

    contenido = comprobantes_a_xls_bytes(todas_las_filas)
    nombre_salida = f"Comprobantes_EmpresasCaja_{datetime.now().strftime('%Y%m%d_%H%M')}.xls"
    return send_file(
        io.BytesIO(contenido),
        as_attachment=True,
        download_name=nombre_salida,
        mimetype="application/vnd.ms-excel",
    )
