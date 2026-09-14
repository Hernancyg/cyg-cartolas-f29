"""
Verificación de "Conciliación" — conciliación asistida contra documentos
auxiliares (14-09-2026), mismo estilo sin-pytest que `tests/test_sii.py`/
`tests/test_depreciacion.py` (reusa el bootstrap de `tests/run_verification.py`
— `flask_app` — importándolo como módulo).

El matching automático (monto Y rut) vive en `app/static/js/conciliacion.js`
(cliente puro) — no se puede probar acá, donde solo corre Python. Estas
pruebas cubren todo lo que SÍ es del servidor: parseo de los 3 Excel
auxiliares, la ruta de carga AJAX, la reconstrucción del pool de
auxiliares tras un error de validación, y el armado del comprobante final
(bloque de Tipo Auxiliar "A"/"H" en la línea Concepto cuando el
movimiento llega resuelto contra un documento, balance Debe==Haber en
cualquier combinación).

Uso:
    python tests/test_conciliacion.py
"""

import io
import sys
from datetime import datetime
from pathlib import Path

import xlrd
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.run_verification import flask_app  # noqa: E402
from app.conciliacion import export_writer  # noqa: E402
from app.conciliacion.documentos import AUXILIAR_MODULOS  # noqa: E402
from app.conciliacion.plan_cuentas import CUENTAS_POR_CODIGO  # noqa: E402

PASSED, FAILED = [], []


def check(label, condition, extra=""):
    if condition:
        PASSED.append(label)
        print(f"  OK  {label}")
    else:
        FAILED.append(label)
        print(f" FAIL {label} {extra}")


