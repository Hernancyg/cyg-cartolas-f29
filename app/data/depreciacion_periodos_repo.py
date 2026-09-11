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


def agregar_periodo(activo_id: str, fecha: str, meses_utilizados: int, factor_ccmm: float = 1.0) -> dict:
    """Inserta UNA fila nueva sin tocar las que ya existen — a diferencia
    de `guardar_todos` (que reemplaza todo el kardex desde el formulario
    de edición manual), esto lo usa "Generar asiento" para extender solo
    el kardex de un activo hasta el mes que se está gestionando (ver
    `app/depreciacion/routes.py:_extender_periodos`)."""
    row = {"activo_id": activo_id, "fecha": fecha, "meses_utilizados": int(meses_utilizados), "factor_ccmm": float(factor_ccmm)}
    resp = get_supabase().table(TABLE).insert(row).execute()
    return resp.data[0]


def actualizar_periodo(periodo_id: str, fecha: str, meses_utilizados: int) -> dict:
    """Cambia la fecha y los meses de UNA fila ya existente, sin tocar su
    factor_ccmm — lo usa "Generar asiento" para sumarle meses a la última
    fila del kardex cuando cae en el mismo año y todavía no se asentó, en
    vez de crear una fila nueva (`app/depreciacion/routes.py:
    _extender_periodos`)."""
    row = {"fecha": fecha, "meses_utilizados": int(meses_utilizados)}
    resp = get_supabase().table(TABLE).update(row).eq("id", periodo_id).execute()
    return resp.data[0]
