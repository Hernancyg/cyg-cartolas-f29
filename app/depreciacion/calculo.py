"""
Cálculo de la depreciación lineal normal (Art. 31 N°5 LIR) de un activo
fijo para un período (mes/año) dado — sin tocar Supabase, para poder
testearlo con datos en memoria (ver `tests/test_depreciacion.py`).

Reglas:

  - Depreciación mensual = valor de adquisición / (vida útil en años * 12),
    en línea recta, SIN valor residual (así deprecia el SII, a diferencia
    de la depreciación financiera/contable que sí suele restar uno).
  - El mes de adquisición cuenta como el primer mes de depreciación (un
    bien comprado en cualquier día de marzo ya tiene depreciación de
    marzo).
  - Un bien comprado DESPUÉS del período consultado no se depreció nada
    todavía (meses_transcurridos = 0, no aparece con saldo).
  - Una vez que los meses transcurridos alcanzan la vida útil completa,
    el bien queda "totalmente depreciado" — el valor libro NO baja a 0,
    se queda en $1 mientras el bien siga en uso (así lo exige el SII para
    poder seguir identificándolo en el activo fijo; es una convención
    tributaria, no un error de redondeo).
"""

from datetime import date, timedelta
from typing import Optional


def _parse_fecha(fecha):
    """Acepta un `date`/`datetime` ya parseado o un string 'YYYY-MM-DD'
    (formato que devuelve Supabase para una columna `date`)."""
    if isinstance(fecha, str):
        return date.fromisoformat(fecha[:10])
    if hasattr(fecha, "date") and not isinstance(fecha, date):
        return fecha.date()
    return fecha


def calcular_fila(activo: dict, periodo_year: int, periodo_month: int) -> Optional[dict]:
    """Depreciación de `activo` (dict con fecha_adquisicion,
    valor_adquisicion, vida_util_anios, nombre_activo) al cierre de
    `periodo_year`-`periodo_month`. `None` si el activo todavía no existe
    en ese período (se compró después)."""
    fecha_adq = _parse_fecha(activo["fecha_adquisicion"])
    valor_adquisicion = float(activo["valor_adquisicion"])
    vida_util_anios = int(activo["vida_util_anios"])
    meses_vida_util = max(vida_util_anios * 12, 1)

    meses_transcurridos = (periodo_year * 12 + periodo_month) - (fecha_adq.year * 12 + fecha_adq.month) + 1
    if meses_transcurridos <= 0:
        return None
    meses_transcurridos = min(meses_transcurridos, meses_vida_util)

    depreciacion_mensual = valor_adquisicion / meses_vida_util
    completamente_depreciado = meses_transcurridos >= meses_vida_util
    depreciacion_acumulada = valor_adquisicion - 1 if completamente_depreciado else depreciacion_mensual * meses_transcurridos
    valor_libro = 1 if completamente_depreciado else valor_adquisicion - depreciacion_acumulada

    return {
        "id": activo.get("id"),
        "nombre_activo": activo["nombre_activo"],
        "fecha_adquisicion": fecha_adq.isoformat(),
        "valor_adquisicion": round(valor_adquisicion),
        "vida_util_anios": vida_util_anios,
        "depreciacion_mensual": round(depreciacion_mensual),
        "meses_transcurridos": meses_transcurridos,
        "meses_vida_util": meses_vida_util,
        "depreciacion_acumulada": round(depreciacion_acumulada),
        "valor_libro": round(valor_libro),
        "completamente_depreciado": completamente_depreciado,
        "de_baja": not activo.get("activo", True),
    }


def calcular_tabla(activos: list, periodo_year: int, periodo_month: int) -> list:
    """Una fila por cada activo que ya existía en ese período (los
    comprados después quedan afuera), en el mismo orden recibido."""
    filas = (calcular_fila(a, periodo_year, periodo_month) for a in activos)
    return [f for f in filas if f is not None]


