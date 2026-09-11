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


def calcular_kardex(activo: dict, periodos: list) -> list:
    """Historial de depreciación de UN activo, encadenando sus períodos
    editables (`periodos`, ya ordenados por fecha — ver
    `depreciacion_periodos_repo.listar_por_activo`). Cada fila calculada
    agrega, sin modificar lo editable (fecha/meses_utilizados/adiciones):

      - costo_total: costo de adquisición + adiciones acumuladas hasta
        esa fila (una adición sube la base de depreciación DESDE esa fila
        en adelante, no retroactivamente).
      - vida_util_antes_meses: meses de vida útil que quedaban ANTES de
        consumir los de esta fila (para que se vea igual que la columna
        "Vida útil" de la planilla de referencia del usuario).
      - depreciacion_ejercicio: (costo_total / vida_util_meses_total) *
        meses_utilizados de esta fila.
      - deprec_acum_apertura/deprec_acum_cierre: acumulada ANTES/DESPUÉS
        de esta fila (para mostrar ambas, como la planilla de referencia).
      - valor_libro: costo_total - deprec_acum_cierre, salvo que ya se
        haya agotado la vida útil — ahí queda en $1 (misma convención SII
        que `calcular_fila`), nunca en $0 ni negativo.

    Si la suma de meses_utilizados de las filas supera la vida útil total
    del activo, el exceso simplemente no depreciación más (se capea) —
    no revienta ni deja valores negativos, solo dejaría de sumar.
    """
    vida_util_meses_total = max(int(activo["vida_util_anios"]) * 12, 1)
    costo_corrido = float(activo["valor_adquisicion"])
    meses_consumidos_antes = 0
    deprec_acum_cierre = 0.0

    filas = []
    for p in periodos:
        adiciones = float(p.get("adiciones") or 0)
        costo_corrido += adiciones
        meses_utilizados = int(p["meses_utilizados"])

        vida_util_antes = max(vida_util_meses_total - meses_consumidos_antes, 0)
        meses_efectivos = max(min(meses_utilizados, vida_util_antes), 0)

        mensual = costo_corrido / vida_util_meses_total
        deprec_ejercicio = mensual * meses_efectivos
        deprec_acum_apertura = deprec_acum_cierre
        completamente_depreciado = (meses_consumidos_antes + meses_efectivos) >= vida_util_meses_total

        if completamente_depreciado:
            deprec_acum_cierre = costo_corrido - 1
            valor_libro = 1
        else:
            deprec_acum_cierre = deprec_acum_apertura + deprec_ejercicio
            valor_libro = costo_corrido - deprec_acum_cierre

        filas.append({
            "id": p.get("id"),
            "fecha": p["fecha"] if isinstance(p["fecha"], str) else p["fecha"].isoformat(),
            "adiciones": round(adiciones),
            "costo_total": round(costo_corrido),
            "vida_util_antes_meses": vida_util_antes,
            "meses_utilizados": meses_utilizados,
            "deprec_acum_apertura": round(deprec_acum_apertura),
            "depreciacion_ejercicio": round(deprec_ejercicio),
            "deprec_acum_cierre": round(deprec_acum_cierre),
            "valor_libro": round(valor_libro),
            "completamente_depreciado": completamente_depreciado,
        })

        meses_consumidos_antes += meses_efectivos

    return filas
