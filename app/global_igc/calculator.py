"""
Cálculo del Impuesto Global Complementario (IGC), año tributario 2026.

Lógica basada en el Formulario 22 AT2026 oficial del SII (hoja "F22
AT2026" y tabla "IGC 2026" del archivo de referencia entregado por el
usuario), simplificada a los conceptos más comunes para un contribuyente
persona natural con rentas de trabajo, retiros/dividendos de empresas
(régimen 14 A o 14 D N°3) y otras rentas afectas — el usuario pidió
explícitamente definir los recuadros según el Excel, separando retiros y
dividendos entre régimen 14 A y 14 D N°3, cada uno con su propio crédito.

Mecánica clave (verificada contra las fórmulas reales del Excel):

  - "Incremento por IDPC" (art. 54 N°1 / 62 LIR): los retiros y
    dividendos afectos a IGC que llevan asociado un crédito por Impuesto
    de Primera Categoría (IDPC) se declaran por su monto BRUTO, es decir
    el monto neto percibido MÁS el crédito. En el Excel esto corresponde
    a la línea 14 (AE39 = M39+Y39, donde esos totales suman las columnas
    de crédito "con derecho a devolución" de las líneas de retiros/
    dividendos). Aquí se aplica ese mismo gross-up a los 4 sub-montos de
    retiros/dividendos (14 A y 14 D N°3).

  - "Débito por restitución" (art. 56 N°3 inciso final LIR, 35%): solo
    para el crédito IDPC de retiros/dividendos del régimen 14 A ("con
    obligación de restitución"). En el Excel: AE59 = 35% × (suma de
    columnas de crédito 14A). El régimen 14 D N°3 ("sin obligación de
    restitución") NO paga este débito.

  - Los créditos por honorarios (retención de boleta) y por arriendos se
    tratan como créditos directos contra el impuesto, sin el gross-up de
    incremento ni la restitución del 35% (esos mecanismos son propios de
    retiros/dividendos con crédito IDPC, no de esas otras rentas).

  - Tabla de tramos IGC AT2026 (hoja "IGC 2026" del Excel), en base a
    1 UTA (31-12-2025) = $834.504.
"""

from dataclasses import dataclass, field

UTA_2026 = 834504

# (límite superior del tramo en $, factor, cantidad a rebajar en $)
# Tomado literalmente de la hoja "IGC 2026" (columnas B:E), año tributario 2026.
TRAMOS_IGC_2026 = [
    (11_265_804, 0.0, 0),
    (25_035_120, 0.04, 450_632),
    (41_725_200, 0.08, 1_452_037),
    (58_415_280, 0.135, 3_746_923),
    (75_105_360, 0.23, 9_296_375),
    (100_140_480, 0.304, 14_854_171),
    (258_696_240, 0.35, 19_460_633),
    (float("inf"), 0.40, 32_397_949),
]

RESTITUCION_TASA = 0.35


def calcular_igc_tabla(base_imponible: float) -> float:
    """Busca el tramo de `base_imponible` en la tabla IGC 2026 y aplica
    factor/rebaja (misma fórmula que AE55 del Excel: ROUND(base*factor -
    rebaja, 0), nunca negativo)."""
    if base_imponible <= 0:
        return 0.0
    for limite, factor, rebaja in TRAMOS_IGC_2026:
        if base_imponible <= limite:
            return max(round(base_imponible * factor - rebaja), 0)
    return 0.0


