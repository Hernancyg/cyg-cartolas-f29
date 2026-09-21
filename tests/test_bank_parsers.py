"""
Verificación del parser de Mercado Pago en `app/parsers/bank_parsers.py`
(21-09-2026, pedido por el usuario: agregar Mercado Pago a "Subir
Cartolas") — a diferencia de los otros bancos (una sola función genérica
por columnas cargo/abono lado a lado), Mercado Pago tiene su propio camino
de extracción porque su tabla trae una sola columna de monto CON SIGNO.

No hay un PDF real de Mercado Pago a mano en este entorno (ver los otros
`tests/test_*` y los 3 "cartola de prueba existe" que fallan siempre en
`run_verification.py` por lo mismo — fixtures de sesiones anteriores que no
están disponibles acá), así que se genera un PDF sintético con reportlab
que reproduce el layout de la captura que mandó el usuario (encabezado
DENOMINACIÓN SOCIAL/RUT/..., bloque de resumen BALANCE INICIAL/DEPÓSITOS/...
y la tabla de movimientos), palabra por palabra en las posiciones (x, y)
correctas, para probar el pipeline completo (pdfplumber incluido), no solo
las funciones auxiliares en aislado.

Uso:
    python tests/test_bank_parsers.py
"""

import io
import sys
from pathlib import Path

from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Importar `tests.run_verification` PRIMERO es obligatorio: ese módulo fija
# las variables de entorno de prueba (SUPABASE_URL/KEY, FLASK_SECRET_KEY,
# etc.) antes de crear la app — si algo bajo `app.*` se importa antes (p.ej.
# `app.parsers.bank_parsers`), `app.config` ya quedó calculado con esas
# variables vacías (los módulos de Python solo se ejecutan una vez), y la
# app creada más abajo pierde la sesión/CSRF ("no secret key was set").
from tests.run_verification import flask_app  # noqa: E402
from app.parsers.bank_parsers import parse_pdf  # noqa: E402

PASSED, FAILED = [], []


def check(label, condition, extra=""):
    if condition:
        PASSED.append(label)
        print(f"  OK  {label}")
    else:
        FAILED.append(label)
        print(f" FAIL {label} {extra}")


# Coordenadas x elegidas a mano para que ninguna columna se pise con la de
# al lado (headers de hasta 3 palabras, letra chica 6pt) — ver el comentario
# de cada rango en `_mercado_pago_pdf_sintetico`.
COL_X = {
    "fecha": 20,
    "hora": 55,
    "tipo_movimiento": 115,
    "tipo_transaccion": 195,
    "id_transaccion": 285,
    "moneda": 365,
    "monto": 410,
    "otros_conceptos": 505,
    "nombre_comercio": 585,
}

FILAS_EJEMPLO = [
    # (fecha, hora, tipo_movimiento, tipo_transaccion, id, monto)
    ("05-01-2026", "13:02:25", "Abono", "Transferencia recibida", "140096574663", "500.000,00"),
    ("05-01-2026", "14:39:47", "Cargo", "Pago", "140759322000", "-2.800,00"),
    ("05-01-2026", "15:08:29", "Cargo", "Pago", "140111799739", "-50.651,00"),
    ("06-01-2026", "09:20:29", "Cargo", "Pago", "140860857992", "-23.681,00"),
]


