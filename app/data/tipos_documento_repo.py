"""
CRUD de la tabla `tipos_documento` en Supabase — el mapeo de texto de "Tipo
de Documento" (tal como viene en los archivos de Clientes/Proveedores/
Honorarios, ej. "FAC-EL", "BOL-HE") a un código numérico, que es lo que
exige la plantilla de salida en la columna "Tipo De Documento" del bloque
de Tipo Auxiliar "A"/"H" (ver `app/caja_empresas/export_writer.py`).

Se administra desde Administrador → Tipos de Documento
(`app/templates/admin/tipos_documento.html`) para que el usuario pueda
agregar más códigos sin pedir un redespliegue — el usuario dio 3 de
partida (FAC-EL=33, FAC-EE=34, BOL-HE=99) pero puede haber más tipos de
documento en archivos futuros.

Mismo patrón tolerante/fail-safe que `app/data/visibilidad_repo.py`: caché
en memoria por poco tiempo, y si Supabase falla o la tabla todavía no
existe, se sigue con los valores por defecto (`DEFAULTS`) en vez de romper
la generación del archivo.
"""

import logging
import time
from typing import Dict

from app.extensions import get_supabase

logger = logging.getLogger(__name__)

TABLE = "tipos_documento"
_CACHE_TTL_SEGUNDOS = 30

# Códigos de partida, confirmados por el usuario (10-09-2026). Se usan
# mientras la tabla de Supabase no tenga ninguna fila propia, o si Supabase
# falla — así un tipo de documento conocido nunca queda sin código por un
# problema pasajero de conexión.
DEFAULTS: Dict[str, int] = {
    "FAC-EL": 33,
    "FAC-EE": 34,
    "BOL-HE": 99,
}

_cache: Dict[str, int] = {}
_cache_at = 0.0


def obtener_mapa() -> Dict[str, int]:
    """{texto_tipo_documento: codigo_numerico}. Nunca lanza — si Supabase
    falla o la tabla está vacía/no existe, devuelve `DEFAULTS`."""
    global _cache, _cache_at
    ahora = time.monotonic()
    if _cache_at and (ahora - _cache_at) < _CACHE_TTL_SEGUNDOS:
        return _cache or dict(DEFAULTS)
    try:
        resp = get_supabase().table(TABLE).select("texto, codigo").execute()
        filas = resp.data or []
        if filas:
            _cache = {f["texto"]: int(f["codigo"]) for f in filas}
        else:
            _cache = dict(DEFAULTS)
        _cache_at = ahora
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "No se pudo leer tipos_documento (¿falta ejecutar "
            "migration/004_tipos_documento.sql en Supabase?): %s. "
            "Se sigue con los códigos por defecto.", exc,
        )
        if not _cache:
            return dict(DEFAULTS)
    return _cache


def codigo_de(texto_tipo_documento: str):
    """Código numérico para un texto de tipo de documento (ej. "FAC-EL"),
    o None si no está configurado (el llamador decide si eso es un error
    bloqueante o si simplemente deja la celda vacía)."""
    return obtener_mapa().get((texto_tipo_documento or "").strip())


def guardar_todos(mapa: Dict[str, int]) -> None:
    """Reemplaza el contenido completo de la tabla (mismo patrón de
    "borrar todo e insertar de nuevo" que `visibilidad_repo.guardar_todas`)
    e invalida el caché en memoria para que el cambio se vea de inmediato
    en este proceso."""
    global _cache, _cache_at
    sb = get_supabase()
    sb.table(TABLE).delete().neq("texto", "__never__").execute()
    filas = [{"texto": texto.strip(), "codigo": int(codigo)} for texto, codigo in mapa.items() if texto.strip()]
    if filas:
        sb.table(TABLE).insert(filas).execute()
    _cache = {f["texto"]: f["codigo"] for f in filas} if filas else dict(DEFAULTS)
    _cache_at = time.monotonic()
