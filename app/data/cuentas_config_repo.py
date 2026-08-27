"""
CRUD de la tabla `cuentas_config` en Supabase — reemplaza la lectura/
escritura de `cuentas_config.json` que hacía `config_manager.py` en la app
de Streamlit. `app/parsers/config_manager.py` (el módulo que SÍ importa
`f29_parser.py` sin cambios) llama a las funciones de este archivo.
"""

from typing import List

from app.extensions import get_supabase

TABLE = "cuentas_config"


def listar() -> List[dict]:
    resp = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .order("orden")
        .execute()
    )
    return resp.data or []


def guardar_todas(filas: List[dict]) -> None:
    """Reemplaza el contenido completo de la tabla por `filas` (mismo
    comportamiento que sobreescribir cuentas_config.json con
    st.data_editor(num_rows='dynamic') en la app de Streamlit: se borra
    todo y se reinserta, para soportar filas agregadas/eliminadas)."""
    sb = get_supabase()
    sb.table(TABLE).delete().neq("codigo_f29", "__never__").execute()
    if filas:
        for idx, fila in enumerate(filas):
            fila["orden"] = idx
        sb.table(TABLE).insert(filas).execute()
