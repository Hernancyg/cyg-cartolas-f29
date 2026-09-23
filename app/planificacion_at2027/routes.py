"""
"Planificación AT 2027": tabla editable de seguimiento de empresas
(analista asignado por mes, prioridad, avance del balance, etc.) —
reemplaza el Excel manual que llevaba el usuario (17-09-2026). Se edita
fila por fila en pantalla (mismo patrón
"clonar fila + guardar todo el formulario" que `depreciacion/categorias.
html` / `admin/tipos_documento.html`, ver `app/static/js/editable_rows.
js`), y también se puede recargar completa subiendo un Excel desde
Administrador → Planificación AT 2027 (ver `app/admin/routes.py`) — ambos
caminos terminan en `planificacion_at2027_repo.guardar_todos`.
"""

import io

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from openpyxl import Workbook

from app.auth.decorators import pagina_required
from app.data import planificacion_at2027_repo
from app.planificacion_at2027.pdf_informe import generar_pdf_informe

planificacion_at2027_bp = Blueprint(
    "planificacion_at2027", __name__, url_prefix="/planificacion_at2027",
)

MESES = ["mes_septiembre", "mes_octubre", "mes_noviembre", "mes_diciembre", "mes_enero", "mes_febrero"]

# Columnas de texto libre en el orden en que se muestran (numero/empresa/
# analista/prioridad/caja_banco se manejan aparte porque tienen su propio
# tipo o su propio <select>).
COLUMNAS_TEXTO = MESES + [
    "actualizacion_balance", "reunion_cat1_1", "reunion_cat2", "reunion_cat3", "reunion_cat1_2",
    "grupo", "estado_balance_ultimo_mes",
]

# Mismo orden que usa la carga masiva (app/admin/routes.py:PLANIFICACION_COLUMNAS)
# y la exportación — para que exportar -> editar en Excel -> volver a
# cargar sea un viaje de ida y vuelta sin sorpresas.
COLUMNAS_EXPORTAR = ["numero", "empresa", "analista", "prioridad", "caja_banco"] + MESES + [
    "actualizacion_balance", "reunion_cat1_1", "reunion_cat2", "reunion_cat3", "reunion_cat1_2",
    "grupo", "estado_balance_ultimo_mes",
]
ENCABEZADOS_EXPORTAR = [
    "N°", "Empresa", "Analista", "Prioridad", "Caja/Banco",
    "Septiembre", "Octubre", "Noviembre", "Diciembre", "Enero", "Febrero",
    "Avance Balance", "Reunión Cat1 (1°)", "Reunión Cat2", "Reunión Cat3",
    "Reunión Cat1 (2°)", "Grupo", "Estado Balance (Último mes trabajado)",
]


# "Actualización Balance" (18-09-2026, redefinido por el usuario): ya no
# es la frecuencia del balance (Mensual/Trimestral/...) sino el AVANCE —
# hasta qué mes del ciclo Septiembre→Febrero está al día el balance de esa
# empresa. Es un <select> con estos 6 valores exactos (ver el template),
# en el mismo orden que MESES.
ORDEN_AVANCE = ["Septiembre", "Octubre", "Noviembre", "Diciembre", "Enero", "Febrero"]


def _ultimo_mes_planificado(fila: dict) -> str | None:
    """Último mes del ciclo (Sep→Feb) que tiene a alguien asignado en las
    columnas de mes, o `None` si ninguno tiene asignación todavía."""
    ultimo = None
    for mes, etiqueta in zip(MESES, ORDEN_AVANCE):
        if (fila.get(mes) or "").strip():
            ultimo = etiqueta
    return ultimo


def _estado_de_fila(fila: dict) -> str:
    """"Sin asignar" (ningún mes tiene analista asignado todavía),
    "Completado" (el "Avance Balance" ya llegó al último mes que SÍ tiene
    alguien asignado) o "En proceso" (tiene meses asignados pero el avance
    todavía no alcanza a ese último mes) — calculado en vivo a partir de
    los 6 meses y de "Actualización Balance", sin guardar nada nuevo en la
    base de datos (19-09-2026, redefinido por el usuario: antes
    "Completado" exigía llegar a Febrero fijo, sin importar hasta qué mes
    se había planificado realmente a esa empresa)."""
    ultimo = _ultimo_mes_planificado(fila)
    if ultimo is None:
        return "sin_asignar"
    avance = (fila.get("actualizacion_balance") or "").strip().lower()
    return "completado" if avance == ultimo.lower() else "en_proceso"


MESES_LABEL = {
    "mes_septiembre": "Sep", "mes_octubre": "Oct", "mes_noviembre": "Nov",
    "mes_diciembre": "Dic", "mes_enero": "Ene", "mes_febrero": "Feb",
}
# Clave corta para los ids del DOM que el JS recalcula al filtrar
# (`plan-mes-<key>-value`/`-sub`) — mismo texto que MESES_LABEL, en
# minúscula, sin acentos.
MESES_KEY = {m: MESES_LABEL[m].lower() for m in MESES}


