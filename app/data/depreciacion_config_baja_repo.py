"""
CRUD de la tabla `depreciacion_config_baja` en Supabase: las 4 cuentas de
resultado que hace falta configurar UNA vez por empresa para poder armar
el asiento de "dar de baja" un activo — Caja/Cuentas por Cobrar y
Pérdida/Utilidad (para pérdida total y venta por contrato de
compraventa), Costo Venta Activo Fijo (para venta CON FACTURA, que no
usa las otras 3 — ver `app/depreciacion/comprobantes_baja.py` para el
porqué). Las cuentas de Activo Fijo y Depreciación Acumulada se sacan del
Grupo Contable del activo mismo (ver `depreciacion_grupos_contables_
repo.py`), no hace falta repetirlas acá.
"""

from typing import Optional

from app.extensions import get_supabase

TABLE = "depreciacion_config_baja"


def obtener(empresa_id: str) -> Optional[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("empresa_id", empresa_id).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def guardar(
    empresa_id: str, cuenta_caja_cliente_codigo: Optional[str], cuenta_perdida_codigo: Optional[str],
    cuenta_utilidad_codigo: Optional[str], cuenta_costo_venta_codigo: Optional[str],
) -> dict:
    sb = get_supabase()
    row = {
        "cuenta_caja_cliente_codigo": cuenta_caja_cliente_codigo,
        "cuenta_perdida_codigo": cuenta_perdida_codigo,
        "cuenta_utilidad_codigo": cuenta_utilidad_codigo,
        "cuenta_costo_venta_codigo": cuenta_costo_venta_codigo,
    }
    if obtener(empresa_id):
        sb.table(TABLE).update(row).eq("empresa_id", empresa_id).execute()
    else:
        sb.table(TABLE).insert({**row, "empresa_id": empresa_id}).execute()
    return obtener(empresa_id)
