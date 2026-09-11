"""
Arma los comprobantes contables de "Depreciación → Generar asiento": por
cada período pendiente (fila del kardex de un activo que todavía no tiene
un asiento generado, ver `app/data/depreciacion_asientos_repo.py`), 2 o 3
líneas:

  - Debe: cuenta "Gasto por Depreciación" del activo, por el monto de la
    depreciación del ejercicio de esa fila (`depreciacion_ejercicio`).
  - Corrección Monetaria (solo si el Factor CCMM de esa fila movió la
    deprec. acum. de apertura, `correccion_monetaria` != 0): Debe si subió
    (factor > 1, lo más común), Haber si bajó (factor < 1).
  - Haber: cuenta "Depreciación Acumulada" del activo, por la suma de
    ambos — el aumento total de la deprec. acum. en esa fila. Así Debe y
    Haber siempre calzan (comprobante balanceado) sea cual sea el signo
    de la corrección.

Mismo formato de 17 columnas ("Comprobantes") que
`app/conciliacion/export_writer.py` — duplicado a propósito, mismo
criterio de ese módulo ("duplicar en vez de refactorizar código ya en
producción"). El campo "Tipo" queda vacío (a diferencia de F29/
Conciliación/Caja Empresas, que usan "I"/"E" porque SIEMPRE hay una
cuenta de caja/banco de por medio) — la depreciación no mueve caja, así
que no hay un ingreso/egreso real que clasificar ahí.
"""

from datetime import datetime


class CuentaFaltante(Exception):
    """Un activo con períodos pendientes no tiene alguna de las cuentas
    que necesita para asentarlos. El llamador (`app/depreciacion/routes.
    py`) decide cómo mostrarlo — no debería bloquear a los DEMÁS activos
    que sí están completos."""

    def __init__(self, activo_nombre, cuentas_faltantes):
        self.activo_nombre = activo_nombre
        self.cuentas_faltantes = cuentas_faltantes
        super().__init__(f"{activo_nombre}: faltan {', '.join(cuentas_faltantes)}")


def _parse_fecha(fecha):
    if isinstance(fecha, str):
        return datetime.fromisoformat(fecha[:10])
    return fecha


def validar_cuentas(activo: dict, pendientes: list) -> None:
    """Lanza `CuentaFaltante` si a `activo` le falta alguna cuenta que
    necesita para asentar sus `pendientes` (filas de calcular_kardex). No
    hace nada si `pendientes` está vacío — un activo al día no necesita
    tener cuentas configuradas."""
    if not pendientes:
        return
    faltan = []
    if not activo.get("cuenta_gasto_codigo"):
        faltan.append("Gasto por Depreciación")
    if not activo.get("cuenta_acumulada_codigo"):
        faltan.append("Depreciación Acumulada")
    if any(p["correccion_monetaria"] for p in pendientes) and not activo.get("cuenta_correccion_codigo"):
        faltan.append("Corrección Monetaria")
    if faltan:
        raise CuentaFaltante(activo["nombre_activo"], faltan)


def construir_filas(activo: dict, pendientes: list, cuentas_por_codigo: dict) -> list:
    """`pendientes`: filas de `calcular_kardex` de `activo` que todavía no
    tienen asiento generado (ya validadas con `validar_cuentas`).
    `cuentas_por_codigo`: `CUENTAS_POR_CODIGO` del plan de cuentas. Cada
    fila devuelta trae 17 columnas, mismo orden que `app/conciliacion/
    export_writer.HEADERS`."""
    cuenta_gasto = cuentas_por_codigo[activo["cuenta_gasto_codigo"]]
    cuenta_acumulada = cuentas_por_codigo[activo["cuenta_acumulada_codigo"]]
    cuenta_correccion = cuentas_por_codigo.get(activo.get("cuenta_correccion_codigo") or "")

    filas = []
    for p in pendientes:
        fecha = _parse_fecha(p["fecha"])
        glosa = f"DEPRECIACIÓN {activo['nombre_activo']}"
        correccion = p["correccion_monetaria"]
        ejercicio = p["depreciacion_ejercicio"]
        total_acumulada = ejercicio + correccion

        primera = {"usada": False}

        def _linea(cuenta, debe, haber):
            cc = 100 if cuenta["requiere_centro_costo"] else ""
            if not primera["usada"]:
                primera["usada"] = True
                return [0, "", fecha, glosa, cuenta["codigo"], glosa, cc, "", debe or "", haber or "", "", "", "", "", "", "", ""]
            return ["", "", "", "", cuenta["codigo"], glosa, cc, "", debe or "", haber or "", "", "", "", "", "", "", ""]

        filas.append(_linea(cuenta_gasto, ejercicio, 0))
        if correccion > 0:
            filas.append(_linea(cuenta_correccion, correccion, 0))
        elif correccion < 0:
            filas.append(_linea(cuenta_correccion, 0, -correccion))
        filas.append(_linea(cuenta_acumulada, 0, total_acumulada))

    return filas
