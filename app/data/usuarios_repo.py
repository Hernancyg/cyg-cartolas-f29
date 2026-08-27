"""
CRUD de la tabla `usuarios` en Supabase — reemplaza la lectura/escritura de
`usuarios.json` que hacía `usuarios.py` en la app de Streamlit. Siempre usa
el cliente con la service-role key (ver app/extensions.py), nunca expuesto
al navegador.
"""

from typing import List, Optional

from app.auth.security import hash_password
from app.extensions import get_supabase

ROLES = ["admin", "trabajador"]

TABLE = "usuarios"


def listar_usuarios() -> List[dict]:
    resp = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .order("nombre")
        .execute()
    )
    return resp.data or []


def buscar_usuario(nombre_usuario: str) -> Optional[dict]:
    objetivo = str(nombre_usuario).strip()
    if not objetivo:
        return None
    resp = (
        get_supabase()
        .table(TABLE)
        .select("*")
        .ilike("usuario", objetivo)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None


def crear_usuario(usuario: str, nombre: str, rol: str, password: str) -> dict:
    salt, hash_val = hash_password(password)
    row = {
        "usuario": usuario.strip(),
        "nombre": nombre.strip(),
        "rol": rol,
        "salt": salt,
        "hash": hash_val,
        "activo": True,
    }
    resp = get_supabase().table(TABLE).insert(row).execute()
    return resp.data[0]


def actualizar_datos(usuario_id: str, nombre: str, rol: str, activo: bool) -> None:
    get_supabase().table(TABLE).update({
        "nombre": nombre.strip(),
        "rol": rol,
        "activo": activo,
    }).eq("id", usuario_id).execute()


def restablecer_password(usuario_id: str, password_nuevo: str) -> None:
    salt, hash_val = hash_password(password_nuevo)
    get_supabase().table(TABLE).update({
        "salt": salt,
        "hash": hash_val,
    }).eq("id", usuario_id).execute()


def eliminar_usuario(usuario_id: str) -> None:
    get_supabase().table(TABLE).delete().eq("id", usuario_id).execute()
