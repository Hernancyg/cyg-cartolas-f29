"""
Compatibilidad con `f29_parser.py` (copiado sin cambios desde la app de
Streamlit), que hace `from config_manager import cargar_config,
CuentaConfig`. Este módulo vive junto a `f29_parser.py` en `app/parsers/`
(agregado a `sys.path` en `app/__init__.py`) para que ese import bare
siga funcionando exactamente igual, pero ahora respaldado por la tabla
`cuentas_config` de Supabase en vez de un archivo JSON local.

Cada `CuentaConfig` sigue teniendo el mismo `build_pattern()`/`compile()`
que usa `f29_parser.py` para ubicar el código en el texto del PDF.
"""

import re
from dataclasses import dataclass
from typing import List

from app.data.cuentas_config_repo import listar, guardar_todas


@dataclass
class CuentaConfig:
    cuenta: str
    codigo_f29: str
    descripcion: str
    tipo: str
    texto_ancla: str
    operador: str = "+"

    def build_pattern(self) -> str:
        return (
            re.escape(self.texto_ancla)
            + r"[\s\S]{0,900}?\b"
            + re.escape(self.codigo_f29)
            + r"\b\s+([\d.,]+)?\s*"
            + re.escape(self.operador)
        )

    def compile(self):
        return re.compile(self.build_pattern())


def cargar_config() -> List[CuentaConfig]:
    filas = listar()
    return [
        CuentaConfig(
            cuenta=f["cuenta"],
            codigo_f29=f["codigo_f29"],
            descripcion=f.get("descripcion") or "",
            tipo=f["tipo"],
            texto_ancla=f["texto_ancla"],
            operador=f.get("operador") or "",
        )
        for f in filas
    ]


def guardar_config(configs: List[CuentaConfig]) -> None:
    filas = [
        {
            "cuenta": c.cuenta,
            "codigo_f29": c.codigo_f29,
            "descripcion": c.descripcion,
            "tipo": c.tipo,
            "texto_ancla": c.texto_ancla,
            "operador": c.operador,
        }
        for c in configs
    ]
    guardar_todas(filas)
