"""
Cliente mínimo de Microsoft Graph para la pestaña "Reuniones" (solo
admin). Usa el flujo "client credentials" de OAuth2 (una app de
Azure/Microsoft Entra ID con permiso de APLICACIÓN Calendars.Read,
consentido por un administrador del tenant de Microsoft 365) — no hay
login interactivo de por medio: la app entra siempre como sí misma y
lee el calendario de un buzón fijo (`MS_USER_UPN`), configurado por el
usuario. No requiere ninguna librería nueva aparte de `requests`, ya
usada por "Indicadores".

Todas las funciones devuelven `(dato, error)`: si algo falla (credenciales
mal puestas, token vencido en Azure, sin red, etc.) se devuelve
`(None, "mensaje legible")` en vez de levantar una excepción — la ruta
Flask decide qué mostrar en pantalla.
"""

import time

import requests

_TOKEN_CACHE = {"access_token": None, "expires_at": 0}


def _config_incompleta(cfg):
    return not all(cfg.get(k) for k in ("MS_CLIENT_ID", "MS_CLIENT_SECRET", "MS_TENANT_ID", "MS_USER_UPN"))


def _obtener_token(cfg):
    """Token de aplicación (client_credentials), cacheado en memoria hasta
    ~5 minutos antes de vencer."""
    ahora = time.time()
    if _TOKEN_CACHE["access_token"] and ahora < _TOKEN_CACHE["expires_at"] - 300:
        return _TOKEN_CACHE["access_token"], None

    url = f"https://login.microsoftonline.com/{cfg['MS_TENANT_ID']}/oauth2/v2.0/token"
    payload = {
        "client_id": cfg["MS_CLIENT_ID"],
        "client_secret": cfg["MS_CLIENT_SECRET"],
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    try:
        resp = requests.post(url, data=payload, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        if not token:
            return None, "Azure no devolvió un token de acceso (revisa client_id/client_secret/tenant_id)."
        _TOKEN_CACHE["access_token"] = token
        _TOKEN_CACHE["expires_at"] = ahora + int(data.get("expires_in", 3600))
        return token, None
    except requests.HTTPError as exc:
        detalle = ""
        try:
            detalle = exc.response.json().get("error_description", "")[:200]
        except Exception:  # noqa: BLE001
            pass
        return None, f"Azure rechazó la autenticación ({exc.response.status_code}). {detalle}"
    except Exception as exc:  # noqa: BLE001
        return None, f"No se pudo contactar a Microsoft (login.microsoftonline.com): {exc}"


def obtener_eventos_de_hoy(cfg, tz_iana="America/Santiago"):
    """Devuelve (lista_de_eventos, error). Cada evento trae: subject,
    start_iso, end_iso, organizer, is_online_meeting, teams_join_url,
    body_content (para extraer el link de Zoom en la ruta)."""
    if _config_incompleta(cfg):
        return None, "config_pendiente"

    token, error = _obtener_token(cfg)
    if error:
        return None, error

    import datetime
    hoy = datetime.date.today()
    inicio = f"{hoy.isoformat()}T00:00:00"
    fin = f"{hoy.isoformat()}T23:59:59"

    url = (
        f"https://graph.microsoft.com/v1.0/users/{cfg['MS_USER_UPN']}/calendarView"
        f"?startDateTime={inicio}&endDateTime={fin}&$orderby=start/dateTime"
        f"&$select=subject,start,end,organizer,isOnlineMeeting,onlineMeeting,bodyPreview,body"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": f'outlook.timezone="{tz_iana}"',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("value", []), None
    except requests.HTTPError as exc:
        detalle = ""
        try:
            detalle = exc.response.json().get("error", {}).get("message", "")[:200]
        except Exception:  # noqa: BLE001
            pass
        return None, f"Microsoft Graph devolvió un error ({exc.response.status_code}). {detalle}"
    except Exception as exc:  # noqa: BLE001
        return None, f"No se pudo contactar a Microsoft Graph: {exc}"
