"""
Decoradores de rutas para exigir sesión iniciada (`login_required`) o rol
admin (`admin_required`). Reemplazan a `_login_gate()` / `_requiere_admin()`
de la app de Streamlit, adaptados al modelo request/response de Flask.
"""

from functools import wraps

from flask import session, redirect, url_for, request, abort


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("usuario"):
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        usuario = session.get("usuario")
        if not usuario:
            return redirect(url_for("auth.login", next=request.path))
        if usuario.get("rol") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def pagina_required(endpoint_pagina):
    """Como `login_required`, pero además exige rol admin si esa pestaña
    del menú está configurada como "solo administrador" — por defecto en
    `app/nav.py:PAGINAS`, o lo que el admin haya guardado en el panel
    Administrador → Pestañas (tabla `visibilidad_pestanas` en Supabase, ver
    `app/data/visibilidad_repo.py`). Se usa en TODAS las rutas de una
    pestaña (no solo la de índice), para que restringir una pestaña la
    bloquee de verdad y no solo la oculte del menú.

    `endpoint_pagina` es la misma cadena que aparece en `PAGINAS`
    (ej. "cartolas.index"), no necesariamente el endpoint real de la ruta
    decorada — varias rutas de una misma pestaña (index/procesar/
    descargar) comparten la misma clave de configuración.
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            usuario = session.get("usuario")
            if not usuario:
                return redirect(url_for("auth.login", next=request.path))
            from app.nav import es_admin_only
            if es_admin_only(endpoint_pagina) and usuario.get("rol") != "admin":
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator
