"""
CRUD de la tabla `usuarios` en Supabase — reemplaza la lectura/escritura de
`usuarios.json` que hacía `usuarios.py` en la app de Streamlit. Siempre usa
el cliente con la service-role key (ver app/extensions.py), nunca expuesto
al navegador.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

from app.auth.security import hash_password
from app.extensions import get_supabase

ROLES = ["admin", "trabajador"]

# Temas visuales asignables por usuario (25-09-2026). "" = el de siempre.
# El CSS de cada tema vive en static/css/styles.css bajo
# :root[data-tema="<clave>"]; base.html pone ese atributo en <html>.
TEMAS = {"": "Predeterminado", "rosa": "Rosa"}

logger = logging.getLogger(__name__)
_CACHE_TEMA_SEGUNDOS = 60
_cache_tema: Dict[str, Tuple[float, str]] = {}

TABLE = "usuarios"


def listar_usuarios() -> List[dict]:
    resp = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .order("nombre")
        .execute()
    )
    return resp.data or []


def buscar_usuario(nombre_usuario: str) -> Optional[dict]:
    objetivo = str(nombre_usuario).strip()
    if not objetivo:
        return None
    resp = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .ilike("usuario", objetivo)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None


def crear_usuario(usuario: str, nombre: str, rol: str, password: str) -> dict:
    salt, hash_val = hash_password(password)
    row = {
        "usuario": usuario.strip(),
        "nombre": nombre.strip(),
        "rol": rol,
        "salt": salt,
        "hash": hash_val,
        "activo": True,
    }
    resp = get_supabase().table(TABLE).insert(row).execute()
    return resp.data[0]


def actualizar_datos(usuario_id: str, nombre: str, rol: str, activo: bool) -> None:
    get_supabase().table(TABLE).update({
        "nombre": nombre.strip(),
        "rol": rol,
        "activo": activo,
    }).eq("id", usuario_id).execute()


def restablecer_password(usuario_id: str, password_nuevo: str) -> None:
    salt, hash_val = hash_password(password_nuevo)
    get_supabase().table(TABLE).update({
        "salt": salt,
        "hash": hash_val,
    }).eq("id", usuario_id).execute()


def eliminar_usuario(usuario_id: str) -> None:
    get_supabase().table(TABLE).delete().eq("id", usuario_id).execute()


def actualizar_tema(usuario_id: str, tema: str) -> None:
    """Lanza si la columna `tema` todavía no existe (falta
    migration/016_tema_usuario.sql): el llamador avisa al admin."""
    tema = tema if tema in TEMAS else ""
    get_supabase().table(TABLE).update({"tema": tema or None}).eq("id", usuario_id).execute()
    _cache_tema.pop(usuario_id, None)


def tema_de(usuario_id: Optional[str]) -> str:
    """Tema del usuario para pintar cada página. Caché corta en memoria
    (se lee en cada request) y nunca lanza: ante cualquier problema (sin
    migración, Supabase caído) se usa el tema de siempre."""
    if not usuario_id:
        return ""
    ahora = time.monotonic()
    guardado = _cache_tema.get(usuario_id)
    if guardado and ahora - guardado[0] < _CACHE_TEMA_SEGUNDOS:
        return guardado[1]
    tema = ""
    try:
        resp = get_supabase().table(TABLE).select("*").eq("id", usuario_id).limit(1).execute()
        filas = resp.data or []
        tema = (filas[0].get("tema") or "") if filas else ""
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo leer el tema del usuario %s", usuario_id)
    tema = tema if tema in TEMAS else ""
    _cache_tema[usuario_id] = (ahora, tema)
    return tema
