"""
"Planificación AT 2027": tabla editable de seguimiento de empresas
(analista asignado por mes, prioridad, frecuencia de actualización del
balance, etc.) — reemplaza el Excel manual que llevaba el usuario
(17-09-2026). Se edita fila por fila en pantalla (mismo patrón
"clonar fila + guardar todo el formulario" que `depreciacion/categorias.
html` / `admin/tipos_documento.html`, ver `app/static/js/editable_rows.
js`), y también se puede recargar completa subiendo un Excel desde
Administrador → Planificación AT 2027 (ver `app/admin/routes.py`) — ambos
caminos terminan en `planificacion_at2027_repo.guardar_todos`.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.auth.decorators import pagina_required
from app.data import planificacion_at2027_repo

planificacion_at2027_bp = Blueprint(
    "planificacion_at2027", __name__, url_prefix="/planificacion_at2027",
)

# Columnas de texto libre en el orden en que se muestran (numero/empresa/
# analista/prioridad/caja_banco se manejan aparte porque tienen su propio
# tipo o su propio <select>).
COLUMNAS_TEXTO = [
    "mes_septiembre", "mes_octubre", "mes_noviembre", "mes_diciembre", "mes_enero", "mes_febrero",
    "actualizacion_balance", "reunion_cat1_1", "reunion_cat2", "reunion_cat3", "reunion_cat1_2",
    "grupo", "estado_balance_ultimo_mes",
]


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
    return render_template("planificacion_at2027/index.html", filas=planificacion_at2027_repo.listar_todos())


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
