"""
CRUD de la tabla `depreciacion_config_baja` en Supabase: las 3 cuentas de
resultado que hace falta configurar UNA vez por empresa para poder armar
el asiento de "dar de baja" un activo (Caja/Cliente por la venta, Pérdida
en Baja de Activo Fijo, Utilidad en Venta de Activo Fijo) — las cuentas
de Activo Fijo y Depreciación Acumulada se sacan del Grupo Contable del
activo mismo (ver `depreciacion_grupos_contables_repo.py`), no hace falta
repetirlas acá.
"""

from typing import Optional

from app.extensions import get_supabase

TABLE = "depreciacion_config_baja"


def obtener(empresa_id: str) -> Optional[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("empresa_id", empresa_id).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def guardar(empresa_id: str, cuenta_caja_cliente_codigo: Optional[str], cuenta_perdida_codigo: Optional[str], cuenta_utilidad_codigo: Optional[str]) -> dict:
    sb = get_supabase()
    row = {
        "cuenta_caja_cliente_codigo": cuenta_caja_cliente_codigo,
        "cuenta_perdida_codigo": cuenta_perdida_codigo,
        "cuenta_utilidad_codigo": cuenta_utilidad_codigo,
    }
    if obtener(empresa_id):
        sb.table(TABLE).update(row).eq("empresa_id", empresa_id).execute()
    else:
        sb.table(TABLE).insert({**row, "empresa_id": empresa_id}).execute()
    return obtener(empresa_id)