def _resumen_de(filas: list) -> dict:
    total = len(filas)
    completado = sum(1 for f in filas if f["estado"] == "completado")
    en_proceso = sum(1 for f in filas if f["estado"] == "en_proceso")
    sin_asignar = sum(1 for f in filas if f["estado"] == "sin_asignar")
    caja = sum(1 for f in filas if (f.get("caja_banco") or "") == "Caja")
    banco = sum(1 for f in filas if (f.get("caja_banco") or "") == "Banco")

    def pct(n):
        return round(n / total * 100) if total else 0

    # Totales por mes (17-09-2026, pedido por el usuario junto con las
    # tarjetas de resumen): cuántas empresas tienen a alguien asignado en
    # cada uno de los 6 meses, calculado en vivo igual que "estado".
    meses = [
        {"key": MESES_KEY[m], "label": MESES_LABEL[m], "count": sum(1 for f in filas if (f.get(m) or "").strip())}
        for m in MESES
    ]

    return {
        # "completado"/"completado_pct" ya no se muestran en la tarjeta KPI
        # de la página (22-09-2026, pedido por el usuario: quitarla) pero
        # siguen aquí porque `pdf_informe.py` reutiliza este mismo resumen
        # por analista para la fila "Completado" del informe PDF.
        "total": total, "completado": completado, "en_proceso": en_proceso, "sin_asignar": sin_asignar,
        "completado_pct": pct(completado), "en_proceso_pct": pct(en_proceso), "sin_asignar_pct": pct(sin_asignar),
        "caja": caja, "banco": banco,
        "meses": meses,
    }


def _leer_filas_formulario(form) -> list:
    numeros = form.getlist("p_numero")
    empresas = form.getlist("p_empresa")
    analistas = form.getlist("p_analista")
    prioridades = form.getlist("p_prioridad")
    caja_bancos = form.getlist("p_caja_banco")
    columnas_texto = {c: form.getlist(f"p_{c}") for c in COLUMNAS_TEXTO}

    filas = []
    for i in range(len(empresas)):
        empresa = (empresas[i] or "").strip()
        if not empresa:
            continue  # fila vacía (ej. la última agregada y no llenada) — se descarta
        numero_raw = (numeros[i] if i < len(numeros) else "").strip()
        prioridad_raw = (prioridades[i] if i < len(prioridades) else "").strip()
        fila = {
            "numero": int(numero_raw) if numero_raw.isdigit() else None,
            "empresa": empresa,
            "analista": (analistas[i] if i < len(analistas) else "").strip(),
            "prioridad": int(prioridad_raw) if prioridad_raw in ("1", "2", "3") else None,
            "caja_banco": (caja_bancos[i] if i < len(caja_bancos) else "").strip(),
        }
        for columna, valores in columnas_texto.items():
            fila[columna] = (valores[i] if i < len(valores) else "").strip()
        filas.append(fila)
    return filas


@planificacion_at2027_bp.route("/", methods=["GET"])
@pagina_required("planificacion_at2027.index")
def index():
    filas = planificacion_at2027_repo.listar_todos()
    for f in filas:
        f["estado"] = _estado_de_fila(f)
    return render_template("planificacion_at2027/index.html", filas=filas, resumen=_resumen_de(filas))


@planificacion_at2027_bp.route("/exportar", methods=["GET"])
@pagina_required("planificacion_at2027.index")
def exportar():
    filas = planificacion_at2027_repo.listar_todos()
    wb = Workbook()
    ws = wb.active
    ws.title = "Planificación AT 2027"
    ws.append(ENCABEZADOS_EXPORTAR)
    for f in filas:
        ws.append([f.get(c) for c in COLUMNAS_EXPORTAR])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer, as_attachment=True, download_name="planificacion_at2027.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@planificacion_at2027_bp.route("/informe", methods=["POST"])
@pagina_required("planificacion_at2027.index")
def informe():
    """Informe PDF por analista (18-09-2026, pedido por el usuario): uno
    o varios a la vez, cada uno con su propio resumen (mismo cálculo que
    las tarjetas KPI, pero acotado a SUS empresas) y el detalle de sus
    empresas — ver `app/planificacion_at2027/pdf_informe.py`."""
    analistas_elegidos = [a.strip() for a in request.form.getlist("analistas") if a.strip()]
    if not analistas_elegidos:
        flash("Selecciona al menos un analista para el informe.", "error")
        return redirect(url_for("planificacion_at2027.index"))

    filas = planificacion_at2027_repo.listar_todos()
    for f in filas:
        f["estado"] = _estado_de_fila(f)

    secciones = []
    for analista in analistas_elegidos:
        filas_analista = [f for f in filas if (f.get("analista") or "").strip() == analista]
        secciones.append({"analista": analista, "filas": filas_analista, "resumen": _resumen_de(filas_analista)})

    pdf = generar_pdf_informe(secciones)
    return send_file(
        pdf, as_attachment=True, download_name="informe_planificacion_at2027.pdf", mimetype="application/pdf",
    )


@planificacion_at2027_bp.route("/guardar", methods=["POST"])
@pagina_required("planificacion_at2027.index")
def guardar():
    filas = _leer_filas_formulario(request.form)
    try:
        planificacion_at2027_repo.guardar_todos(filas)
    except Exception as exc:  # noqa: BLE001
        from flask import current_app
        current_app.logger.warning("No se pudo guardar planificacion_at2027: %s", exc)
        flash(
            "No se pudo guardar: falta crear la tabla 'planificacion_at2027' en Supabase "
            "(ejecuta migration/014_planificacion_at2027.sql una vez en el SQL Editor) o "
            "hubo un problema de conexión.",
            "error",
        )
        return redirect(url_for("planificacion_at2027.index"))
    flash("Planificación guardada.", "success")
    return redirect(url_for("planificacion_at2027.index"))
