"""
Cálculo del Impuesto Global Complementario (IGC), año tributario 2026.

Lógica basada en el Formulario 22 AT2026 oficial del SII (hoja "F22
AT2026" y tabla "IGC 2026" del archivo de referencia entregado por el
usuario), simplificada a los conceptos más comunes para un contribuyente
persona natural con rentas de trabajo (sueldos + honorarios), retiros de
empresas (régimen 14 A o 14 D N°3) y otras rentas afectas.

Ajustado el 02-09-2026 según correcciones del usuario:

  - "Total Imponible" (sueldos) se rebaja específicamente por "Leyes
    Sociales" (cotizaciones previsionales) para obtener la renta líquida
    afecta por sueldos que entra a la base del IGC — ya no es una rebaja
    genérica sobre el total, sino una resta puntual sobre el ingreso por
    sueldos.
  - Se agrega el Impuesto Único de Segunda Categoría (IUSC) ya retenido
    sobre los sueldos como un crédito contra el IGC (art. 47 LIR:
    reliquidación anual de impuesto único cuando el contribuyente además
    tiene otras rentas que lo obligan a declarar IGC).
  - Honorarios: se calcula automáticamente la rebaja de 30% de gasto
    presunto (art. 50 LIR) sobre el monto bruto de las boletas, y solo el
    70% restante ("honorarios a tributar") entra a la base imponible. El
    crédito por honorarios (retención de boleta) se mantiene aparte, tal
    como lo entrega el usuario, calculado sobre el monto bruto.
  - Se eliminó la sección de "Dividendos": el usuario pidió dejar en esta
    calculadora solo Retiros, separados en régimen 14 A / 14 D N°3.

Ajustado el 02-09-2026 (segunda corrección) según regla adicional del
usuario para honorarios:

  - Quienes emiten boletas de honorarios por un monto anual igual o
    superior a 5 ingresos mínimos mensuales (Ley 21.133, cotización
    previsional obligatoria de independientes) quedan afectos al pago de
    cotizaciones previsionales. El usuario pidió aproximarlo como el 85%
    de la retención de honorarios (corregido el mismo día: no 0,85%, sino
    0.85 tal cual), y aclaró que este ítem es un "pago", no un crédito
    contra el impuesto.

Ajustado el 03-09-2026 (tercera corrección) sobre dónde se aplica ese pago:

  - El usuario corrigió que la cotización previsional de honorarios "debe
    ser en positivo, por ende rebaja la devolución" — es decir, NO es una
    rebaja de la base imponible (eso reduciría el IGC según tabla y, al
    mantener los créditos iguales, terminaba AUMENTANDO el saldo a favor,
    justo al revés de lo esperado). Ahora se suma en positivo directamente
    al resultado final (junto al impuesto determinado, después de restar
    los créditos): reduce el saldo a favor o aumenta el impuesto a pagar,
    según corresponda. La base imponible y el IGC según tabla ya no se ven
    afectados por este pago.

Agregado el 03-09-2026: campos de "Datos del Contribuyente" (Año
Tributario, Nombre, RUT) y descarga de un PDF con el resumen del cálculo,
a partir de un mockup de referencia entregado por el usuario. Estos tres
campos son puramente identificatorios — no participan en ningún cálculo,
solo se usan para el encabezado del PDF (ver `app/global_igc/
pdf_generator.py`).

Mecánica clave (verificada contra las fórmulas reales del Excel):

  - "Incremento por IDPC" (art. 54 N°1 / 62 LIR): los retiros afectos a
    IGC que llevan asociado un crédito por Impuesto de Primera Categoría
    (IDPC) se declaran por su monto BRUTO, es decir el monto neto
    percibido MÁS el crédito. En el Excel esto corresponde a la línea 14
    (AE39 = M39+Y39). Aquí se aplica ese mismo gross-up a los 2 sub-montos
    de retiros (14 A y 14 D N°3).

  - "Débito por restitución" (art. 56 N°3 inciso final LIR, 35%): solo
    para el crédito IDPC de retiros del régimen 14 A ("con obligación de
    restitución"). En el Excel: AE59 = 35% × (suma de columnas de crédito
    14A). El régimen 14 D N°3 ("sin obligación de restitución") NO paga
    este débito.

  - Los créditos por honorarios (retención de boleta), por IUSC (sueldos)
    y por arriendos se tratan como créditos directos contra el impuesto,
    sin el gross-up de incremento ni la restitución del 35% (esos
    mecanismos son propios de retiros con crédito IDPC, no de esas otras
    rentas).

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
GASTO_PRESUNTO_HONORARIOS_TASA = 0.30

# Cotización previsional obligatoria de honorarios (Ley 21.133): aplica a
# quienes facturan boletas de honorarios por un monto anual igual o mayor a
# 5 ingresos mínimos mensuales. Aproximación pedida por el usuario: 0.85
# (85%) de la retención de honorarios (no del monto bruto) — corregido el
# 02-09-2026, no es 0,85%. Es un "pago" (rebaja a la base imponible), no
# un crédito contra el impuesto.
INGRESO_MINIMO_2026 = 553_553
MESES_UMBRAL_COTIZACION_HONORARIOS = 5
UMBRAL_COTIZACION_HONORARIOS = INGRESO_MINIMO_2026 * MESES_UMBRAL_COTIZACION_HONORARIOS
TASA_COTIZACION_PREVISIONAL_HONORARIOS = 0.85


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


# Campos de texto libre (no pasan por _num en desde_formulario) — solo se
# usan para identificar al contribuyente en el PDF descargable, no afectan
# ningún cálculo.
CAMPOS_TEXTO_CONTRIBUYENTE = ("nombre_contribuyente", "rut_contribuyente")

ANIO_TRIBUTARIO_DEFAULT = 2026


@dataclass
class EntradaGlobal:
    # Datos del contribuyente (03-09-2026, pedido por el usuario para el
    # encabezado del PDF descargable) — no participan en ningún cálculo.
    anio_tributario: float = ANIO_TRIBUTARIO_DEFAULT
    nombre_contribuyente: str = ""
    rut_contribuyente: str = ""

    # Rentas del trabajo — sueldos
    total_imponible: float = 0.0       # sueldos brutos imponibles (antes de descontar leyes sociales)
    leyes_sociales: float = 0.0        # cotizaciones previsionales; se resta del total imponible
    credito_iusc: float = 0.0          # Impuesto Único de 2ª Categoría ya retenido sobre el sueldo (crédito)

    # Rentas del trabajo — honorarios
    honorarios: float = 0.0            # honorarios brutos (boleta); se le resta 30% de gasto presunto
    credito_honorarios: float = 0.0    # retención boleta de honorarios, sobre el monto bruto (crédito directo)

    # Retiros — régimen 14 A (con obligación de restitución) y 14 D N°3 (sin restitución)
    retiros_14a: float = 0.0
    credito_retiros_14a: float = 0.0
    retiros_14d3: float = 0.0
    credito_retiros_14d3: float = 0.0

    # Otras rentas afectas
    arriendos_netos: float = 0.0
    credito_arriendos: float = 0.0
    intereses_reajustes: float = 0.0
    ganancias_capital: float = 0.0
    otros_ingresos_afectos: float = 0.0

    # Rebajas a la base imponible
    pensiones_alimenticias: float = 0.0

    # Otros créditos directos contra el impuesto (donaciones, etc.)
    otros_creditos: float = 0.0

    @classmethod
    def desde_formulario(cls, form) -> "EntradaGlobal":
        campos = {}
        for nombre in cls.__dataclass_fields__:
            if nombre in CAMPOS_TEXTO_CONTRIBUYENTE:
                campos[nombre] = (form.get(nombre) or "").strip()
            else:
                campos[nombre] = _num(form.get(nombre))
        campos["anio_tributario"] = int(campos["anio_tributario"]) or ANIO_TRIBUTARIO_DEFAULT
        return cls(**campos)


@dataclass
class ResultadoGlobal:
    renta_neta_sueldos: float = 0.0
    gasto_presunto_honorarios: float = 0.0
    honorarios_tributables: float = 0.0
    afecto_cotizacion_honorarios: bool = False
    pago_cotizacion_honorarios: float = 0.0
    renta_bruta_retiros: float = 0.0
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

    # --- 1) Sueldos: renta líquida afecta = Total Imponible - Leyes Sociales ---
    r.renta_neta_sueldos = max(entrada.total_imponible - entrada.leyes_sociales, 0)

    # --- 2) Honorarios: rebaja automática de 30% de gasto presunto ---
    r.gasto_presunto_honorarios = round(entrada.honorarios * GASTO_PRESUNTO_HONORARIOS_TASA)
    r.honorarios_tributables = entrada.honorarios - r.gasto_presunto_honorarios

    # --- 2b) Honorarios: cotización previsional obligatoria (Ley 21.133) ---
    r.afecto_cotizacion_honorarios = entrada.honorarios >= UMBRAL_COTIZACION_HONORARIOS
    r.pago_cotizacion_honorarios = (
        round(entrada.credito_honorarios * TASA_COTIZACION_PREVISIONAL_HONORARIOS)
        if r.afecto_cotizacion_honorarios else 0
    )

    # --- 3) Retiros: gross-up por incremento de IDPC ---
    creditos_14a = entrada.credito_retiros_14a
    creditos_14d3 = entrada.credito_retiros_14d3
    r.total_creditos_idpc = creditos_14a + creditos_14d3

    r.renta_bruta_retiros = (
        entrada.retiros_14a + entrada.credito_retiros_14a
        + entrada.retiros_14d3 + entrada.credito_retiros_14d3
    )

    # --- 4) Otras rentas afectas (sin gross-up) ---
    r.otras_rentas_afectas = (
        r.renta_neta_sueldos + r.honorarios_tributables
        + entrada.arriendos_netos + entrada.intereses_reajustes
        + entrada.ganancias_capital + entrada.otros_ingresos_afectos
    )

    # --- 5) Rebajas de la base imponible ---
    # La cotización previsional de honorarios NO es una rebaja de la base
    # imponible (no reduce el IGC según tabla): es un pago que se salda
    # directamente al final, junto al impuesto determinado (ver paso 10) —
    # corregido el 03-09-2026 por pedido del usuario ("debe ser en
    # positivo, por ende rebaja la devolución"). Antes se restaba de la
    # base imponible, lo que erróneamente aumentaba el saldo a favor en
    # vez de disminuirlo.
    r.total_rebajas = entrada.pensiones_alimenticias

    # --- 6) Base imponible anual ---
    r.base_imponible = max(
        r.renta_bruta_retiros + r.otras_rentas_afectas - r.total_rebajas,
        0,
    )

    # --- 7) IGC según tabla ---
    r.igc_segun_tabla = calcular_igc_tabla(r.base_imponible)

    # --- 8) Débito por restitución (35% del crédito IDPC de 14 A) ---
    r.debito_restitucion = round(creditos_14a * RESTITUCION_TASA) if creditos_14a > 0 else 0

    r.impuesto_determinado = r.igc_segun_tabla + r.debito_restitucion

    # --- 9) Total créditos contra el impuesto ---
    r.total_creditos = (
        r.total_creditos_idpc
        + entrada.credito_iusc
        + entrada.credito_honorarios
        + entrada.credito_arriendos
        + entrada.otros_creditos
    )
    r.detalle_creditos = {
        "credito_idpc_retiros": r.total_creditos_idpc,
        "credito_iusc": entrada.credito_iusc,
        "credito_honorarios": entrada.credito_honorarios,
        "credito_arriendos": entrada.credito_arriendos,
        "otros_creditos": entrada.otros_creditos,
    }

    # --- 10) Resultado final ---
    # La cotización previsional de honorarios se suma en positivo al
    # resultado (no es un crédito, es un pago exigido) — reduce el saldo a
    # favor o aumenta el impuesto a pagar, según corresponda.
    r.resultado = r.impuesto_determinado - r.total_creditos + r.pago_cotizacion_honorarios
    r.a_pagar = r.resultado >= 0
    return r
