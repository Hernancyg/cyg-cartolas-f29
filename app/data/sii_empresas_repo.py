"""
CRUD de la tabla `sii_empresas` en Supabase: empresas clientes con su RUT
y, opcionalmente, la clave del SII guardada cifrada (ver
`app/sii/crypto.py`), usada por "RCV" para llamar a SimpleAPI en su
nombre. Mismo patrón que `usuarios_repo.py`: siempre contra el cliente
service-role (ver `app/extensions.py`).
"""

from typing import List, Optional

from app.extensions import get_supabase

TABLE = "sii_empresas"


def listar_empresas() -> List[dict]:
    resp = get_supabase().table(TABLE).select("*").order("nombre").execute()
    return resp.data or []


def obtener_empresa(empresa_id: str) -> Optional[dict]:
    resp = get_supabase().table(TABLE).select("*").eq("id", empresa_id).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def crear_empresa(rut: str, nombre: str, clave_sii_cifrada: Optional[str]) -> dict:
    row = {"rut": rut.strip(), "nombre": nombre.strip(), "clave_sii_cifrada": clave_sii_cifrada}
    resp = get_supabase().table(TABLE).insert(row).execute()
    return resp.data[0]


def actualizar_empresa(empresa_id: str, nombre: str, clave_sii_cifrada: Optional[str] = None, actualizar_clave: bool = False) -> dict:
    row = {"nombre": nombre.strip()}
    if actualizar_clave:
        row["clave_sii_cifrada"] = clave_sii_cifrada
    resp = get_supabase().table(TABLE).update(row).eq("id", empresa_id).execute()
    return resp.data[0]


def eliminar_empresa(empresa_id: str) -> None:
    get_supabase().table(TABLE).delete().eq("id", empresa_id).execute()
