"""
CRUD de la tabla `planificacion_at2027` en Supabase — el Excel de
seguimiento de empresas (analista asignado, prioridad, mes a mes, etc.)
que el usuario llevaba a mano, ahora editable desde la pestaña
"Planificación AT 2027" y reemplazable de una vez con una carga masiva
por Excel desde Administrador (17-09-2026).

Mismo patrón "borrar todo e insertar de nuevo" que `tipos_documento_repo.
guardar_todos` / `depreciacion_categorias_repo.guardar_todas` — tanto el
guardado manual (tabla editable en pantalla) como la carga masiva por
Excel llaman a `guardar_todos`, confirmado con el usuario: una carga
nueva reemplaza la tabla completa, no se intenta preservar ediciones
manuales frente a una carga de Excel más reciente.

Sin caché en memoria (a diferencia de `tipos_documento_repo`/
`visibilidad_repo`/`depreciacion_categorias_repo`): esos cachean porque
son mapas de configuración leídos en casi cada request; esta es una
tabla de ~150-200 filas de datos reales, mismo criterio que
`depreciacion_activos_repo`/`sii_empresas_repo` (SELECT directo cada
vez).
"""

from typing import List, Optional

from app.extensions import get_supabase

TABLE = "planificacion_at2027"

# Cada tupla: (nombre de columna en Supabase, si es entero)
COLUMNAS = [
    ("numero", True),
    ("empresa", False),
    ("analista", False),
    ("prioridad", True),
    ("caja_banco", False),
    ("mes_septiembre", False),
    ("mes_octubre", False),
    ("mes_noviembre", False),
    ("mes_diciembre", False),
    ("mes_enero", False),
    ("mes_febrero", False),
    ("actualizacion_balance", False),
    ("reunion_cat1_1", False),
    ("reunion_cat2", False),
    ("reunion_cat3", False),
    ("reunion_cat1_2", False),
    ("grupo", False),
    ("estado_balance_ultimo_mes", False),
]


def listar_todos() -> List[dict]:
    """Lista completa, ordenada por `orden` (el orden en que se guardaron/
    cargaron las filas — no necesariamente el mismo que `numero`, que es
    solo el N° de referencia del Excel de origen)."""
    resp = get_supabase().table(TABLE).select("*").order("orden").execute()
    return resp.data or []


def obtener_por_id(fila_id: str) -> Optional[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("id", fila_id).limit(1).execute()
    filas = resp.data or []
    return filas[0] if filas else None


def guardar_todos(filas: List[dict]) -> None:
    """Reemplaza el contenido completo de la tabla. Cada fila de `filas`
    es un dict con las claves de `COLUMNAS` (las que falten se guardan
    como None) — filas sin `empresa` no deberían llegar acá (el llamador
    ya las descarta antes)."""
    sb = get_supabase()
    sb.table(TABLE).delete().neq("empresa", "__never_matches__").execute()
    payload = []
    for i, f in enumerate(filas):
        fila = {"orden": i}
        for columna, es_entero in COLUMNAS:
            valor = f.get(columna)
            if es_entero:
                fila[columna] = valor if valor is not None else None
            else:
                fila[columna] = (valor or "").strip() or None if isinstance(valor, str) else valor
        payload.append(fila)
    if payload:
        sb.table(TABLE).insert(payload).execute()