def calcular_kardex(activo: dict, periodos: list) -> list:
    """Historial de depreciación de UN activo, encadenando sus períodos
    editables (`periodos`, ya ordenados por fecha — ver
    `depreciacion_periodos_repo.listar_por_activo`). Cada fila trae lo
    editable (fecha, meses_utilizados, factor_ccmm) sin tocar, más lo
    calculado:

      - costo_total: la base de este período — el "valor_actualizado" de
        la fila ANTERIOR (o el costo de adquisición, en la primera fila).
      - factor_ccmm: corrección monetaria de este período (1 = sin
        corrección). valor_actualizado = costo_total * factor_ccmm, y ESE
        valor (no el costo_total sin corregir) es la base de la fila
        siguiente — así la corrección se va acumulando año a año, como en
        la contabilidad financiera chilena tradicional.
      - vida_util_antes_meses: meses de vida útil que quedaban ANTES de
        consumir los de esta fila (en MESES, no se corrige monetariamente).
      - depreciacion_ejercicio: se calcula con el costo YA corregido de
        esta fila (valor_actualizado / vida_util_meses_total) * meses de
        esta fila — la corrección monetaria se aplica primero, y la
        depreciación del ejercicio se calcula sobre esa base actualizada
        (corregido 11-09-2026 contra un caso real: con costo 40.991.368,
        factor 1,0670 y 12 meses, la depreciación del ejercicio debe dar
        4.373.779 = 43.737.790/120*12, no 4.099.137 = 40.991.368/120*12).
      - deprec_acum_apertura/deprec_acum_actualizado: la acumulada de
        apertura (heredada de la fila anterior) corregida por el mismo
        factor_ccmm de esta fila.
      - deprec_acum_cierre: deprec_acum_actualizado + depreciacion del
        ejercicio — es la que hereda la fila siguiente como su apertura.
      - valor_libro: valor_actualizado - deprec_acum_cierre, salvo que ya
        se haya agotado la vida útil — ahí queda en $1 (misma convención
        SII que `calcular_fila`), nunca en $0 ni negativo.

    Si la suma de meses_utilizados de las filas supera la vida útil total
    del activo, el exceso simplemente no depreciación más (se capea) — no
    revienta ni deja valores negativos, solo dejaría de sumar.
    """
    vida_util_meses_total = max(int(activo["vida_util_anios"]) * 12, 1)
    costo_total = float(activo["valor_adquisicion"])
    deprec_acum_apertura = 0.0
    meses_consumidos_antes = 0

    filas = []
    for p in periodos:
        meses_utilizados = int(p["meses_utilizados"])
        factor_ccmm = float(p.get("factor_ccmm") or 1)

        vida_util_antes = max(vida_util_meses_total - meses_consumidos_antes, 0)
        meses_efectivos = max(min(meses_utilizados, vida_util_antes), 0)

        valor_actualizado = costo_total * factor_ccmm
        deprec_acum_actualizado = deprec_acum_apertura * factor_ccmm

        mensual = valor_actualizado / vida_util_meses_total
        deprec_ejercicio = mensual * meses_efectivos
        completamente_depreciado = (meses_consumidos_antes + meses_efectivos) >= vida_util_meses_total

        if completamente_depreciado:
            deprec_acum_cierre = valor_actualizado - 1
            valor_libro = 1
        else:
            deprec_acum_cierre = deprec_acum_actualizado + deprec_ejercicio
            valor_libro = valor_actualizado - deprec_acum_cierre

        filas.append({
            "id": p.get("id"),
            "fecha": p["fecha"] if isinstance(p["fecha"], str) else p["fecha"].isoformat(),
            "meses_utilizados": meses_utilizados,
            "costo_total": round(costo_total),
            "factor_ccmm": factor_ccmm,
            "valor_actualizado": round(valor_actualizado),
            "vida_util_antes_meses": vida_util_antes,
            "depreciacion_ejercicio": round(deprec_ejercicio),
            "deprec_acum_apertura": round(deprec_acum_apertura),
            "deprec_acum_actualizado": round(deprec_acum_actualizado),
            "deprec_acum_cierre": round(deprec_acum_cierre),
            "valor_libro": round(valor_libro),
            "completamente_depreciado": completamente_depreciado,
            # Cuánto de esta fila se debe a la corrección monetaria (subir
            # la deprec. acum. de apertura por el factor) en vez de al
            # gasto normal del período — lo usa "Generar asiento" para la
            # línea contra la cuenta de Corrección Monetaria.
            "correccion_monetaria": round(deprec_acum_actualizado - deprec_acum_apertura),
        })

        costo_total = valor_actualizado
        deprec_acum_apertura = deprec_acum_cierre
        meses_consumidos_antes += meses_efectivos

    return filas


def parse_fecha(fecha):
    """Versión pública de `_parse_fecha`, para que otros módulos (ej.
    `app/depreciacion/routes.py`) no tengan que tocar un nombre privado."""
    return _parse_fecha(fecha)


