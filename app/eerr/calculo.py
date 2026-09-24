"""
Cálculo del "EERR Dinámico" (24-09-2026): arma el Estado de Resultados por
conceptos definidos por empresa, a partir del Estado de Resultados
Comparativo de Nubox (CSV del puente, ver `app/data/nubox_importado_repo.py`).

- Un **concepto** (`tipo: "g"`) agrupa las cuentas que el usuario le asigna
  y se suma en una de las 4 secciones (`SECCIONES`).
- Un **total** (`tipo: "t"`) suma los conceptos de su sección.
- Un **margen** (`tipo: "f"`) es la resta de dos filas (`a − b`); el último
  es el Resultado del ejercicio.

Signos: Nubox entrega los saldos de ganancias y de pérdidas como positivos.
Una cuenta suma en una sección de su misma naturaleza (ganancia en Total
Ganancias, pérdida en las demás) y resta si el usuario la pone en la
sección contraria — así, con todas las cuentas asignadas, el Resultado del
ejercicio siempre cuadra con Nubox (ganancias − pérdidas).

Porcentajes (confirmados en la vista previa): en cada cuenta, su peso
dentro de su concepto en ese mes; en conceptos, totales y márgenes, sobre
el Total Ganancias del mes. "No incluir" solo oculta la fila del informe:
su monto sigue sumando en su total.

El mismo cálculo alimenta la pantalla y las exportaciones a Excel y PDF,
para que los tres muestren exactamente las mismas cifras.
"""

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

GANANCIA, PERDIDA = 3, 4

# id de sección -> (nombre del total, naturaleza de la sección)
SECCIONES: Dict[str, Tuple[str, int]] = {
    "tg": ("Total Ganancias", GANANCIA),
    "tc": ("Total Costos", PERDIDA),
    "toc": ("Total Otros Costos", PERDIDA),
    "te": ("Total Egresos", PERDIDA),
}

# Plantilla de partida (definida por el usuario, 24-09-2026). Cada empresa
# parte de esta lista y puede agregar conceptos o marcar "No incluir".
CONCEPTOS_BASE: List[dict] = [
    {"id": "ing_exp", "n": "INGRESOS DE EXPLOTACION", "tipo": "g", "sec": "tg"},
    {"id": "otros_ing", "n": "OTROS INGRESOS", "tipo": "g", "sec": "tg"},
    {"id": "ing_reaj", "n": "INGRESOS POR REAJUSTES", "tipo": "g", "sec": "tg"},
    {"id": "tg", "n": "Total Ganancias", "tipo": "t"},
    {"id": "costos_exp", "n": "COSTOS DE EXPLOTACION", "tipo": "g", "sec": "tc"},
    {"id": "tc", "n": "Total Costos", "tipo": "t"},
    {"id": "mo", "n": "Margen Operacional", "tipo": "f", "a": "tg", "b": "tc"},
    {"id": "remu", "n": "REMUNERACIONES Y PERSONAL", "tipo": "g", "sec": "toc"},
    {"id": "arr", "n": "ARRIENDOS Y GASTOS ASOCIADOS", "tipo": "g", "sec": "toc"},
    {"id": "mant", "n": "MANTENCION Y REPARACIONES", "tipo": "g", "sec": "toc"},
    {"id": "ofi", "n": "GASTOS DE OFICINA Y ADMINISTRACION", "tipo": "g", "sec": "toc"},
    {"id": "sbas", "n": "SERVICIOS BASICOS", "tipo": "g", "sec": "toc"},
    {"id": "transp", "n": "SERVICIO DE TRANSPORTES Y COMBUSTIBLES", "tipo": "g", "sec": "toc"},
    {"id": "toc", "n": "Total Otros Costos", "tipo": "t"},
    {"id": "mb", "n": "Margen Bruto", "tipo": "f", "a": "mo", "b": "toc"},
    {"id": "ases", "n": "ASESORIAS EXTERNAS", "tipo": "g", "sec": "te"},
    {"id": "oper", "n": "OPERATIVAS", "tipo": "g", "sec": "te"},
    {"id": "ocp", "n": "OTROS COSTOS DE PRODUCCION", "tipo": "g", "sec": "te"},
    {"id": "pat", "n": "PATENTES COMERCIALES", "tipo": "g", "sec": "te"},
    {"id": "int", "n": "INTERESES", "tipo": "g", "sec": "te"},
    {"id": "dep", "n": "DEPRECIACION", "tipo": "g", "sec": "te"},
    {"id": "preaj", "n": "PERDIDAS POR REAJUSTE", "tipo": "g", "sec": "te"},
    {"id": "renta", "n": "IMPUESTO A LA RENTA", "tipo": "g", "sec": "te"},
    {"id": "te", "n": "Total Egresos", "tipo": "t"},
    {"id": "res", "n": "Resultado del ejercicio", "tipo": "f", "a": "mb", "b": "te"},
]

