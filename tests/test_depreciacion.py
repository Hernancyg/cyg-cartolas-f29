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
from app.depreciacion import comprobantes  # noqa: E402
from app.depreciacion.calculo import calcular_fila, calcular_kardex, calcular_tabla, fusionar_kardex_por_anio  # noqa: E402
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


def test_kardex():
    """Valida calcular_kardex contra la planilla real que entregó el
    usuario (Grúa horquilla, 8.250.000, 10 años/120 meses) — 11-09-2026."""
    activo = {"valor_adquisicion": 8_250_000, "vida_util_anios": 10}
    periodos = [
        {"fecha": "2017-04-01", "meses_utilizados": 8},
        {"fecha": "2018-12-31", "meses_utilizados": 12},
        {"fecha": "2019-12-31", "meses_utilizados": 12},
        {"fecha": "2020-12-31", "meses_utilizados": 12},
        {"fecha": "2021-12-31", "meses_utilizados": 12},
        {"fecha": "2022-12-31", "meses_utilizados": 12},
        {"fecha": "2023-12-31", "meses_utilizados": 12},
        {"fecha": "2024-12-31", "meses_utilizados": 12},
        {"fecha": "2025-12-31", "meses_utilizados": 12},
        {"fecha": "2026-09-30", "meses_utilizados": 9},
    ]
    # Sin factor_ccmm explícito -> se asume 1 (sin corrección), debe dar
    # exactamente los mismos números que la planilla de referencia.
    kardex = calcular_kardex(activo, periodos)

    check("kardex: 10 filas calculadas", len(kardex) == 10)
    f1, f2, f10 = kardex[0], kardex[1], kardex[-1]

    check("fila 1: vida útil antes = 120 (total, nada consumido aún)", f1["vida_util_antes_meses"] == 120)
    check("fila 1: depreciación del ejercicio = 550.000 (8 meses x 68.750)", f1["depreciacion_ejercicio"] == 550_000)
    check("fila 1: acumulada de cierre = 550.000", f1["deprec_acum_cierre"] == 550_000)
    check("fila 1: valor libro = 7.700.000", f1["valor_libro"] == 7_700_000)

    check("fila 2: vida útil antes = 112 (120 - 8)", f2["vida_util_antes_meses"] == 112)
    check("fila 2: acumulada de apertura = 550.000 (cierre de la fila 1)", f2["deprec_acum_apertura"] == 550_000)
    check("fila 2: depreciación del ejercicio = 825.000 (12 meses x 68.750)", f2["depreciacion_ejercicio"] == 825_000)
    check("fila 2: acumulada de cierre = 1.375.000", f2["deprec_acum_cierre"] == 1_375_000)
    check("fila 2: valor libro = 6.875.000", f2["valor_libro"] == 6_875_000)

    check("última fila: vida útil antes = 16 (120 - 104 meses ya consumidos)", f10["vida_util_antes_meses"] == 16)
    check("última fila: depreciación del ejercicio = 618.750 (9 meses x 68.750)", f10["depreciacion_ejercicio"] == 618_750)
    check("última fila: acumulada de cierre = 7.768.750", f10["deprec_acum_cierre"] == 7_768_750)
    check("última fila: valor libro = 481.250", f10["valor_libro"] == 481_250)

    # Factor CCMM: corrige el costo (y la deprec. acum. de apertura) de
    # ESTA MISMA fila antes de calcular su depreciación del ejercicio — la
    # corrección se aplica primero, no queda solo para la fila siguiente.
    periodos_ccmm = [
        {"fecha": "2017-04-01", "meses_utilizados": 8, "factor_ccmm": 1.10},
        {"fecha": "2018-12-31", "meses_utilizados": 12, "factor_ccmm": 1},
    ]
    kardex_ccmm = calcular_kardex(activo, periodos_ccmm)
    f1c, f2c = kardex_ccmm[0], kardex_ccmm[1]
    check("factor CCMM: valor actualizado = costo total x factor", f1c["valor_actualizado"] == round(8_250_000 * 1.10))
    check(
        "factor CCMM: la depreciación del ejercicio de la fila 1 SÍ usa el costo YA corregido por su propio factor",
        f1c["depreciacion_ejercicio"] == round(f1c["valor_actualizado"] / 120 * 8),
    )
    check(
        "factor CCMM: el costo total de la fila 2 es el valor actualizado de la fila 1",
        f2c["costo_total"] == f1c["valor_actualizado"],
    )
    check(
        "factor CCMM: la depreciación del ejercicio de la fila 2 ya usa el costo corregido",
        f2c["depreciacion_ejercicio"] == round(f1c["valor_actualizado"] / 120 * 12),
    )
    check(
        "factor CCMM: la deprec. acum. de apertura de la fila 2 es la 'cierre' de la fila 1",
        f2c["deprec_acum_apertura"] == f1c["deprec_acum_cierre"],
    )

    # Caso real reportado por el usuario (11-09-2026): costo 40.991.368,
    # factor 1,0670, 12 meses -> depreciación del ejercicio 4.373.779 (NO
    # 4.099.137, que es lo que daba con el costo SIN corregir).
    activo_real = {"valor_adquisicion": 40_991_368, "vida_util_anios": 10}
    fila_real = calcular_kardex(activo_real, [{"fecha": "2021-12-31", "meses_utilizados": 12, "factor_ccmm": 1.0670}])[0]
    check("caso real: valor actualizado = 43.737.790", fila_real["valor_actualizado"] == 43_737_790)
    check("caso real: depreciación del ejercicio = 4.373.779 (con el costo YA corregido)", fila_real["depreciacion_ejercicio"] == 4_373_779)
    check("caso real: deprec. acum. cierre = 4.373.779 (primera fila, apertura en 0)", fila_real["deprec_acum_cierre"] == 4_373_779)

    # Si la suma de meses supera la vida útil, se capea en $1 (no revienta, no queda negativo).
    periodos_exceso = [{"fecha": "2017-01-01", "meses_utilizados": 200}]
    kardex_exceso = calcular_kardex(activo, periodos_exceso)
    check("meses en exceso: queda completamente depreciado", kardex_exceso[0]["completamente_depreciado"] is True)
    check("meses en exceso: valor libro en $1, no negativo", kardex_exceso[0]["valor_libro"] == 1)


def test_fusionar_kardex_por_anio():
    """`fusionar_kardex_por_anio` — validado contra un caso real que
    reportó el usuario (11-09-2026): activo 'Instalaciones', costo
    55.640.548, 6 años (72 meses), con el kardex quedando en 2 filas
    separadas de 2026 (jul=7 meses, ago=1 mes) porque julio ya se había
    asentado antes de generar agosto."""
    activo = {"valor_adquisicion": 55_640_548, "vida_util_anios": 6}
    periodos = [
        {"fecha": "2023-12-31", "meses_utilizados": 12},
        {"fecha": "2024-12-31", "meses_utilizados": 12},
        {"fecha": "2025-12-31", "meses_utilizados": 12},
        {"fecha": "2026-07-31", "meses_utilizados": 7},
        {"fecha": "2026-08-31", "meses_utilizados": 1},
    ]
    kardex = calcular_kardex(activo, periodos)

    # El kardex SIN fusionar (la tabla editable en pantalla) reproduce exactamente los 5 valores reportados.
    check("sin fusionar: 5 filas (una por período real)", len(kardex) == 5)
    check("sin fusionar: valor libro de julio = 22.410.776", kardex[3]["valor_libro"] == 22_410_776)
    check("sin fusionar: valor libro de agosto = 21.637.991", kardex[4]["valor_libro"] == 21_637_991)

    fusionado = fusionar_kardex_por_anio(kardex)
    check("fusionado: 3 años de 12 meses + 1 fila fusionada de 2026 = 4 filas (no 5)", len(fusionado) == 4)

    fila_2023, fila_2024, fila_2025, fila_2026 = fusionado
    check("2023, 2024 y 2025 no cambian (eran una sola fila cada uno)", fila_2023 == kardex[0] and fila_2024 == kardex[1] and fila_2025 == kardex[2])

    check("2026 fusionado: fecha = la última (2026-08-31)", fila_2026["fecha"] == "2026-08-31")
    check("2026 fusionado: meses utilizados = 7 + 1 = 8", fila_2026["meses_utilizados"] == 8)
    check("2026 fusionado: depreciación del ejercicio = 5.409.498 + 772.785 = 6.182.283", fila_2026["depreciacion_ejercicio"] == 6_182_283)
    check("2026 fusionado: vida útil antes = la de la PRIMERA fila del año (36)", fila_2026["vida_util_antes_meses"] == 36)
    check("2026 fusionado: deprec. acum. apertura = la de la PRIMERA fila del año (27.820.274)", fila_2026["deprec_acum_apertura"] == 27_820_274)
    check("2026 fusionado: deprec. acum. cierre = la de la ÚLTIMA fila del año (34.002.557)", fila_2026["deprec_acum_cierre"] == 34_002_557)
    check("2026 fusionado: valor libro = el de la ÚLTIMA fila del año (21.637.991)", fila_2026["valor_libro"] == 21_637_991)
    check("2026 fusionado: factor CCMM efectivo = 1,0 (ninguna fila del grupo tenía corrección)", fila_2026["factor_ccmm"] == 1.0)

    check("fusionar una lista vacía no revienta", fusionar_kardex_por_anio([]) == [])


def test_comprobantes():
    """`app/depreciacion/comprobantes.py` (rediseño 11-09-2026: se
    consolida por GRUPO CONTABLE, no por activo individual)."""
    grua = {"nombre_activo": "Grua horquilla", "grupo_contable_codigo": None}
    camion = {"nombre_activo": "Camion 1", "grupo_contable_codigo": "1204-01"}
    camion2 = {"nombre_activo": "Camion 2", "grupo_contable_codigo": "1204-01"}
    pend_camion1 = [{"fecha": "2017-12-31", "depreciacion_ejercicio": 550_000, "correccion_monetaria": 0}]
    pend_camion2 = [{"fecha": "2018-12-31", "depreciacion_ejercicio": 825_000, "correccion_monetaria": 50_000}]

    # agrupar_pendientes: sin grupo asignado -> queda en "sin grupo", no se agrupa.
    grupos, sin_grupo = comprobantes.agrupar_pendientes([(grua, pend_camion1), (camion, []), (camion2, [])])
    check("activo sin grupo con pendientes -> aparece en 'sin grupo'", sin_grupo == ["Grua horquilla"])
    check("activo CON grupo pero sin pendientes -> no aparece en ningún lado", grupos == {} and "Camion 1" not in sin_grupo)

    # Dos activos del MISMO grupo -> se suman en una sola entrada.
    grupos, sin_grupo = comprobantes.agrupar_pendientes([(camion, pend_camion1), (camion2, pend_camion2)])
    check("dos activos del mismo grupo -> una sola entrada de grupo", list(grupos.keys()) == ["1204-01"])
    check("se suman los montos de ambos activos", grupos["1204-01"]["ejercicio"] == 550_000 + 825_000 and grupos["1204-01"]["correccion"] == 50_000)
    check("guarda los nombres de los activos incluidos", grupos["1204-01"]["nombres_activos"] == ["Camion 1", "Camion 2"])
    check("ningún activo sin grupo en este caso", sin_grupo == [])

    # validar_grupos: sin configurar en absoluto.
    try:
        comprobantes.validar_grupos(grupos, {})
        check("grupo sin configurar -> debería haber lanzado GrupoFaltante", False)
    except comprobantes.GrupoFaltante as exc:
        check("avisa que el grupo no está configurado", "sin configurar" in str(exc))

    # Con 2 cuentas pero falta Corrección Monetaria (el grupo trae corrección != 0).
    grupos_contables_2 = {"1204-01": {"cuenta_gasto_codigo": "4205-05", "cuenta_acumulada_codigo": "1207-25"}}
    try:
        comprobantes.validar_grupos(grupos, grupos_contables_2)
        check("con corrección y sin cuenta CCMM -> debería haber lanzado GrupoFaltante", False)
    except comprobantes.GrupoFaltante as exc:
        check("exige la cuenta de Corrección Monetaria cuando el grupo la necesita", "Corrección Monetaria" in str(exc))

    # Con las 3 cuentas: arma las filas del comprobante, consolidadas.
    grupos_contables_3 = {"1204-01": {**grupos_contables_2["1204-01"], "cuenta_correccion_codigo": "5501-05"}}
    comprobantes.validar_grupos(grupos, grupos_contables_3)  # no debería lanzar
    filas = comprobantes.construir_filas(grupos, grupos_contables_3, "2018-12-31", "Diciembre 2018")
    check("3 líneas cuando el grupo trae corrección monetaria positiva", len(filas) == 3)
    total_debe = sum(f[8] for f in filas if f[8])
    total_haber = sum(f[9] for f in filas if f[9])
    check("el comprobante consolidado queda balanceado (Debe == Haber)", total_debe == total_haber == 1_425_000)
    check("Gasto por Depreciación = suma de AMBOS activos del grupo", filas[0][8] == 1_375_000 and filas[0][4] == "4205-05")
    check("Corrección Monetaria = suma del grupo", filas[1][8] == 50_000 and filas[1][4] == "5501-05")
    check("Depreciación Acumulada = total consolidado", filas[2][9] == 1_425_000 and filas[2][4] == "1207-25")
    check("la glosa incluye la descripción del grupo y el período, TODO EN MAYÚSCULAS", "VEHICULOS" in filas[0][3] and "DICIEMBRE 2018" in filas[0][3])
    check("la glosa es exactamente igual en mayúsculas y minúsculas (o sea, ya viene en mayúsculas)", filas[0][3] == filas[0][3].upper())
    check("Tipo = 'T' en la primera línea, vacío en las siguientes", filas[0][1] == "T" and filas[1][1] == "" and filas[2][1] == "")
    check("Centro Costo se llena en las cuentas que lo requieren (4205-05 y 5501-05)", filas[0][6] == 100 and filas[1][6] == 100)
    check("Centro Costo vacío en la cuenta que no lo requiere (1207-25)", filas[2][6] == "")

    # Sin corrección monetaria: solo 2 líneas.
    grupos_sin_ccmm, _ = comprobantes.agrupar_pendientes([(camion, pend_camion1)])
    filas_sin_ccmm = comprobantes.construir_filas(grupos_sin_ccmm, grupos_contables_3, "2017-12-31", "Diciembre 2017")
    check("2 líneas cuando no hay corrección monetaria", len(filas_sin_ccmm) == 2)

    # Corrección monetaria negativa (factor < 1, caso raro): va al Haber, sigue balanceado.
    pend_negativa = [{"fecha": "2019-12-31", "depreciacion_ejercicio": 825_000, "correccion_monetaria": -30_000}]
    grupos_neg, _ = comprobantes.agrupar_pendientes([(camion, pend_negativa)])
    filas_negativas = comprobantes.construir_filas(grupos_neg, grupos_contables_3, "2019-12-31", "Diciembre 2019")
    total_debe_neg = sum(f[8] for f in filas_negativas if f[8])
    total_haber_neg = sum(f[9] for f in filas_negativas if f[9])
    check("corrección negativa: sigue balanceado", total_debe_neg == total_haber_neg == 825_000)
    check("corrección negativa: la línea de Corrección Monetaria va al Haber", filas_negativas[1][9] == 30_000 and filas_negativas[1][4] == "5501-05")


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

    # --- Kardex del activo (períodos editables) ---
    r = client.get(f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}")
    check("GET ficha del activo (kardex vacío) -> 200", r.status_code == 200)

    r = client.post(
        f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}/periodos/guardar",
        data={
            "p_fecha": ["2024-12-31", "2025-12-31"],
            "p_meses": ["12", "12"],
            "p_factor_ccmm": ["1", "1"],
        },
        follow_redirects=True,
    )
    check("guardar kardex -> ok", r.status_code == 200 and "guardado" in r.get_data(as_text=True).lower())

    periodos_guardados = FAKE.table("depreciacion_periodos").select("*").eq("activo_id", activo_id).execute().data
    check("quedaron las 2 filas del kardex guardadas", len(periodos_guardados) == 2)

    r = client.get(f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}")
    body_kardex = r.get_data(as_text=True)
    deprec_esperada = round(10_000_000 / 84 * 12)  # vida útil del activo de prueba: 7 años = 84 meses
    deprec_esperada_fmt = "{:,.0f}".format(deprec_esperada).replace(",", ".")
    check(
        "la ficha del activo muestra la depreciación calculada de la 1ª fila (10.000.000/84 meses x 12)",
        r.status_code == 200 and deprec_esperada_fmt in body_kardex,
    )

    r = client.get(f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}/descargar")
    check("descargar kardex en Excel -> 200 con content-type de xlsx", r.status_code == 200 and "spreadsheetml" in r.headers.get("Content-Type", ""))

    r = client.get(f"/depreciacion/empresas/{empresa_id}/descargar")
    check(
        "descargar kardex de TODOS los activos de la empresa -> 200 con content-type de xlsx",
        r.status_code == 200 and "spreadsheetml" in r.headers.get("Content-Type", ""),
    )

    r = client.post(
        f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}/periodos/guardar",
        data={"p_fecha": ["2024-12-31"], "p_meses": ["no-es-un-numero"], "p_factor_ccmm": ["1"]},
        follow_redirects=True,
    )
    check("meses inválidos -> avisa el error, no revienta", r.status_code == 200 and "meses utilizados" in r.get_data(as_text=True).lower())

    r = client.post(
        f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}/periodos/guardar",
        data={"p_fecha": ["2024-12-31"], "p_meses": ["12"], "p_factor_ccmm": ["0"]},
        follow_redirects=True,
    )
    check("factor CCMM en 0 -> avisa el error, no revienta", r.status_code == 200 and "factor ccmm" in r.get_data(as_text=True).lower())

    r = client.post(f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}/baja", follow_redirects=True)
    check("dar de baja el activo -> ok", r.status_code == 200 and "dado de baja" in r.get_data(as_text=True).lower())

    r = client.post(f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}/eliminar", follow_redirects=True)
    check("eliminar activo -> ok", r.status_code == 200)
    check("el activo ya no está en la 'base de datos'", FAKE.table("depreciacion_activos").select("*").execute().data == [])

    r = client.post(f"/depreciacion/empresas/{empresa_id}/eliminar", follow_redirects=True)
    check("eliminar empresa -> ok", r.status_code == 200 and "eliminada" in r.get_data(as_text=True))
    check("la empresa ya no está en la 'base de datos'", FAKE.table("depreciacion_empresas").select("*").execute().data == [])


