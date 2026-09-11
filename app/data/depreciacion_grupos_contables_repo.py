"""
CRUD de la tabla `depreciacion_grupos_contables` en Supabase: las 3
cuentas de depreciación (Gasto / Acumulada / Corrección Monetaria) de un
"grupo contable" — el código del plan de cuentas del activo fijo en sí
(ej. "1204-01 VEHICULOS"), que agrupa todos los activos de esa clase. Se
configuran UNA vez por grupo POR EMPRESA (rediseño 11-09-2026: antes era
global, pero dos empresas pueden compartir un mismo código de grupo y
necesitar cuentas de depreciación distintas) — cada activo solo elige a
cuál pertenece (`depreciacion_activos.grupo_contable_codigo`, ver
`depreciacion_activos_repo.py`).
"""

from typing import List, Optional

from app.extensions import get_supabase

TABLE = "depreciacion_grupos_contables"


def listar_por_empresa(empresa_id: str) -> List[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("empresa_id", empresa_id).order("codigo").execute()
    return resp.data or []


def obtener(empresa_id: str, codigo: str) -> Optional[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("empresa_id", empresa_id).eq("codigo", codigo).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def guardar(empresa_id: str, codigo: str, cuenta_gasto_codigo: str, cuenta_acumulada_codigo: str, cuenta_correccion_codigo: Optional[str]) -> dict:
    """Crea el grupo si no existía para esta empresa, o actualiza sus 3
    cuentas si ya existía (mismo empresa_id + código = mismo grupo, sin
    duplicar filas)."""
    sb = get_supabase()
    row = {
        "cuenta_gasto_codigo": cuenta_gasto_codigo,
        "cuenta_acumulada_codigo": cuenta_acumulada_codigo,
        "cuenta_correccion_codigo": cuenta_correccion_codigo,
    }
    if obtener(empresa_id, codigo):
        sb.table(TABLE).update(row).eq("empresa_id", empresa_id).eq("codigo", codigo).execute()
    else:
        sb.table(TABLE).insert({**row, "empresa_id": empresa_id, "codigo": codigo}).execute()
    return obtener(empresa_id, codigo)


def eliminar(empresa_id: str, codigo: str) -> None:
    get_supabase().table(TABLE).delete().eq("empresa_id", empresa_id).eq("codigo", codigo).execute()
