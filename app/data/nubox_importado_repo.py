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


# ---------------------------------------------------------------------------
# EERR Dinámico (24-09-2026): empresas que autoriza el conector NuboxMCP y
# Estado de Resultados Comparativo por empresa/año, que el mismo puente deja
# en `nubox_importado/empresas.csv` y
# `nubox_importado/estado_resultado_comparativo/<alias>_<AAAA>.csv`.
# ---------------------------------------------------------------------------

ARCHIVO_EMPRESAS = _RAIZ / "nubox_importado" / "empresas.csv"
CARPETA_EERR = _RAIZ / "nubox_importado" / "estado_resultado_comparativo"

_ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_EERR_RE = re.compile(r"^(?P<alias>.+)_(?P<anio>\d{4})\.csv$", re.IGNORECASE)


def alias_valido(alias: str) -> bool:
    """El alias viene del navegador y se usa para armar una ruta de archivo:
    solo letras, números, guion y guion bajo (nada de `..` ni `/`)."""
    return bool(alias and _ALIAS_RE.match(alias))


def listar_empresas_nubox() -> List[dict]:
    """Empresas seleccionadas en el conector NuboxMCP (las que la llave de
    acceso autoriza), tal como las dejó la última corrida del puente:
    [{alias, rut, razon_social}]. Vacía si el puente todavía no escribió
    el archivo."""
    import csv
    if not ARCHIVO_EMPRESAS.is_file():
        return []
    with open(ARCHIVO_EMPRESAS, newline="", encoding="utf-8-sig") as fh:
        return [
            {"alias": (f.get("alias") or "").strip(), "rut": (f.get("rut") or "").strip(),
             "razon_social": (f.get("razon_social") or "").strip()}
            for f in csv.DictReader(fh) if (f.get("alias") or "").strip()
        ]


def eerr_anios_disponibles(alias: str) -> List[int]:
    """Años con Estado de Resultados Comparativo importado para esa empresa,
    del más reciente al más antiguo."""
    if not alias_valido(alias) or not CARPETA_EERR.is_dir():
        return []
    anios = set()
    for archivo in CARPETA_EERR.glob(f"{alias}_*.csv"):
        m = _EERR_RE.match(archivo.name)
        if m and m.group("alias") == alias:
            anios.add(int(m.group("anio")))
    return sorted(anios, reverse=True)


def ruta_eerr(alias: str, anio: int) -> Optional[Path]:
    if not alias_valido(alias):
        return None
    ruta = CARPETA_EERR / f"{alias}_{int(anio)}.csv"
    return ruta if ruta.is_file() else None