def test_asientos_flujo():
    client = flask_app.test_client()
    client.post("/login", data={"usuario": "", "clave": "test_local_only_1234"}, follow_redirects=True)

    client.post("/depreciacion/empresas/crear", data={"rut": "", "nombre": "TRANSPORTES CPK LTDA"}, follow_redirects=True)
    empresa = [e for e in FAKE.table("depreciacion_empresas").select("*").execute().data if e["nombre"] == "TRANSPORTES CPK LTDA"][0]
    empresa_id = empresa["id"]

    client.post(
        f"/depreciacion/empresas/{empresa_id}/activos/crear",
        data={"nombre_activo": "Grua horquilla", "fecha_adquisicion": "2017-04-01", "valor_adquisicion": "8250000", "vida_util_anios": "10", "categoria_id": "", "grupo_contable_codigo": ""},
        follow_redirects=True,
    )
    activo = FAKE.table("depreciacion_activos").select("*").eq("empresa_id", empresa_id).execute().data[0]
    activo_id = activo["id"]

    client.post(
        f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}/periodos/guardar",
        data={"p_fecha": ["2017-12-31", "2018-12-31"], "p_meses": ["8", "12"], "p_factor_ccmm": ["1", "1.05"]},
        follow_redirects=True,
    )

    # Sin grupo contable asignado: el panel avisa que ese activo queda afuera.
    r = client.get(f"/depreciacion/empresas/{empresa_id}/asientos?periodo=2018-12")
    body = r.get_data(as_text=True)
    check("GET /asientos -> 200", r.status_code == 200)
    check("sin grupo: avisa que ese activo no se incluye", "Sin grupo contable" in body and "Grua horquilla" in body)

    r = client.post(f"/depreciacion/empresas/{empresa_id}/asientos/generar", data={"periodo": "2018-12"}, follow_redirects=True)
    check("generar sin grupo -> no descarga, avisa el motivo", r.status_code == 200 and "sin grupo contable asignado" in r.get_data(as_text=True).lower())
    check("no se creó ningún asiento todavía", FAKE.table("depreciacion_asientos").select("*").execute().data == [])

    # Asigna el activo a un grupo contable, y configura ese grupo (una vez, no por activo).
    r = client.post(
        f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}/grupo/guardar",
        data={"grupo_contable_codigo": "1204-01"}, follow_redirects=True,
    )
    check("asignar grupo al activo -> ok", r.status_code == 200 and "guardado" in r.get_data(as_text=True).lower())

    r = client.post(
        f"/depreciacion/empresas/{empresa_id}/grupos-contables/guardar",
        data={"grupo_codigo": "1204-01", "cuenta_gasto_codigo": "4205-05", "cuenta_acumulada_codigo": "1207-25", "cuenta_correccion_codigo": "5501-05"},
        follow_redirects=True,
    )
    check("guardar grupo contable -> ok", r.status_code == 200 and "guardado" in r.get_data(as_text=True).lower())

    # Otra empresa puede usar el MISMO código de grupo con cuentas distintas, sin pisarse.
    client.post("/depreciacion/empresas/crear", data={"rut": "", "nombre": "OTRA EMPRESA SPA"}, follow_redirects=True)
    otra_empresa = [e for e in FAKE.table("depreciacion_empresas").select("*").execute().data if e["nombre"] == "OTRA EMPRESA SPA"][0]
    r = client.get(f"/depreciacion/empresas/{otra_empresa['id']}/grupos-contables")
    check("GET grupos contables de otra empresa -> 200", r.status_code == 200)
    check(
        "otra empresa no ve el grupo 1204-01 de la primera (no es global)",
        FAKE.table("depreciacion_grupos_contables").select("*").eq("empresa_id", otra_empresa["id"]).execute().data == [],
    )
    check(
        "la primera empresa conserva su propio grupo 1204-01",
        len(FAKE.table("depreciacion_grupos_contables").select("*").eq("empresa_id", empresa_id).execute().data) == 1,
    )

    r = client.get(f"/depreciacion/empresas/{empresa_id}/asientos?periodo=2018-12")
    check("con el grupo configurado, ya no hay activos sin grupo", "Sin grupo contable" not in r.get_data(as_text=True))

    # Generar hasta 2018-12 (coincide con la última fila del kardex, no hace falta extenderlo): descarga y marca.
    r = client.post(f"/depreciacion/empresas/{empresa_id}/asientos/generar", data={"periodo": "2018-12"})
    check("generar con grupo completo -> 200, descarga un .xls", r.status_code == 200 and r.headers.get("Content-Type") == "application/vnd.ms-excel")

    asentados = FAKE.table("depreciacion_asientos").select("*").eq("activo_id", activo_id).execute().data
    check("quedaron 2 asientos generados (uno por período)", len(asentados) == 2)
    fechas_asentadas = {a["fecha"] for a in asentados}
    check("las fechas asentadas son las 2 del kardex", fechas_asentadas == {"2017-12-31", "2018-12-31"})
    fila_2018 = [a for a in asentados if a["fecha"] == "2018-12-31"][0]
    check("el monto de corrección quedó guardado (Factor CCMM 1.05 sobre apertura 550.000)", fila_2018["monto_correccion"] == round(550_000 * 0.05))
    check("el kardex NO se extendió (2018-12 ya existía)", len(FAKE.table("depreciacion_periodos").select("*").eq("activo_id", activo_id).execute().data) == 2)

    # Generar de nuevo el mismo mes: no hay nada pendiente, no duplica.
    r = client.post(f"/depreciacion/empresas/{empresa_id}/asientos/generar", data={"periodo": "2018-12"}, follow_redirects=True)
    check("generar de nuevo el mismo mes -> avisa que no hay nada pendiente, no duplica", "no había ningún período pendiente" in r.get_data(as_text=True).lower())
    check("sigue habiendo solo 2 asientos (no se duplicó)", len(FAKE.table("depreciacion_asientos").select("*").eq("activo_id", activo_id).execute().data) == 2)

    # Pide junio de 2019 (6 meses después de la última fila, dic-2018): el kardex se extiende SOLO al generar.
    r = client.get(f"/depreciacion/empresas/{empresa_id}/asientos?periodo=2019-06")
    check("previsualizar un mes que el kardex no alcanza -> NO escribe nada (GET no muta)", len(FAKE.table("depreciacion_periodos").select("*").eq("activo_id", activo_id).execute().data) == 2)
    check("la vista previa igual muestra el monto proyectado de ese mes", "1204-01" in r.get_data(as_text=True) or "VEHICULOS" in r.get_data(as_text=True))

    r = client.post(f"/depreciacion/empresas/{empresa_id}/asientos/generar", data={"periodo": "2019-06"})
    check("generar junio 2019 -> 200, descarga de nuevo", r.status_code == 200)

    periodos_finales = FAKE.table("depreciacion_periodos").select("*").eq("activo_id", activo_id).execute().data
    check("el kardex SÍ quedó extendido con una fila nueva (2019-06-30, 6 meses)", any(p["fecha"] == "2019-06-30" and p["meses_utilizados"] == 6 for p in periodos_finales))
    check("ahora hay 3 asientos en total", len(FAKE.table("depreciacion_asientos").select("*").eq("activo_id", activo_id).execute().data) == 3)

    # Deshacer el asiento de la fila auto-generada -> vuelve a quedar pendiente.
    r = client.post(f"/depreciacion/empresas/{empresa_id}/activos/{activo_id}/asientos/2019-06-30/deshacer", follow_redirects=True)
    check("deshacer asiento -> ok", r.status_code == 200 and "deshecho" in r.get_data(as_text=True).lower())
    check("vuelve a haber 2 asientos (se deshizo el de 2019-06)", len(FAKE.table("depreciacion_asientos").select("*").eq("activo_id", activo_id).execute().data) == 2)

    # Segundo activo, mismo grupo contable: sus pendientes se CONSOLIDAN con los del primero en una sola línea.
    client.post(
        f"/depreciacion/empresas/{empresa_id}/activos/crear",
        data={"nombre_activo": "Camion 2", "fecha_adquisicion": "2019-01-01", "valor_adquisicion": "6000000", "vida_util_anios": "5", "categoria_id": "", "grupo_contable_codigo": "1204-01"},
        follow_redirects=True,
    )
    activo2 = [a for a in FAKE.table("depreciacion_activos").select("*").eq("empresa_id", empresa_id).execute().data if a["nombre_activo"] == "Camion 2"][0]
    client.post(
        f"/depreciacion/empresas/{empresa_id}/activos/{activo2['id']}/periodos/guardar",
        data={"p_fecha": ["2019-06-30"], "p_meses": ["6"], "p_factor_ccmm": ["1"]},
        follow_redirects=True,
    )

    r = client.get(f"/depreciacion/empresas/{empresa_id}/asientos?periodo=2019-06")
    body = r.get_data(as_text=True)
    check("ambos activos del grupo aparecen listados en la misma fila del grupo", "Grua horquilla" in body and "Camion 2" in body)

    # Pide julio 2019 para el primer activo: la fila de junio (2019-06-30, 6 meses) es del MISMO año y todavía
    # NO está asentada -> se le suman los meses en vez de crear una fila aparte.
    r = client.post(f"/depreciacion/empresas/{empresa_id}/asientos/generar", data={"periodo": "2019-07"})
    check("generar julio 2019 -> 200", r.status_code == 200)
    periodos_2019 = [p for p in FAKE.table("depreciacion_periodos").select("*").eq("activo_id", activo_id).execute().data if p["fecha"].startswith("2019")]
    check("se fusionó en UNA sola fila 2019 (no quedaron 2 filas separadas)", len(periodos_2019) == 1)
    check("la fila fusionada quedó con fecha 2019-07-31 y 7 meses (6 de junio + 1 de julio)", periodos_2019[0]["fecha"] == "2019-07-31" and periodos_2019[0]["meses_utilizados"] == 7)

    # Pide agosto 2019: la fila de julio YA está asentada (se generó recién) -> esta vez SÍ se crea una fila aparte.
    r = client.post(f"/depreciacion/empresas/{empresa_id}/asientos/generar", data={"periodo": "2019-08"})
    check("generar agosto 2019 -> 200", r.status_code == 200)
    periodos_2019_v2 = sorted(
        (p for p in FAKE.table("depreciacion_periodos").select("*").eq("activo_id", activo_id).execute().data if p["fecha"].startswith("2019")),
        key=lambda p: p["fecha"],
    )
    check(
        "esta vez NO se fusionó (la fila de julio ya estaba asentada) -> quedan 2 filas de 2019",
        len(periodos_2019_v2) == 2 and periodos_2019_v2[0]["fecha"] == "2019-07-31" and periodos_2019_v2[1]["fecha"] == "2019-08-31" and periodos_2019_v2[1]["meses_utilizados"] == 1,
    )


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
    test_kardex()
    test_fusionar_kardex_por_anio()
    test_comprobantes()
    test_categorias_defaults()
    test_rutas_flujo_completo()
    test_asientos_flujo()
    test_categorias_guardar()
    test_trabajador_no_puede_ver_depreciacion()

    print(f"\n{len(PASSED)} OK, {len(FAILED)} FAIL")
    if FAILED:
        print("Fallaron:", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    main()
