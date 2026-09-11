"""
Utilidades de RUT chileno: normalización ('76.192.083-9' / '761920839' ->
'76192083-9') y validación del dígito verificador (módulo 11) — para
detectar un RUT mal tipeado ANTES de gastar cuota en una llamada a
API Gateway o SimpleAPI (ver `app/sii/client.py`).
"""

import re

_RUT_LIMPIO_RE = re.compile(r"[^0-9kK]")


def _calcular_dv(numero: int) -> str:
    suma = 0
    multiplicador = 2
    for digito in reversed(str(numero)):
        suma += int(digito) * multiplicador
        multiplicador = 2 if multiplicador == 7 else multiplicador + 1
    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)


def normalizar_rut(rut: str):
    """'76.192.083-9' / '761920839' -> '76192083-9'. None si no alcanza a
    tener número + dígito verificador."""
    limpio = _RUT_LIMPIO_RE.sub("", rut or "")
    if len(limpio) < 2:
        return None
    numero, dv = limpio[:-1], limpio[-1].upper()
    if not numero.isdigit():
        return None
    return f"{int(numero)}-{dv}"


def validar_rut(rut: str) -> bool:
    """True si el dígito verificador calza con el número (módulo 11)."""
    normalizado = normalizar_rut(rut)
    if not normalizado:
        return False
    numero, dv = normalizado.split("-")
    return _calcular_dv(int(numero)) == dv