def _mercado_pago_pdf_sintetico() -> bytes:
    """Arma un PDF de una página que reproduce el layout de la cartola real
    (captura de pantalla que mandó el usuario): encabezado con "Mercado
    Pago" (para que `detect_bank` lo reconozca), un bloque de resumen con
    encabezados de una sola palabra (BALANCE INICIAL, DEPÓSITOS, etc. — a
    propósito, para probar que la búsqueda de encabezado de la tabla de
    movimientos NO se confunde con este bloque) y la tabla de movimientos
    de verdad, con las 4 filas de ejemplo de la cartola real."""
    buffer = io.BytesIO()
    ancho, alto = landscape(A4)
    c = canvas.Canvas(buffer, pagesize=(ancho, alto))

    y = alto - 40
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20, y, "Mercado Pago Emisora S.A.")
    y -= 20

    c.setFont("Helvetica", 7)
    c.drawString(20, y, "DENOMINACION SOCIAL")
    c.drawString(150, y, "RUT")
    c.drawString(220, y, "DOMICILIO")
    c.drawString(400, y, "NOMBRE")
    y -= 14
    c.drawString(20, y, "Mercado Pago Emisora S.A.")
    c.drawString(150, y, "77.214.066-5")
    c.drawString(220, y, "Avenida Apoquindo 4800")
    c.drawString(400, y, "ISERMA SPA")
    y -= 24

    # Bloque de resumen: encabezados de una sola palabra que NO deben
    # confundirse con la tabla de movimientos real (esta fila no tiene
    # "FECHA DE ACREDITACION" ni "MONTO DE TRANSACCION" como frase).
    c.drawString(20, y, "BALANCE")
    c.drawString(70, y, "INICIAL")
    c.drawString(150, y, "DEPOSITOS")
    c.drawString(250, y, "DEBITOS")
    c.drawString(340, y, "COMISIONES")
    c.drawString(440, y, "BALANCE")
    c.drawString(500, y, "FINAL")
    y -= 14
    c.drawString(20, y, "11.223,00")
    c.drawString(150, y, "3.500.528,00")
    c.drawString(250, y, "3.263.890,00")
    c.drawString(340, y, "0,00")
    c.drawString(440, y, "247.861,00")
    y -= 30

    # Encabezado real de la tabla de movimientos.
    c.setFont("Helvetica-Bold", 6)
    c.drawString(COL_X["fecha"], y, "FECHA DE ACREDITACION")
    c.drawString(COL_X["tipo_movimiento"], y, "TIPO DE MOVIMIENTO")
    c.drawString(COL_X["tipo_transaccion"], y, "TIPO DE TRANSACCION")
    c.drawString(COL_X["id_transaccion"], y, "ID DE TRANSACCION")
    c.drawString(COL_X["moneda"], y, "MONEDA")
    c.drawString(COL_X["monto"], y, "MONTO DE TRANSACCION")
    c.drawString(COL_X["otros_conceptos"], y, "OTROS CONCEPTOS")
    c.drawString(COL_X["nombre_comercio"], y, "NOMBRE DEL COMERCIO")
    y -= 16

    c.setFont("Helvetica", 6)
    for fecha, hora, tipo_mov, tipo_trans, id_tx, monto in FILAS_EJEMPLO:
        c.drawString(COL_X["fecha"], y, fecha)
        c.drawString(COL_X["hora"], y, hora)
        c.drawString(COL_X["tipo_movimiento"], y, tipo_mov)
        c.drawString(COL_X["tipo_transaccion"], y, tipo_trans)
        c.drawString(COL_X["id_transaccion"], y, id_tx)
        c.drawString(COL_X["moneda"], y, "CLP")
        c.drawString(COL_X["monto"], y, monto)
        c.drawString(COL_X["otros_conceptos"], y, "0,00")
        # nombre_comercio queda vacío en las 4 filas, igual que en la
        # cartola real de ejemplo.
        y -= 14

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def test_detecta_mercado_pago_y_extrae_movimientos():
    pdf_bytes = _mercado_pago_pdf_sintetico()
    resultado = parse_pdf(io.BytesIO(pdf_bytes))

    check("detecta el banco como 'Mercado Pago'", resultado.banco_detectado == "Mercado Pago")
    check("extrae las 4 filas de movimientos", len(resultado.transacciones) == 4, f"(trajo {len(resultado.transacciones)})")
    check("no hay advertencias", resultado.advertencias == [], str(resultado.advertencias))

    if len(resultado.transacciones) != 4:
        return  # sin las 4 filas, los checks de abajo no tienen sentido

    tx1, tx2, tx3, tx4 = resultado.transacciones

    check("fila 1: fecha sin la hora", tx1.fecha == "05-01-2026", tx1.fecha)
    check("fila 1: detalle = 'Tipo de Transacción' (Transferencia recibida), no 'Tipo de Movimiento'", tx1.descripcion == "Transferencia recibida", tx1.descripcion)
    check("fila 1 (Abono): va a la columna de abonos", tx1.abono == 500000.0 and tx1.cargo == 0.0, f"(cargo={tx1.cargo}, abono={tx1.abono})")

    check("fila 2: detalle = 'Pago'", tx2.descripcion == "Pago", tx2.descripcion)
    check("fila 2 (Cargo, monto negativo): va a la columna de cargos, en positivo", tx2.cargo == 2800.0 and tx2.abono == 0.0, f"(cargo={tx2.cargo}, abono={tx2.abono})")

    check("fila 3 (Cargo): monto correcto", tx3.cargo == 50651.0 and tx3.abono == 0.0, f"(cargo={tx3.cargo}, abono={tx3.abono})")

    check("fila 4: fecha del día siguiente", tx4.fecha == "06-01-2026", tx4.fecha)
    check("fila 4 (Cargo): monto correcto", tx4.cargo == 23681.0 and tx4.abono == 0.0, f"(cargo={tx4.cargo}, abono={tx4.abono})")

    total_cargo = sum(t.cargo for t in resultado.transacciones)
    total_abono = sum(t.abono for t in resultado.transacciones)
    check("total cargos = 2.800 + 50.651 + 23.681", total_cargo == 77132.0, total_cargo)
    check("total abonos = 500.000", total_abono == 500000.0, total_abono)


