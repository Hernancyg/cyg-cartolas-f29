"""
Lee (no escribe) la carpeta `nubox_importado/` en la raíz del repo —
donde el puente Nubox -> repo (agente de Claude + conector MCP NuboxMCP,
corrido a mano o como rutina programada, ver `nubox_importado/README.md`)
deja los CSV de Balance General y Libro Mayor por empresa/período
(`<alias>_<periodo>.csv`). A diferencia del resto de `app/data/*_repo.py`
(siempre contra Supabase vía `get_supabase()`), este repo lee el
filesystem directamente — no hay tabla en Supabase para esto.
"""

import re
from pathlib import Path
from typing import List, Optional, Tuple

# Raíz del repo: dos niveles arriba de este archivo (app/data/ -> app/ -> raíz).
_RAIZ = Path(__file__).resolve().parent.parent.parent
CARPETA_BALANCE = _RAIZ / "nubox_importado" / "balance_general"
CARPETA_MAYOR = _RAIZ / "nubox_importado" / "libro_mayor"

_NOMBRE_RE = re.compile(r"^(?P<alias>.+)_(?P<periodo>\d{6})\.csv$", re.IGNORECASE)


def _parsear_nombre(path: Path) -> Optional[dict]:
    m = _NOMBRE_RE.match(path.name)
    if not m:
        return None
    return {"alias": m.group("alias"), "periodo": m.group("periodo")}


def listar_disponibles() -> List[dict]:
    """Combinaciones (alias, período) que tienen AMBOS reportes (Balance
    General y Libro Mayor) disponibles — si solo existe uno de los dos, se
    omite (no hay suficiente información para generar el análisis)."""
    if not CARPETA_BALANCE.is_dir():
        return []

    disponibles = []
    for archivo in sorted(CARPETA_BALANCE.glob("*.csv")):
        info = _parsear_nombre(archivo)
        if not info:
            continue
        ruta_mayor = CARPETA_MAYOR / archivo.name
        if not ruta_mayor.is_file():
            continue
        disponibles.append(info)
    return disponibles


def rutas_de(alias: str, periodo: str) -> Optional[Tuple[Path, Path]]:
    """Devuelve (ruta_balance, ruta_mayor) para esa combinación, o None si
    no existen ambos archivos."""
    nombre = f"{alias}_{periodo}.csv"
    ruta_balance = CARPETA_BALANCE / nombre
    ruta_mayor = CARPETA_MAYOR / nombre
    if not ruta_balance.is_file() or not ruta_mayor.is_file():
        return None
    return ruta_balance, ruta_mayor
