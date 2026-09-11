"""
Verificación de "Depreciación" (cálculo, categorías por defecto y rutas),
mismo estilo sin-pytest que `tests/test_sii.py` (reusa el bootstrap de
`tests/run_verification.py` — `flask_app` + `FakeSupabase` — importándolo
como módulo; importar NO corre sus pruebas).

Uso:
    python tests/test_depreciacion.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.run_verification import flask_app, FAKE, seed_data  # noqa: E402
from app.depreciacion.calculo import calcular_fila, calcular_tabla  # noqa: E402
from app.data import depreciacion_categorias_repo  # noqa: E402

PASSED, FAILED = [], []


def check(label, condition, extra=""):
    if condition:
        PASSED.append(label)
        print(f"  OK  {label}")
    else:
        FAILED.append(label)
        print(f" FAIL {label} {extra}")


def test_calculo():
    activo = {
        "id": "a1", "nombre_activo": "Camioneta", "fecha_adquisicion": "2024-03-15",
        "valor_adquisicion": 12_000_000, "vida_util_anios": 5, "activo": True,
    }

    # Mismo mes de la compra: 1 mes depreciado.
    fila = calcular_fila(activo, 2024, 3)
    check("mes de la compra cuenta como el primer mes depreciado", fila["meses_transcurridos"] == 1)
    check("depreciación mensual = valor / (años*12)", fila["depreciacion_mensual"] == round(12_000_000 / 60))
    check("depreciación acumulada = 1 mes de depreciación mensual", fila["depreciacion_acumulada"] == fila["depreciacion_mensual"])
    check("valor libro = valor adquisición - acumulada", fila["valor_libro"] == 12_000_000 - fila["depreciacion_acumulada"])
    check("no está completamente depreciado todavía", fila["completamente_depreciado"] is False)

    # Un año después (mismo mes): 13 meses (marzo 2024 ya contó como el primero).
    fila_1a = calcular_fila(activo, 2025, 3)
    check("un año después (mismo mes) lleva 13 meses depreciados", fila_1a["meses_transcurridos"] == 13)

    # Exactamente al cumplir la vida útil (60 meses = 5 años, desde marzo 2024 -> febrero 2029).
    fila_fin = calcular_fila(activo, 2029, 2)
    check("al cumplir la vida útil queda completamente depreciado", fila_fin["completamente_depreciado"] is True)
    check("valor libro queda en $1 (convención SII), no en $0", fila_fin["valor_libro"] == 1)

    # Más allá de la vida útil: se mantiene en $1, no sigue bajando ni se cae a negativo.
    fila_despues = calcular_fila(activo, 2031, 6)
    check("después de agotada la vida útil sigue en $1", fila_despues["valor_libro"] == 1)
    check("los meses transcurridos no superan la vida útil en meses", fila_despues["meses_transcurridos"] == 60)

    # Comprado después del período consultado: no existe todavía.
    fila_futura = calcular_fila(activo, 2023, 12)
    check("un activo comprado después del período consultado no aparece", fila_futura is None)

    check(
        "calcular_tabla descarta los activos que todavía no existían",
        calcular_tabla([activo, {**activo, "id": "a2", "fecha_adquisicion": "2030-01-01"}], 2024, 3) == [calcular_fila(activo, 2024, 3)],
    )


def test_categorias_defaults():
    categorias = depreciacion_categorias_repo.DEFAULTS
    check("hay categorías por defecto cargadas", len(categorias) > 50)
    check("todas las categorías tienen sección y descripción", all(c["seccion"] and c["descripcion"] for c in categorias))
    vehiculos = [c for c in categorias if "Camiones de uso general" in c["descripcion"]]
    check("'Camiones de uso general' está con 7 años (tabla oficial SII)", vehiculos and vehiculos[0]["vida_util_anios"] == 7)
    computadores = [c for c in categorias if "Sistemas computacionales" in c["descripcion"]]
    check("'Sistemas computacionales' está con 6 años (tabla oficial SII)", computadores and computadores[0]["vida_util_anios"] == 6)
    vinedos = [c for c in categorias if c["descripcion"] == "Viñedos."]
    check("'Viñedos' no trae vida útil fija (variable según variedad)", vinedos and vinedos[0]["vida_util_anios"] is None and vinedos[0]["nota"])


def test_rutas_flujo_completo():
    client = flask_app.test_client()
    r = client.post("/login", data={"usuario": "", "clave": "test_local_only_1234"}, follow_redirects=True)
    check("login admin ok (fixture)", r.status_code == 200)

    r = client.get("/depreciacion/empresas")
    check("GET /depreciacion/empresas -> 200", r.status_code == 200)

    r = client.post("/depreciacion/empresas/crear", data={"rut": "76192083-9", "nombre": "ACME SPA"}, follow_redirects=True)
    check("crear empresa -> ok, redirige al detalle", r.status_code == 200 and "ACME SPA" in r.get_data(as_text=True))

    empresa = FAKE.table("depreciacion_empresas").select("*").execute().data[0]
    empresa_id = empresa["id"]

    r = client.get(f"/depreciacion/empresas/{empresa_id}")
    check("GET detalle de empresa -> 200", r.status_code == 200)
    check("el selector de categorías trae 'Camiones de uso general'", "Camiones de uso general" in r.get_data(as_text=True))

    r = client.post(
        f"/depreciacion/empresas/{empresa_id}/activos/crear",
        data={
            "nombre_activo": "Camioneta Hilux", "fecha_adquisicion": "2024-01-15",
            "valor_adquisicion": "10.000.000", "vida_util_anios": "7", "categoria_id": "",
        },
        follow_redirects=True,
    )
    check("crear activo -> ok", r.status_code == 200 and "Camioneta Hilux" in r.get_data(as_text=True))

    activo = FAKE.table("depreciacion_activos").select("*").execute().data[0]
    check("el activo quedó con el valor de adquisición correcto (parseado desde '10.000.000')", activo["valor_adquisicion"] == 10_000_000.0)
    activo_id = activo["id"]

    r = client.get(f"/depreciacion/empresas/{empresa_id}?periodo=2024-06")
    body = r.get_data(as_text=True)
    check("la tabla de depreciación de un período posterior muestra el activo", r.status_code == 200 and "Camioneta Hilux" in body)

    r = client.get(f"/depreciacion/empresas/{empresa_id}/descargar?periodo=2024-06")
    check("descargar Excel -> 200 con content-type de xlsx", r.status_code == 200 and "spreadsheetml" in r.headers.get("Content-Type", ""))

    r = client.post(f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}/baja", follow_redirects=True)
    check("dar de baja el activo -> ok", r.status_code == 200 and "dado de baja" in r.get_data(as_text=True).lower())

    r = client.post(f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}/eliminar", follow_redirects=True)
    check("eliminar activo -> ok", r.status_code == 200)
    check("el activo ya no está en la 'base de datos'", FAKE.table("depreciacion_activos").select("*").execute().data == [])

    r = client.post(f"/depreciacion/empresas/{empresa_id}/eliminar", follow_redirects=True)
    check("eliminar empresa -> ok", r.status_code == 200 and "eliminada" in r.get_data(as_text=True))
    check("la empresa ya no está en la 'base de datos'", FAKE.table("depreciacion_empresas").select("*").execute().data == [])


def test_categorias_guardar():
    client = flask_app.test_client()
    client.post("/login", data={"usuario": "", "clave": "test_local_only_1234"}, follow_redirects=True)

    r = client.get("/depreciacion/categorias")
    check("GET /depreciacion/categorias -> 200", r.status_code == 200)

    r = client.post(
        "/depreciacion/categorias/guardar",
        data={
            "c_seccion": ["Z.- Prueba"], "c_descripcion": ["Bien de prueba"],
            "c_vida_util": ["4"], "c_nota": [""],
        },
        follow_redirects=True,
    )
    check("guardar categorías -> ok", r.status_code == 200 and "Prueba" in r.get_data(as_text=True))

    guardadas = depreciacion_categorias_repo.listar_categorias()
    check("la tabla quedó con exactamente la fila guardada (reemplazo total)", len(guardadas) == 1 and guardadas[0]["descripcion"] == "Bien de prueba")

    # Deja la tabla de vuelta con los defaults en memoria para no afectar otros checks.
    depreciacion_categorias_repo._cache = None
    depreciacion_categorias_repo._cache_at = 0.0
    FAKE.table("depreciacion_categorias").delete().neq("descripcion", "__never__").execute()


def test_trabajador_no_puede_ver_depreciacion():
    client = flask_app.test_client()
    r = client.post("/login", data={"usuario": "testuser", "clave": "trabajador123"}, follow_redirects=True)
    check("login trabajador ok (fixture)", r.status_code == 200)
    r = client.get("/depreciacion/empresas")
    check("trabajador NO puede ver Depreciación por defecto (403)", r.status_code == 403)


def main():
    seed_data()
    test_calculo()
    test_categorias_defaults()
    test_rutas_flujo_completo()
    test_categorias_guardar()
    test_trabajador_no_puede_ver_depreciacion()

    print(f"\n{len(PASSED)} OK, {len(FAILED)} FAIL")
    if FAILED:
        print("Fallaron:", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    main()
