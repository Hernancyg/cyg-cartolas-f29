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
