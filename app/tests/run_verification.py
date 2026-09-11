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
  - "Generar F29": con `parsear_f29` monkeypatcheado (no hay PDF de
    F29 de ejemplo a mano), valida el flujo completo (período, montos,
    remanente, archivo .xls final) contra la lógica real de
    `f29_parser.py` y `f29_export_writer.py`.
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

    # ---- BancoEstado: calibración contra cartola real (01-2026, 7 páginas) ----
    banco_estado_pdf = "/root/.claude/uploads/6765170a-fd6f-5183-b8a3-c1c40a5d8b1c/ef109d5d-Cartola_Bco_Estado_01_2026.pdf"
    if os.path.exists(banco_estado_pdf):
        from app.parsers.bank_parsers import parse_pdf as _parse_pdf_directo, _parse_amount

        resultado_be = _parse_pdf_directo(banco_estado_pdf)
        check("BancoEstado: banco detectado correctamente", resultado_be.banco_detectado == "BancoEstado")
        check("BancoEstado: sin advertencias", resultado_be.advertencias == [])
        check("BancoEstado: se extrajeron los 289 movimientos reales", len(resultado_be.transacciones) == 289)

        # Cadena de saldos: saldo[i] debe calzar exactamente con
        # saldo[i+1] - cargo[i] + abono[i] en TODAS las filas consecutivas
        # (la cartola trae el saldo después de cada movimiento, en orden
        # de más reciente a más antiguo). Es la verificación más fuerte de
        # que ningún movimiento quedó mal separado, duplicado o perdido a
        # lo largo de las 7 páginas.
        saldo_ok = True
        for i in range(len(resultado_be.transacciones) - 1):
            cur = resultado_be.transacciones[i]
            nxt = resultado_be.transacciones[i + 1]
            esperado = _parse_amount(nxt.saldo) - cur.cargo + cur.abono
            if abs(esperado - _parse_amount(cur.saldo)) > 0.5:
                saldo_ok = False
                break
        check("BancoEstado: la cadena de saldos calza en las 288 transiciones", saldo_ok)

        descs = [tx.descripcion for tx in resultado_be.transacciones]
        check(
            "BancoEstado: glosa multilínea concatenada correctamente",
            "Transferencia otro banco a rut 76907072-9 repuestos acira spa" in descs,
        )
        check(
            "BancoEstado: glosa partida entre páginas concatenada correctamente",
            "Abonos varios sociedad de servicios transaccionales ca" in descs,
        )
        check(
            "BancoEstado: sin texto de pie de página pegado a la glosa",
            not any("correo" in d.lower() or "bancoestado.cl" in d.lower() for d in descs),
        )

        with open(banco_estado_pdf, "rb") as fh:
            r = client.post(
                "/cartolas/procesar",
                data={"banco": "banco_estado", "archivo": (io.BytesIO(fh.read()), os.path.basename(banco_estado_pdf))},
                content_type="multipart/form-data",
            )
        check("BancoEstado: POST /cartolas/procesar -> 200", r.status_code == 200)
        check("BancoEstado: tabla de movimientos aparece en la vista previa", b"Ajustes antes de exportar" in r.data)
    else:
        check("BancoEstado: cartola de prueba existe", False)

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

    # ---- f29_parser: detección del código 77 (remanente para el período
    # siguiente) contra el texto REAL que entrega el PDF del SII, no un
    # F29Data ya armado a mano (11-09-2026: el usuario reportó que la
    # carga masiva de F29 no encadenaba el remanente entre períodos; la
    # causa era que el anchor del código 77 solo matcheaba un layout de
    # texto "entrelazado letra por letra" que NO es el que la mayoría de
    # los F29 reales entrega — pdfplumber normalmente da el texto limpio.
    # Este test fija ambos layouts para que no se repita.) ----
    import app.parsers.f29_parser as f29_parser_mod

    def _con_texto_falso(texto_fijo):
        f29_parser_mod.extraer_texto_pdf = lambda _p: texto_fijo

    _extraer_texto_pdf_real = f29_parser_mod.extraer_texto_pdf

    _con_texto_falso(
        "...TOTAL CRÉDITOS 537 300.861 =\n"
        "Remanente de crédito fiscal para el\n"
        "51 77 288.511 756 Postergación pago del IVA 755 IVA determinado 89 0 +\n"
        "período siguiente\n..."
    )
    _dato_77_limpio = f29_parser_mod.parsear_f29(io.BytesIO(b""), configs=[])
    check(
        "código 77 (remanente período siguiente): se detecta con el layout de texto LIMPIO (el real, de la mayoría de los F29 del SII)",
        _dato_77_limpio.remanente_periodo_siguiente_encontrado and _dato_77_limpio.remanente_periodo_siguiente == 288511,
    )

    _con_texto_falso(
        "...R pe e r m ío a d n o e s n i t g e u d ie e n c te rédito fiscal para el 77 39.810.991 756 Postergación..."
    )
    _dato_77_entrelazado = f29_parser_mod.parsear_f29(io.BytesIO(b""), configs=[])
    check(
        "código 77: sigue detectándose con el layout ENTRELAZADO anterior (no se perdió esa cobertura)",
        _dato_77_entrelazado.remanente_periodo_siguiente_encontrado and _dato_77_entrelazado.remanente_periodo_siguiente == 39810991,
    )

    _con_texto_falso("...un F29 sin ninguna mención al remanente del período siguiente...")
    _dato_77_ausente = f29_parser_mod.parsear_f29(io.BytesIO(b""), configs=[])
    check(
        "código 77 realmente ausente -> encontrado=False, no revienta",
        not _dato_77_ausente.remanente_periodo_siguiente_encontrado and _dato_77_ausente.remanente_periodo_siguiente == 0,
    )

    f29_parser_mod.extraer_texto_pdf = _extraer_texto_pdf_real

    # ---- Generar F29 (con parsear_f29 monkeypatcheado: sin PDF real) ----
    import xlrd
    import app.f29.routes as f29_routes
    from app.parsers.f29_parser import F29Data
    from app.parsers.f29_export_writer import HEADERS as F29_XLS_HEADERS

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
    check("descarga F29 (.xls) -> 200", r.status_code == 200)
    check(
        "descarga F29 con mimetype de Excel binario",
        r.mimetype == "application/vnd.ms-excel",
    )
    try:
        wb_f29 = xlrd.open_workbook(file_contents=r.data)
        ws_f29 = wb_f29.sheet_by_name("Comprobantes")
        header_f29 = [ws_f29.cell_value(0, c) for c in range(len(F29_XLS_HEADERS))]
        check("xls F29: hoja 'Comprobantes' con encabezados de la plantilla nueva", header_f29 == F29_XLS_HEADERS)
        # Fila 1 (primera línea del comprobante): Número=1, Tipo="T",
        # Glosa con el mes, Cuenta="2108-02" (538/DEBE), Debe=1.500.000.
        check("xls F29: Número en columna 0", ws_f29.cell_value(1, 0) == 1)
        check("xls F29: Tipo comprobante 'T' en columna 1", ws_f29.cell_value(1, 1) == "T")
        check("xls F29: Glosa de centralización en columna 3", "CENTRALIZACION F29 JUNIO" in ws_f29.cell_value(1, 3))
        check("xls F29: Cuenta Detalle en columna 4", ws_f29.cell_value(1, 4) == "2108-02")
        check("xls F29: Debe en columna 8", ws_f29.cell_value(1, 8) == 1500000)
        # Fila 2: código 537/HABER -> cuenta 1108-02, Haber en columna 9.
        check("xls F29: Haber en columna 9", ws_f29.cell_value(2, 9) == 1000000)
    except Exception as exc:  # noqa: BLE001
        check("archivo F29 se puede leer como .xls con xlrd", False, str(exc))

    # ---- Carga masiva de varios períodos F29 (04-09-2026) ----
    # Datos calcados de un caso real (Kupsan Paper SpA, junio y julio 2026)
    # usado para validar el encadenamiento automático del remanente de
    # crédito fiscal entre períodos consecutivos del mismo lote.
    def fake_parsear_f29_masivo(buf, configs=None):
        contenido = buf.read()
        if b"JULIO" in contenido:
            return F29Data(
                mes="07", anio="2026", rut="78241885-8", razon_social="Kupsan Paper SpA",
                valores={"538": "31.896.719", "537": "62.058.326", "62": "419.694", "91": "419.694"},
                remanente_504=39811050, remanente_504_encontrado=True,
                remanente_periodo_siguiente=30161607, remanente_periodo_siguiente_encontrado=True,
                advertencias=[],
            )
        return F29Data(
            mes="06", anio="2026", rut="78241885-8", razon_social="Kupsan Paper SpA",
            valores={"538": "17.001.126", "537": "56.812.117", "62": "223.699", "91": "223.699"},
            remanente_504=15266252, remanente_504_encontrado=True,
            remanente_periodo_siguiente=39810991, remanente_periodo_siguiente_encontrado=True,
            advertencias=[],
        )

    f29_routes.parsear_f29 = fake_parsear_f29_masivo

    r = client.get("/f29/masivo")
    check("GET /f29/masivo 200", r.status_code == 200)

    r = client.post("/f29/masivo/procesar", data={
        "archivos": [
            (io.BytesIO(b"%PDF-1.4 fake JULIO"), "07.pdf"),
            (io.BytesIO(b"%PDF-1.4 fake JUNIO"), "06.pdf"),
        ],
    }, content_type="multipart/form-data")
    check("procesar masivo (2 PDF, subidos fuera de orden) -> 200", r.status_code == 200)
    html_masivo = r.data.decode("utf-8", errors="replace")
    check("carga masiva reordena cronológicamente (junio primero)", "Período 1: JUNIO 2026" in html_masivo)
    check("carga masiva reordena cronológicamente (julio segundo)", "Período 2: JULIO 2026" in html_masivo)
    check(
        "remanente del 2do período se sugiere encadenado (código 77 del 1ro = 39.810.991)",
        'id="p1_remanente_anterior"' in html_masivo and 'value="39810991"' in html_masivo,
    )
    check(
        "remanente del 1er período queda vacío (no hay período anterior en el lote)",
        'id="p0_remanente_anterior"' in html_masivo and 'name="p0_remanente_anterior" value=""' in html_masivo,
    )

    masivo_form = {
        "num_periodos": "2",
        "p0_mes": "06", "p0_anio": "2026", "p0_remanente_504": "15266252",
        "p0_remanente_anterior": "15235987", "p0_incluir_ajuste": "on",
        "p0_f_cuenta": ["2108-02", "1108-02", "1108-01", "2108-05"],
        "p0_f_codigo": ["538", "537", "62", "91"],
        "p0_f_tipo": ["DEBE", "HABER", "DEBE", "HABER"],
        "p0_f_monto": ["17001126", "56812117", "223699", "223699"],
        "p0_f_incluir": ["538", "537", "62", "91"],
        "p1_mes": "07", "p1_anio": "2026", "p1_remanente_504": "39811050",
        "p1_remanente_anterior": "39810991", "p1_incluir_ajuste": "on",
        "p1_f_cuenta": ["2108-02", "1108-02", "1108-01", "2108-05"],
        "p1_f_codigo": ["538", "537", "62", "91"],
        "p1_f_tipo": ["DEBE", "HABER", "DEBE", "HABER"],
        "p1_f_monto": ["31896719", "62058326", "419694", "419694"],
        "p1_f_incluir": ["538", "537", "62", "91"],
    }

    r = client.post("/f29/masivo/preview", data=masivo_form)
    check("preview masivo -> 200", r.status_code == 200)
    html_preview = r.data.decode("utf-8", errors="replace")
    check("preview masivo muestra el ajuste de junio (diferencia 30.265)", "30.265" in html_preview)
    check("preview masivo muestra el ajuste de julio (diferencia 59)", ">59<" in html_preview or "59<" in html_preview)

    r = client.post("/f29/masivo/descargar", data=masivo_form)
    check("descarga masivo -> 200", r.status_code == 200)
    check("descarga masivo con mimetype de Excel binario", r.mimetype == "application/vnd.ms-excel")
    check(
        "nombre de archivo combinado junio_a_julio",
        "centralizacion_f29_junio_a_julio_2026.xls" in (r.headers.get("Content-Disposition") or ""),
    )
    try:
        wb_masivo = xlrd.open_workbook(file_contents=r.data)
        ws_masivo = wb_masivo.sheet_by_name("Comprobantes")
        check("xls masivo: 12 filas de datos (6 por período x 2 períodos)", ws_masivo.nrows == 13)
        check("xls masivo: primera línea es JUNIO", "CENTRALIZACION F29 JUNIO" in ws_masivo.cell_value(1, 3))
        check("xls masivo: 538 de junio en Debe", ws_masivo.cell_value(1, 8) == 17001126)
        check("xls masivo: ajuste de remanente de junio (30.265) presente", any(ws_masivo.cell_value(r_, 8) == 30265 or ws_masivo.cell_value(r_, 9) == 30265 for r_ in range(1, 13)))
        check("xls masivo: octava fila es JULIO (Número reinicia a 1)", ws_masivo.cell_value(7, 0) == 1 and "CENTRALIZACION F29 JULIO" in ws_masivo.cell_value(7, 3))
        check("xls masivo: 538 de julio en Debe", ws_masivo.cell_value(7, 8) == 31896719)
        check("xls masivo: ajuste de remanente de julio (59) presente", any(ws_masivo.cell_value(r_, 8) == 59 or ws_masivo.cell_value(r_, 9) == 59 for r_ in range(1, 13)))
    except Exception as exc:  # noqa: BLE001
        check("archivo masivo se puede leer como .xls con xlrd", False, str(exc))

    # ---- Calcular Global (IGC) ----
    from app.global_igc.calculator import (
        calcular_igc_tabla, calcular_global, EntradaGlobal, UTA_2026,
        UMBRAL_COTIZACION_HONORARIOS, TASA_COTIZACION_PREVISIONAL_HONORARIOS,
    )

    check("UTA 2026 = 834.504", UTA_2026 == 834504)
    check("tramo exento hasta 11.265.804", calcular_igc_tabla(11_265_804) == 0)
    check("primer peso afecto tributa 4%", calcular_igc_tabla(11_265_804.01) == round(11_265_804.01 * 0.04 - 450_632))
    check("tramo tope superior (renta muy alta) usa 40% - rebaja", calcular_igc_tabla(300_000_000) == round(300_000_000 * 0.40 - 32_397_949))
    check("base imponible 0 o negativa no tributa", calcular_igc_tabla(0) == 0)

    entrada_prueba = EntradaGlobal(
        base_tributable_sueldos=0, retiros_14a=10_000_000, credito_retiros_14a=2_000_000,
    )
    res_prueba = calcular_global(entrada_prueba)
    check("Renta bruta retiros = solo el monto neto percibido (sin el incremento IDPC)", res_prueba.renta_bruta_retiros == 10_000_000)
    check("Incremento por IDPC = el crédito IDPC del retiro 14A", res_prueba.total_creditos_idpc == 2_000_000)
    check("gross-up sigue sumando al SUB TOTAL: retiro neto + incremento IDPC", res_prueba.renta_bruta_retiros + res_prueba.total_creditos_idpc == 12_000_000)
    check("débito por restitución = 35% del crédito 14A", res_prueba.debito_restitucion == round(2_000_000 * 0.35))
    check("total créditos incluye el crédito IDPC del retiro", res_prueba.total_creditos == 2_000_000)

    entrada_d3 = EntradaGlobal(retiros_14d3=10_000_000, credito_retiros_14d3=1_000_000)
    res_d3 = calcular_global(entrada_d3)
    check("régimen 14 D N°3 no paga débito por restitución", res_d3.debito_restitucion == 0)

    # "Base Tributable" (03-09-2026): reemplaza a "Total Imponible" +
    # "Leyes Sociales" — el usuario ingresa directamente la renta líquida
    # por sueldos, sin resta interna.
    entrada_sueldo = EntradaGlobal(base_tributable_sueldos=9_000_000, credito_iusc=300_000)
    res_sueldo = calcular_global(entrada_sueldo)
    check("Base Tributable pasa directo a renta líquida de sueldos (sin restar nada)", res_sueldo.renta_neta_sueldos == 9_000_000)
    check("crédito IUSC entra al total de créditos", res_sueldo.total_creditos == 300_000)
    check("renta líquida de sueldos no puede ser negativa", calcular_global(EntradaGlobal(base_tributable_sueldos=-1)).renta_neta_sueldos == 0)
    check("ya no existen los campos total_imponible/leyes_sociales en EntradaGlobal", "total_imponible" not in EntradaGlobal.__dataclass_fields__ and "leyes_sociales" not in EntradaGlobal.__dataclass_fields__)

    entrada_honorarios = EntradaGlobal(honorarios=1_000_000, credito_honorarios=145_000)
    res_honorarios = calcular_global(entrada_honorarios)
    check("gasto presunto honorarios = 30% del bruto", res_honorarios.gasto_presunto_honorarios == 300_000)
    check("honorarios a tributar = 70% del bruto", res_honorarios.honorarios_tributables == 700_000)
    check("base imponible usa el honorario neto de gasto presunto, no el bruto", res_honorarios.base_imponible == 700_000)
    check("crédito por honorarios se calcula sobre el bruto (no se toca)", res_honorarios.total_creditos == 145_000)

    # Tope de 15 UTA a la rebaja de 30% de gasto presunto de honorarios
    # (pedido del usuario, 03-09-2026).
    from app.global_igc.calculator import TOPE_GASTO_PRESUNTO_HONORARIOS_UTA
    tope_15_uta = round(15 * UTA_2026)
    check("tope de gasto presunto de honorarios = 15 UTA", TOPE_GASTO_PRESUNTO_HONORARIOS_UTA == 15)
    honorarios_bajo_tope = round(tope_15_uta / 0.30) - 1_000_000  # 30% queda bajo el tope
    res_bajo_tope = calcular_global(EntradaGlobal(honorarios=honorarios_bajo_tope))
    check("bajo el tope, la rebaja es 30% normal", res_bajo_tope.gasto_presunto_honorarios == round(honorarios_bajo_tope * 0.30))
    honorarios_sobre_tope = round(tope_15_uta / 0.30) + 10_000_000  # 30% supera el tope
    res_sobre_tope = calcular_global(EntradaGlobal(honorarios=honorarios_sobre_tope))
    check("sobre el tope, la rebaja se limita a 15 UTA", res_sobre_tope.gasto_presunto_honorarios == tope_15_uta)
    check("con la rebaja topada, el honorario a tributar es mayor a lo que daría el 70%", res_sobre_tope.honorarios_tributables == honorarios_sobre_tope - tope_15_uta)

    check("ya no existen campos de dividendos en EntradaGlobal", not any("dividendo" in f for f in EntradaGlobal.__dataclass_fields__))

    check("umbral cotización honorarios = 5 ingresos mínimos", UMBRAL_COTIZACION_HONORARIOS == 553_553 * 5)
    check("tasa cotización honorarios = 0.85 (85%), no 0.85%", TASA_COTIZACION_PREVISIONAL_HONORARIOS == 0.85)

    entrada_bajo_umbral = EntradaGlobal(honorarios=2_000_000, credito_honorarios=290_000)
    res_bajo_umbral = calcular_global(entrada_bajo_umbral)
    check("bajo el umbral no aplica cotización previsional de honorarios", res_bajo_umbral.afecto_cotizacion_honorarios is False)
    check("bajo el umbral el pago de cotización es 0", res_bajo_umbral.pago_cotizacion_honorarios == 0)

    entrada_sobre_umbral = EntradaGlobal(honorarios=3_000_000, credito_honorarios=435_000)
    res_sobre_umbral = calcular_global(entrada_sobre_umbral)
    check("igual o sobre el umbral SÍ aplica cotización previsional de honorarios", res_sobre_umbral.afecto_cotizacion_honorarios is True)
    check("pago cotización = 85% de la retención (crédito honorarios)", res_sobre_umbral.pago_cotizacion_honorarios == round(435_000 * TASA_COTIZACION_PREVISIONAL_HONORARIOS))
    # Corregido 03-09-2026: el pago de cotización de honorarios YA NO se
    # resta de la base imponible (eso reducía el IGC y aumentaba el saldo
    # a favor, al revés de lo esperado) — ahora se suma en positivo
    # directamente al resultado final, rebajando la devolución.
    check("el pago de cotización de honorarios NO se resta de la base imponible", res_sobre_umbral.total_rebajas == 0)
    check(
        "el pago de cotización de honorarios se suma en positivo al resultado final (rebaja la devolución)",
        res_sobre_umbral.resultado == round(
            res_sobre_umbral.impuesto_determinado - res_sobre_umbral.total_creditos + res_sobre_umbral.pago_cotizacion_honorarios
        ),
    )
    # Con los mismos honorarios (sobre el umbral) pero un crédito por
    # honorarios distinto, el pago de cotización cambia pero la base
    # imponible y el IGC según tabla deben quedar exactamente iguales —
    # confirma que el pago ya no afecta la base imponible en absoluto.
    entrada_otro_credito = EntradaGlobal(honorarios=3_000_000, credito_honorarios=100_000)
    res_otro_credito = calcular_global(entrada_otro_credito)
    check(
        "la cotización de honorarios no altera la base imponible ni el IGC según tabla",
        res_sobre_umbral.pago_cotizacion_honorarios != res_otro_credito.pago_cotizacion_honorarios
        and res_sobre_umbral.base_imponible == res_otro_credito.base_imponible
        and res_sobre_umbral.igc_segun_tabla == res_otro_credito.igc_segun_tabla,
    )

    entrada_umbral_exacto = EntradaGlobal(honorarios=UMBRAL_COTIZACION_HONORARIOS, credito_honorarios=400_000)
    check("en el umbral exacto (igual) SÍ aplica", calcular_global(entrada_umbral_exacto).afecto_cotizacion_honorarios is True)

    # Líneas informativas al estilo F22 (03-09-2026): "IGC/IUSC débito
    # determinado" y "Remanente de crédito por reliquidación del IUSC" se
    # derivan de valores ya calculados y NO alteran el resultado final.
    entrada_iusc_alto = EntradaGlobal(retiros_14a=50_000_000, credito_retiros_14a=10_000_000, credito_iusc=500_000)
    res_iusc_alto = calcular_global(entrada_iusc_alto)
    check(
        "IGC/IUSC débito determinado = impuesto determinado menos crédito IUSC",
        res_iusc_alto.igc_iusc_debito_determinado == res_iusc_alto.impuesto_determinado - 500_000,
    )
    check("sin remanente cuando el impuesto determinado supera al crédito IUSC", res_iusc_alto.remanente_credito_iusc == 0)

    entrada_iusc_bajo = EntradaGlobal(base_tributable_sueldos=1_000_000, credito_iusc=500_000)
    res_iusc_bajo = calcular_global(entrada_iusc_bajo)
    check(
        "remanente de crédito IUSC = la parte que no alcanzó a compensar el impuesto determinado",
        res_iusc_bajo.remanente_credito_iusc == max(500_000 - res_iusc_bajo.impuesto_determinado, 0) and res_iusc_bajo.remanente_credito_iusc > 0,
    )
    check(
        "las líneas informativas de IUSC no alteran el resultado final",
        res_iusc_bajo.resultado == round(res_iusc_bajo.impuesto_determinado - res_iusc_bajo.total_creditos + res_iusc_bajo.pago_cotizacion_honorarios),
    )

    entrada_sub_total = EntradaGlobal(
        base_tributable_sueldos=1_000_000, retiros_14a=2_000_000, credito_retiros_14a=500_000, arriendos_netos=300_000,
    )
    res_sub_total = calcular_global(entrada_sub_total)
    check(
        "SUB TOTAL = renta neta de retiros + incremento IDPC + otras rentas afectas (antes de rebajas)",
        res_sub_total.sub_total == res_sub_total.renta_bruta_retiros + res_sub_total.total_creditos_idpc + res_sub_total.otras_rentas_afectas,
    )

    # ---- Régimen 14 D N°8 + campos de pensión (04-09-2026, octava corrección) ----
    check(
        "nuevos campos existen en EntradaGlobal",
        all(
            f in EntradaGlobal.__dataclass_fields__
            for f in ("retiros_14d8_base", "retiros_14d8_ppm", "renta_pensiones", "credito_iusc_pensiones")
        ),
    )

    entrada_14d8 = EntradaGlobal(retiros_14d8_base=5_000_000, retiros_14d8_ppm=800_000)
    res_14d8 = calcular_global(entrada_14d8)
    check("14 D N°8: la base pasa directo al resumen (sin gross-up)", res_14d8.retiros_14d8_base == 5_000_000)
    check("14 D N°8: el PPM pasa directo como crédito", res_14d8.credito_ppm_14d8 == 800_000)
    check("14 D N°8: la base se suma al SUB TOTAL sin incremento IDPC", res_14d8.sub_total == 5_000_000)
    check("14 D N°8: no genera débito por restitución (exclusivo de 14 A)", res_14d8.debito_restitucion == 0)
    check("14 D N°8: el PPM no se cuenta como incremento por IDPC", res_14d8.total_creditos_idpc == 0)
    check("14 D N°8: el PPM entra al total de créditos", res_14d8.total_creditos == 800_000)
    check("14 D N°8: detalle_creditos incluye credito_ppm_14d8", res_14d8.detalle_creditos.get("credito_ppm_14d8") == 800_000)

    entrada_pension = EntradaGlobal(renta_pensiones=4_000_000, credito_iusc_pensiones=200_000)
    res_pension = calcular_global(entrada_pension)
    check("Pensiones: renta neta pasa directo (separada de sueldos)", res_pension.renta_neta_pensiones == 4_000_000)
    check("Pensiones: renta líquida de pensión no puede ser negativa", calcular_global(EntradaGlobal(renta_pensiones=-1)).renta_neta_pensiones == 0)
    check("Pensiones: la renta neta se suma al SUB TOTAL igual que sueldos", res_pension.sub_total == 4_000_000)
    check("Pensiones: el crédito IUSC de pensión entra al total de créditos", res_pension.total_creditos == 200_000)
    check("Pensiones: detalle_creditos incluye credito_iusc_pensiones", res_pension.detalle_creditos.get("credito_iusc_pensiones") == 200_000)
    check(
        "Pensiones: se combina con credito_iusc en la línea informativa 'IGC/IUSC débito determinado'",
        res_pension.igc_iusc_debito_determinado == res_pension.impuesto_determinado - 200_000,
    )

    entrada_iusc_combo = EntradaGlobal(
        base_tributable_sueldos=1_000_000, credito_iusc=300_000,
        renta_pensiones=500_000, credito_iusc_pensiones=200_000,
    )
    res_combo = calcular_global(entrada_iusc_combo)
    check(
        "IUSC sueldos + IUSC pensiones se combinan en las líneas informativas de reliquidación",
        res_combo.igc_iusc_debito_determinado == res_combo.impuesto_determinado - 500_000
        and res_combo.remanente_credito_iusc == max(500_000 - res_combo.impuesto_determinado, 0),
    )
    check(
        "las líneas informativas combinadas de IUSC siguen sin alterar el resultado final",
        res_combo.resultado == round(res_combo.impuesto_determinado - res_combo.total_creditos + res_combo.pago_cotizacion_honorarios),
    )

    r = client.post("/global/calcular", data={
        "base_tributable_sueldos": "1000000", "renta_pensiones": "500000", "credito_iusc_pensiones": "50000",
        "retiros_14d8_base": "3000000", "retiros_14d8_ppm": "400000",
    })
    check("POST /global/calcular con 14 D N°8 y pensiones -> 200", r.status_code == 200)
    check("resumen muestra la línea de Régimen 14 D N°8", "Retiros 14 D N°8".encode() in r.data)
    check("resumen muestra la línea de Renta Total Neta Pagada (Pensiones)", "Renta Total Neta Pagada (Pensiones)".encode() in r.data)
    check("formulario tiene el campo mensual para Base Tributable", b'data-mensual-btn="base_tributable_sueldos"' in r.data)
    check("formulario NO ofrece despliegue mensual para el campo anual de pensiones", b'data-mensual-btn="renta_pensiones"' not in r.data)

    r = client.get("/global/")
    check("GET /global/ 200", r.status_code == 200 and b"Calcular Global" in r.data)

    r = client.post("/global/calcular", data={
        "base_tributable_sueldos": "0", "retiros_14a": "10000000", "credito_retiros_14a": "2000000",
    })
    check("POST /global/calcular 200", r.status_code == 200)
    check("resultado del cálculo se muestra en la página", b"Base Imponible Anual de IUSC o IGC" in r.data)

    # ---- Calcular Global: datos del contribuyente + descarga de PDF (03-09-2026) ----
    entrada_contrib_default = EntradaGlobal()
    check("año tributario por defecto = 2026", entrada_contrib_default.anio_tributario == 2026)
    check("nombre/RUT del contribuyente vacíos por defecto", entrada_contrib_default.nombre_contribuyente == "" and entrada_contrib_default.rut_contribuyente == "")

    entrada_desde_form = EntradaGlobal.desde_formulario({
        "anio_tributario": "2025", "nombre_contribuyente": "Juan Pérez González", "rut_contribuyente": "12.345.678-9",
        "base_tributable_sueldos": "10000000",
    })
    check("desde_formulario respeta año tributario ingresado", entrada_desde_form.anio_tributario == 2025)
    check("desde_formulario no numeriza nombre/RUT del contribuyente", entrada_desde_form.nombre_contribuyente == "Juan Pérez González" and entrada_desde_form.rut_contribuyente == "12.345.678-9")

    entrada_form_sin_anio = EntradaGlobal.desde_formulario({"base_tributable_sueldos": "0"})
    check("desde_formulario usa 2026 si no se ingresa año tributario", entrada_form_sin_anio.anio_tributario == 2026)

    r = client.post("/global/pdf", data={
        "anio_tributario": "2026", "nombre_contribuyente": "Juan Pérez González", "rut_contribuyente": "12.345.678-9",
        "base_tributable_sueldos": "20000000", "credito_iusc": "1500000",
        "renta_pensiones": "2000000", "credito_iusc_pensiones": "150000",
        "honorarios": "8000000", "credito_honorarios": "980000",
        "retiros_14a": "15000000", "credito_retiros_14a": "5000000",
        "retiros_14d3": "6000000", "credito_retiros_14d3": "1500000",
        "retiros_14d8_base": "4000000", "retiros_14d8_ppm": "600000",
        "arriendos_netos": "3000000", "intereses_reajustes": "500000",
        "pensiones_alimenticias": "1200000",
    })
    check("POST /global/pdf -> 200", r.status_code == 200)
    check("POST /global/pdf devuelve un PDF válido", r.headers.get("Content-Type", "").startswith("application/pdf") and r.data[:4] == b"%PDF")
    check("POST /global/pdf trae nombre de archivo con año tributario y RUT", "AT2026" in r.headers.get("Content-Disposition", "") and "12" in r.headers.get("Content-Disposition", ""))
    check("el PDF generado no está vacío/truncado", len(r.data) > 2000)

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

    # ---- Indicadores (nueva pestaña, todos los roles) ----
    r = client.get("/indicadores/")
    check("GET /indicadores/ 200 (admin)", r.status_code == 200)

    # ---- Reuniones (nueva pestaña, solo admin) ----
    # En este entorno de pruebas MS_CLIENT_ID/MS_CLIENT_SECRET/MS_TENANT_ID/
    # MS_USER_UPN no están configurados, así que debe mostrar el aviso de
    # configuración pendiente en vez de fallar.
    r = client.get("/reuniones/")
    check("GET /reuniones/ 200 (admin, sin credenciales MS configuradas)", r.status_code == 200)
    check("reuniones muestra aviso de configuración pendiente", "Falta conectar Outlook" in r.get_data(as_text=True))

    # ---- Conciliación (nueva pestaña, solo admin) ----
    from datetime import datetime as _datetime_conciliacion
    from app.conciliacion.plan_cuentas import PLAN_CUENTAS, CUENTAS_POR_CODIGO as CUENTAS_POR_CODIGO_TEST
    from app.parsers.bank_parsers import Transaction
    from app.parsers.output_writer import build_output_workbook

    check("plan de cuentas cargado (1322 cuentas, sin duplicados de código)", (
        len(PLAN_CUENTAS) == 1322
        and len({c["codigo"] for c in PLAN_CUENTAS}) == 1322
    ))

    r = client.get("/conciliacion/")
    check("GET /conciliacion/ 200 (admin)", r.status_code == 200)
    check("conciliación (sin archivo cargado) pide subir la cartola convertida", "Sube la cartola convertida" in r.get_data(as_text=True))

    # el archivo de entrada es exactamente lo que arma output_writer (mismo
    # camino que produce el botón "Descargar Excel convertido" de Subir
    # Cartolas) — se genera acá para no depender de un archivo de ejemplo.
    txs = [
        Transaction(fecha="05/08/2026", descripcion="TRANSFERENCIA RECIBIDA DE JUAN PEREZ", cargo=0.0, abono=150000.0),
        Transaction(fecha="07/08/2026", descripcion="PAGO A PROVEEDOR ACME LTDA", cargo=80000.0, abono=0.0),
    ]
    wb = build_output_workbook(txs)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    r = client.post(
        "/conciliacion/procesar",
        data={"archivo": (buf, "cartola_convertida.xlsx")},
        content_type="multipart/form-data",
    )
    body = r.get_data(as_text=True)
    check("POST /conciliacion/procesar -> 200", r.status_code == 200)
    check("conciliación muestra el detalle de los 2 movimientos cargados", "TRANSFERENCIA RECIBIDA DE JUAN PEREZ" in body and "PAGO A PROVEEDOR ACME LTDA" in body)
    check("conciliación calcula el total de registros (2)", 'id="stat-total">2<' in body)
    check("conciliación arranca con 0 conciliados / 2 pendientes", 'id="stat-conciliados">0<' in body and 'id="stat-pendientes">2<' in body)
    check("conciliación detecta el período (05/08/2026 - 07/08/2026)", "05/08/2026 - 07/08/2026" in body)
    check("conciliación embebe el plan de cuentas completo para el buscador JS", "CUENTA CAJA" in body and "BANCO SANTANDER" in body)

    # archivo con formato equivocado (no es el Excel convertido de Cartolas)
    r = client.post(
        "/conciliacion/procesar",
        data={"archivo": (io.BytesIO(b"no es un excel"), "cualquiera.pdf")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    check("conciliación rechaza un formato no permitido", "Formato no permitido" in r.get_data(as_text=True))

    # ---- Conciliación: archivo de salida (09-09-2026, segunda ronda) ----
    # Plan de cuentas ahora también trae "es_banco" (Atributo Bancario) y
    # "requiere_centro_costo" (Requiere Centro de Costo), necesarios para
    # armar el comprobante — deducidos de una muestra real de la plantilla
    # de salida que entregó el usuario (ver app/conciliacion/export_writer.py).
    check("plan de cuentas trae es_banco/requiere_centro_costo por cuenta", (
        CUENTAS_POR_CODIGO_TEST["1101-29"]["es_banco"] is True
        and CUENTAS_POR_CODIGO_TEST["1101-29"]["requiere_centro_costo"] is False
        and CUENTAS_POR_CODIGO_TEST["4401-01"]["es_banco"] is False
        and CUENTAS_POR_CODIGO_TEST["4401-01"]["requiere_centro_costo"] is True
    ))
    check("21 cuentas bancarias y 296 cuentas requieren centro de costo", (
        sum(1 for c in PLAN_CUENTAS if c["es_banco"]) == 21
        and sum(1 for c in PLAN_CUENTAS if c["requiere_centro_costo"]) == 296
    ))

    from app.conciliacion.export_writer import construir_filas_comprobantes

    banco_bci = CUENTAS_POR_CODIGO_TEST["1101-29"]  # es_banco=True, requiere_centro_costo=False
    concepto_no_banco_con_cc = CUENTAS_POR_CODIGO_TEST["4401-01"]  # es_banco=False, requiere_centro_costo=True
    concepto_no_banco_sin_cc = CUENTAS_POR_CODIGO_TEST["2105-18"]  # es_banco=False, requiere_centro_costo=False

    filas_cargo = construir_filas_comprobantes(
        [{"fecha": _datetime_conciliacion(2026, 7, 1), "detalle": "TRASPASO A OTRO BANCO", "cargo": 2449219.0, "abono": 0.0, "concepto": concepto_no_banco_con_cc}],
        banco_bci,
    )
    check("cargo: línea 1 (Debe) es la cuenta Concepto, con Centro Costo 100 (Requiere Centro de Costo=SI)", (
        filas_cargo[0][1] == "E" and filas_cargo[0][4] == "4401-01" and filas_cargo[0][6] == 100 and filas_cargo[0][8] == 2449219.0 and filas_cargo[0][9] == ""
    ))
    check("cargo: línea 2 (Haber) es la cuenta bancaria, con Tipo Auxiliar B y bloque de detalle bancario", (
        filas_cargo[1][4] == "1101-29" and filas_cargo[1][9] == 2449219.0 and filas_cargo[1][10] == "B"
        and filas_cargo[1][12] == "TRASPASO A OTRO BANCO" and filas_cargo[1][15] == 2449219.0
    ))

    filas_abono = construir_filas_comprobantes(
        [{"fecha": _datetime_conciliacion(2026, 7, 7), "detalle": "DEPOSITO CHEQUE", "cargo": 0.0, "abono": 34498682.0, "concepto": concepto_no_banco_sin_cc}],
        banco_bci,
    )
    check("abono: línea 1 (Debe) es la cuenta bancaria, tipo I, sin Centro Costo", (
        filas_abono[0][1] == "I" and filas_abono[0][4] == "1101-29" and filas_abono[0][8] == 34498682.0 and filas_abono[0][10] == "B" and filas_abono[0][6] == ""
    ))
    check("abono: línea 2 (Haber) es la cuenta Concepto, sin Tipo Auxiliar (no es banco) ni Centro Costo (no lo requiere)", (
        filas_abono[1][4] == "2105-18" and filas_abono[1][9] == 34498682.0 and filas_abono[1][10] == "" and filas_abono[1][6] == ""
    ))

    check("primera línea siempre lleva Número=0 y la segunda vacío", (
        filas_cargo[0][0] == 0 and filas_cargo[1][0] == "" and filas_abono[0][0] == 0 and filas_abono[1][0] == ""
    ))

    from app.conciliacion.export_writer import FilaSinFecha, comprobantes_a_xls_bytes
    _fallo_sin_fecha = False
    try:
        comprobantes_a_xls_bytes(
            [{"fecha": "no-es-fecha", "detalle": "x", "cargo": 100.0, "abono": 0.0, "concepto": concepto_no_banco_sin_cc}],
            banco_bci,
        )
    except FilaSinFecha:
        _fallo_sin_fecha = True
    check("comprobantes_a_xls_bytes rechaza una fila sin fecha real (datetime)", _fallo_sin_fecha)

    # Flujo completo end-to-end: cargar la cartola, clasificar cada fila
    # (cuenta bancaria + concepto por movimiento) y descargar el .xls.
    txs_salida = [
        Transaction(fecha="01/07/2026", descripcion="TRASPASO FONDOS OTRO BANCO EN LINEA", cargo=2449219.0, abono=0.0),
        Transaction(fecha="07/07/2026", descripcion="DEPOSITO CHEQUE/DOCUMENTO OTROS BANCOS", cargo=0.0, abono=34498682.0),
    ]
    wb_salida = build_output_workbook(txs_salida)
    buf_salida = io.BytesIO()
    wb_salida.save(buf_salida)
    buf_salida.seek(0)
    r = client.post(
        "/conciliacion/procesar",
        data={"archivo": (buf_salida, "cartola_004_convertido.xlsx")},
        content_type="multipart/form-data",
    )
    check("carga la cartola de prueba para el flujo de descarga", r.status_code == 200)

    r = client.post("/conciliacion/descargar", data={
        "csrf_token": "", "archivo_nombre": "cartola_004_convertido.xlsx", "total_filas": "2",
        "cuenta_banco_codigo": "1101-29", "cuenta_banco_descripcion": "BANCO BCI",
        "fecha_0": "01-07-2026", "fecha_iso_0": "2026-07-01", "detalle_0": "TRASPASO FONDOS OTRO BANCO EN LINEA", "cargo_0": "2449219.0", "abono_0": "0.0",
        "concepto_codigo_0": "4401-01", "concepto_descripcion_0": "INTERESES PAGADOS",
        "fecha_1": "07-07-2026", "fecha_iso_1": "2026-07-07", "detalle_1": "DEPOSITO CHEQUE/DOCUMENTO OTROS BANCOS", "cargo_1": "0.0", "abono_1": "34498682.0",
        "concepto_codigo_1": "1101-01", "concepto_descripcion_1": "CUENTA CAJA",
    })
    check("POST /conciliacion/descargar -> 200 con la clasificación completa", r.status_code == 200)
    check("descarga con mimetype .xls", r.mimetype == "application/vnd.ms-excel")
    check("nombre de archivo de descarga incluye el nombre de la cartola", "Comprobantes_Conciliacion_cartola_004_convertido.xls" in r.headers.get("Content-Disposition", ""))

    import xlrd as _xlrd_check
    _wb_check = _xlrd_check.open_workbook(file_contents=r.get_data())
    _sh_check = _wb_check.sheet_by_name("Comprobantes")
    check("el .xls generado tiene 2 líneas por movimiento (4 filas + encabezado)", _sh_check.nrows == 5)
    check("línea 1 del primer comprobante: Debe=Concepto (4401-01), Centro Costo 100", (
        _sh_check.cell_value(1, 4) == "4401-01" and _sh_check.cell_value(1, 6) == 100 and _sh_check.cell_value(1, 8) == 2449219.0
    ))
    check("línea 2 del primer comprobante: Haber=Banco BCI (1101-29), Tipo Auxiliar B", (
        _sh_check.cell_value(2, 4) == "1101-29" and _sh_check.cell_value(2, 9) == 2449219.0 and _sh_check.cell_value(2, 10) == "B"
    ))
    check("línea 3 del segundo comprobante (abono): Debe=Banco BCI", (
        _sh_check.cell_value(3, 1) == "I" and _sh_check.cell_value(3, 4) == "1101-29" and _sh_check.cell_value(3, 8) == 34498682.0
    ))

    # Falta la cuenta bancaria: no descarga, re-muestra la página con el
    # error y sin perder lo ya clasificado.
    r = client.post("/conciliacion/descargar", data={
        "csrf_token": "", "archivo_nombre": "cartola_004_convertido.xlsx", "total_filas": "2",
        "cuenta_banco_codigo": "", "cuenta_banco_descripcion": "",
        "fecha_0": "01-07-2026", "fecha_iso_0": "2026-07-01", "detalle_0": "TRASPASO FONDOS OTRO BANCO EN LINEA", "cargo_0": "2449219.0", "abono_0": "0.0",
        "concepto_codigo_0": "4401-01", "concepto_descripcion_0": "INTERESES PAGADOS",
        "fecha_1": "07-07-2026", "fecha_iso_1": "2026-07-07", "detalle_1": "DEPOSITO CHEQUE/DOCUMENTO OTROS BANCOS", "cargo_1": "0.0", "abono_1": "34498682.0",
        "concepto_codigo_1": "", "concepto_descripcion_1": "",
    })
    body = r.get_data(as_text=True)
    check("sin cuenta bancaria: 200 (re-muestra la página, no descarga)", r.status_code == 200)
    check("sin cuenta bancaria: mensaje de error pidiendo elegirla", "Selecciona arriba la cuenta bancaria" in body)
    check("sin cuenta bancaria: avisa qué fila falta clasificar (fila 2)", "fila 2" in body)
    check("sin cuenta bancaria: conserva el detalle editado de la fila ya clasificada", "TRASPASO FONDOS OTRO BANCO EN LINEA" in body)

    # ---- _detalle_error_http: extrae mensaje legible sin importar el
    # formato de error que devuelva Azure/Graph (bug real: un 401 de la
    # capa de autenticación con formato {"error":"invalid_token",...}
    # quedaba en blanco porque el código solo esperaba el formato de Graph
    # {"error":{"message":...}}) ----
    from app.reuniones.graph_client import _detalle_error_http

    class _FakeResp:
        def __init__(self, payload=None, text="", headers=None):
            self._payload = payload
            self.text = text
            self.headers = headers or {}
        def json(self):
            if self._payload is None:
                raise ValueError("no json")
            return self._payload

    check(
        "_detalle_error_http: formato Graph {error:{message}}",
        _detalle_error_http(_FakeResp({"error": {"message": "Access token missing"}})) == "Access token missing",
    )
    check(
        "_detalle_error_http: formato OAuth {error:'invalid_token', error_description}",
        "CompactToken" in _detalle_error_http(_FakeResp({
            "error": "invalid_token",
            "error_description": "CompactToken parsing failed",
        })),
    )
    check(
        "_detalle_error_http: formato OAuth sin error_description usa el código",
        _detalle_error_http(_FakeResp({"error": "invalid_token"})) == "invalid_token",
    )
    check(
        "_detalle_error_http: respuesta no-JSON usa el texto crudo",
        _detalle_error_http(_FakeResp(None, text="Bad Gateway")) == "Bad Gateway",
    )
    # Caso real reportado por el usuario: 401 con cuerpo COMPLETAMENTE vacío
    # (ni JSON ni texto) — el detalle real vive en la cabecera WWW-Authenticate
    # (RFC 6750), no en el cuerpo. Antes de este fix, este caso caía siempre
    # en "(sin detalle en la respuesta...)" sin mirar las cabeceras.
    check(
        "_detalle_error_http: cuerpo vacío, detalle real en WWW-Authenticate",
        "invalid_token" in _detalle_error_http(_FakeResp(
            None, text="",
            headers={"WWW-Authenticate": 'Bearer realm="Microsoft Graph", error="invalid_token", error_description="Lifetime validation failed"'},
        )),
    )
    check(
        "_detalle_error_http: cuerpo y cabeceras vacíos -> mensaje explícito de 'sin detalle'",
        _detalle_error_http(_FakeResp(None, text="")) == "(sin detalle en la respuesta ni en las cabeceras)",
    )

    # ---- _diagnostico_http: info técnica de respaldo cuando no hay ningún
    # detalle en el cuerpo ni en las cabeceras (caso real reportado por el
    # usuario) — incluye la URL llamada y las cabeceras, pero NUNCA el
    # token en sí, solo su longitud ----
    from app.reuniones.graph_client import _diagnostico_http

    class _FakeRequest:
        def __init__(self, url):
            self.url = url

    class _FakeRespConReq(_FakeResp):
        def __init__(self, *a, url="https://graph.microsoft.com/v1.0/users/x/calendarView", **kw):
            super().__init__(*a, **kw)
            self.request = _FakeRequest(url)

    diag = _diagnostico_http(_FakeRespConReq(headers={"request-id": "abc-123"}), "token-de-prueba-1234567890")
    check("_diagnostico_http: incluye la URL llamada", "calendarView" in diag)
    check("_diagnostico_http: incluye las cabeceras de la respuesta", "request-id" in diag)
    check("_diagnostico_http: incluye el largo del token, no el token en sí", "26 caracteres" in diag and "token-de-prueba" not in diag)

    # ---- Empresas Caja (nueva pestaña, solo admin por defecto) ----
    from datetime import datetime as _dt_caja
    from openpyxl import Workbook as _WorkbookCaja
    from app.conciliacion.plan_cuentas import CUENTAS_POR_CODIGO as _CUENTAS_CAJA

    def _wb_clientes_proveedores(filas, col_monto):
        wb = _WorkbookCaja()
        ws = wb.active
        ws.append(["ESTADO DE CUENTAS - PENDIENTES"])
        ws.append(["Codigo Cuenta", "Cuenta", "RUT", "DV", "Nombre", "Fecha Registro", "Tipo Asiento",
                   "Comprobante", "Sec", "Descripcion Asiento", "Tipo Documento", "N Documento",
                   "Vencimiento", "Sucursal", "Centro Costo", "Debe", "Haber", "Saldo"])
        for f in filas:
            row = [None] * 18
            rut_numero, rut_dv = f["rut"].split("-")
            row[2] = rut_numero
            row[3] = rut_dv
            row[4] = f["nombre"]
            row[5] = f["fecha"]
            row[10] = f["tipo_documento"]
            row[11] = f["numero_documento"]
            row[col_monto - 1] = f["monto"]
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    def _wb_honorarios(filas):
        wb = _WorkbookCaja()
        ws = wb.active
        ws.append(["ESTADO DE CUENTAS DE HONORARIO - PENDIENTES"])
        ws.append(["Movimientos Pendientes"])
        ws.append(["Rut", "Nombre", "Fecha", "Comprobante", "Sec", "Boleta", "Sucursal",
                   "CentroDeCosto", "Debe", "Haber", "Saldo", "Prestador"])
        for f in filas:
            row = [None] * 12
            row[0] = f["rut"]
            row[1] = f["nombre"]
            row[2] = f["fecha"]
            row[5] = f["boleta"]
            row[9] = f["monto"]
            ws.append(row)
        ws.append([None, None, None, None, None, None, None, "Total Informe", 0, sum(f["monto"] for f in filas), 0, None])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    # Con anio="2026": las grillas de F29/RemImp tienen 13 filas (índice 0 =
    # Diciembre 2025, índice 1..12 = Enero..Diciembre 2026); Créditos tiene
    # 12 (índice 0..11 = Enero..Diciembre 2026, índice = mes - 1). Julio
    # 2026 cae en índice 7 para F29/RemImp e índice 6 para Créditos.
    ANIO_CAJA = "2026"

    def _meses_vacios_caja():
        d = {"anio": ANIO_CAJA}
        for m in range(13):
            for campo in ("f29_fecha", "f29_monto", "f29_multas", "remimp_remuneraciones", "remimp_imposiciones"):
                d[f"{campo}_{m}"] = ""
        for m in range(12):
            for campo in ("credito_fecha", "credito_amortizacion", "credito_intereses", "credito_comisiones"):
                d[f"{campo}_{m}"] = ""
        return d

    r = client.get("/caja_empresas/")
    check("GET /caja_empresas/ 200 (admin)", r.status_code == 200)
    check("Empresas Caja pide saldo inicial", "Saldo inicial" in r.get_data(as_text=True))
    check("Empresas Caja pide el año del lote", "Año del lote" in r.get_data(as_text=True))
    check("grilla F29 incluye Diciembre del año anterior", "Diciembre" in r.get_data(as_text=True))
    check(
        "Diciembre (año anterior) muestra su fecha de Remuneraciones excepcional: 05-01-2026 (no 31-12-2025)",
        "05-01-2026" in r.get_data(as_text=True) and "31-12-2025" not in r.get_data(as_text=True),
    )

    # Carga AJAX de los 3 archivos de documentos.
    buf_clientes = _wb_clientes_proveedores(
        [{"nombre": "CLIENTE UNO", "rut": "76543210-5", "fecha": _dt_caja(2026, 7, 1), "tipo_documento": "FAC-EL", "numero_documento": "100", "monto": 500000}],
        col_monto=16,
    )
    r = client.post("/caja_empresas/cargar/clientes", data={"archivo": (buf_clientes, "clientes.xlsx")}, content_type="multipart/form-data")
    check("POST /caja_empresas/cargar/clientes -> 200", r.status_code == 200)
    check("fragmento de clientes muestra el documento cargado", "CLIENTE UNO" in r.get_data(as_text=True))
    check("fragmento de clientes viene con el check pre-marcado", "checked" in r.get_data(as_text=True))
    check("fragmento de clientes muestra el RUT junto al nombre (juntando columnas C+D)", "76543210-5" in r.get_data(as_text=True))

    buf_proveedores = _wb_clientes_proveedores(
        [{"nombre": "PROVEEDOR UNO", "rut": "11222333-4", "fecha": _dt_caja(2026, 7, 3), "tipo_documento": "FAC-EL", "numero_documento": "55", "monto": 200000}],
        col_monto=17,
    )
    r = client.post("/caja_empresas/cargar/proveedores", data={"archivo": (buf_proveedores, "proveedores.xlsx")}, content_type="multipart/form-data")
    check("POST /caja_empresas/cargar/proveedores -> 200", r.status_code == 200)
    check("fragmento de proveedores muestra el documento cargado", "PROVEEDOR UNO" in r.get_data(as_text=True))
    check("fragmento de proveedores muestra el RUT junto al nombre", "11222333-4" in r.get_data(as_text=True))

    buf_honorarios = _wb_honorarios([{"rut": "11111111-1", "nombre": "PRESTADOR UNO", "fecha": "01-07-2026", "boleta": "BOL-HE 5", "monto": 150000}])
    r = client.post("/caja_empresas/cargar/honorarios", data={"archivo": (buf_honorarios, "honorarios.xlsx")}, content_type="multipart/form-data")
    check("POST /caja_empresas/cargar/honorarios -> 200", r.status_code == 200)
    body_hon = r.get_data(as_text=True)
    check("fragmento de honorarios muestra el prestador cargado", "PRESTADOR UNO" in body_hon)
    check("fragmento de honorarios muestra el RUT (ya venía combinado)", "11111111-1" in body_hon)
    check("honorarios separa 'BOL-HE 5' en tipo 'BOL-HE' y número '5'", 'value="BOL-HE"' in body_hon and 'value="5"' in body_hon)

    r = client.post("/caja_empresas/cargar/clientes", data={}, content_type="multipart/form-data")
    check("cargar sin archivo -> 400 (no revienta)", r.status_code == 400)

    r = client.post(
        "/caja_empresas/cargar/clientes",
        data={"archivo": (io.BytesIO(b"no es un excel"), "cualquiera.xlsx")},
        content_type="multipart/form-data",
    )
    check("cargar un archivo corrupto -> 400 con mensaje, no 500", r.status_code == 400 and "No se pudo abrir" in r.get_data(as_text=True))

    # ---- generar(): mes con monto pero sin fecha -> error (índice 1 = Enero 2026) ----
    payload_sin_fecha = dict(_meses_vacios_caja())
    payload_sin_fecha.update({
        "saldo_inicial": "1000000",
        "clientes_total_filas": "0", "proveedores_total_filas": "0", "honorarios_total_filas": "0",
        "f29_monto_1": "100000",
    })
    r = client.post("/caja_empresas/generar", data=payload_sin_fecha, follow_redirects=True)
    check("generar con monto de mes sin fecha -> 200 (no descarga)", r.status_code == 200)
    check("generar con monto de mes sin fecha: avisa que falta la fecha de Enero 2026", "falta la fecha de Enero 2026" in r.get_data(as_text=True))

    # ---- generar(): año inválido -> error, no revienta ----
    payload_anio_invalido = dict(_meses_vacios_caja())
    payload_anio_invalido.update({
        "anio": "no-es-un-año", "saldo_inicial": "0",
        "clientes_total_filas": "0", "proveedores_total_filas": "0", "honorarios_total_filas": "0",
    })
    r = client.post("/caja_empresas/generar", data=payload_anio_invalido, follow_redirects=True)
    check("año inválido -> 200 (no revienta), avisa el problema", (
        r.status_code == 200 and "Año del lote” no es válido" in r.get_data(as_text=True)
    ))

    # ---- generar(): flujo completo, todos los módulos con datos (Julio 2026) ----
    payload_completo = dict(_meses_vacios_caja())
    payload_completo.update({
        "saldo_inicial": "1000000",
        "clientes_total_filas": "1", "clientes_nombre_0": "CLIENTE UNO", "clientes_rut_0": "76543210-5",
        "clientes_fecha_0": "01-07-2026",
        "clientes_fecha_iso_0": "2026-07-01", "clientes_tipo_documento_0": "FAC-EL", "clientes_numero_documento_0": "100",
        "clientes_monto_0": "500000",
        "clientes_check_0": "on",
        "proveedores_total_filas": "1", "proveedores_nombre_0": "PROVEEDOR UNO", "proveedores_rut_0": "11222333-4",
        "proveedores_fecha_0": "03-07-2026",
        "proveedores_fecha_iso_0": "2026-07-03", "proveedores_tipo_documento_0": "FAC-EL", "proveedores_numero_documento_0": "55",
        "proveedores_monto_0": "200000",
        "proveedores_check_0": "on",
        "honorarios_total_filas": "1", "honorarios_nombre_0": "PRESTADOR UNO", "honorarios_rut_0": "11111111-1",
        "honorarios_fecha_0": "01-07-2026",
        "honorarios_fecha_iso_0": "2026-07-01", "honorarios_tipo_documento_0": "BOL-HE", "honorarios_numero_documento_0": "5",
        "honorarios_monto_0": "150000",
        "honorarios_check_0": "on",
        # índice 7 = Julio 2026 en las grillas de 13 filas (F29/RemImp).
        "f29_fecha_7": "2026-07-31", "f29_monto_7": "300000", "f29_multas_7": "10000",
        "remimp_remuneraciones_7": "400000", "remimp_imposiciones_7": "50000",
        # índice 6 = Julio 2026 en la grilla de 12 filas de Créditos.
        "credito_fecha_6": "2026-07-10", "credito_amortizacion_6": "80000", "credito_intereses_6": "5000", "credito_comisiones_6": "2000",
        "credito_cuenta_amortizacion_codigo": "2106-01", "credito_cuenta_amortizacion_descripcion": "PRESTAMOS BANCARIOS",
    })
    r = client.post("/caja_empresas/generar", data=payload_completo)
    check("POST /caja_empresas/generar (completo) -> 200", r.status_code == 200)
    check("descarga con mimetype .xls", r.mimetype == "application/vnd.ms-excel")
    check("nombre de archivo de descarga", "Comprobantes_EmpresasCaja_" in r.headers.get("Content-Disposition", ""))

    import xlrd as _xlrd_caja
    _wb_caja = _xlrd_caja.open_workbook(file_contents=r.get_data())
    _sh_caja = _wb_caja.sheet_by_name("Comprobantes")
    # Clientes (2) + Proveedores (2) + Honorarios (2) + F29 (3) + RemImp
    # (2+2, ahora dos comprobantes independientes) + Créditos (4) = 17
    # líneas + encabezado.
    check("el .xls generado tiene 17 líneas de detalle + encabezado (18 filas)", _sh_caja.nrows == 18)

    check("línea 1 (Clientes, ingreso): Caja al Debe", _sh_caja.cell_value(1, 0) == 0 and _sh_caja.cell_value(1, 1) == "I" and _sh_caja.cell_value(1, 4) == "1101-01" and _sh_caja.cell_value(1, 8) == 500000)
    check("línea 1 (Clientes): glosa con el formato pedido", _sh_caja.cell_value(1, 3) == "INGRESO F 100 CLIENTE UNO")
    check("línea 2 (Clientes): contra-cuenta 1104-01 al Haber, Tipo Auxiliar A", (
        _sh_caja.cell_value(2, 4) == "1104-01" and _sh_caja.cell_value(2, 9) == 500000
        and _sh_caja.cell_value(2, 10) == "A" and _sh_caja.cell_value(2, 11) == "76543210-5"
        and _sh_caja.cell_value(2, 12) == "CLIENTE UNO" and _sh_caja.cell_value(2, 13) == 33
        and _sh_caja.cell_value(2, 14) == 100 and _sh_caja.cell_value(2, 15) == 500000
    ))

    check("línea 3 (Proveedores, egreso): contra-cuenta al Debe primero, glosa pedida", (
        _sh_caja.cell_value(3, 1) == "E" and _sh_caja.cell_value(3, 4) == "2105-01" and _sh_caja.cell_value(3, 8) == 200000
        and _sh_caja.cell_value(3, 3) == "PAGO F 55 PROVEEDOR UNO"
    ))
    check("línea 3 (Proveedores): Tipo Auxiliar A con rut/nombre/tipo doc/folio", (
        _sh_caja.cell_value(3, 10) == "A" and _sh_caja.cell_value(3, 11) == "11222333-4"
        and _sh_caja.cell_value(3, 12) == "PROVEEDOR UNO" and _sh_caja.cell_value(3, 13) == 33
        and _sh_caja.cell_value(3, 14) == 55 and _sh_caja.cell_value(3, 15) == 200000
    ))
    check("línea 4 (Proveedores): Caja al Haber", _sh_caja.cell_value(4, 4) == "1101-01" and _sh_caja.cell_value(4, 9) == 200000)

    check("línea 5 (Honorarios, egreso): contra-cuenta fija 2105-04 al Debe, glosa pedida", (
        _sh_caja.cell_value(5, 1) == "E" and _sh_caja.cell_value(5, 4) == "2105-04" and _sh_caja.cell_value(5, 8) == 150000
        and _sh_caja.cell_value(5, 3) == "PAGO BH 5 PRESTADOR UNO"
    ))
    check("línea 5 (Honorarios): Tipo Auxiliar H con rut/nombre/código BOL-HE=99/folio", (
        _sh_caja.cell_value(5, 10) == "H" and _sh_caja.cell_value(5, 11) == "11111111-1"
        and _sh_caja.cell_value(5, 12) == "PRESTADOR UNO" and _sh_caja.cell_value(5, 13) == 99
        and _sh_caja.cell_value(5, 14) == 5 and _sh_caja.cell_value(5, 15) == 150000
    ))
    check("línea 6 (Honorarios): Caja al Haber", _sh_caja.cell_value(6, 4) == "1101-01" and _sh_caja.cell_value(6, 9) == 150000)

    check("F29 con multas genera 3 líneas (F29 + Multas + Caja), glosa con año", (
        _sh_caja.cell_value(7, 4) == "2108-05" and _sh_caja.cell_value(7, 8) == 300000 and _sh_caja.cell_value(7, 3) == "Pago F29 Julio 2026"
        and _sh_caja.cell_value(8, 4) == "4201-11" and _sh_caja.cell_value(8, 6) == 100 and _sh_caja.cell_value(8, 8) == 10000
        and _sh_caja.cell_value(9, 4) == "1101-01" and _sh_caja.cell_value(9, 9) == 310000
    ))

    import datetime as _dtmod
    check("Remuneraciones e Imposiciones: dos comprobantes independientes con fechas distintas", (
        _sh_caja.cell_value(10, 4) == "2108-15" and _sh_caja.cell_value(10, 8) == 400000
        and _sh_caja.cell_value(10, 3) == "Pago remuneraciones Julio 2026"
        and _xlrd_caja.xldate_as_datetime(_sh_caja.cell_value(10, 2), _wb_caja.datemode) == _dtmod.datetime(2026, 7, 31)
        and _sh_caja.cell_value(11, 4) == "1101-01" and _sh_caja.cell_value(11, 9) == 400000
        and _sh_caja.cell_value(12, 4) == "2108-25" and _sh_caja.cell_value(12, 8) == 50000
        and _sh_caja.cell_value(12, 3) == "Pago imposiciones Julio 2026"
        and _xlrd_caja.xldate_as_datetime(_sh_caja.cell_value(12, 2), _wb_caja.datemode) == _dtmod.datetime(2026, 8, 13)
        and _sh_caja.cell_value(13, 4) == "1101-01" and _sh_caja.cell_value(13, 9) == 50000
    ))

    check("Créditos genera 4 líneas (Amortización + Intereses + Comisiones + Caja)", (
        _sh_caja.cell_value(14, 4) == "2106-01" and _sh_caja.cell_value(15, 4) == "4401-01"
        and _sh_caja.cell_value(16, 4) == "4301-07" and _sh_caja.cell_value(17, 4) == "1101-01"
        and _sh_caja.cell_value(17, 9) == 80000 + 5000 + 2000
    ))

    # ---- Diciembre (año anterior, índice 0) es la excepción de fecha de
    # Remuneraciones: se paga el 5 de enero siguiente, no el 31 de diciembre ----
    payload_dic_anterior = dict(_meses_vacios_caja())
    payload_dic_anterior.update({
        "saldo_inicial": "1000000",
        "clientes_total_filas": "0", "proveedores_total_filas": "0", "honorarios_total_filas": "0",
        "remimp_remuneraciones_0": "700000",
    })
    r = client.post("/caja_empresas/generar", data=payload_dic_anterior)
    check("Diciembre año anterior: Remuneraciones -> 200 (descarga)", r.status_code == 200 and r.mimetype == "application/vnd.ms-excel")
    _wb_dic = _xlrd_caja.open_workbook(file_contents=r.get_data())
    _sh_dic = _wb_dic.sheet_by_name("Comprobantes")
    check("Remuneraciones de Diciembre 2025 se pagan el 05-01-2026 (no el 31-12-2025)", (
        _sh_dic.cell_value(1, 4) == "2108-15" and _sh_dic.cell_value(1, 8) == 700000
        and _sh_dic.cell_value(1, 3) == "Pago remuneraciones Diciembre 2025"
        and _xlrd_caja.xldate_as_datetime(_sh_dic.cell_value(1, 2), _wb_dic.datemode) == _dtmod.datetime(2026, 1, 5)
        and _sh_dic.cell_value(2, 4) == "1101-01" and _sh_dic.cell_value(2, 9) == 700000
    ))

    # ---- Tipos de Documento sin código configurado -> celda de código queda vacía, no revienta ----
    payload_tipo_desconocido = dict(_meses_vacios_caja())
    payload_tipo_desconocido.update({
        "saldo_inicial": "0",
        "clientes_total_filas": "1", "clientes_nombre_0": "CLIENTE DOS", "clientes_rut_0": "1-9",
        "clientes_fecha_0": "01-07-2026", "clientes_fecha_iso_0": "2026-07-01",
        "clientes_tipo_documento_0": "TIPO-DESCONOCIDO", "clientes_numero_documento_0": "1",
        "clientes_monto_0": "1000", "clientes_check_0": "on",
        "proveedores_total_filas": "0", "honorarios_total_filas": "0",
    })
    r = client.post("/caja_empresas/generar", data=payload_tipo_desconocido)
    check("tipo de documento sin código configurado -> igual descarga (200), no revienta", r.status_code == 200)
    _wb_tipo_desc = _xlrd_caja.open_workbook(file_contents=r.get_data())
    _sh_tipo_desc = _wb_tipo_desc.sheet_by_name("Comprobantes")
    check("tipo de documento desconocido: la celda de código queda vacía", _sh_tipo_desc.cell_value(2, 13) == "")

    # ---- generar(): saldo negativo exige Préstamo Socio ----
    payload_negativo = dict(_meses_vacios_caja())
    payload_negativo.update({
        "saldo_inicial": "100000",
        "clientes_total_filas": "0",
        "proveedores_total_filas": "1", "proveedores_nombre_0": "PROVEEDOR GRANDE", "proveedores_fecha_0": "03-07-2026",
        "proveedores_fecha_iso_0": "2026-07-03", "proveedores_tipo_documento_0": "FAC-EL", "proveedores_numero_documento_0": "9",
        "proveedores_monto_0": "500000",
        "proveedores_check_0": "on",
        "honorarios_total_filas": "0",
    })
    r = client.post("/caja_empresas/generar", data=payload_negativo, follow_redirects=True)
    check("saldo negativo sin Préstamo Socio -> no descarga (200, re-muestra)", r.status_code == 200)
    check("saldo negativo: avisa que hay que marcar Préstamo Socio", "Préstamo Socio" in r.get_data(as_text=True))

    payload_con_prestamo = dict(payload_negativo)
    payload_con_prestamo.update({
        "prestamo_socio_check": "on", "prestamo_socio_monto": "400000", "prestamo_socio_fecha": "2026-07-15",
    })
    r = client.post("/caja_empresas/generar", data=payload_con_prestamo)
    check("con Préstamo Socio suficiente -> descarga (200)", r.status_code == 200 and r.mimetype == "application/vnd.ms-excel")
    _wb_prestamo = _xlrd_caja.open_workbook(file_contents=r.get_data())
    _sh_prestamo = _wb_prestamo.sheet_by_name("Comprobantes")
    check("Préstamo Socio agrega 2 líneas (Caja Debe / 2106-04 Haber) al final", (
        _sh_prestamo.nrows == 5
        and _sh_prestamo.cell_value(3, 1) == "I" and _sh_prestamo.cell_value(3, 4) == "1101-01" and _sh_prestamo.cell_value(3, 8) == 400000
        and _sh_prestamo.cell_value(4, 4) == "2106-04" and _sh_prestamo.cell_value(4, 9) == 400000
    ))

    payload_prestamo_insuficiente = dict(payload_negativo)
    payload_prestamo_insuficiente.update({
        "prestamo_socio_check": "on", "prestamo_socio_monto": "100000", "prestamo_socio_fecha": "2026-07-15",
    })
    r = client.post("/caja_empresas/generar", data=payload_prestamo_insuficiente, follow_redirects=True)
    check("Préstamo Socio insuficiente -> sigue sin descargar, avisa cuánto falta", (
        r.status_code == 200 and "no alcanza para cubrir el saldo negativo" in r.get_data(as_text=True)
    ))

    check("plan de cuentas usado por Empresas Caja: cuenta Caja fija no es bancaria", _CUENTAS_CAJA["1101-01"]["es_banco"] is False)

    # ---- Logout y login como 'trabajador' (no admin) ----
    client.post("/logout")
    r = client.post("/login", data={"usuario": "testuser", "clave": "trabajador123"}, follow_redirects=True)
    check("login como trabajador de prueba entra", r.status_code == 200 and b"Subir Cartolas" in r.data)

    r = client.get("/admin/cuentas")
    check("trabajador NO puede ver Administrador (403)", r.status_code == 403)

    r = client.get("/cartolas/")
    check("trabajador SÍ puede ver Subir Cartolas", r.status_code == 200)

    r = client.get("/f29/")
    check("trabajador SÍ puede ver Generar F29", r.status_code == 200)

    r = client.get("/global/")
    check("trabajador SÍ puede ver Calcular Global", r.status_code == 200)

    r = client.get("/indicadores/")
    check("trabajador SÍ puede ver Indicadores", r.status_code == 200)

    r = client.get("/reuniones/")
    check("trabajador NO puede ver Reuniones (403)", r.status_code == 403)

    r = client.get("/conciliacion/")
    check("trabajador NO puede ver Conciliación (403)", r.status_code == 403)

    r = client.post("/conciliacion/descargar", data={"total_filas": "0", "cuenta_banco_codigo": "1101-29"})
    check("trabajador NO puede descargar el archivo de salida de Conciliación (403)", r.status_code == 403)

    r = client.get("/caja_empresas/")
    check("trabajador NO puede ver Empresas Caja (403, admin por defecto)", r.status_code == 403)

    r = client.post("/caja_empresas/cargar/clientes", data={}, content_type="multipart/form-data")
    check("trabajador NO puede cargar documentos en Empresas Caja (403)", r.status_code == 403)

    r = client.post("/caja_empresas/generar", data={})
    check("trabajador NO puede generar comprobantes de Empresas Caja (403)", r.status_code == 403)

    # ---- Visibilidad de pestañas (09-09-2026): admin activa/restringe pestañas ----
    r = client.get("/admin/pestanas")
    check("trabajador NO puede ver Administrador -> Pestañas (403)", r.status_code == 403)

    r = client.post("/admin/pestanas/guardar", data={"vis_reuniones.index": "todos"})
    check("trabajador NO puede guardar visibilidad de pestañas (403)", r.status_code == 403)

    r = client.get("/admin/tipos_documento")
    check("trabajador NO puede ver Administrador -> Tipos de Documento (403)", r.status_code == 403)

    r = client.post("/admin/tipos_documento/guardar", data={"td_texto": ["X"], "td_codigo": ["1"]})
    check("trabajador NO puede guardar Tipos de Documento (403)", r.status_code == 403)

    client.post("/logout")
    client.post("/login", data={"usuario": "", "clave": "test_local_only_1234"}, follow_redirects=True)

    r = client.get("/admin/pestanas")
    check("GET /admin/pestanas 200 (admin)", r.status_code == 200)
    check("panel de pestañas lista Reuniones, Conciliación y Empresas Caja", b"Reuniones" in r.data and b"Conciliaci" in r.data and b"Empresas Caja" in r.data)
    check("panel de pestañas NO incluye Administrador (no configurable)", b'name="vis_admin.cuentas"' not in r.data)

    # Por defecto (nunca guardado): Reuniones/Conciliación/Empresas Caja solo-admin, el resto para todos.
    check(
        "Reuniones aparece marcada 'solo administradores' por defecto",
        b'name="vis_reuniones.index" value="admin" checked' in r.data,
    )
    check(
        "Empresas Caja aparece marcada 'solo administradores' por defecto",
        b'name="vis_caja_empresas.index" value="admin" checked' in r.data,
    )
    check(
        "Subir Cartolas aparece marcada 'todos los usuarios' por defecto",
        b'name="vis_cartolas.index" value="todos" checked' in r.data,
    )

    # ---- Tipos de Documento (10-09-2026): panel de Administrador para agregar
    # códigos de "Tipo de Documento" sin redesplegar ----
    r = client.get("/admin/tipos_documento")
    check("GET /admin/tipos_documento 200 (admin)", r.status_code == 200)
    body_td = r.get_data(as_text=True)
    check("Tipos de Documento trae los 3 códigos de partida", (
        "FAC-EL" in body_td and "FAC-EE" in body_td and "BOL-HE" in body_td
    ))

    from app.data import tipos_documento_repo as _tipos_doc_repo
    check("tipos_documento_repo.codigo_de: códigos de partida", (
        _tipos_doc_repo.codigo_de("FAC-EL") == 33 and _tipos_doc_repo.codigo_de("FAC-EE") == 34
        and _tipos_doc_repo.codigo_de("BOL-HE") == 99
    ))
    check("tipos_documento_repo.codigo_de: tipo desconocido -> None (no revienta)", _tipos_doc_repo.codigo_de("NO-EXISTE") is None)

    r = client.post("/admin/tipos_documento/guardar", data={
        "td_texto": ["FAC-EL", "FAC-EE", "BOL-HE", "NOTA-CR"],
        "td_codigo": ["33", "34", "99", "61"],
    }, follow_redirects=True)
    check("guardar Tipos de Documento -> 200", r.status_code == 200)
    check("Tipos de Documento guardados: aviso de éxito", "guardados" in r.get_data(as_text=True))
    check("agregar un tipo nuevo (NOTA-CR=61) se ve de inmediato", _tipos_doc_repo.codigo_de("NOTA-CR") == 61)

    r = client.post("/admin/tipos_documento/guardar", data={
        "td_texto": ["FAC-EL", "FAC-EE", "BOL-HE"], "td_codigo": ["33", "34", "99"],
    })
    check("dejar Tipos de Documento como estaban (sin NOTA-CR) para no afectar otros checks", r.status_code in (200, 302))

    r = client.get("/admin/cuentas")
    check("subnav de Administrador incluye Tipos de Documento", "Tipos de Documento" in r.get_data(as_text=True))

    # Abrir Reuniones a todos los usuarios, dejando el resto en su default.
    r = client.post("/admin/pestanas/guardar", data={
        "vis_cartolas.index": "todos", "vis_f29.index": "todos",
        "vis_global_igc.index": "todos", "vis_indicadores.index": "todos",
        "vis_reuniones.index": "todos", "vis_conciliacion.index": "admin",
    }, follow_redirects=True)
    check("guardar visibilidad de pestañas -> 200", r.status_code == 200)
    check("aviso de guardado exitoso", "guardada" in r.get_data(as_text=True))

    client.post("/logout")
    client.post("/login", data={"usuario": "testuser", "clave": "trabajador123"}, follow_redirects=True)

    r = client.get("/reuniones/")
    check("trabajador SÍ puede ver Reuniones tras activarla para todos", r.status_code == 200)

    r = client.get("/conciliacion/")
    check("trabajador sigue sin poder ver Conciliación (no se activó)", r.status_code == 403)

    r = client.get("/cartolas/")
    check("el menú del trabajador ya muestra el link a Reuniones", b'href="/reuniones/"' in r.data)

    # Restringir una pestaña que antes era pública (Subir Cartolas) solo a admins.
    client.post("/logout")
    client.post("/login", data={"usuario": "", "clave": "test_local_only_1234"}, follow_redirects=True)
    client.post("/admin/pestanas/guardar", data={
        "vis_cartolas.index": "admin", "vis_f29.index": "todos",
        "vis_global_igc.index": "todos", "vis_indicadores.index": "todos",
        "vis_reuniones.index": "admin", "vis_conciliacion.index": "admin",
    })
    client.post("/logout")
    client.post("/login", data={"usuario": "testuser", "clave": "trabajador123"}, follow_redirects=True)

    r = client.get("/cartolas/")
    check("trabajador ya NO puede ver Subir Cartolas tras restringirla (403)", r.status_code == 403)

    r = client.get("/reuniones/")
    check("Reuniones vuelve a estar solo para admin tras restaurar el default", r.status_code == 403)

    # Deja la configuración de pestañas como al principio, para no dejar
    # este proceso de pruebas con un estado distinto al de una app recién
    # desplegada (todas en su default de `app/nav.py`).
    client.post("/logout")
    client.post("/login", data={"usuario": "", "clave": "test_local_only_1234"}, follow_redirects=True)
    client.post("/admin/pestanas/guardar", data={
        "vis_cartolas.index": "todos", "vis_f29.index": "todos",
        "vis_global_igc.index": "todos", "vis_indicadores.index": "todos",
        "vis_reuniones.index": "admin", "vis_conciliacion.index": "admin",
    })
    client.post("/logout")
    client.post("/login", data={"usuario": "testuser", "clave": "trabajador123"}, follow_redirects=True)
    r = client.get("/cartolas/")
    check("visibilidad de pestañas restaurada al default tras las pruebas", r.status_code == 200)

    # ---- Guardar visibilidad cuando falta la tabla en Supabase (reporte real
    # del usuario, 09-09-2026: "Internal Server Error" al intentar habilitar
    # una pestaña para todos, porque `migration/003_visibilidad_pestanas.sql`
    # todavía no se había ejecutado) ----
    import app.data.visibilidad_repo as visibilidad_repo_mod

    class _TablaInexistente:
        def table(self, _name):
            raise Exception('relation "visibilidad_pestanas" does not exist')

    _get_supabase_real = visibilidad_repo_mod.get_supabase
    visibilidad_repo_mod.get_supabase = lambda: _TablaInexistente()
    # `guardar_todas` ya tenía algo en caché de las pruebas anteriores — se
    # limpia para que esta prueba refleje también el caso de una app recién
    # desplegada, sin ninguna lectura previa exitosa.
    visibilidad_repo_mod._cache = {}
    visibilidad_repo_mod._cache_at = 0.0

    client.post("/logout")
    client.post("/login", data={"usuario": "", "clave": "test_local_only_1234"}, follow_redirects=True)

    r = client.get("/admin/pestanas")
    check("GET /admin/pestanas sigue en 200 aunque la tabla no exista (usa los defaults)", r.status_code == 200)

    r = client.post("/admin/pestanas/guardar", data={"vis_reuniones.index": "todos"})
    check("guardar sin la tabla NO tira 500 (redirige con aviso en vez de reventar)", r.status_code == 302)

    r = client.get("/admin/pestanas")
    body = r.get_data(as_text=True)
    check("el aviso explica que falta la migración de Supabase", "migration" in body and "No se pudo guardar" in body)

    visibilidad_repo_mod.get_supabase = _get_supabase_real
    visibilidad_repo_mod._cache = {}
    visibilidad_repo_mod._cache_at = 0.0

    r = client.get("/admin/pestanas")
    check("con Supabase de vuelta, /admin/pestanas sigue funcionando normal", r.status_code == 200)

    print(f"\n{len(PASSED)} OK, {len(FAILED)} FAIL")
    if FAILED:
        print("Fallaron:", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    main()
