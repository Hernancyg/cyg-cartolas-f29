"""
Tablas de Supabase del "EERR Dinámico" (24-09-2026, ver
`migration/015_eerr.sql`):

- `eerr_empresas`: empresas que se trabajan con Softland o Defontana
  (agregadas a mano desde Administrador → Sistemas contables). Las de
  Nubox NO se guardan acá: salen del conector NuboxMCP vía el puente
  (`nubox_importado_repo.listar_empresas_nubox`).
- `eerr_config`: por empresa (`clave` = "<sistema>:<código>"), la lista de
  conceptos del informe y en qué concepto va cada cuenta — se guarda para
  no tener que asignar las cuentas cada vez.

Sin caché en memoria (se lee al abrir una empresa, no en cada request),
mismo criterio que `sii_empresas_repo`/`planificacion_at2027_repo`.
"""

from datetime import datetime, timezone
from typing import List, Optional

from app.extensions import get_supabase

TABLE_EMPRESAS = "eerr_empresas"
TABLE_CONFIG = "eerr_config"

SISTEMAS = {
    "nubox": "Nubox",
    "softland": "Softland",
    "defontana": "Defontana",
}
SISTEMAS_MANUALES = ("softland", "defontana")


def clave_empresa(sistema: str, codigo: str) -> str:
    return f"{sistema}:{codigo}"


def listar_empresas_manuales() -> List[dict]:
    resp = get_supabase().table(TABLE_EMPRESAS).select("*").order("razon_social").execute()
    return resp.data or []


def agregar_empresa(codigo: str, razon_social: str, rut: str, sistema: str) -> dict:
    resp = get_supabase().table(TABLE_EMPRESAS).insert({
        "codigo": codigo, "razon_social": razon_social, "rut": rut or None, "sistema": sistema,
    }).execute()
    return (resp.data or [{}])[0]


def eliminar_empresa(empresa_id: str) -> None:
    get_supabase().table(TABLE_EMPRESAS).delete().eq("id", empresa_id).execute()


def obtener_config(clave: str) -> Optional[dict]:
    """{conceptos, asignaciones} guardados para esa empresa, o None si
    nunca se guardó nada."""
    resp = get_supabase().table(TABLE_CONFIG).select("*").eq("clave", clave).limit(1).execute()
    filas = resp.data or []
    return filas[0] if filas else None


def guardar_config(clave: str, conceptos: list, asignaciones: dict) -> None:
    sb = get_supabase()
    sb.table(TABLE_CONFIG).delete().eq("clave", clave).execute()
    sb.table(TABLE_CONFIG).insert({
        "clave": clave, "conceptos": conceptos, "asignaciones": asignaciones,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
