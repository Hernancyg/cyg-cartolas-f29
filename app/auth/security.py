"""
Hashing de contraseñas: misma técnica que usaba `usuarios.py` en la app de
Streamlit — PBKDF2-HMAC-SHA256, 100.000 iteraciones, salt aleatorio por
usuario. Los hashes existentes (migrados desde `usuarios.json`) siguen
siendo válidos porque no se cambia el algoritmo ni el número de
iteraciones.
"""

import hashlib
import hmac
import secrets as _secrets
from typing import Optional, Tuple

ITERACIONES_HASH = 100_000


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Devuelve (salt_hex, hash_hex). Si no se pasa salt, genera uno nuevo
    (usar para crear un usuario o restablecer su contraseña)."""
    if salt is None:
        salt = _secrets.token_hex(16)
    hash_bytes = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERACIONES_HASH
    )
    return salt, hash_bytes.hex()


def verificar_password(password: str, salt: str, hash_esperado: str) -> bool:
    _, hash_calculado = hash_password(password, salt)
    return hmac.compare_digest(hash_calculado, hash_esperado)


def verificar_clave_maestra(clave_ingresada: str, clave_maestra: str) -> bool:
    """Compara contra la llave maestra (admin_password) usando
    comparación de tiempo constante, para no filtrar por timing si la
    clave ingresada calza parcialmente."""
    if not clave_maestra:
        return False
    return hmac.compare_digest(clave_ingresada, clave_maestra)
