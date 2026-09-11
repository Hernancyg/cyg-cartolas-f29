"""
Cifrado de la clave del SII de cada empresa antes de guardarla en Supabase
(tabla `sii_empresas`, ver `app/data/sii_empresas_repo.py`) — la usa "RCV"
para llamar a SimpleAPI en nombre de esa empresa (`app/sii/client.py`).

Usa Fernet (AES-128-CBC + HMAC, de `cryptography`) con una llave simétrica
propia de esta app (`SII_CREDENTIALS_KEY`, distinta de cualquier otra
clave del sistema) que solo vive en las variables de entorno del
servidor — igual que `SUPABASE_KEY`, nunca en la base de datos ni en el
navegador. Así, aunque alguien lea la tabla directo en Supabase, no puede
recuperar la clave del SII sin esa llave.

Generar una llave nueva (una vez, guardarla en SII_CREDENTIALS_KEY):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from cryptography.fernet import Fernet, InvalidToken


def _fernet(clave_cifrado: str) -> Fernet:
    if not clave_cifrado:
        raise RuntimeError(
            "SII_CREDENTIALS_KEY no está configurada — no se puede cifrar "
            "ni leer la clave del SII de ninguna empresa."
        )
    return Fernet(clave_cifrado.encode("utf-8"))


def cifrar(clave_cifrado: str, texto_plano: str) -> str:
    return _fernet(clave_cifrado).encrypt(texto_plano.encode("utf-8")).decode("utf-8")


def descifrar(clave_cifrado: str, texto_cifrado: str):
    """None si la llave no calza o el valor está corrupto, en vez de
    reventar — para que un cambio de SII_CREDENTIALS_KEY (o un dato viejo)
    se vea en pantalla como "hay que reingresar la clave" y no como un
    error 500."""
    try:
        return _fernet(clave_cifrado).decrypt(texto_cifrado.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