def _bytes(wb):
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _xlsx_cartola(filas):
    """`filas`: lista de (fecha_dt, detalle, cargo, abono). Mismo layout
    que arma `app/parsers/output_writer.py` (hoja "Banco", columnas
    B:E)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Banco"
    ws["B1"] = "FECHA DIA/MES"
    ws["C1"] = "DETALLE DE TRANSACCION"
    ws["D1"] = "MONTO CHEQUES O CARGOS"
    ws["E1"] = "MONTO DEPOSITOS O ABONOS"
    for i, (fecha, detalle, cargo, abono) in enumerate(filas, start=2):
        ws.cell(row=i, column=2, value=fecha)
        ws.cell(row=i, column=3, value=detalle)
        ws.cell(row=i, column=4, value=cargo or None)
        ws.cell(row=i, column=5, value=abono or None)
    return _bytes(wb)


def _xlsx_clientes_proveedores(docs, col_monto):
    """`docs`: lista de dicts {rut_numero, rut_dv, nombre, fecha (datetime),
    tipo_documento, numero_documento, monto}. `col_monto`: 16 (P, Clientes)
    o 17 (Q, Proveedores) — mismo layout que `caja_parsers.parsear_
    clientes`/`parsear_proveedores` (encabezado fila 2, datos desde fila 3)."""
    wb = Workbook()
    ws = wb.active
    for i, d in enumerate(docs, start=3):
        ws.cell(row=i, column=3, value=d["rut_numero"])
        ws.cell(row=i, column=4, value=d["rut_dv"])
        ws.cell(row=i, column=5, value=d["nombre"])
        ws.cell(row=i, column=6, value=d["fecha"])
        ws.cell(row=i, column=11, value=d["tipo_documento"])
        ws.cell(row=i, column=12, value=d["numero_documento"])
        ws.cell(row=i, column=col_monto, value=d["monto"])
    return _bytes(wb)


def _xlsx_honorarios(docs):
    """`docs`: lista de dicts {rut, nombre, fecha_txt (DD-MM-AAAA), boleta,
    monto} — mismo layout que `caja_parsers.parsear_honorarios` (encabezado
    fila 3, datos desde fila 4)."""
    wb = Workbook()
    ws = wb.active
    for i, d in enumerate(docs, start=4):
        ws.cell(row=i, column=1, value=d["rut"])
        ws.cell(row=i, column=2, value=d["nombre"])
        ws.cell(row=i, column=3, value=d["fecha_txt"])
        ws.cell(row=i, column=6, value=d["boleta"])
        ws.cell(row=i, column=10, value=d["monto"])
    return _bytes(wb)


def test_auxiliar_modulos_config():
    check("Clientes: cuenta fija 1104-01, bloque A, dirección abono",
          AUXILIAR_MODULOS["clientes"]["cuenta_codigo"] == "1104-01"
          and AUXILIAR_MODULOS["clientes"]["tipo_auxiliar"] == "A"
          and AUXILIAR_MODULOS["clientes"]["direccion"] == "abono")
    check("Proveedores: cuenta fija 2105-01, bloque A, dirección cargo",
          AUXILIAR_MODULOS["proveedores"]["cuenta_codigo"] == "2105-01"
          and AUXILIAR_MODULOS["proveedores"]["tipo_auxiliar"] == "A"
          and AUXILIAR_MODULOS["proveedores"]["direccion"] == "cargo")
    check("Honorarios: cuenta fija 2105-04, bloque H, dirección cargo",
          AUXILIAR_MODULOS["honorarios"]["cuenta_codigo"] == "2105-04"
          and AUXILIAR_MODULOS["honorarios"]["tipo_auxiliar"] == "H"
          and AUXILIAR_MODULOS["honorarios"]["direccion"] == "cargo")
    for modulo, info in AUXILIAR_MODULOS.items():
        check(f"{modulo}: la cuenta fija existe en el plan de cuentas", info["cuenta_codigo"] in CUENTAS_POR_CODIGO)


def test_construir_filas_comprobantes_con_auxiliar():
    """El bloque de Tipo Auxiliar "A"/"H" se escribe en la línea de la
    cuenta Concepto (no en la del banco, que sigue siempre con "B") — y el
    comprobante queda balanceado igual que sin auxiliar."""
    cuenta_banco = {"codigo": "1101-29", "descripcion": "BANCO BCI", "es_banco": True, "requiere_centro_costo": False}
    cuenta_clientes = {"codigo": "1104-01", "descripcion": "DEUDORES CLIENTES", "es_banco": False, "requiere_centro_costo": False}
    auxiliar = {
        "tipo": "A", "rut": "76123456-7", "nombre": "PAC HDI SEGUROS SA",
        "tipo_documento_codigo": 33, "numero_documento": "456", "fecha": datetime(2026, 8, 18),
    }
    movimientos = [{
        "fecha": datetime(2026, 8, 18), "detalle": "TRANSFERENCIA PAC HDI SEGUROS SA",
        "cargo": 0.0, "abono": 103_733.0, "concepto": cuenta_clientes, "auxiliar": auxiliar,
    }]
    filas = export_writer.construir_filas_comprobantes(movimientos, cuenta_banco)
    check("2 líneas (banco + concepto), como sin auxiliar", len(filas) == 2)

    fila_banco = next(f for f in filas if f[4] == "1101-29")
    fila_concepto = next(f for f in filas if f[4] == "1104-01")
    check("línea del banco sigue con Tipo Auxiliar 'B' (no la pisa el auxiliar)", fila_banco[10] == "B")
    check("línea del concepto lleva el bloque 'A' del documento auxiliar", fila_concepto[10] == "A")
    check("línea del concepto: Rut del documento", fila_concepto[11] == "76123456-7")
    check("línea del concepto: Razón Social del documento", fila_concepto[12] == "PAC HDI SEGUROS SA")
    check("línea del concepto: código de Tipo De Documento (33 = FAC-EL)", fila_concepto[13] == 33)
    check("línea del concepto: Folio/N° Documento", fila_concepto[14] == "456")
    check("línea del concepto: Monto = el mismo del movimiento", fila_concepto[15] == 103_733.0)
    check("balanceado", sum(f[8] for f in filas if f[8]) == sum(f[9] for f in filas if f[9]) == 103_733.0)


def test_construir_filas_comprobantes_sin_auxiliar_no_cambia():
    """Regresión: un movimiento sin `auxiliar` (o con `auxiliar=None`, o
    directamente sin la clave) se comporta exactamente como antes de esta
    ronda — sin bloque en la línea Concepto."""
    cuenta_banco = {"codigo": "1101-29", "descripcion": "BANCO BCI", "es_banco": True, "requiere_centro_costo": False}
    cuenta_gasto = {"codigo": "5501-05", "descripcion": "GASTOS VARIOS", "es_banco": False, "requiere_centro_costo": False}
    movimientos = [{
        "fecha": datetime(2026, 8, 21), "detalle": "OF CENTRA",
        "cargo": 50_000.0, "abono": 0.0, "concepto": cuenta_gasto,
    }]
    filas = export_writer.construir_filas_comprobantes(movimientos, cuenta_banco)
    fila_concepto = next(f for f in filas if f[4] == "5501-05")
    check("sin auxiliar: la línea Concepto no lleva Tipo Auxiliar", not fila_concepto[10])
    check("sin auxiliar: balanceado igual que siempre", sum(f[8] for f in filas if f[8]) == sum(f[9] for f in filas if f[9]) == 50_000.0)


def test_cargar_auxiliar_rutas():
    client = flask_app.test_client()
    r = client.post("/login", data={"usuario": "", "clave": "test_local_only_1234"}, follow_redirects=True)
    check("login admin ok (fixture)", r.status_code == 200)

    r = client.post("/conciliacion/cargar-auxiliar/modulo-inexistente", data={}, content_type="multipart/form-data")
    check("módulo desconocido -> 404", r.status_code == 404)

    r = client.post("/conciliacion/cargar-auxiliar/clientes", data={}, content_type="multipart/form-data")
    check("sin archivo -> 400", r.status_code == 400)

    xlsx_clientes = _xlsx_clientes_proveedores(
        [{"rut_numero": "76123456", "rut_dv": "7", "nombre": "PAC HDI SEGUROS SA", "fecha": datetime(2026, 8, 1),
          "tipo_documento": "FAC-EL", "numero_documento": "456", "monto": 103_733}],
        col_monto=16,
    )
    r = client.post(
        "/conciliacion/cargar-auxiliar/clientes",
        data={"archivo": (io.BytesIO(xlsx_clientes), "clientes.xlsx")},
        content_type="multipart/form-data",
    )
    body = r.get_data(as_text=True)
    check("cargar Clientes -> 200", r.status_code == 200)
    check("el fragmento trae el nombre del documento", "PAC HDI SEGUROS SA" in body)
    check("el fragmento trae el RUT armado (76123456-7)", "76123456-7" in body)
    check("el fragmento trae el monto formateado", "103.733" in body or "103733" in body)
    check("el fragmento marca el documento como 'Disponible'", "Disponible" in body)
    check("el fragmento trae el campo oculto aux_clientes_total = 1", 'name="aux_clientes_total" id="aux-total-clientes" value="1"' in body)

    xlsx_vacio = _xlsx_clientes_proveedores([], col_monto=16)
    r = client.post(
        "/conciliacion/cargar-auxiliar/clientes",
        data={"archivo": (io.BytesIO(xlsx_vacio), "vacio.xlsx")},
        content_type="multipart/form-data",
    )
    check("Excel sin documentos -> 400", r.status_code == 400)

    xlsx_honorarios = _xlsx_honorarios([
        {"rut": "16876802-8", "nombre": "Juan Pérez", "fecha_txt": "10-08-2026", "boleta": "BOL-HE 7", "monto": 80_000},
    ])
    r = client.post(
        "/conciliacion/cargar-auxiliar/honorarios",
        data={"archivo": (io.BytesIO(xlsx_honorarios), "honorarios.xlsx")},
        content_type="multipart/form-data",
    )
    body_hon = r.get_data(as_text=True)
    check("cargar Honorarios -> 200", r.status_code == 200)
    check("Honorarios: separa boleta en tipo BOL-HE + número 7", 'value="BOL-HE"' in body_hon and 'value="7"' in body_hon)


def test_descargar_con_auxiliares_y_concepto_plano():
    """Flujo completo de `/conciliacion/descargar` con 3 movimientos: uno
    resuelto contra un documento de Clientes (abono), uno contra un
    documento de Proveedores (cargo), y uno resuelto a mano contra una
    cuenta suelta del plan de cuentas (sin auxiliar) — exactamente lo que
    dejaría armado el JS de matching/búsqueda antes de enviar el
    formulario. Verifica que el .xls final balancea y que cada línea trae
    el bloque de Tipo Auxiliar correcto."""
    client = flask_app.test_client()
    client.post("/login", data={"usuario": "", "clave": "test_local_only_1234"}, follow_redirects=True)

    r = client.post(
        "/conciliacion/procesar",
        data={"archivo": (io.BytesIO(_xlsx_cartola([
            (datetime(2026, 8, 18), "TRANSFERENCIA PAC HDI SEGUROS SA", 0, 103_733),
            (datetime(2026, 8, 20), "PAGO A PROVEEDOR ACME LTDA", 161_721, 0),
            (datetime(2026, 8, 21), "OF CENTRA", 50_000, 0),
        ])), "cartola.xlsx")},
        content_type="multipart/form-data",
    )
    check("procesar cartola -> 200", r.status_code == 200)

    form = {
        "archivo_nombre": "cartola.xlsx",
        "cuenta_banco_codigo": "1101-29",
        "cuenta_banco_descripcion": "BANCO BCI",
        "total_filas": "3",
        # Fila 0: abono, resuelto contra un documento de Clientes.
        "fecha_0": "18-08-2026", "fecha_iso_0": "2026-08-18", "detalle_0": "TRANSFERENCIA PAC HDI SEGUROS SA",
        "cargo_0": "0", "abono_0": "103733",
        "concepto_codigo_0": "1104-01", "concepto_descripcion_0": "DEUDORES CLIENTES",
        "aux_tipo_0": "A", "aux_modulo_0": "clientes", "aux_doc_idx_0": "0",
        "aux_rut_0": "76123456-7", "aux_nombre_0": "PAC HDI SEGUROS SA",
        "aux_tipo_doc_0": "FAC-EL", "aux_numero_doc_0": "456", "aux_fecha_iso_0": "2026-08-18",
        # Fila 1: cargo, resuelto contra un documento de Proveedores.
        "fecha_1": "20-08-2026", "fecha_iso_1": "2026-08-20", "detalle_1": "PAGO A PROVEEDOR ACME LTDA",
        "cargo_1": "161721", "abono_1": "0",
        "concepto_codigo_1": "2105-01", "concepto_descripcion_1": "FACTURAS POR PAGAR",
        "aux_tipo_1": "A", "aux_modulo_1": "proveedores", "aux_doc_idx_1": "0",
        "aux_rut_1": "12345678-9", "aux_nombre_1": "ACME LTDA",
        "aux_tipo_doc_1": "FAC-EL", "aux_numero_doc_1": "789", "aux_fecha_iso_1": "2026-08-15",
        # Fila 2: cargo, resuelto a mano contra una cuenta suelta (sin documento).
        "fecha_2": "21-08-2026", "fecha_iso_2": "2026-08-21", "detalle_2": "OF CENTRA",
        "cargo_2": "50000", "abono_2": "0",
        "concepto_codigo_2": "5501-05", "concepto_descripcion_2": CUENTAS_POR_CODIGO["5501-05"]["descripcion"],
        "aux_tipo_2": "", "aux_modulo_2": "", "aux_doc_idx_2": "",
        "aux_rut_2": "", "aux_nombre_2": "", "aux_tipo_doc_2": "", "aux_numero_doc_2": "", "aux_fecha_iso_2": "",
        # Pool de documentos auxiliares ya cargados (lo que viajaría desde
        # los campos ocultos del fragmento de /cargar-auxiliar).
        "aux_clientes_total": "1",
        "aux_clientes_nombre_0": "PAC HDI SEGUROS SA", "aux_clientes_rut_0": "76123456-7",
        "aux_clientes_fecha_0": "01-08-2026", "aux_clientes_fecha_iso_0": "2026-08-01",
        "aux_clientes_tipo_documento_0": "FAC-EL", "aux_clientes_numero_documento_0": "456", "aux_clientes_monto_0": "103733",
        "aux_proveedores_total": "1",
        "aux_proveedores_nombre_0": "ACME LTDA", "aux_proveedores_rut_0": "12345678-9",
        "aux_proveedores_fecha_0": "15-08-2026", "aux_proveedores_fecha_iso_0": "2026-08-15",
        "aux_proveedores_tipo_documento_0": "FAC-EL", "aux_proveedores_numero_documento_0": "789", "aux_proveedores_monto_0": "161721",
        "aux_honorarios_total": "0",
    }

    r = client.post("/conciliacion/descargar", data=form)
    check("descargar -> 200, entrega un .xls", r.status_code == 200 and r.headers.get("Content-Type") == "application/vnd.ms-excel")

    wb = xlrd.open_workbook(file_contents=r.data)
    ws = wb.sheet_by_index(0)
    filas = [ws.row_values(i) for i in range(1, ws.nrows) if ws.cell(i, 4).value]  # columna Cuenta Detalle no vacía
    check("6 líneas en total (2 por movimiento x 3 movimientos)", len(filas) == 6)

    total_debe = sum(f[8] for f in filas if isinstance(f[8], (int, float)))
    total_haber = sum(f[9] for f in filas if isinstance(f[9], (int, float)))
    check("el comprobante completo queda balanceado (Debe == Haber)", round(total_debe) == round(total_haber) == 103_733 + 161_721 + 50_000)

    fila_clientes = next(f for f in filas if f[4] == "1104-01")
    check("Clientes: Tipo Auxiliar 'A' en la línea 1104-01", fila_clientes[10] == "A")
    check("Clientes: Rut del documento", fila_clientes[11] == "76123456-7")

    fila_proveedores = next(f for f in filas if f[4] == "2105-01")
    check("Proveedores: Tipo Auxiliar 'A' en la línea 2105-01", fila_proveedores[10] == "A")
    check("Proveedores: Rut del documento", fila_proveedores[11] == "12345678-9")

    fila_gasto = next(f for f in filas if f[4] == "5501-05")
    check("Movimiento sin documento: sin Tipo Auxiliar en la línea Concepto", not fila_gasto[10])

    # ---- Ahora un error de validación (falta la cuenta bancaria):
    # confirma que el pool de Clientes/Proveedores se reconstruye y se
    # vuelve a mostrar en pantalla, sin que el admin tenga que volver a
    # subir los Excel. ----
    form_incompleto = dict(form)
    form_incompleto["cuenta_banco_codigo"] = ""
    r = client.post("/conciliacion/descargar", data=form_incompleto)
    body = r.get_data(as_text=True)
    check("sin cuenta bancaria -> 200 (re-muestra la página con el error)", r.status_code == 200)
    check("el pool de Clientes se reconstruye en la página tras el error", "PAC HDI SEGUROS SA" in body)
    check("el pool de Proveedores se reconstruye en la página tras el error", "ACME LTDA" in body)
    check("el movimiento ya resuelto sigue mostrando su detalle", "TRANSFERENCIA PAC HDI SEGUROS SA" in body)


def main():
    test_auxiliar_modulos_config()
    test_construir_filas_comprobantes_con_auxiliar()
    test_construir_filas_comprobantes_sin_auxiliar_no_cambia()
    test_cargar_auxiliar_rutas()
    test_descargar_con_auxiliares_y_concepto_plano()

    print(f"\n{len(PASSED)} OK, {len(FAILED)} FAIL")
    if FAILED:
        print("Fallaron:", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    main()
