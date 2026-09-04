"""
Parser de formularios F29 (SII Chile) para centralización contable.

Extrae del PDF del F29:
  - Periodo tributario (mes / año) desde el código 15.
  - RUT y razón social (solo referencia visual).
  - Los montos de los códigos F29 configurados en cuentas_config.json
    (ver config_manager.py).

Y genera el CSV de "comprobantes unificados" con la estructura entregada
por el usuario (separador ';', codificación Windows-1252/Latin-1, fin de
línea CRLF), siempre respetando estas reglas fijas:
  - Columna A (NUMERO COMPROBANTE): siempre 1
  - Columna B (FECHA COMPROBANTE): último día del mes/año del período
  - Columna C (GLOSA COMPROBANTE) y F (GLOSA DETALLE): "CENTRALIZACION F29 <MES>"
  - Columna D (TIPO COMPROBANTE): siempre T
  - Columna E (CODIGO CUENTA): según cuentas_config.json
  - Columna I (DEBE) / J (HABER): según el "tipo" configurado para esa cuenta
"""

import re
import calendar
from dataclasses import dataclass, field
from typing import Optional

from config_manager import cargar_config, CuentaConfig  # noqa: F401 (re-exportado)

MESES = [
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
]

# ---------------------------------------------------------------------------
# Ajuste de Remanente de Crédito Fiscal (código 504 del F29).
#
# El código 504 es lo que el SII declara como "remanente de crédito fiscal
# del mes anterior" que se está usando este mes. Si ese código trae un
# monto (> 0), significa que la empresa arrastra remanente de IVA, y hay que
# comparar ese monto contra el remanente que efectivamente quedó registrado
# en la contabilidad al cierre del mes anterior (que el usuario ingresa a
# mano, porque viene de los libros, no del PDF).
#
# diferencia = remanente_504 (este mes, según el F29) - remanente_anterior (ingresado a mano)
#   diferencia > 0 -> el remanente contable quedó CORTO: se agrega crédito
#     DEBE  cuenta 1108-02 (Crédito Fiscal IVA)          monto = diferencia
#     HABER cuenta 5203-01 (centro costo "100")            monto = diferencia
#   diferencia < 0 -> el remanente contable quedó LARGO: se rebaja crédito
#     DEBE  cuenta 4405-01 (centro costo "100")            monto = |diferencia|
#     HABER cuenta 1108-02 (Crédito Fiscal IVA)          monto = |diferencia|
#   diferencia == 0 -> no se necesita ningún ajuste.
#
# Estas cuatro cuentas/valores están hardcodeados acá (no en
# cuentas_config.json) porque la lógica es condicional, no un simple
# código -> cuenta. Si alguna vez cambian, se editan estas constantes.
# ---------------------------------------------------------------------------
CODIGO_REMANENTE = "504"
TEXTO_ANCLA_REMANENTE = "Remanente Crédito Fiscal mes anterior"

CUENTA_CREDITO_FISCAL = "1108-02"
CUENTA_REMANENTE_AUMENTA = "5203-01"   # cuando el remanente del F29 > el de los libros
CUENTA_REMANENTE_DISMINUYE = "4405-01"  # cuando el remanente del F29 < el de los libros
CENTRO_COSTO_REMANENTE = "100"

# ---------------------------------------------------------------------------
# Remanente de Crédito Fiscal "para el período siguiente" (código 77).
#
# Agregado 04-09-2026 para la carga masiva de varios períodos: es el
# remanente que el propio F29 de ESTE mes declara que se traspasa al mes
# SIGUIENTE. Sirve para encadenar automáticamente el remanente_anterior del
# período siguiente cuando se procesan varios F29 consecutivos de una vez
# (en vez de pedírselo al usuario a mano, como hay que hacer para el primer
# período de la carga, que no tiene un F29 previo en el lote).
#
# El recuadro donde vive el código 77 en el PDF del SII queda muy pegado a
# los recuadros vecinos ("Postergación pago del IVA" / "IVA determinado"),
# así que `page.extract_text()` de pdfplumber entrega esa zona con el texto
# de la etiqueta entrelazado letra por letra con el de los recuadros de al
# lado (ej.: "R pe e r m ío a d n o e s n i t g e u d ie e n c te rédito
# fiscal para el 77 39.810.991 756 Postergación..."). Es un texto raro pero
# ESTABLE: sale exactamente igual en todos los F29 (mismo layout de
# plantilla del SII), así que sirve igual de bien como texto ancla fijo que
# cualquier otro código de esta app — se verificó contra dos F29 reales de
# meses distintos y el texto ancla salió idéntico en ambos.
CODIGO_REMANENTE_SIGUIENTE = "77"
TEXTO_ANCLA_REMANENTE_SIGUIENTE = (
    "R pe e r m ío a d n o e s n i t g e u d ie e n c te rédito fiscal para el"
)