_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")
_CODIGO_RE = re.compile(r"^[0-9A-Za-z.\-]{1,30}$")


def conceptos_por_defecto() -> List[dict]:
    return [dict(c, inc=True) for c in CONCEPTOS_BASE]


# ---------------------------------------------------------------------------
# Lectura del CSV del puente
# ---------------------------------------------------------------------------

def _numero(texto) -> float:
    try:
        return float(texto or 0)
    except (TypeError, ValueError):
        return 0.0


def leer_eerr_csv(ruta: Path) -> dict:
    """Pivotea el CSV (una fila por subcuenta y mes) a una fila por cuenta
    con sus 12 meses. Devuelve {cuentas, meses_con_datos, generado_en}.

    - Solo filas de subcuenta (las de cuenta mayor, sin subcuenta, son
      subtotales de Nubox) y sin cuenta de análisis (ese nivel es detalle
      de la subcuenta; sumarlo duplicaría montos).
    - `meses_con_datos`: meses (1-12) que Nubox incluyó en el reporte.
    """
    cuentas: Dict[str, dict] = {}
    meses_con_datos = set()
    generado_en = ""
    with open(ruta, newline="", encoding="utf-8-sig") as fh:
        for f in csv.DictReader(fh):
            periodo = (f.get("periodo") or "").strip()
            if len(periodo) < 7:
                continue
            mes = int(periodo[5:7])
            if not 1 <= mes <= 12:
                continue
            meses_con_datos.add(mes)
            generado_en = generado_en or (f.get("generado_en") or "").strip()
            subcuenta = (f.get("subcuenta") or "").strip()
            if not subcuenta or (f.get("cuentaanalisis") or "").strip():
                continue
            codigo, _, nombre = subcuenta.partition(" ")
            c = cuentas.get(codigo)
            if c is None:
                tipo = GANANCIA if str(f.get("tipocuentaid")).strip() == "3" else PERDIDA
                c = cuentas[codigo] = {
                    "codigo": codigo, "nombre": " ".join(nombre.split()), "tipo": tipo,
                    "mayor": (f.get("cuentamayor") or "").strip(), "meses": [0.0] * 12,
                }
            c["meses"][mes - 1] += _numero(f.get("saldo"))
    lista = sorted((c for c in cuentas.values() if any(c["meses"])), key=lambda c: c["codigo"])
    return {"cuentas": lista, "meses_con_datos": sorted(meses_con_datos), "generado_en": generado_en}


# ---------------------------------------------------------------------------
# Validación de lo que llega desde el navegador
# ---------------------------------------------------------------------------

def normalizar_conceptos(conceptos) -> List[dict]:
    """Deja una lista válida de conceptos a partir de lo que mandó el
    navegador (o lo guardado en Supabase). Los conceptos de la plantilla,
    totales y márgenes siempre existen, en el orden de la plantilla y con
    su fórmula original (desde afuera solo se puede cambiar "Incluir / No
    incluir"); los conceptos propios del usuario van justo antes del total
    de su sección, en el orden en que se agregaron."""
    if not isinstance(conceptos, list):
        conceptos = []
    base_ids = {c["id"] for c in CONCEPTOS_BASE}
    inc, propios, vistos = {}, {sid: [] for sid in SECCIONES}, set()
    for c in conceptos:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "")
        if not _ID_RE.match(cid) or cid in vistos:
            continue
        vistos.add(cid)
        if cid in base_ids:
            inc[cid] = c.get("inc") is not False
        elif c.get("tipo") == "g" and c.get("sec") in SECCIONES:
            nombre = " ".join(str(c.get("n") or "").split())[:80].upper()
            if nombre:
                propios[c["sec"]].append({"id": cid, "n": nombre, "tipo": "g", "sec": c["sec"],
                                          "inc": c.get("inc") is not False, "custom": True})
    resultado = []
    for c in CONCEPTOS_BASE:
        if c["tipo"] == "t":
            resultado.extend(propios[c["id"]])
        resultado.append(dict(c, inc=inc.get(c["id"], True)))
    return resultado


def normalizar_asignaciones(asignaciones, conceptos: List[dict]) -> Dict[str, str]:
    """{codigo_cuenta: id_concepto}, descartando cuentas o conceptos
    inválidos (p. ej. asignaciones a un concepto que se quitó)."""
    if not isinstance(asignaciones, dict):
        return {}
    grupos = {c["id"] for c in conceptos if c["tipo"] == "g"}
    return {
        str(k): str(v) for k, v in asignaciones.items()
        if _CODIGO_RE.match(str(k)) and str(v) in grupos
    }


