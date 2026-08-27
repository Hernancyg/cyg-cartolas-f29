"""
Configuración de la app, leída siempre desde variables de entorno (nunca
hardcodeada). En Render estas se configuran en el dashboard del Web
Service; en local se puede usar un archivo `.env` (ver `.env.example`) que
`python-dotenv` carga automáticamente en `wsgi.py`.
"""

import os


class Config:
    # --- Supabase ---
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

    # --- Llave maestra de administrador (bypass de usuarios/contraseña) ---
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

    # --- Flask ---
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "")

    # Cookies de sesión: solo HTTPS, no accesibles desde JS, no cross-site.
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_DEBUG", "0") != "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Tamaño máximo de archivo subido (cartola / F29 en PDF o Excel): 20 MB.
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024

    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"


def validate_config(app):
    """Avisa (sin explotar) si falta alguna variable crítica, para que el
    error sea legible en los logs de Render en vez de un traceback críptico
    en medio de una request."""
    missing = []
    for key in ("SUPABASE_URL", "SUPABASE_KEY", "SECRET_KEY"):
        if not app.config.get(key):
            missing.append(key)
    if missing:
        app.logger.warning(
            "Faltan variables de entorno: %s. La app puede no funcionar "
            "correctamente hasta que se configuren.", ", ".join(missing)
        )
    if not app.config.get("ADMIN_PASSWORD"):
        app.logger.warning(
            "ADMIN_PASSWORD no está configurado: no habrá clave maestra de "
            "administrador disponible (solo se podrá entrar con usuarios "
            "ya creados en Supabase)."
        )
