"""
CRUD de la tabla `depreciacion_asientos` en Supabase: la "memoria" de qué
períodos de qué activo ya se incluyeron en un comprobante contable
generado ("Depreciación → Generar asiento"). Se guarda por
(activo_id, fecha) — no por el id de la fila del kardex
(`depreciacion_periodos`), porque ese id cambia cada vez que se edita y
guarda el kardex (`depreciacion_periodos_repo.guardar_todos` borra todo
y reinserta) — la fecha del período, en cambio, es estable.
"""

from typing import List, Optional

from app.extensions import get_supabase

TABLE = "depreciacion_asientos"


def listar_por_activo(activo_id: str) -> List[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("activo_id", activo_id).order("fecha").execute()
    return resp.data or []


def fechas_ya_generadas(activo_id: str) -> set:
    return {a["fecha"] for a in listar_por_activo(activo_id)}


def crear_muchos(filas: List[dict]) -> None:
    """`filas`: lista de {"activo_id", "fecha", "monto_ejercicio", "monto_correccion"}."""
    if filas:
        get_supabase().table(TABLE).insert(filas).execute()


def eliminar(asiento_id: str) -> None:
    get_supabase().table(TABLE).delete().eq("id", asiento_id).execute()


def eliminar_por_activo_y_fecha(activo_id: str, fecha: str) -> None:
    """Para "deshacer" un asiento puntual (ej. si hay que corregir un
    período ya asentado) sin necesitar conocer su id."""
    get_supabase().table(TABLE).delete().eq("activo_id", activo_id).eq("fecha", fecha).execute()


def obtener_asiento(asiento_id: str) -> Optional[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("id", asiento_id).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None