@dataclass
class F29Data:
    mes: Optional[str] = None       # "06"
    anio: Optional[str] = None      # "2026"
    rut: Optional[str] = None
    razon_social: Optional[str] = None
    valores: dict = field(default_factory=dict)  # codigo_f29 -> str monto crudo
    remanente_504: int = 0
    remanente_504_encontrado: bool = False
    remanente_periodo_siguiente: int = 0
    remanente_periodo_siguiente_encontrado: bool = False
    advertencias: list = field(default_factory=list)


def _clean_monto(raw: Optional[str]) -> int:
    """Convierte '35.656.723' o '' o None -> int (0 si vacío)."""
    if not raw:
        return 0
    limpio = raw.strip().replace(".", "").replace(",", "")
    if not limpio:
        return 0
    try:
        return int(limpio)
    except ValueError:
        return 0


def extraer_texto_pdf(path_or_file) -> str:
    import pdfplumber

    texto_paginas = []
    with pdfplumber.open(path_or_file) as pdf:
        for page in pdf.pages:
            texto_paginas.append(page.extract_text() or "")
    return "\n".join(texto_paginas)


def parsear_periodo(texto: str, advertencias: list):
    mes = anio = None
    # El SII no siempre imprime el mes y el año en la misma línea (a veces
    # van en la línea siguiente a "Mes Año", a veces en la misma línea junto
    # a otros códigos), así que se busca el mes y el año como los primeros
    # números válidos que aparecen después del encabezado "Mes Año", sin
    # exigir una línea exacta.
    m = re.search(
        r"Mes\s+A[ñn]o[\s\S]{0,60}?\b(0[1-9]|1[0-2])\b[\s\S]{0,30}?\b(20\d{2})\b",
        texto,
    )
    if m:
        mes, anio = m.group(1), m.group(2)
    else:
        advertencias.append(
            "No se pudo detectar automáticamente el período (mes/año) del F29. "
            "Debes ingresarlo manualmente."
        )
    return mes, anio


def parsear_contribuyente(texto: str):
    rut = None
    razon_social = None

    m_rut = re.search(r"(\d{7,8}-[\dkK])", texto)
    if m_rut:
        rut = m_rut.group(1)

    m_rs = re.search(r"Nombres\s*\n(.+)\n", texto)
    if m_rs:
        razon_social = m_rs.group(1).strip()

    return rut, razon_social


def parsear_f29(path_or_file, configs=None) -> F29Data:
    if configs is None:
        configs = cargar_config()

    data = F29Data()
    texto = extraer_texto_pdf(path_or_file)

    data.mes, data.anio = parsear_periodo(texto, data.advertencias)
    data.rut, data.razon_social = parsear_contribuyente(texto)

    for cfg in configs:
        match = cfg.compile().search(texto)
        if match:
            data.valores[cfg.codigo_f29] = match.group(1) or "0"
            if not match.group(1):
                data.advertencias.append(
                    f"El código {cfg.codigo_f29} ({cfg.descripcion}) se encontró "
                    f"pero sin monto asociado; se usará 0. Verifica manualmente."
                )
        else:
            data.valores[cfg.codigo_f29] = None
            data.advertencias.append(
                f"No se pudo ubicar el código {cfg.codigo_f29} ({cfg.descripcion}) "
                f"en el PDF con el texto de referencia configurado. Ingresa el "
                f"monto manualmente o ajusta el texto de referencia en el panel "
                f"de administrador."
            )

    # --- Remanente de Crédito Fiscal (código 504) ---
    remanente_cfg = CuentaConfig(
        cuenta="",
        codigo_f29=CODIGO_REMANENTE,
        descripcion="Remanente Crédito Fiscal mes anterior",
        tipo="",
        texto_ancla=TEXTO_ANCLA_REMANENTE,
        operador="+",
    )
    match_504 = remanente_cfg.compile().search(texto)
    if match_504:
        data.remanente_504 = _clean_monto(match_504.group(1))
        data.remanente_504_encontrado = True
    else:
        data.remanente_504 = 0
        data.remanente_504_encontrado = False
        data.advertencias.append(
            f"No se pudo ubicar el código {CODIGO_REMANENTE} (Remanente Crédito "
            f"Fiscal mes anterior) en el PDF. Se asumirá que no hay remanente "
            f"este mes; verifica manualmente si esperabas que lo hubiera."
        )

    # --- Remanente de Crédito Fiscal para el período SIGUIENTE (código 77) ---
    # Usado solo por la carga masiva de varios períodos, para encadenar el
    # remanente_anterior del período que sigue a este en el mismo lote.
    match_77 = re.search(
        re.escape(TEXTO_ANCLA_REMANENTE_SIGUIENTE)
        + r"[\s\S]{0,200}?\b"
        + re.escape(CODIGO_REMANENTE_SIGUIENTE)
        + r"\b\s+([\d.,]+)?",
        texto,
    )
    if match_77:
        data.remanente_periodo_siguiente = _clean_monto(match_77.group(1))
        data.remanente_periodo_siguiente_encontrado = True
    else:
        data.remanente_periodo_siguiente = 0
        data.remanente_periodo_siguiente_encontrado = False

    return data


