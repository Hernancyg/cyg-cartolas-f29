"""
CRUD de la tabla `visibilidad_pestanas` en Supabase — guarda, por pestaña
del menú, si el admin la dejó visible para todos los usuarios o solo para
administradores (panel Administrador → Pestañas, ver `app/admin/routes.py`
y `app/templates/admin/pestanas.html`).

Solo se guarda una fila por pestaña que el admin haya tocado; las que
nunca se guarden (o la tabla completa, si Supabase todavía no tiene esta
tabla) usan el valor por defecto de `app/nav.py:PAGINAS` — así una
sesión nueva, o un problema pasajero con Supabase, nunca deja una pestaña
sensible (Reuniones, Conciliación) abierta a todos por accidente ni
bloquea el menú.

Cacheado en memoria por poco tiempo (mismo patrón que
`app/indicadores/routes.py`) para no consultar Supabase en cada request
que dibuja el menú o entra a una página, y para seguir funcionando con el
último valor bueno conocido si Supabase está lento o caído.
"""

import time
from typing import Dict

from app.extensions import get_supabase

TABLE = "visibilidad_pestanas"
_CACHE_TTL_SEGUNDOS = 30

_cache: Dict[str, bool] = {}
_cache_at = 0.0


def obtener_mapa() -> Dict[str, bool]:
    """{endpoint: admin_only} solo para las pestañas que el admin ya
    guardó explícitamente al menos una vez. Nunca lanza — si Supabase
    falla, devuelve el último valor bueno (o {} si todavía no hay
    ninguno), para que el llamador siga con los valores por defecto de
    `PAGINAS` en vez de romper el menú o el control de acceso."""
    global _cache, _cache_at
    ahora = time.monotonic()
    if _cache_at and (ahora - _cache_at) < _CACHE_TTL_SEGUNDOS:
        return _cache
    try:
        resp = get_supabase().table(TABLE).select("endpoint, admin_only").execute()
        _cache = {fila["endpoint"]: bool(fila["admin_only"]) for fila in (resp.data or [])}
        _cache_at = ahora
    except Exception:
        pass
    return _cache


def guardar_todas(mapa: Dict[str, bool]) -> None:
    """Reemplaza el contenido completo de la tabla (mismo patrón que
    `cuentas_config_repo.guardar_todas`: borra todo y reinserta) e
    invalida el caché en memoria de este proceso para que el cambio se
    vea de inmediato aquí mismo (otros workers de gunicorn, si hay más de
    uno, lo verán en máximo `_CACHE_TTL_SEGUNDOS` segundos)."""
    global _cache, _cache_at
    sb = get_supabase()
    sb.table(TABLE).delete().neq("endpoint", "__never__").execute()
    filas = [{"endpoint": ep, "admin_only": bool(v)} for ep, v in mapa.items()]
    if filas:
        sb.table(TABLE).insert(filas).execute()
    _cache = dict(mapa)
    _cache_at = time.monotonic()
