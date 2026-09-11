"""
CRUD de la tabla `depreciacion_grupos_contables` en Supabase: las 3
cuentas de depreciación (Gasto / Acumulada / Corrección Monetaria) de un
"grupo contable" — el código del plan de cuentas del activo fijo en sí
(ej. "1204-01 VEHICULOS"), que agrupa todos los activos de esa clase. Se
configuran UNA vez por grupo; cada activo solo elige a cuál pertenece
(`depreciacion_activos.grupo_contable_codigo`, ver
`depreciacion_activos_repo.py`) — así 10 vehículos comparten las mismas
3 cuentas sin tener que elegirlas 10 veces.
"""

from typing import List, Optional

from app.extensions import get_supabase

TABLE = "depreciacion_grupos_contables"


def listar() -> List[dict]:
    resp = get_supabase().table(TABLE).select("*").order("codigo").execute()
    return resp.data or []


def obtener(codigo: str) -> Optional[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("codigo", codigo).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def guardar(codigo: str, cuenta_gasto_codigo: str, cuenta_acumulada_codigo: str, cuenta_correccion_codigo: Optional[str]) -> dict:
    """Crea el grupo si no existía, o actualiza sus 3 cuentas si ya
    existía (mismo código = mismo grupo, sin duplicar filas)."""
    sb = get_supabase()
    row = {
        "cuenta_gasto_codigo": cuenta_gasto_codigo,
        "cuenta_acumulada_codigo": cuenta_acumulada_codigo,
        "cuenta_correccion_codigo": cuenta_correccion_codigo,
    }
    if obtener(codigo):
        sb.table(TABLE).update(row).eq("codigo", codigo).execute()
    else:
        sb.table(TABLE).insert({**row, "codigo": codigo}).execute()
    return obtener(codigo)


def eliminar(codigo: str) -> None:
    get_supabase().table(TABLE).delete().eq("codigo", codigo).execute()
