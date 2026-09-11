"""
Arma el comprobante contable consolidado de "Depreciación → Generar
asiento": todos los activos de una empresa que comparten el mismo GRUPO
CONTABLE (la cuenta del activo fijo en sí, ej. "1204-01 VEHICULOS" — ver
`app/data/depreciacion_grupos_contables_repo.py`) se suman en 2 o 3
líneas TOTALES por grupo, no una por cada activo individual (rediseño
11-09-2026: antes era por activo; varios vehículos ahora arman UNA sola
línea de Gasto y UNA de Depreciación Acumulada, sumando todos).

Por cada grupo con algo pendiente:

  - Debe: cuenta "Gasto por Depreciación" del grupo, por la suma de la
    depreciación del ejercicio de todos los períodos pendientes de todos
    los activos de ese grupo.
  - Corrección Monetaria (solo si la suma de `correccion_monetaria` del
    grupo es distinta de 0): Debe si es positiva, Haber si es negativa.
  - Haber: cuenta "Depreciación Acumulada" del grupo, por la suma total
    (ejercicio + corrección) — así Debe y Haber siempre calzan.

Mismo formato de 17 columnas ("Comprobantes") que
`app/conciliacion/export_writer.py` — duplicado a propósito, mismo
criterio de ese módulo. El campo "Tipo" queda vacío (a diferencia de F29/
Conciliación/Caja Empresas, que usan "I"/"E" porque SIEMPRE hay una
cuenta de caja/banco de por medio) — la depreciación no mueve caja.
"""

from datetime import datetime

from app.conciliacion.plan_cuentas import CUENTAS_POR_CODIGO


class GrupoFaltante(Exception):
    """Un activo con períodos pendientes no tiene grupo contable
    asignado, o su grupo no tiene las cuentas que necesita configuradas.
    El llamador (`app/depreciacion/routes.py`) decide cómo mostrarlo — no
    debería bloquear a los DEMÁS grupos que sí están completos."""

    def __init__(self, mensaje):
        super().__init__(mensaje)


def _parse_fecha(fecha):
    if isinstance(fecha, str):
        return datetime.fromisoformat(fecha[:10])
    return fecha


def agrupar_pendientes(activos_con_pendientes: list) -> tuple:
    """`activos_con_pendientes`: lista de (activo, pendientes) — pendientes
    son filas de `calcular_kardex` sin asiento todavía. Devuelve
    (grupos, activos_sin_grupo):

      - `grupos`: {grupo_contable_codigo: {"ejercicio": total,
        "correccion": total, "nombres_activos": [...]}}
      - `activos_sin_grupo`: nombres de activos con pendientes pero sin
        `grupo_contable_codigo` asignado (no se pueden asentar todavía)."""
    grupos: dict = {}
    activos_sin_grupo = []
    for activo, pendientes in activos_con_pendientes:
        if not pendientes:
            continue
        codigo = activo.get("grupo_contable_codigo")
        if not codigo:
            activos_sin_grupo.append(activo["nombre_activo"])
            continue
        g = grupos.setdefault(codigo, {"ejercicio": 0, "correccion": 0, "nombres_activos": []})
        g["ejercicio"] += sum(p["depreciacion_ejercicio"] for p in pendientes)
        g["correccion"] += sum(p["correccion_monetaria"] for p in pendientes)
        g["nombres_activos"].append(activo["nombre_activo"])
    return grupos, activos_sin_grupo


def validar_grupos(grupos: dict, grupos_contables: dict) -> None:
    """Lanza `GrupoFaltante` si algún código de `grupos` (salida de
    `agrupar_pendientes`) no tiene fila en `grupos_contables` (salida de
    `depreciacion_grupos_contables_repo.listar`, ya indexada por código) o
    le falta alguna cuenta obligatoria."""
    faltantes = []
    for codigo, datos in grupos.items():
        gc = grupos_contables.get(codigo)
        descripcion = CUENTAS_POR_CODIGO.get(codigo, {}).get("descripcion", codigo)
        if not gc:
            faltantes.append(f"{codigo} {descripcion}: sin configurar en Grupos Contables")
            continue
        falta_campos = []
        if not gc.get("cuenta_gasto_codigo"):
            falta_campos.append("Gasto por Depreciación")
        if not gc.get("cuenta_acumulada_codigo"):
            falta_campos.append("Depreciación Acumulada")
        if datos["correccion"] and not gc.get("cuenta_correccion_codigo"):
            falta_campos.append("Corrección Monetaria")
        if falta_campos:
            faltantes.append(f"{codigo} {descripcion}: faltan {', '.join(falta_campos)}")
    if faltantes:
        raise GrupoFaltante("; ".join(faltantes))


def construir_filas(grupos: dict, grupos_contables: dict, fecha, periodo_label: str) -> list:
    """`grupos`/`grupos_contables`: ya validados con `validar_grupos`.
    `fecha`: fecha del comprobante (fin del mes que se está generando).
    Devuelve las filas (17 columnas) listas para el .xls."""
    filas = []
    for codigo, datos in grupos.items():
        gc = grupos_contables[codigo]
        cuenta_gasto = CUENTAS_POR_CODIGO[gc["cuenta_gasto_codigo"]]
        cuenta_acumulada = CUENTAS_POR_CODIGO[gc["cuenta_acumulada_codigo"]]
        cuenta_correccion = CUENTAS_POR_CODIGO.get(gc.get("cuenta_correccion_codigo") or "")

        descripcion = CUENTAS_POR_CODIGO.get(codigo, {}).get("descripcion", codigo)
        glosa = f"DEPRECIACIÓN {descripcion} — {periodo_label}"
        ejercicio = datos["ejercicio"]
        correccion = datos["correccion"]

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
        filas.append(_linea(cuenta_acumulada, 0, ejercicio + correccion))

    return filas
