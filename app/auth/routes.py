"""
/login, /logout — reemplaza `_login_gate()` de la app de Streamlit. La
llave maestra (`ADMIN_PASSWORD`) sigue funcionando como acceso de
administrador aunque no exista ningún usuario creado en Supabase todavía,
para no quedar bloqueado.
"""

from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    current_app, flash,
)

from app.auth.security import verificar_clave_maestra, verificar_password
from app.data.usuarios_repo import buscar_usuario
from app.extensions import limiter

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if session.get("usuario"):
        return redirect(url_for("cartolas.index"))

    clave_maestra = current_app.config.get("ADMIN_PASSWORD")
    error = None

    if request.method == "POST":
        usuario_ingresado = (request.form.get("usuario") or "").strip()
        clave_ingresada = request.form.get("clave") or ""

        if clave_maestra and verificar_clave_maestra(clave_ingresada, clave_maestra):
            session["usuario"] = {"usuario": "admin", "nombre": "Administrador", "rol": "admin", "is_master": True}
            return redirect(request.args.get("next") or url_for("cartolas.index"))

        u = buscar_usuario(usuario_ingresado) if usuario_ingresado else None
        if u and u.get("activo", True) and verificar_password(clave_ingresada, u["salt"], u["hash"]):
            session["usuario"] = {
                "usuario": u["usuario"], "nombre": u["nombre"], "rol": u["rol"],
                "id": u["id"], "is_master": False,
            }
            return redirect(request.args.get("next") or url_for("cartolas.index"))

        error = "Usuario o contraseña incorrectos."

    return render_template(
        "login.html",
        error=error,
        clave_maestra_configurada=bool(clave_maestra),
    )


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.pop("usuario", None)
    return redirect(url_for("auth.login"))
