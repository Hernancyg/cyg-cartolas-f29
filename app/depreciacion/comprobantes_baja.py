"""
Arma el comprobante contable de "dar de baja" UN activo (pérdida total o
venta) — a diferencia de `app/depreciacion/comprobantes.py` (que
consolida la depreciación del ejercicio de TODOS los activos de un mismo
grupo contable), la baja siempre es de un activo puntual, nunca se
consolida con otros.

Reglas (confirmadas con el usuario, 11-09-2026):

  - `resultado` = monto_venta - valor_libro (si es venta) o -valor_libro
    (si es pérdida total, monto_venta=0) — positivo es utilidad, negativo
    es pérdida.
  - Debe: Depreciación Acumulada del Grupo Contable del activo, por el
    valor acumulado a la fecha de baja (se limpia por completo).
  - Debe (solo si es venta): Caja/Cliente, por el monto de venta.
  - Debe (si resultado < 0) o Haber (si resultado > 0): Pérdida en Baja /
    Utilidad en Venta, por el valor absoluto del resultado.
  - Haber: Activo Fijo — el código del Grupo Contable del activo MISMO
    (es literalmente la cuenta del activo fijo, ver `depreciacion_grupos_
    contables_repo.py`), por el valor actualizado (costo corregido) a la
    fecha de baja. Siempre balanceado: Debe == Haber en cualquier
    combinación de signos.

No calcula IVA (venta con factura y venta por contrato de compraventa se
tratan igual en el asiento, el usuario decidió dejarlo así por ahora,
11-09-2026) — la única diferencia entre ambas modalidades es la glosa.

Mismo formato de 17 columnas ("Comprobantes") que `app/depreciacion/
comprobantes.py` / `app/conciliacion/export_writer.py` — reutiliza
`app/depreciacion/export_writer.build_comprobantes_workbook` tal cual,
sin necesidad de un escritor de Excel propio.
"""

from app.conciliacion.plan_cuentas import CUENTAS_POR_CODIGO

MODALIDAD_LABEL = {"factura": "VENTA CON FACTURA", "contrato": "VENTA POR CONTRATO DE COMPRAVENTA"}


class CuentaBajaFaltante(Exception):
    """Al activo o a la empresa le falta alguna cuenta necesaria para
    armar el asiento de baja. El llamador (`app/depreciacion/routes.py`)
    decide cómo mostrarlo."""


def calcular_resultado(tipo_baja: str, monto_venta: float, valor_libro: float) -> float:
    if tipo_baja == "perdida_total":
        return -valor_libro
    return monto_venta - valor_libro


def validar_cuentas(activo: dict, grupo_contable: dict, config_baja: dict, tipo_baja: str, resultado: float) -> None:
    faltan = []
    if not activo.get("grupo_contable_codigo"):
        faltan.append("Grupo contable del activo (Activo Fijo) — asígnaselo en su ficha")
    elif not grupo_contable:
        faltan.append(f"El grupo '{activo['grupo_contable_codigo']}' no está configurado en Grupos Contables")
    elif not grupo_contable.get("cuenta_acumulada_codigo"):
        faltan.append("Depreciación Acumulada (del grupo contable del activo)")

    if tipo_baja == "venta" and not (config_baja or {}).get("cuenta_caja_cliente_codigo"):
        faltan.append("Caja/Cliente")
    if resultado < 0 and not (config_baja or {}).get("cuenta_perdida_codigo"):
        faltan.append("Pérdida en Baja de Activo Fijo")
    if resultado > 0 and not (config_baja or {}).get("cuenta_utilidad_codigo"):
        faltan.append("Utilidad en Venta de Activo Fijo")

    if faltan:
        raise CuentaBajaFaltante("; ".join(faltan))


def construir_filas(
    activo: dict, grupo_contable: dict, config_baja: dict, tipo_baja: str, modalidad_venta,
    monto_venta: float, valor_actualizado: float, deprec_acumulada: float, resultado: float, fecha,
) -> list:
    """Ya validado con `validar_cuentas`. Devuelve las filas (17
    columnas) listas para `export_writer.build_comprobantes_workbook`."""
    cuenta_activo_fijo = CUENTAS_POR_CODIGO[activo["grupo_contable_codigo"]]
    cuenta_acumulada = CUENTAS_POR_CODIGO[grupo_contable["cuenta_acumulada_codigo"]]

    if tipo_baja == "perdida_total":
        motivo = "PÉRDIDA TOTAL"
    else:
        motivo = MODALIDAD_LABEL[modalidad_venta]
    glosa = f"BAJA {activo['nombre_activo']} — {motivo}".upper()

    primera = {"usada": False}

    def _linea(cuenta, debe, haber):
        cc = 100 if cuenta["requiere_centro_costo"] else ""
        if not primera["usada"]:
            primera["usada"] = True
            return [0, "T", fecha, glosa, cuenta["codigo"], glosa, cc, "", debe or "", haber or "", "", "", "", "", "", "", ""]
        return ["", "", "", "", cuenta["codigo"], glosa, cc, "", debe or "", haber or "", "", "", "", "", "", "", ""]

    filas = [_linea(cuenta_acumulada, deprec_acumulada, 0)]

    if tipo_baja == "venta" and monto_venta:
        cuenta_caja = CUENTAS_POR_CODIGO[config_baja["cuenta_caja_cliente_codigo"]]
        filas.append(_linea(cuenta_caja, monto_venta, 0))

    if resultado < 0:
        cuenta_perdida = CUENTAS_POR_CODIGO[config_baja["cuenta_perdida_codigo"]]
        filas.append(_linea(cuenta_perdida, -resultado, 0))
    elif resultado > 0:
        cuenta_utilidad = CUENTAS_POR_CODIGO[config_baja["cuenta_utilidad_codigo"]]
        filas.append(_linea(cuenta_utilidad, 0, resultado))

    filas.append(_linea(cuenta_activo_fijo, 0, valor_actualizado))
    return filas
