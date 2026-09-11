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

from datetime import date
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
