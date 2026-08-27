"""
"Administrador": puerto de `pagina_administrador()` de la app de
Streamlit. Ahora edita directamente las tablas de Supabase (`cuentas_config`
/ `usuarios`) en vez de descargar/subir JSON a GitHub — la mejora natural
que permite tener una base de datos real detrás.
"""

import io

from flask import Blueprint, render_template, request, redirect, url_for, flash

from app.auth.decorators import admin_required, login_required
from app.auth.security import hash_password
from app.parsers.config_manager import cargar_config, guardar_config, CuentaConfig
from app.parsers.f29_parser import parsear_f29, _clean_monto
from app.data import usuarios_repo

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

SENTINEL_SIN_OPERADOR = "(sin símbolo)"
OPERADORES = ["+", "-", "=", SENTINEL_SIN_OPERADOR]


# ---------------------------------------------------------------------------
# Cuentas F29
# ---------------------------------------------------------------------------

def _leer_filas_config(form):
    cuentas = form.getlist("c_cuenta")
    codigos = form.getlist("c_codigo")
    descripciones = form.getlist("c_descripcion")
    tipos = form.getlist("c_tipo")
    anclas = form.getlist("c_ancla")
    operadores = form.getlist("c_operador")

    configs = []
    for i in range(len(cuentas)):
        campos = [cuentas[i], codigos[i], descripciones[i], tipos[i], anclas[i]]
        if any(c is None or str(c).strip() == "" for c in campos):
            continue
        operador_val = operadores[i].strip() if i < len(operadores) else ""
        if operador_val == SENTINEL_SIN_OPERADOR:
            operador_val = ""
        configs.append(CuentaConfig(
            cuenta=cuentas[i].strip(), codigo_f29=codigos[i].strip(),
            descripcion=descripciones[i].strip(), tipo=tipos[i].strip(),
            texto_ancla=anclas[i].strip(), operador=operador_val,
        ))
    return configs


@admin_bp.route("/cuentas", methods=["GET"])
@admin_required
def cuentas():
    configs = cargar_config()
    return render_template(
        "admin/cuentas.html", configs=configs, sentinel=SENTINEL_SIN_OPERADOR,
        operadores=OPERADORES, prueba=None,
    )


@admin_bp.route("/cuentas/guardar", methods=["POST"])
@admin_required
def cuentas_guardar():
    nuevas_configs = _leer_filas_config(request.form)
    guardar_config(nuevas_configs)
    flash("Cambios guardados. Se aplicarán de inmediato.", "success")
    return redirect(url_for("admin.cuentas"))


@admin_bp.route("/cuentas/probar", methods=["POST"])
@admin_required
def cuentas_probar():
    nuevas_configs = _leer_filas_config(request.form)
    archivo = request.files.get("pdf_prueba")
    prueba = None
    if archivo and archivo.filename and nuevas_configs:
        try:
            data_prueba = parsear_f29(io.BytesIO(archivo.read()), configs=nuevas_configs)
            prueba = {
                "filas": [{
                    "cuenta": c.cuenta, "codigo_f29": c.codigo_f29,
                    "monto": _clean_monto(data_prueba.valores.get(c.codigo_f29)),
                    "detectado": data_prueba.valores.get(c.codigo_f29) is not None,
                } for c in nuevas_configs],
                "advertencias": data_prueba.advertencias,
            }
        except Exception as exc:  # noqa: BLE001
            flash(f"No se pudo leer el PDF de prueba: {exc}", "error")
    return render_template(
        "admin/cuentas.html", configs=nuevas_configs or cargar_config(),
        sentinel=SENTINEL_SIN_OPERADOR, operadores=OPERADORES, prueba=prueba,
    )


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------

@admin_bp.route("/usuarios", methods=["GET"])
@admin_required
def usuarios():
    from flask import session
    lista = usuarios_repo.listar_usuarios()
    yo = session.get("usuario") or {}
    return render_template(
        "admin/usuarios.html", usuarios=lista, roles=usuarios_repo.ROLES,
        mi_id=yo.get("id"),
    )


@admin_bp.route("/usuarios/actualizar", methods=["POST"])
@admin_required
def usuarios_actualizar():
    from flask import session
    ids = request.form.getlist("u_id")
    nombres = request.form.getlist("u_nombre")
    roles = request.form.getlist("u_rol")
    activos = set(request.form.getlist("u_activo"))  # ids marcados activos
    mi_id = (session.get("usuario") or {}).get("id")

    for i, uid in enumerate(ids):
        if uid == mi_id:
            continue  # un admin no puede editarse su propio rol/estado, para no auto-bloquearse
        usuarios_repo.actualizar_datos(
            uid, nombres[i] if i < len(nombres) else "",
            roles[i] if i < len(roles) else "trabajador",
            uid in activos,
        )
    flash("Cambios de usuarios guardados.", "success")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/crear", methods=["POST"])
@admin_required
def usuarios_crear():
    usuario = (request.form.get("usuario") or "").strip()
    nombre = (request.form.get("nombre") or "").strip()
    rol = request.form.get("rol") or "trabajador"
    clave = request.form.get("clave") or ""
    clave_confirmar = request.form.get("clave_confirmar") or ""

    if not usuario or not nombre or not clave:
        flash("Completa usuario, nombre y contraseña.", "error")
    elif clave != clave_confirmar:
        flash("Las contraseñas no coinciden.", "error")
    elif len(clave) < 4:
        flash("La contraseña debe tener al menos 4 caracteres.", "error")
    elif usuarios_repo.buscar_usuario(usuario) is not None:
        flash(f"Ya existe un usuario '{usuario}'.", "error")
    else:
        usuarios_repo.crear_usuario(usuario, nombre, rol, clave)
        flash(f"Usuario '{usuario}' creado.", "success")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/resetear", methods=["POST"])
@admin_required
def usuarios_resetear():
    usuario_id = request.form.get("usuario_id")
    nueva_clave = request.form.get("nueva_clave") or ""
    if len(nueva_clave) < 4:
        flash("La contraseña debe tener al menos 4 caracteres.", "error")
    elif usuario_id:
        usuarios_repo.restablecer_password(usuario_id, nueva_clave)
        flash("Contraseña actualizada.", "success")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/eliminar", methods=["POST"])
@admin_required
def usuarios_eliminar():
    from flask import session
    usuario_id = request.form.get("usuario_id")
    mi_id = (session.get("usuario") or {}).get("id")
    if usuario_id and usuario_id != mi_id:
        usuarios_repo.eliminar_usuario(usuario_id)
        flash("Usuario eliminado.", "success")
    else:
        flash("No puedes eliminar tu propio usuario.", "error")
    return redirect(url_for("admin.usuarios"))
