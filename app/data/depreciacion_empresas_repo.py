"""
CRUD de la tabla `depreciacion_empresas` en Supabase: registro de empresas
propio de la pestaña "Depreciación" (independiente de `sii_empresas`, sin
clave del SII ni nada sensible — solo agrupa los activos fijos de cada
empresa). Mismo patrón que `usuarios_repo.py`: siempre contra el cliente
service-role (ver `app/extensions.py`).
"""

from typing import List, Optional

from app.extensions import get_supabase

TABLE = "depreciacion_empresas"


def listar_empresas() -> List[dict]:
    resp = get_supabase().table(TABLE).select("*").order("nombre").execute()
    return resp.data or []


def obtener_empresa(empresa_id: str) -> Optional[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("id", empresa_id).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def crear_empresa(rut: str, nombre: str) -> dict:
    row = {"rut": (rut or "").strip() or None, "nombre": nombre.strip()}
    resp = get_supabase().table(TABLE).insert(row).execute()
    return resp.data[0]


def eliminar_empresa(empresa_id: str) -> None:
    get_supabase().table(TABLE).delete().eq("id", empresa_id).execute()
