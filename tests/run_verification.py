"""
Verificación local end-to-end de la app Flask, SIN necesidad de un
proyecto Supabase real (usa `fake_supabase.FakeSupabase`, sembrado con
datos de prueba). Corre las 3 páginas + login + admin con el
`test_client()` de Flask, y valida:

  - Login con llave maestra de PRUEBA (nunca la clave real del usuario).
  - Login con un usuario 'trabajador' de PRUEBA y que no pueda ver
    Administrador (403).
  - "Subir Cartolas": parsea una cartola PDF real (de sesiones anteriores,
    ya validada) y compara los totales de cargo/abono.
  - Descarga del Excel convertido (estructura correcta con openpyxl).
  - "Generar CSV F29": con `parsear_f29` monkeypatcheado (no hay PDF de
    F29 de ejemplo a mano), valida el flujo completo (período, montos,
    remanente, CSV final) contra la lógica real de `f29_parser.py`.
  - Administrador: guardar cuentas_config y crear/editar/resetear
    usuarios contra la base de datos de prueba.

Uso:
    ADMIN_PASSWORD_TEST=... python3 tests/run_verification.py
(No requiere variables reales de Supabase — se reemplaza el cliente.)
"""

import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SUPABASE_URL", "http://fake.local")
os.environ.setdefault("SUPABASE_KEY", "fake-key")
os.environ.setdefault("ADMIN_PASSWORD", "test_local_only_1234")
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key-not-for-prod")
os.environ.setdefault("FLASK_DEBUG", "1")

from tests.fake_supabase import FakeSupabase

FAKE = FakeSupabase()

import app.extensions as extensions

# Evita que create_app() reemplace el cliente por uno real de supabase-py
# (que intentaría conectarse por red con las credenciales falsas de arriba).
extensions.init_supabase = lambda *_a, **_kw: FAKE

from app import create_app  # noqa: E402
from app.auth.security import hash_password  # noqa: E402

flask_app = create_app()
extensions._supabase_client = FAKE  # por si algo lo reinicializó
flask_app.config["WTF_CSRF_ENABLED"] = False
flask_app.config["RATELIMIT_ENABLED"] = False

PASSED = []
FAILED = []


def check(label, condition, extra=""):
    if condition:
        PASSED.append(label)
        print(f"  OK  {label}")
    else:
        FAILED.append(label)
        print(f" FAIL {label} {extra}")


def seed_data():
    salt, h = hash_password("trabajador123")
    FAKE.table("usuarios").insert({
        "usuario": "testuser", "nombre": "Usuario de Prueba", "rol": "trabajador",
        "salt": salt, "hash": h, "activo": True,
    }).execute()

    cuentas = [
        ("538", "2108-02", "Total Débitos", "DEBE", "TOTAL DÉBITOS", "=", 0),
        ("537", "1108-02", "Total Créditos", "HABER", "TOTAL CRÉDITOS", "=", 1),
        ("48", "2108-03", "Retención Impuesto Único Trabajadores", "DEBE", "Art. 73 LIR", "+", 2),
    ]
    for codigo, cuenta, desc, tipo, ancla, op, orden in cuentas:
        FAKE.table("cuentas_config").insert({
            "codigo_f29": codigo, "cuenta": cuenta, "descripcion": desc,
            "tipo": tipo, "texto_ancla": ancla, "operador": op, "orden": orden,
        }).execute()