def fusionar_kardex_por_anio(filas: list) -> list:
    """SOLO para el archivo de salida del kardex (Descargar Excel) — NO
    para la tabla editable en pantalla, que tiene que seguir mostrando
    cada fila real de `depreciacion_periodos` para poder editarlas o
    deshacer un asiento puntual. Junta en una sola fila todos los
    períodos CONSECUTIVOS del mismo año calendario: si el kardex real
    quedó con varias filas de un mismo año (normal cuando se fue
    generando el asiento mes a mes — ver `app/depreciacion/routes.py:
    _extender_periodos`, que no fusiona una fila ya asentada), el Excel
    de salida las muestra como una sola fila de ese año, sea cual sea la
    cantidad de meses con la que se fue procesando.

    Cada fila fusionada:
      - meses_utilizados / depreciacion_ejercicio: suma de las filas del
        grupo (la depreciación del ejercicio de cada fila ya refleja
        cualquier corrección aplicada hasta esa fila, así que sumarlas es
        siempre válido).
      - costo_total / vida_util_antes_meses / deprec_acum_apertura: los
        de la PRIMERA fila del grupo (el estado ANTES de que empezara a
        consumirse ese año).
      - factor_ccmm: el factor EFECTIVO combinado del grupo
        (valor_actualizado de la última fila / costo_total de la
        primera) — para que, aplicado sobre el costo/la apertura de la
        primera fila, siga dando el mismo valor actualizado/acumulada
        actualizada que la última fila calculó de verdad.
      - valor_actualizado / deprec_acum_cierre / valor_libro /
        completamente_depreciado: los de la ÚLTIMA fila del grupo (el
        estado de cierre real, ya con todas las correcciones del año
        aplicadas)."""
    if not filas:
        return []

    def _cerrar_grupo(grupo):
        primera, ultima = grupo[0], grupo[-1]
        costo_total = primera["costo_total"]
        factor_ccmm = round(ultima["valor_actualizado"] / costo_total, 4) if costo_total else 1.0
        return {
            "id": ultima["id"],
            "fecha": ultima["fecha"],
            "meses_utilizados": sum(f["meses_utilizados"] for f in grupo),
            "costo_total": costo_total,
            "factor_ccmm": factor_ccmm,
            "valor_actualizado": ultima["valor_actualizado"],
            "vida_util_antes_meses": primera["vida_util_antes_meses"],
            "depreciacion_ejercicio": sum(f["depreciacion_ejercicio"] for f in grupo),
            "deprec_acum_apertura": primera["deprec_acum_apertura"],
            "deprec_acum_actualizado": round(primera["deprec_acum_apertura"] * factor_ccmm),
            "deprec_acum_cierre": ultima["deprec_acum_cierre"],
            "valor_libro": ultima["valor_libro"],
            "completamente_depreciado": ultima["completamente_depreciado"],
            "correccion_monetaria": sum(f["correccion_monetaria"] for f in grupo),
        }

    fusionadas = []
    grupo = [filas[0]]
    for fila in filas[1:]:
        if _parse_fecha(fila["fecha"]).year == _parse_fecha(grupo[-1]["fecha"]).year:
            grupo.append(fila)
        else:
            fusionadas.append(_cerrar_grupo(grupo))
            grupo = [fila]
    fusionadas.append(_cerrar_grupo(grupo))
    return fusionadas


def meses_faltantes(fecha_ultima_fila, fecha_adquisicion, anio_objetivo: int, mes_objetivo: int) -> int:
    """Cuántos meses hay que agregar como una fila NUEVA del kardex para
    que llegue hasta el cierre de `anio_objetivo`-`mes_objetivo` — lo usa
    "Generar asiento" para extender solo el kardex de un activo hasta el
    mes que se está gestionando (`app/depreciacion/routes.py:
    _extender_periodos`), sin que el usuario tenga que agregar esa fila a
    mano en la ficha del activo primero.

    - Si el activo ya tiene filas, cuenta desde el mes SIGUIENTE al de la
      última fila (esa fila ya "usó" su propio mes de cierre).
    - Si todavía no tiene ninguna, cuenta desde el mes de adquisición
      INCLUSIVE (mismo criterio que `calcular_fila`: el mes de compra ya
      cuenta como el primero).
    - 0 si el kardex ya llega hasta ese mes o más allá (nada que agregar)."""
    objetivo_ordinal = anio_objetivo * 12 + mes_objetivo
    if fecha_ultima_fila is not None:
        base_ordinal = fecha_ultima_fila.year * 12 + fecha_ultima_fila.month
        return max(objetivo_ordinal - base_ordinal, 0)
    base_ordinal = fecha_adquisicion.year * 12 + fecha_adquisicion.month
    return max(objetivo_ordinal - base_ordinal + 1, 0)


def ultimo_dia_mes(anio: int, mes: int) -> date:
    """Fecha del último día de `anio`-`mes` (ej. 2026-02 -> 2026-02-28) —
    la fecha que se le pone a la fila que agrega `meses_faltantes`."""
    if mes == 12:
        return date(anio + 1, 1, 1) - timedelta(days=1)
    return date(anio, mes + 1, 1) - timedelta(days=1)
