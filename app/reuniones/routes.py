"""
"Reuniones": pestaña nueva, solo para el rol admin, que muestra las
reuniones de hoy tomadas directo de Outlook (Microsoft Graph API) —
conectada de verdad, a diferencia del mockup anterior que solo simulaba
los datos. Reutiliza el diseño ya validado con el usuario (alertas
emergentes 15 minutos antes de cada reunión, y el link de Zoom con botón
"Copiar" 5 minutos antes), ahora con datos reales.

Requiere que el usuario haya creado una app en Azure/Microsoft Entra ID
con permiso de aplicación `Calendars.Read` (consentido por un admin del
tenant) y haya configurado las variables de entorno MS_CLIENT_ID,
MS_CLIENT_SECRET, MS_TENANT_ID y MS_USER_UPN en Render. Si faltan, la
página muestra instrucciones en vez de romperse.
"""

import re

from flask import Blueprint, current_app, render_template

from app.auth.decorators import pagina_required
from app.reuniones.graph_client import obtener_eventos_de_hoy

reuniones_bp = Blueprint("reuniones", __name__, url_prefix="/reuniones")

ZOOM_RE = re.compile(r"https?://[a-zA-Z0-9.-]*zoom\.us/j/\S+?(?=[\"'<\s])", re.IGNORECASE)


def _normalizar_datetime(valor):
    """Graph devuelve 'YYYY-MM-DDTHH:MM:SS.fffffff' (7 decimales) — se
    recorta a milisegundos para que `new Date(...)` en el navegador lo
    parsee sin problemas en cualquier browser."""
    if not valor:
        return None
    if "." in valor:
        base, frac = valor.split(".", 1)
        return f"{base}.{frac[:3]}"
    return valor


def _extraer_zoom(evento):
    body = (evento.get("body") or {}).get("content") or evento.get("bodyPreview") or ""
    m = ZOOM_RE.search(body + " ")  # espacio final para que el lookahead siempre calce
    if m:
        return m.group(0).rstrip("\"'<")
    return None


@reuniones_bp.route("/", methods=["GET"])
@pagina_required("reuniones.index")
def index():
    cfg = current_app.config
    eventos_raw, error = obtener_eventos_de_hoy(cfg)

    if error == "config_pendiente":
        return render_template("reuniones.html", config_pendiente=True, reuniones=[], error=None)

    if error:
        return render_template("reuniones.html", config_pendiente=False, reuniones=[], error=error)

    reuniones = []
    for ev in (eventos_raw or []):
        online_meeting = ev.get("onlineMeeting") or {}
        teams_url = online_meeting.get("joinUrl")
        zoom_url = _extraer_zoom(ev)
        if teams_url:
            tipo, enlace = "teams", teams_url
        elif zoom_url:
            tipo, enlace = "zoom", zoom_url
        else:
            tipo, enlace = None, None

        reuniones.append({
            "asunto": ev.get("subject") or "(sin título)",
            "organizador": (ev.get("organizer") or {}).get("emailAddress", {}).get("name", ""),
            "inicio": _normalizar_datetime((ev.get("start") or {}).get("dateTime")),
            "fin": _normalizar_datetime((ev.get("end") or {}).get("dateTime")),
            "tipo": tipo,
            "enlace": enlace,
        })

    return render_template("reuniones.html", config_pendiente=False, reuniones=reuniones, error=None)