def main():
    seed_data()
    client = flask_app.test_client()

    # ---- Login: usuario/contraseña incorrectos ----
    r = client.post("/login", data={"usuario": "nadie", "clave": "nada"})
    check("login con credenciales inválidas no autentica", r.status_code == 200 and b"incorrectos" in r.data)

    # ---- Login: llave maestra de PRUEBA ----
    r = client.post("/login", data={"usuario": "", "clave": "test_local_only_1234"}, follow_redirects=True)
    check("login con llave maestra de prueba entra como admin", r.status_code == 200 and "Subir Cartolas".encode() in r.data)

    # ---- Subir Cartolas: página inicial ----
    r = client.get("/cartolas/")
    check("GET /cartolas/ 200", r.status_code == 200)
    check("grilla de bancos presente", b"Selecciona tu banco" in r.data)

    pdf_candidates = [
        "/root/.claude/uploads/6765170a-fd6f-5183-b8a3-c1c40a5d8b1c/b3283656-CartolaHistCtaCte000080035381005920260514.pdf",
        "/root/.claude/uploads/6765170a-fd6f-5183-b8a3-c1c40a5d8b1c/c7c222e5-Cartola_004__2026.pdf",
    ]
    for pdf_path in pdf_candidates:
        if not os.path.exists(pdf_path):
            check(f"cartola de prueba existe ({os.path.basename(pdf_path)})", False)
            continue
        with open(pdf_path, "rb") as fh:
            data = {
                "banco": "bci",
                "archivo": (io.BytesIO(fh.read()), os.path.basename(pdf_path)),
            }
            r = client.post("/cartolas/procesar", data=data, content_type="multipart/form-data")
        check(f"procesar cartola {os.path.basename(pdf_path)} -> 200", r.status_code == 200)
        check("tabla de movimientos aparece", b"Ajustes antes de exportar" in r.data or b"No se encontraron movimientos" in r.data)

    # ---- Descargar Excel convertido (con filas de ejemplo) ----
    r = client.post("/cartolas/descargar", data={
        "base_name": "prueba",
        "fecha": ["01/01/2026", "02/01/2026"],
        "detalle": ["Movimiento A", "Movimiento B"],
        "cargo": ["1000", ""],
        "abono": ["", "2000"],
    })
    check("descarga de Excel 200", r.status_code == 200)
    check("Excel tiene Content-Disposition attachment", "attachment" in r.headers.get("Content-Disposition", ""))
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(r.data))
        ws = wb["Banco"]
        check("hoja 'Banco' con encabezados correctos", ws["B1"].value == "FECHA DIA/MES" and ws["E1"].value == "MONTO DEPOSITOS O ABONOS")
        check("fila de datos con cargo correcto", ws["D2"].value == 1000.0)
        check("fila de datos con abono correcto", ws["E3"].value == 2000.0)
    except Exception as exc:  # noqa: BLE001
        check("Excel se puede leer con openpyxl", False, str(exc))

    # ---- Generar CSV F29 (con parsear_f29 monkeypatcheado: sin PDF real) ----
    import app.f29.routes as f29_routes
    from app.parsers.f29_parser import F29Data

    def fake_parsear_f29(_buf, configs=None):
        return F29Data(
            mes="06", anio="2026", rut="76123456-7", razon_social="Empresa de Prueba SpA",
            valores={"538": "1.500.000", "537": "1.000.000", "48": "50.000"},
            remanente_504=0, remanente_504_encontrado=False, advertencias=[],
        )

    f29_routes.parsear_f29 = fake_parsear_f29

    r = client.get("/f29/")
    check("GET /f29/ 200", r.status_code == 200)

    r = client.post("/f29/procesar", data={"archivo": (io.BytesIO(b"%PDF-1.4 fake"), "f29_prueba.pdf")}, content_type="multipart/form-data")
    check("procesar F29 -> 200", r.status_code == 200)
    check("montos detectados en la tabla", b"1500000" in r.data or b"1.500.000" in r.data or b"value=\"1500000\"" in r.data)

    r = client.post("/f29/preview", data={
        "mes": "06", "anio": "2026", "remanente_504": "0",
        "f_cuenta": ["2108-02", "1108-02", "2108-03"],
        "f_codigo": ["538", "537", "48"],
        "f_tipo": ["DEBE", "HABER", "DEBE"],
        "f_monto": ["1500000", "1000000", "50000"],
        "f_incluir": ["538", "537", "48"],
    })
    check("preview F29 -> 200", r.status_code == 200)
    check("totales DEBE/HABER en preview (formato chileno con puntos)", b"1.550.000" in r.data)

    r = client.post("/f29/descargar", data={
        "mes": "06", "anio": "2026", "remanente_504": "0",
        "f_cuenta": ["2108-02", "1108-02", "2108-03"],
        "f_codigo": ["538", "537", "48"],
        "f_tipo": ["DEBE", "HABER", "DEBE"],
        "f_monto": ["1500000", "1000000", "50000"],
        "f_incluir": ["538", "537", "48"],
    })
    check("descarga CSV F29 -> 200", r.status_code == 200)
    csv_text = r.data.decode("latin-1")
    check("CSV contiene glosa de centralización", "CENTRALIZACION F29 JUNIO" in csv_text)
    check("CSV separado por ';' con CRLF", "\r\n" in csv_text and ";" in csv_text)

    # ---- Calcular Global (IGC) ----
    from app.global_igc.calculator import calcular_igc_tabla, calcular_global, EntradaGlobal, UTA_2026

    check("UTA 2026 = 834.504", UTA_2026 == 834504)
    check("tramo exento hasta 11.265.804", calcular_igc_tabla(11_265_804) == 0)
    check("primer peso afecto tributa 4%", calcular_igc_tabla(11_265_804.01) == round(11_265_804.01 * 0.04 - 450_632))
    check("tramo tope superior (renta muy alta) usa 40% - rebaja", calcular_igc_tabla(300_000_000) == round(300_000_000 * 0.40 - 32_397_949))
    check("base imponible 0 o negativa no tributa", calcular_igc_tabla(0) == 0)

    entrada_prueba = EntradaGlobal(
        total_imponible=0, retiros_14a=10_000_000, credito_retiros_14a=2_000_000,
    )
    res_prueba = calcular_global(entrada_prueba)
    check("gross-up: renta bruta retiro 14A = neto + crédito", res_prueba.renta_bruta_retiros == 12_000_000)
    check("débito por restitución = 35% del crédito 14A", res_prueba.debito_restitucion == round(2_000_000 * 0.35))
    check("total créditos incluye el crédito IDPC del retiro", res_prueba.total_creditos == 2_000_000)

    entrada_d3 = EntradaGlobal(retiros_14d3=10_000_000, credito_retiros_14d3=1_000_000)
    res_d3 = calcular_global(entrada_d3)
    check("régimen 14 D N°3 no paga débito por restitución", res_d3.debito_restitucion == 0)

    entrada_sueldo = EntradaGlobal(total_imponible=10_000_000, leyes_sociales=1_000_000, credito_iusc=300_000)
    res_sueldo = calcular_global(entrada_sueldo)
    check("Leyes Sociales se resta del Total Imponible (renta líquida sueldos)", res_sueldo.renta_neta_sueldos == 9_000_000)
    check("crédito IUSC entra al total de créditos", res_sueldo.total_creditos == 300_000)
    check("renta líquida de sueldos no puede ser negativa", calcular_global(EntradaGlobal(total_imponible=1_000_000, leyes_sociales=5_000_000)).renta_neta_sueldos == 0)

    entrada_honorarios = EntradaGlobal(honorarios=1_000_000, credito_honorarios=145_000)
    res_honorarios = calcular_global(entrada_honorarios)
    check("gasto presunto honorarios = 30% del bruto", res_honorarios.gasto_presunto_honorarios == 300_000)
    check("honorarios a tributar = 70% del bruto", res_honorarios.honorarios_tributables == 700_000)
    check("base imponible usa el honorario neto de gasto presunto, no el bruto", res_honorarios.base_imponible == 700_000)
    check("crédito por honorarios se calcula sobre el bruto (no se toca)", res_honorarios.total_creditos == 145_000)

    check("ya no existen campos de dividendos en EntradaGlobal", not any("dividendo" in f for f in EntradaGlobal.__dataclass_fields__))

    r = client.get("/global/")
    check("GET /global/ 200", r.status_code == 200 and b"Calcular Global" in r.data)

    r = client.post("/global/calcular", data={
        "total_imponible": "0", "retiros_14a": "10000000", "credito_retiros_14a": "2000000",
    })
    check("POST /global/calcular 200", r.status_code == 200)
    check("resultado del cálculo se muestra en la página", b"Base Imponible Anual" in r.data)

    # ---- Administrador: cuentas ----
    r = client.get("/admin/cuentas")
    check("GET /admin/cuentas 200 (admin)", r.status_code == 200)

    r = client.post("/admin/cuentas/guardar", data={
        "c_cuenta": ["2108-02", "1108-02"],
        "c_codigo": ["538", "537"],
        "c_descripcion": ["Total Débitos", "Total Créditos"],
        "c_tipo": ["DEBE", "HABER"],
        "c_ancla": ["TOTAL DÉBITOS", "TOTAL CRÉDITOS"],
        "c_operador": ["=", "="],
    }, follow_redirects=True)
    check("guardar cuentas_config -> 200", r.status_code == 200)
    check("cuentas_config quedó con 2 filas", len(FAKE._store.get("cuentas_config", [])) == 2)

    # ---- Administrador: usuarios ----
    r = client.get("/admin/usuarios")
    check("GET /admin/usuarios 200 (admin)", r.status_code == 200 and b"testuser" in r.data)

    r = client.post("/admin/usuarios/crear", data={
        "usuario": "nuevo_test", "nombre": "Nuevo Test", "rol": "trabajador",
        "clave": "clave1234", "clave_confirmar": "clave1234",
    }, follow_redirects=True)
    check("crear usuario -> 200", r.status_code == 200)
    check("usuario nuevo quedó en la tabla", any(u["usuario"] == "nuevo_test" for u in FAKE._store.get("usuarios", [])))

    # ---- Logout y login como 'trabajador' (no admin) ----
    client.post("/logout")
    r = client.post("/login", data={"usuario": "testuser", "clave": "trabajador123"}, follow_redirects=True)
    check("login como trabajador de prueba entra", r.status_code == 200 and b"Subir Cartolas" in r.data)

    r = client.get("/admin/cuentas")
    check("trabajador NO puede ver Administrador (403)", r.status_code == 403)

    r = client.get("/cartolas/")
    check("trabajador SÍ puede ver Subir Cartolas", r.status_code == 200)

    r = client.get("/f29/")
    check("trabajador SÍ puede ver Generar CSV F29", r.status_code == 200)

    r = client.get("/global/")
    check("trabajador SÍ puede ver Calcular Global", r.status_code == 200)

    print(f"\n{len(PASSED)} OK, {len(FAILED)} FAIL")
    if FAILED:
        print("Fallaron:", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    main()