def test_bank_by_key_y_tarjeta():
    from app.cartolas.banks import BANKS, BANK_DISPLAY_TO_DETECTED, bank_by_key

    mp = next((b for b in BANKS if b["key"] == "mercado_pago"), None)
    check("Mercado Pago está en la lista de tarjetas de bancos", mp is not None)
    if mp:
        check("tarjeta de Mercado Pago sin logo cae al respaldo de color", mp.get("logo") is None and bool(mp.get("color")))
    check(
        "el mapeo tarjeta->banco detectado incluye Mercado Pago",
        BANK_DISPLAY_TO_DETECTED.get("Mercado Pago") == "Mercado Pago",
    )
    check("bank_by_key('mercado_pago') encuentra la tarjeta", bank_by_key("mercado_pago") is not None)


def test_flujo_completo_via_rutas():
    """Sube la cartola sintética de Mercado Pago por `/cartolas/procesar`
    (como lo haría un usuario de verdad, tarjeta incluida) y confirma que
    la vista previa trae los valores esperados, luego descarga el Excel
    convertido por `/cartolas/descargar` y confirma su contenido."""
    from openpyxl import load_workbook

    client = flask_app.test_client()
    client.post("/login", data={"usuario": "", "clave": "test_local_only_1234"}, follow_redirects=True)

    pdf_bytes = _mercado_pago_pdf_sintetico()
    r = client.post(
        "/cartolas/procesar",
        data={"banco": "mercado_pago", "archivo": (io.BytesIO(pdf_bytes), "cartola_mp.pdf")},
        content_type="multipart/form-data",
    )
    check("POST /cartolas/procesar (Mercado Pago) -> 200", r.status_code == 200)
    body = r.get_data(as_text=True)
    check("la vista previa NO avisa de banco equivocado", "pero el contenido del archivo parece ser de" not in body)
    check("la vista previa trae la fila 'Transferencia recibida'", "Transferencia recibida" in body)
    check("la vista previa trae 4 movimientos encontrados", ">4<" in body)

    r = client.post(
        "/cartolas/descargar",
        data={
            "csrf_token": "",
            "base_name": "cartola_mp",
            "fecha": ["05-01-2026", "05-01-2026", "05-01-2026", "06-01-2026"],
            "detalle": ["Transferencia recibida", "Pago", "Pago", "Pago"],
            "cargo": ["0", "2800", "50651", "23681"],
            "abono": ["500000", "0", "0", "0"],
        },
    )
    check("POST /cartolas/descargar -> 200", r.status_code == 200)
    check(
        "descarga entrega un .xlsx (Content-Type correcto)",
        "spreadsheetml.sheet" in (r.headers.get("Content-Type") or ""),
    )
    wb = load_workbook(io.BytesIO(r.data))
    ws = wb.active
    check("hoja de salida se llama 'Banco'", ws.title == "Banco")
    # Columnas del openpyxl.iter_rows: 0=A(vacía) 1=B(fecha) 2=C(detalle)
    # 3=D(cargo) 4=E(abono).
    filas = list(ws.iter_rows(min_row=2, max_row=5, values_only=True))
    check("fila 1 exportada: abono 500.000, sin cargo", filas[0][4] == 500000 and filas[0][3] is None, filas[0])
    check("fila 2 exportada: cargo 2.800, sin abono", filas[1][3] == 2800 and filas[1][4] is None, filas[1])


def main():
    test_detecta_mercado_pago_y_extrae_movimientos()
    test_bank_by_key_y_tarjeta()
    test_flujo_completo_via_rutas()

    print(f"\n{len(PASSED)} OK, {len(FAILED)} FAIL")
    if FAILED:
        print("Fallaron:", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    main()
