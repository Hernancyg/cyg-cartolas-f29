"""
CRUD de la tabla `depreciacion_bajas` en Supabase: el registro histórico
de cada vez que se dio de baja un activo (pérdida total o venta), con el
valor libro y el resultado (utilidad/pérdida) calculados al momento — ver
`app/depreciacion/comprobantes_baja.py` para el armado del asiento
contable que genera cada baja.
"""

from typing import List, Optional

from app.extensions import get_supabase

TABLE = "depreciacion_bajas"


def crear(
    activo_id: str, fecha_baja: str, tipo_baja: str, modalidad_venta: Optional[str],
    monto_venta: float, valor_actualizado: float, deprec_acumulada: float, valor_libro: float, resultado: float,
) -> dict:
    row = {
        "activo_id": activo_id,
        "fecha_baja": fecha_baja,
        "tipo_baja": tipo_baja,
        "modalidad_venta": modalidad_venta,
        "monto_venta": monto_venta,
        "valor_actualizado": valor_actualizado,
        "deprec_acumulada": deprec_acumulada,
        "valor_libro": valor_libro,
        "resultado": resultado,
    }
    resp = get_supabase().table(TABLE).insert(row).execute()
    return resp.data[0]


def listar_por_activo(activo_id: str) -> List[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("activo_id", activo_id).order("fecha_baja").execute()
    return resp.data or []