# ---------------------------------------------------------------------------
# Cálculo del informe
# ---------------------------------------------------------------------------

def _pct(valor: float, base: float) -> Optional[float]:
    if not base or not valor:
        return None
    return valor / base * 100


def calcular(cuentas: List[dict], conceptos: List[dict], asignaciones: Dict[str, str],
             desde: int, hasta: int) -> dict:
    """Informe listo para dibujar: columnas (meses del rango) y filas en
    orden, cada una con sus montos, porcentajes y acumulado.

    Tipos de fila: "grupo" (concepto), "cta" (cuenta dentro de un concepto),
    "total", "formula" (margen), "resultado" (Resultado del ejercicio) y
    "sinasig" (efecto de las cuentas sin asignar, si las hay)."""
    desde = max(1, min(12, int(desde)))
    hasta = max(desde, min(12, int(hasta)))
    idx = list(range(desde - 1, hasta))
    n = len(idx)
    naturaleza = {sid: nat for sid, (_, nat) in SECCIONES.items()}

    en_rango = [c for c in cuentas if any(c["meses"][i] for i in idx)]
    valores = {c["id"]: [0.0] * n for c in conceptos}
    cuentas_de = {c["id"]: [] for c in conceptos}
    sin_asignar = []
    por_id = {c["id"]: c for c in conceptos}

    for cta in en_rango:
        g = por_id.get(asignaciones.get(cta["codigo"], ""))
        if not g or g["tipo"] != "g":
            sin_asignar.append(cta)
            continue
        signo = 1 if cta["tipo"] == naturaleza[g["sec"]] else -1
        montos = [cta["meses"][i] * signo for i in idx]
        cuentas_de[g["id"]].append((cta, montos))
        for j, v in enumerate(montos):
            valores[g["id"]][j] += v

    for c in conceptos:
        if c["tipo"] == "t":
            for g in conceptos:
                if g["tipo"] == "g" and g["sec"] == c["id"]:
                    for j in range(n):
                        valores[c["id"]][j] += valores[g["id"]][j]
        elif c["tipo"] == "f":
            valores[c["id"]] = [a - b for a, b in zip(valores[c["a"]], valores[c["b"]])]

    base = valores["tg"]
    base_acum = sum(base)

    def fila(tipo, nombre, montos, base_mes, base_total, **extra):
        acum = sum(montos)
        return {
            "tipo": tipo, "nombre": nombre, "valores": montos,
            "pcts": [_pct(v, b) for v, b in zip(montos, base_mes)],
            "acum": acum, "acum_pct": _pct(acum, base_total), **extra,
        }

    filas = []
    for c in conceptos:
        if not c.get("inc", True):
            continue
        if c["tipo"] == "g":
            v = valores[c["id"]]
            filas.append(fila("grupo", c["n"], v, base, base_acum, id=c["id"]))
            for cta, montos in cuentas_de[c["id"]]:
                filas.append(fila("cta", f"{cta['codigo']} {cta['nombre']}", montos, v, sum(v), padre=c["id"]))
        elif c["tipo"] == "t":
            filas.append(fila("total", c["n"], valores[c["id"]], base, base_acum, id=c["id"]))
        else:
            tipo = "resultado" if c["id"] == "res" else "formula"
            filas.append(fila(tipo, c["n"], valores[c["id"]], base, base_acum, id=c["id"]))

    def resultado_nubox(lista):
        return [sum((c["meses"][i] if c["tipo"] == GANANCIA else -c["meses"][i]) for c in lista) for i in idx]

    if sin_asignar:
        filas.append(fila("sinasig", f"Cuentas sin asignar ({len(sin_asignar)}) · efecto en resultado",
                          resultado_nubox(sin_asignar), base, base_acum))

    nubox = resultado_nubox(en_rango)
    diferencia = sum(valores["res"]) - sum(nubox)
    return {
        "meses": [i + 1 for i in idx],
        "columnas": [MESES[i] for i in idx],
        "filas": filas,
        "cuadre": {"resultado_nubox": sum(nubox), "resultado_informe": sum(valores["res"]),
                   "diferencia": diferencia, "cuadra": abs(diferencia) < 1},
        "sin_asignar": [c["codigo"] for c in sin_asignar],
    }


def rango_legible(desde: int, hasta: int, anio: int) -> str:
    if desde == hasta:
        return f"{MESES[desde - 1]} {anio}"
    return f"{MESES[desde - 1]} a {MESES[hasta - 1]} {anio}"