def calcular_lineas_remanente(remanente_actual: int, remanente_anterior: int) -> list:
    """
    Compara el remanente de crédito fiscal declarado este mes (código 504)
    contra el remanente que quedó registrado en la contabilidad al cierre
    del mes anterior, y arma las líneas contables del ajuste.

    Devuelve una lista de líneas (dicts con cuenta/tipo/monto/centro_costo)
    lista para agregar a la lista de líneas del comprobante. Lista vacía si
    no hay diferencia.
    """
    diferencia = remanente_actual - remanente_anterior
    if diferencia == 0:
        return []

    monto = abs(diferencia)
    if diferencia > 0:
        return [
            {"cuenta": CUENTA_CREDITO_FISCAL, "tipo": "DEBE", "monto": monto, "centro_costo": ""},
            {"cuenta": CUENTA_REMANENTE_AUMENTA, "tipo": "HABER", "monto": monto, "centro_costo": CENTRO_COSTO_REMANENTE},
        ]
    else:
        return [
            {"cuenta": CUENTA_REMANENTE_DISMINUYE, "tipo": "DEBE", "monto": monto, "centro_costo": CENTRO_COSTO_REMANENTE},
            {"cuenta": CUENTA_CREDITO_FISCAL, "tipo": "HABER", "monto": monto, "centro_costo": ""},
        ]


def ultimo_dia_mes(mes: str, anio: str) -> str:
    mes_i, anio_i = int(mes), int(anio)
    ultimo_dia = calendar.monthrange(anio_i, mes_i)[1]
    return f"{ultimo_dia:02d}-{mes_i:02d}-{anio_i}"


def nombre_mes(mes: str) -> str:
    return MESES[int(mes) - 1]


def construir_filas(mes: str, anio: str, lineas: list) -> list:
    """
    lineas: lista de dicts, cada uno con:
      - cuenta: código de cuenta contable
      - tipo: "DEBE" o "HABER"
      - monto: int
      - centro_costo: str, opcional (columna H). Por defecto "".

    Se acepta una lista (no un dict) porque una misma cuenta puede aparecer
    en más de una línea del comprobante (por ejemplo, el ajuste de remanente
    de crédito fiscal agrega una línea extra a la cuenta 1108-02 además de
    la que ya viene de los códigos F29 normales).

    Devuelve lista de listas (16 columnas cada una) lista para volcar a CSV.
    """
    fecha = ultimo_dia_mes(mes, anio)
    glosa = f"CENTRALIZACION F29 {nombre_mes(mes)}"

    filas = []
    primera = True
    for linea in lineas:
        cuenta = linea["cuenta"]
        tipo = linea["tipo"]
        monto = linea["monto"]
        centro_costo = linea.get("centro_costo") or ""

        debe = str(monto) if tipo == "DEBE" else ""
        haber = str(monto) if tipo == "HABER" else ""
        fila = [
            "1" if primera else "",
            fecha if primera else "",
            glosa if primera else "",
            "T" if primera else "",
            cuenta,
            glosa,
            "",              # SUCURSAL
            centro_costo,    # CENTRO COSTO
            debe, haber,
            "", "", "", "", "", "",
        ]
        filas.append(fila)
        primera = False
    return filas


HEADER = [
    "NUMERO COMPROBANTE",
    "FECHA COMPROBANTE (DD/MM/AAAA)",
    "GLOSA COMPROBANTE",
    "TIPO COMPROBANTE (I: Ingreso, E: Egreso, T: Traspaso)",
    "CODIGO CUENTA",
    "GLOSA DETALLE",
    "SUCURSAL",
    "CENTRO COSTO",
    " DEBE ",
    " HABER ",
    "TIPO AUXILIAR (A: Auxiliar, C: Conciliación, H: Honorario)",
    "A: RUT CUENTA CORRIENTE/C: CÓDIGO BANCARIO/H: RUT PRESTADOR",
    "A: RAZON SOCIAL CUENTA CORRIENTE C: DESCRIPCIÓN CODIGO BANCARIO (OPCIONAL), H: NOMBRE PRESTADOR SERVICIOS",
    "A: NUMERO DOCUMENTO/C: NUMERO DOCUMENTO/H: NUMERO BOLETA",
    "A: VALOR, C: VALOR, H: VALOR NETO",
    "A: FECHA VENCIMIENTO/C: FECHA/H: FECHA EMISIÓN   (DD/MM/AAAA)",
]


def filas_a_csv_bytes(filas: list) -> bytes:
    lineas = [";".join(HEADER)]
    for fila in filas:
        lineas.append(";".join(fila))
    contenido = "\r\n".join(lineas) + "\r\n"
    return contenido.encode("latin-1", errors="replace")
