"""
CRUD de la tabla `depreciacion_periodos` en Supabase: el kardex editable
de un activo (una fila por período — ver
`migration/007_depreciacion_periodos.sql` para el detalle). Mismo patrón
de "reemplazar todo" que `depreciacion_categorias_repo.guardar_todas` —
la ficha del activo siempre manda la lista completa de filas (con las que
se agregaron/quitaron/editaron en el formulario), así no hay que llevar
un diff fila por fila.
"""

from typing import List

from app.extensions import get_supabase

TABLE = "depreciacion_periodos"


def listar_por_activo(activo_id: str) -> List[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("activo_id", activo_id).order("fecha").execute()
    return resp.data or []


def guardar_todos(activo_id: str, filas: List[dict]) -> None:
    """Reemplaza todas las filas del kardex de `activo_id`. Cada fila de
    `filas`: {"fecha": "YYYY-MM-DD", "meses_utilizados": int, "factor_ccmm": float}."""
    sb = get_supabase()
    sb.table(TABLE).delete().eq("activo_id", activo_id).execute()
    payload = [
        {
            "activo_id": activo_id,
            "fecha": f["fecha"],
            "meses_utilizados": int(f["meses_utilizados"]),
            "factor_ccmm": float(f.get("factor_ccmm") or 1),
        }
        for f in filas
        if f.get("fecha") and f.get("meses_utilizados")
    ]
    if payload:
        sb.table(TABLE).insert(payload).execute()
