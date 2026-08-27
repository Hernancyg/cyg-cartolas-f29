"""
Fábrica de la app Flask. `wsgi.py` (en la raíz del repo) llama a
`create_app()` para obtener la instancia que sirve gunicorn en Render.
"""

import sys
from pathlib import Path

# `f29_parser.py` (copiado sin cambios desde la app de Streamlit) hace
# `from config_manager import cargar_config, CuentaConfig` como import
# bare (sin paquete). Para que siga funcionando exactamente igual sin
# tocar ese archivo, se agrega `app/parsers/` a sys.path — ahí vive
# `config_manager.py`, la versión respaldada por Supabase.
_PARSERS_DIR = Path(__file__).parent / "parsers"
if str(_PARSERS_DIR) not in sys.path:
    sys.path.insert(0, str(_PARSERS_DIR))

from flask import Flask
from flask_wtf import CSRFProtect

from app.config import Config, validate_config
from app.extensions import limiter, init_supabase

csrf = CSRFProtect()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    validate_config(app)

    if app.config.get("SUPABASE_URL") and app.config.get("SUPABASE_KEY"):
        init_supabase(app.config["SUPABASE_URL"], app.config["SUPABASE_KEY"])

    csrf.init_app(app)
    limiter.init_app(app)

    def _clp(n):
        """Formato de números chileno: punto como separador de miles
        (igual que `fmt = lambda n: f"{n:,}".replace(",", ".")` en la app
        de Streamlit)."""
        try:
            n = float(n)
        except (TypeError, ValueError):
            return n
        sign = "-" if n < 0 else ""
        return sign + "{:,.0f}".format(abs(n)).replace(",", ".")

    app.jinja_env.filters["clp"] = _clp

    def _numval(v):
        """Para inputs numéricos editables (cargo/abono/monto): '' si es
        0/None, y sin '.0' final cuando el valor es entero (Jinja
        renderiza floats de Python con decimal siempre)."""
        if v in (None, "", 0, 0.0):
            return ""
        try:
            f = float(v)
        except (TypeError, ValueError):
            return v
        return str(int(f)) if f == int(f) else str(f)

    app.jinja_env.filters["numval"] = _numval

    from app.auth.routes import auth_bp
    from app.cartolas.routes import cartolas_bp
    from app.f29.routes import f29_bp
    from app.admin.routes import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(cartolas_bp)
    app.register_blueprint(f29_bp)
    app.register_blueprint(admin_bp)

    from app.nav import PAGINAS

    @app.context_processor
    def inject_globals():
        from flask import session
        usuario = session.get("usuario")
        return {
            "usuario_actual": usuario,
            "es_admin": bool(usuario and usuario.get("rol") == "admin"),
            "paginas": PAGINAS,
        }

    @app.errorhandler(403)
    def forbidden(_e):
        from flask import render_template
        return render_template("error.html", codigo=403, mensaje="No tienes permiso para ver esta página."), 403

    @app.errorhandler(404)
    def not_found(_e):
        from flask import render_template
        return render_template("error.html", codigo=404, mensaje="Página no encontrada."), 404

    return app
