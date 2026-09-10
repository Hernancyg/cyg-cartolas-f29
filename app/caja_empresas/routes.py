"""
"Empresas Caja": pestaña nueva pedida por el usuario para generar
comprobantes contables masivos de la caja de una empresa, en un solo lote
que puede cubrir varios meses a la vez (mismo espíritu que "Generar F29 →
Carga masiva").

Seis módulos, en orden (cada uno sube o baja el saldo corrido que arrastra
del anterior, empezando por el saldo inicial digitado):

1. Clientes  (cobros — sube el saldo): se sube un Excel con los documentos
   pendientes de cobro (ver `app/caja_empresas/parsers.py` para el mapeo de
   columnas) y se destildan los que no correspondan a esta cobranza. La
   cuenta contra la que se cobra es FIJA (1104-01 DEUDORES CLIENTES) — el
   usuario confirmó que no se digita ni se elige por documento. Glosa:
   "INGRESO F {n° documento} {nombre}". Lleva Tipo Auxiliar "A" en el
   archivo de salida (RUT + nombre + tipo/n° de documento + fecha).
2. Proveedores (pagos — baja el saldo): mismo mecanismo, cuenta fija
   2105-01 FACTURAS POR PAGAR, glosa "PAGO F {n° documento} {nombre}",
   también Tipo Auxiliar "A".
3. Honorarios  (pagos — baja el saldo): mismo mecanismo, cuenta fija
   2105-04 HONORARIOS POR PAGAR, con la particularidad de que "Tipo
   Documento"/"N° Documento" se separan de la columna "Boleta" del
   archivo (por ejemplo "BOL-HE 2"). Glosa "PAGO BH {n° documento}
   {nombre}", Tipo Auxiliar "H".
4. F29 (baja el saldo): grilla de 13 meses (Diciembre del año anterior +
   Enero..Diciembre del "Año del lote"), fecha digitada a mano por fila,
   monto F29 (cuenta fija 2108-05) y monto Multas (cuenta fija 4201-11).
5. Remuneraciones e Imposiciones (baja el saldo): misma grilla de 13 meses,
   pero SIN fecha digitada — Remuneraciones (2108-15) se paga el último
   día de ese mes; Imposiciones (2108-25) el día 13 del mes siguiente
   (confirmado por el usuario, 10-09-2026). Por eso cada mes con montos
   genera hasta DOS comprobantes independientes, cada uno con su propia
   fecha calculada.
6. Créditos (baja el saldo): grilla de 12 meses (Enero..Diciembre del "Año
   del lote"), fecha digitada a mano, Amortización (cuenta elegida por
   buscador, una sola vez para todo el lote — no cambia mes a mes),
   Intereses (4401-01) y Comisiones (4301-07).

El "Año del lote" (campo `anio`) es lo que permite calcular a qué mes/año
calendario corresponde cada fila de las grillas y, con eso, las fechas
automáticas de Remuneraciones/Imposiciones — el servidor SIEMPRE recalcula
todo desde el `anio` que llega en el POST, nunca confía en lo que ya se ve
en pantalla.

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

import calendar
import io
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from app.auth.decorators import pagina_required
from app.caja_empresas import parsers
from app.caja_empresas.export_writer import comprobantes_a_xls_bytes, construir_filas_comprobante
from app.conciliacion.plan_cuentas import CUENTAS_POR_CODIGO, PLAN_CUENTAS
from app.data import tipos_documento_repo

caja_empresas_bp = Blueprint("caja_empresas", __name__, url_prefix="/caja_empresas")

MESES_LABEL = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

# Clientes/Proveedores/Honorarios: cuenta fija (no se digita ni se elige,
# confirmado por el usuario), glosa de cada comprobante en el formato
# exacto que pidió (10-09-2026), y el tipo de bloque auxiliar que le
# corresponde en el archivo de salida ("A" para Clientes/Proveedores, "H"
# para Honorarios — ver `app/caja_empresas/export_writer.py`).
DOCUMENTO_MODULOS = {
    "clientes": {
        "parser": parsers.parsear_clientes,
        "titulo": "Clientes",
        "ingreso": True,
        "cuenta_codigo": "1104-01",
        "tipo_auxiliar": "A",
        "glosa": lambda f: f"INGRESO F {f['numero_documento']} {f['nombre']}".strip(),
        "error_archivo": "¿Es el Excel de “Estado de Cuentas - Pendientes” de Clientes?",
    },
    "proveedores": {
        "parser": parsers.parsear_proveedores,
        "titulo": "Proveedores",
        "ingreso": False,
        "cuenta_codigo": "2105-01",
        "tipo_auxiliar": "A",
        "glosa": lambda f: f"PAGO F {f['numero_documento']} {f['nombre']}".strip(),
        "error_archivo": "¿Es el Excel de “Estado de Cuentas - Pendientes” de Proveedores?",
    },
    "honorarios": {
        "parser": parsers.parsear_honorarios,
        "titulo": "Honorarios",
        "ingreso": False,
        "cuenta_codigo": "2105-04",
        "tipo_auxiliar": "H",
        "glosa": lambda f: f"PAGO BH {f['numero_documento']} {f['nombre']}".strip(),
        "error_archivo": "¿Es el Excel de “Estado de Cuentas de Honorario - Pendientes”?",
    },
}

# Cada entrada: (prefijo, título, [(campo, etiqueta, código_cuenta_fijo_o_None)],
# incluye_diciembre_anterior, fecha_manual).
# La cuenta de "amortizacion" es None porque se elige con un buscador (una
# sola vez para todo el lote), no es fija como las demás.
#
# F29 y Remuneraciones-e-Imposiciones agregan una fila extra de "Diciembre
# del año anterior" (10-09-2026: las imposiciones de diciembre se pagan el
# 13 de enero, que puede caer en el mismo lote) — Créditos no la necesita.
# Remuneraciones-e-Imposiciones ya no trae fecha manual: se calcula sola
# (ver `_comprobantes_remuneraciones_imposiciones`).
GRILLAS_MENSUALES = [
    ("f29", "F29", [("monto", "Monto F29", "2108-05"), ("multas", "Multas", "4201-11")], True, True),
    ("remimp", "Remuneraciones e Imposiciones", [
        ("remuneraciones", "Remuneraciones", "2108-15"),
        ("imposiciones", "Imposiciones", "2108-25"),
    ], True, False),
    ("credito", "Créditos", [
        ("amortizacion", "Amortización", None),
        ("intereses", "Intereses", "4401-01"),
        ("comisiones", "Comisiones", "4301-07"),
    ], False, True),
]

CUENTA_PRESTAMO_SOCIO = "2106-04"


def _meses_grid(anio, incluye_diciembre_anterior):
    """Devuelve la lista de (mes_num, anio_efectivo, etiqueta) de la
    grilla: 13 filas (Diciembre del año anterior + Enero..Diciembre del
    año elegido) para F29/Remuneraciones-Imposiciones, o 12 filas
    (Enero..Diciembre) para Créditos."""
    filas = []
    if incluye_diciembre_anterior:
        filas.append((12, anio - 1, f"Diciembre {anio - 1}"))
    for mes_num in range(1, 13):
        filas.append((mes_num, anio, f"{MESES_LABEL[mes_num - 1]} {anio}"))
    return filas


def _fecha_remuneraciones(anio_efectivo, mes_num):
    """Último día del mes/año efectivo."""
    ultimo_dia = calendar.monthrange(anio_efectivo, mes_num)[1]
    return datetime(anio_efectivo, mes_num, ultimo_dia)


def _fecha_imposiciones(anio_efectivo, mes_num):
    """El 13 del mes siguiente (regla confirmada por el usuario: las
    imposiciones de enero se pagan el 13-02; diciembre rueda al enero del
    año siguiente)."""
    if mes_num == 12:
        return datetime(anio_efectivo + 1, 1, 13)
    return datetime(anio_efectivo, mes_num + 1, 13)


def _grilla_vacia(campos, filas_count=12):
    return [dict({"fecha_iso": ""}, **{campo: 0 for campo, _label, _cuenta in campos}) for _ in range(filas_count)]


def _enriquecer_meses(meses, anio, incluye_diciembre_anterior, con_fechas_calculadas):
    """Agrega a cada fila de la grilla su etiqueta ("Diciembre 2025",
    "Enero 2026", ...) y, si corresponde (Remuneraciones e Imposiciones),
    las fechas de pago YA calculadas para mostrarlas en pantalla — el
    cálculo real que manda es el que hace `generar()` con el `anio` que
    de verdad vino en el POST, esto es solo para que se vea en la
    pantalla."""
    info = _meses_grid(anio, incluye_diciembre_anterior)
    for mes, (mes_num, anio_ef, label) in zip(meses, info):
        mes["label"] = label
        mes["mes_num"] = mes_num
        mes["anio_efectivo"] = anio_ef
        if con_fechas_calculadas:
            mes["remuneraciones_fecha_display"] = _fecha_remuneraciones(anio_ef, mes_num).strftime("%d-%m-%Y")
            mes["imposiciones_fecha_display"] = _fecha_imposiciones(anio_ef, mes_num).strftime("%d-%m-%Y")
    return meses


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
            "rut": form.get(f"{modulo}_rut_{i}", ""),
            "fecha": form.get(f"{modulo}_fecha_{i}", ""),
            "fecha_iso": form.get(f"{modulo}_fecha_iso_{i}", ""),
            "tipo_documento": form.get(f"{modulo}_tipo_documento_{i}", ""),
            "numero_documento": form.get(f"{modulo}_numero_documento_{i}", ""),
            "monto": monto,
            "seleccionado": form.get(f"{modulo}_check_{i}") == "on",
        })
    return filas


def _leer_grilla_mensual(form, prefijo, campos, filas_count=12):
    meses = []
    for m in range(filas_count):
        fila = {"fecha_iso": form.get(f"{prefijo}_fecha_{m}", "")}
        for campo, _label, _cuenta in campos:
            try:
                fila[campo] = float(form.get(f"{prefijo}_{campo}_{m}") or 0)
            except ValueError:
                fila[campo] = 0.0
        meses.append(fila)
    return meses


def _anio_desde_form(form, errores):
    crudo = (form.get("anio") or "").strip()
    try:
        anio = int(crudo)
        if not (2000 <= anio <= 2100):
            raise ValueError
        return anio
    except ValueError:
        errores.append("El “Año del lote” no es válido — ingresa un año de 4 dígitos (ej. 2026).")
        return datetime.now().year


def _contexto_vacio():
    anio = datetime.now().year
    return {
        "cuentas": PLAN_CUENTAS,
        "anio": anio,
        "clientes_filas": [],
        "proveedores_filas": [],
        "honorarios_filas": [],
        "f29_meses": _enriquecer_meses(_grilla_vacia(GRILLAS_MENSUALES[0][2], 13), anio, True, False),
        "remimp_meses": _enriquecer_meses(_grilla_vacia(GRILLAS_MENSUALES[1][2], 13), anio, True, True),
        "credito_meses": _enriquecer_meses(_grilla_vacia(GRILLAS_MENSUALES[2][2], 12), anio, False, False),
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


def _comprobantes_documentos(filas, modulo, errores):
    """Arma un comprobante por cada documento SELECCIONADO de un módulo de
    Clientes/Proveedores/Honorarios, contra la cuenta FIJA de ese módulo
    (no se digita ni se elige en pantalla, el usuario confirmó que son
    siempre las mismas), con la glosa exacta y el bloque de Tipo Auxiliar
    "A"/"H" que pidió el usuario (10-09-2026). Devuelve (filas_planas,
    total_monto_seleccionado)."""
    info = DOCUMENTO_MODULOS[modulo]
    cuenta = CUENTAS_POR_CODIGO[info["cuenta_codigo"]]
    etiqueta_modulo = info["titulo"]
    todas = []
    total = 0.0
    for i, f in enumerate(filas):
        if not f["seleccionado"]:
            continue
        try:
            fecha = datetime.strptime(f["fecha_iso"], "%Y-%m-%d")
        except ValueError:
            errores.append(
                f"{etiqueta_modulo}: el documento de la fila {i + 1} no trae una fecha reconocible."
            )
            continue
        glosa = info["glosa"](f)
        auxiliar = {
            "tipo": info["tipo_auxiliar"],
            "rut": f.get("rut", ""),
            "nombre": f["nombre"],
            "tipo_documento_codigo": tipos_documento_repo.codigo_de(f["tipo_documento"]),
            "numero_documento": f["numero_documento"],
            "fecha": fecha,
        }
        todas.extend(construir_filas_comprobante(fecha, glosa, [(cuenta, f["monto"], auxiliar)], ingreso=info["ingreso"]))
        total += f["monto"]

    return todas, total


def _comprobantes_mensuales(meses, campos, glosa_prefix, errores, etiqueta_modulo, cuenta_amortizacion=None):
    """`campos`: la lista de (campo, etiqueta, codigo_cuenta_fijo_o_None)
    de `GRILLAS_MENSUALES`. `cuenta_amortizacion`: dict de la cuenta
    elegida por buscador para el campo cuyo código fijo es None (hoy solo
    ocurre en Créditos/Amortización) — puede ser None si ese campo no se
    usa este lote. Usado por F29 y Créditos, que siguen con fecha digitada
    a mano por fila (a diferencia de Remuneraciones e Imposiciones, ver
    `_comprobantes_remuneraciones_imposiciones`)."""
    todas = []
    total = 0.0
    for mes in meses:
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
                f"{mes['label']} trae un monto de amortización."
            )
        if not lineas:
            continue
        if not mes["fecha_iso"]:
            errores.append(f"{etiqueta_modulo}: falta la fecha de {mes['label']}.")
            continue

        fecha = datetime.strptime(mes["fecha_iso"], "%Y-%m-%d")
        glosa = f"{glosa_prefix} {mes['label']}"
        todas.extend(construir_filas_comprobante(fecha, glosa, lineas, ingreso=False))
        total += sum(m for _c, m in lineas)

    return todas, total


def _comprobantes_remuneraciones_imposiciones(meses):
    """Remuneraciones e Imposiciones se pagan en fechas distintas (regla
    confirmada por el usuario, 10-09-2026): Remuneraciones el último día
    del mes; Imposiciones el 13 del mes siguiente. Por eso cada mes con
    montos genera hasta DOS comprobantes independientes (no uno solo como
    el resto de las grillas mensuales), cada uno con su propia fecha ya
    calculada — no hay fecha digitada a mano aquí, así que no hay caso de
    "falta la fecha"."""
    cuenta_remuneraciones = CUENTAS_POR_CODIGO["2108-15"]
    cuenta_imposiciones = CUENTAS_POR_CODIGO["2108-25"]
    todas = []
    total = 0.0
    for mes in meses:
        monto_remuneraciones = mes.get("remuneraciones") or 0
        monto_imposiciones = mes.get("imposiciones") or 0

        if monto_remuneraciones > 0:
            fecha = _fecha_remuneraciones(mes["anio_efectivo"], mes["mes_num"])
            glosa = f"Pago remuneraciones {mes['label']}"
            todas.extend(construir_filas_comprobante(fecha, glosa, [(cuenta_remuneraciones, monto_remuneraciones)], ingreso=False))
            total += monto_remuneraciones

        if monto_imposiciones > 0:
            fecha = _fecha_imposiciones(mes["anio_efectivo"], mes["mes_num"])
            glosa = f"Pago imposiciones {mes['label']}"
            todas.extend(construir_filas_comprobante(fecha, glosa, [(cuenta_imposiciones, monto_imposiciones)], ingreso=False))
            total += monto_imposiciones

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

    anio = _anio_desde_form(form, errores)

    clientes_filas = _leer_filas_documentos(form, "clientes")
    proveedores_filas = _leer_filas_documentos(form, "proveedores")
    honorarios_filas = _leer_filas_documentos(form, "honorarios")

    f29_meses = _enriquecer_meses(_leer_grilla_mensual(form, "f29", GRILLAS_MENSUALES[0][2], 13), anio, True, False)
    remimp_meses = _enriquecer_meses(_leer_grilla_mensual(form, "remimp", GRILLAS_MENSUALES[1][2], 13), anio, True, True)
    credito_meses = _enriquecer_meses(_leer_grilla_mensual(form, "credito", GRILLAS_MENSUALES[2][2], 12), anio, False, False)

    credito_cuenta_codigo = form.get("credito_cuenta_amortizacion_codigo", "").strip()
    credito_cuenta_descripcion = form.get("credito_cuenta_amortizacion_descripcion", "").strip()
    cuenta_amortizacion = CUENTAS_POR_CODIGO.get(credito_cuenta_codigo)

    prestamo_socio_check = form.get("prestamo_socio_check") == "on"
    try:
        prestamo_socio_monto = float(form.get("prestamo_socio_monto") or 0)
    except ValueError:
        prestamo_socio_monto = 0.0
    prestamo_socio_fecha_iso = form.get("prestamo_socio_fecha", "")

    filas_clientes, total_clientes = _comprobantes_documentos(clientes_filas, "clientes", errores)
    filas_proveedores, total_proveedores = _comprobantes_documentos(proveedores_filas, "proveedores", errores)
    filas_honorarios, total_honorarios = _comprobantes_documentos(honorarios_filas, "honorarios", errores)
    filas_f29, total_f29 = _comprobantes_mensuales(
        f29_meses, GRILLAS_MENSUALES[0][2], "Pago F29", errores, "F29",
    )
    filas_remimp, total_remimp = _comprobantes_remuneraciones_imposiciones(remimp_meses)
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
            anio=anio,
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
