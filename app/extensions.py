"""
Cliente de Supabase (singleton) y otras extensiones compartidas
(Flask-Limiter). Se inicializan en `create_app()` (ver app/__init__.py).
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from supabase import create_client, Client

limiter = Limiter(key_func=get_remote_address)

_supabase_client: Client | None = None


def init_supabase(url: str, key: str) -> Client:
    global _supabase_client
    _supabase_client = create_client(url, key)
    return _supabase_client


def get_supabase() -> Client:
    if _supabase_client is None:
        raise RuntimeError(
            "Supabase no está inicializado todavía (falta llamar "
            "init_supabase — revisa SUPABASE_URL / SUPABASE_KEY)."
        )
    return _supabase_client
