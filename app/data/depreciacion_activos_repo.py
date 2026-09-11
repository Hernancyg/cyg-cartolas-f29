"""
CRUD de la tabla `depreciacion_activos` en Supabase: los bienes del activo
fijo de cada empresa (ver `depreciacion_empresas_repo.py`), usados por
`app/depreciacion/calculo.py` para armar la tabla de depreciación mensual.

`activo` (booleano) permite dar de baja un bien sin borrarlo — así la
tabla de depreciación de meses PASADOS sigue mostrándolo (el bien existió
y se depreció durante esos meses), pero deja de aparecer para agregarle
más meses hacia adelante. `eliminar_activo` sí borra de verdad, para el
caso de un bien cargado por error.
"""

from typing import List, Optional

from app.extensions import get_supabase

TABLE = "depreciacion_activos"


def listar_por_empresa(empresa_id: str, solo_activos: bool = False) -> List[dict]:
    query = get_supabase().table(TABLE).select("*").eq("empresa_id", empresa_id)
    if solo_activos:
        query = query.eq("activo", True)
    resp = query.order("fecha_adquisicion").execute()
    return resp.data or []


def obtener_activo(activo_id: str) -> Optional[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("id", activo_id).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def crear_activo(
    empresa_id: str, categoria_id: Optional[str], nombre_activo: str,
    fecha_adquisicion: str, valor_adquisicion: float, vida_util_anios: int,
) -> dict:
    row = {
        "empresa_id": empresa_id,
        "categoria_id": categoria_id,
        "nombre_activo": nombre_activo.strip(),
        "fecha_adquisicion": fecha_adquisicion,
        "valor_adquisicion": valor_adquisicion,
        "vida_util_anios": vida_util_anios,
        "activo": True,
    }
    resp = get_supabase().table(TABLE).insert(row).execute()
    return resp.data[0]


def dar_de_baja(activo_id: str) -> None:
    get_supabase().table(TABLE).update({"activo": False}).eq("id", activo_id).execute()


def eliminar_activo(activo_id: str) -> None:
    get_supabase().table(TABLE).delete().eq("id", activo_id).execute()
