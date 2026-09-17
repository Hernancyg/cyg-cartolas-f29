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
# empresa. Es un <select> con estos 6 valores exactos (ver el template).
ORDEN_AVANCE = ["Septiembre", "Octubre", "Noviembre", "Diciembre", "Enero", "Febrero"]
_ORDEN_AVANCE_LOWER = [m.lower() for m in ORDEN_AVANCE]


def _estado_de_fila(fila: dict) -> str:
    """"Sin asignar" (sin avance registrado), "Completado" (avance =
    Febrero, el último mes del ciclo) o "En proceso" (cualquier mes
    intermedio) — calculado en vivo a partir de "Actualización Balance",
    sin guardar nada nuevo en la base de datos (18-09-2026, redefinido a
    partir de cómo el usuario usa esa columna: antes se derivaba de
    cuántos de los 6 meses tenían a alguien asignado, pero eso refleja
    quién quedó a cargo, no si el balance de ese mes ya se hizo)."""
    avance = (fila.get("actualizacion_balance") or "").strip().lower()
    if not avance or avance not in _ORDEN_AVANCE_LOWER:
        return "sin_asignar"
    return "completado" if avance == _ORDEN_AVANCE_LOWER[-1] else "en_proceso"


MESES_LABEL = {
    "mes_septiembre": "Sep", "mes_octubre": "Oct", "mes_noviembre": "Nov",
    "mes_diciembre": "Dic", "mes_enero": "Ene", "mes_febrero": "Feb",
}


def _resumen_de(filas: list) -> dict:
    total = len(filas)
    completado = sum(1 for f in filas if f["estado"] == "completado")
    en_proceso = sum(1 for f in filas if f["estado"] == "en_proceso")
    sin_asignar = sum(1 for f in filas if f["estado"] == "sin_asignar")

    def pct(n):
        return round(n / total * 100) if total else 0

    # Totales por mes (17-09-2026, pedido por el usuario junto con las
    # tarjetas de resumen): cuántas empresas tienen a alguien asignado en
    # cada uno de los 6 meses, calculado en vivo igual que "estado".
    meses = [
        {"label": MESES_LABEL[m], "count": sum(1 for f in filas if (f.get(m) or "").strip())}
        for m in MESES
    ]

    return {
        "total": total, "completado": completado, "en_proceso": en_proceso, "sin_asignar": sin_asignar,
        "completado_pct": pct(completado), "en_proceso_pct": pct(en_proceso), "sin_asignar_pct": pct(sin_asignar),
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
