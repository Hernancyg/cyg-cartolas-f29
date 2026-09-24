"""
Verificación del tema visual por usuario (25-09-2026): el admin asigna un
tema desde Administrador → Usuarios y solo ese usuario lo ve (atributo
data-tema en <html>). Mismo estilo sin-pytest que `tests/test_eerr.py`.

Uso:
    python tests/test_tema_usuario.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.run_verification import FAKE, flask_app, seed_data  # noqa: E402
from app.auth.security import hash_password  # noqa: E402
from app.data import usuarios_repo  # noqa: E402

PASSED, FAILED = [], []


def check(label, condition, extra=""):
    if condition:
        PASSED.append(label)
        print(f"  OK  {label}")
    else:
        FAILED.append(label)
        print(f" FAIL {label} {extra}")


def _login(usuario, clave):
    client = flask_app.test_client()
    client.post("/login", data={"usuario": usuario, "clave": clave}, follow_redirects=True)
    return client


def test_tema_por_usuario():
    salt, h = hash_password("otra123")
    FAKE.table("usuarios").insert({
        "usuario": "otrouser", "nombre": "Otra Persona", "rol": "trabajador",
        "salt": salt, "hash": h, "activo": True,
    }).execute()
    usuarios = {u["usuario"]: u for u in usuarios_repo.listar_usuarios()}

    admin = _login("", "test_local_only_1234")
    r = admin.get("/admin/usuarios")
    html = r.get_data(as_text=True)
    check("admin: columna Tema", "<th>Tema</th>" in html)
    check("admin: selector de tema por usuario", f'name="u_tema_{usuarios["testuser"]["id"]}"' in html and ">Rosa<" in html)

    form = {"u_id": [u["id"] for u in usuarios.values()],
            "u_nombre": [u["nombre"] for u in usuarios.values()],
            "u_rol": [u["rol"] for u in usuarios.values()],
            "u_activo": [u["id"] for u in usuarios.values()],
            f"u_tema_{usuarios['testuser']['id']}": "rosa",
            f"u_tema_{usuarios['otrouser']['id']}": ""}
    r = admin.post("/admin/usuarios/actualizar", data=form, follow_redirects=True)
    check("admin: guarda sin avisos de error", "no se guardaron" not in r.get_data(as_text=True))
    check("tema guardado en el usuario", usuarios_repo.tema_de(usuarios["testuser"]["id"]) == "rosa")

    r = _login("testuser", "trabajador123").get("/inicio/", follow_redirects=True)
    check("el usuario con tema Rosa lo ve", 'data-tema="rosa"' in r.get_data(as_text=True))
    r = _login("otrouser", "otra123").get("/inicio/", follow_redirects=True)
    check("los demás ven el tema de siempre", "data-tema=" not in r.get_data(as_text=True))
    r = admin.get("/inicio/", follow_redirects=True)
    check("la llave maestra no tiene tema", "data-tema=" not in r.get_data(as_text=True))

    form[f"u_tema_{usuarios['testuser']['id']}"] = "no-existe"
    admin.post("/admin/usuarios/actualizar", data=form)
    check("tema desconocido vuelve al predeterminado", usuarios_repo.tema_de(usuarios["testuser"]["id"]) == "")
    check("tema_de sin usuario", usuarios_repo.tema_de(None) == "")


def test_css_del_tema():
    css = (Path(__file__).resolve().parent.parent / "app/static/css/styles.css").read_text(encoding="utf-8")
    check("CSS: tema Rosa claro", ':root[data-tema="rosa"] {' in css and "--rosa: #E44F9C" in css)
    check("CSS: tema Rosa oscuro", ':root[data-tema="rosa"][data-theme="dark"]' in css)


def main():
    seed_data()
    test_tema_por_usuario()
    test_css_del_tema()
    print(f"\n{len(PASSED)} OK, {len(FAILED)} FAIL")
    if FAILED:
        print("Fallaron:", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    main()
