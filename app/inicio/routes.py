"""
"Inicio" (rediseño 24-09-2026): pantalla de entrada después de iniciar
sesión. Muestra accesos directos a las pestañas que este usuario puede ver
y los indicadores del día (los mismos de la pestaña "Indicadores", con su
caché). No tiene datos propios ni guarda nada.
"""

from flask import Blueprint, render_template, session

from app.auth.decorators import login_required
from app.nav import paginas_con_visibilidad

inicio_bp = Blueprint("inicio", __name__, url_prefix="/inicio")

# Qué indicadores se muestran en el resumen (el resto sigue en su pestaña).
_RESUMEN = ["uf", "dolar", "utm", "uta"]


@inicio_bp.route("/", methods=["GET"])
@login_required
def index():
    usuario = session.get("usuario") or {}
    es_admin = usuario.get("rol") == "admin"
    accesos = [p for p in paginas_con_visibilidad()
               if (not p["admin_only"] or es_admin) and p["endpoint"] != "admin.cuentas"]

    indicadores, error = [], None
    try:
        from app.indicadores.routes import INDICADORES_MOSTRADOS, _fetch_indicadores, _formatear
        data, error = _fetch_indicadores()
        if data:
            for item in INDICADORES_MOSTRADOS:
                info = data.get(item["codigo"])
                if item["codigo"] in _RESUMEN and info:
                    indicadores.append({**item, "valor_fmt": _formatear(info.get("valor"), item["unidad"])})
    except Exception as exc:  # noqa: BLE001 — el resumen nunca debe romper la pantalla de inicio
        error = f"No se pudieron obtener los indicadores: {exc}"

    nombre = (usuario.get("nombre") or usuario.get("usuario") or "").split(" ")[0]
    return render_template("inicio.html", accesos=accesos, indicadores=indicadores,
                           error=error, nombre=nombre)