def _num(v) -> float:
    try:
        if v in (None, ""):
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class EntradaGlobal:
    # Rentas del trabajo
    total_imponible: float = 0.0       # sueldos afectos (ya líquidos de IUSC, sin crédito)
    honorarios: float = 0.0            # honorarios brutos (boleta)
    credito_honorarios: float = 0.0    # retención boleta de honorarios (crédito directo)

    # Retiros — régimen 14 A (con obligación de restitución) y 14 D N°3 (sin restitución)
    retiros_14a: float = 0.0
    credito_retiros_14a: float = 0.0
    retiros_14d3: float = 0.0
    credito_retiros_14d3: float = 0.0

    # Dividendos — mismos dos regímenes
    dividendos_14a: float = 0.0
    credito_dividendos_14a: float = 0.0
    dividendos_14d3: float = 0.0
    credito_dividendos_14d3: float = 0.0

    # Otras rentas afectas
    arriendos_netos: float = 0.0
    credito_arriendos: float = 0.0
    intereses_reajustes: float = 0.0
    ganancias_capital: float = 0.0
    otros_ingresos_afectos: float = 0.0

    # Rebajas a la base imponible
    leyes_sociales: float = 0.0        # cotizaciones previsionales (independientes)
    pensiones_alimenticias: float = 0.0

    # Otros créditos directos contra el impuesto (donaciones, etc.)
    otros_creditos: float = 0.0

    @classmethod
    def desde_formulario(cls, form) -> "EntradaGlobal":
        campos = {}
        for nombre in cls.__dataclass_fields__:
            campos[nombre] = _num(form.get(nombre))
        return cls(**campos)


@dataclass
class ResultadoGlobal:
    renta_bruta_retiros_dividendos: float = 0.0
    total_creditos_idpc: float = 0.0
    otras_rentas_afectas: float = 0.0
    total_rebajas: float = 0.0
    base_imponible: float = 0.0
    igc_segun_tabla: float = 0.0
    debito_restitucion: float = 0.0
    impuesto_determinado: float = 0.0
    total_creditos: float = 0.0
    resultado: float = 0.0
    a_pagar: bool = True
    detalle_creditos: dict = field(default_factory=dict)


def calcular_global(entrada: EntradaGlobal) -> ResultadoGlobal:
    r = ResultadoGlobal()

    # --- 1) Retiros y dividendos: gross-up por incremento de IDPC ---
    creditos_14a = entrada.credito_retiros_14a + entrada.credito_dividendos_14a
    creditos_14d3 = entrada.credito_retiros_14d3 + entrada.credito_dividendos_14d3
    r.total_creditos_idpc = creditos_14a + creditos_14d3

    r.renta_bruta_retiros_dividendos = (
        entrada.retiros_14a + entrada.credito_retiros_14a
        + entrada.retiros_14d3 + entrada.credito_retiros_14d3
        + entrada.dividendos_14a + entrada.credito_dividendos_14a
        + entrada.dividendos_14d3 + entrada.credito_dividendos_14d3
    )

    # --- 2) Otras rentas afectas (sin gross-up) ---
    r.otras_rentas_afectas = (
        entrada.total_imponible + entrada.honorarios
        + entrada.arriendos_netos + entrada.intereses_reajustes
        + entrada.ganancias_capital + entrada.otros_ingresos_afectos
    )

    # --- 3) Rebajas ---
    r.total_rebajas = entrada.leyes_sociales + entrada.pensiones_alimenticias

    # --- 4) Base imponible anual ---
    r.base_imponible = max(
        r.renta_bruta_retiros_dividendos + r.otras_rentas_afectas - r.total_rebajas,
        0,
    )

    # --- 5) IGC según tabla ---
    r.igc_segun_tabla = calcular_igc_tabla(r.base_imponible)

    # --- 6) Débito por restitución (35% del crédito IDPC de 14 A) ---
    r.debito_restitucion = round(creditos_14a * RESTITUCION_TASA) if creditos_14a > 0 else 0

    r.impuesto_determinado = r.igc_segun_tabla + r.debito_restitucion

    # --- 7) Total créditos contra el impuesto ---
    r.total_creditos = (
        r.total_creditos_idpc
        + entrada.credito_honorarios
        + entrada.credito_arriendos
        + entrada.otros_creditos
    )
    r.detalle_creditos = {
        "credito_idpc_retiros_dividendos": r.total_creditos_idpc,
        "credito_honorarios": entrada.credito_honorarios,
        "credito_arriendos": entrada.credito_arriendos,
        "otros_creditos": entrada.otros_creditos,
    }

    # --- 8) Resultado final ---
    r.resultado = r.impuesto_determinado - r.total_creditos
    r.a_pagar = r.resultado >= 0
    return r
