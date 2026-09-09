"""
"Indicadores": nueva pestaña, pedida por el usuario, que muestra los
indicadores económicos chilenos del día (UF, dólar, UTM, IPC, etc.) —
útil para una app usada por un estudio contable. Se consumen desde
mindicador.cl (API pública y gratuita, sin necesidad de credenciales ni
API key: https://mindicador.cl/api).

Se cachea la respuesta en memoria por unos minutos (`_CACHE`) para no
pegarle a la API en cada clic de un usuario dentro de la misma app, y
para que la página siga sirviendo el último dato bueno si la API externa
falla o está lenta.
"""

import time

import requests
from flask import Blueprint, render_template

from app.auth.decorators import pagina_required

indicadores_bp = Blueprint("indicadores", __name__, url_prefix="/indicadores")

MINDICADOR_URL = "https://mindicador.cl/api"
CACHE_TTL_SEGUNDOS = 10 * 60  # 10 minutos: estos indicadores solo cambian una vez al día.

# Códigos que interesan mostrar, en el orden en que se muestran, con una
# etiqueta y unidad más amigables que las que trae la API.
INDICADORES_MOSTRADOS = [
    {"codigo": "uf", "label": "UF", "unidad": "$", "detalle": "Unidad de Fomento"},
    {"codigo": "dolar", "label": "Dólar Observado", "unidad": "$", "detalle": "USD/CLP"},
    {"codigo": "euro", "label": "Euro", "unidad": "$", "detalle": "EUR/CLP"},
    {"codigo": "utm", "label": "UTM", "unidad": "$", "detalle": "Unidad Tributaria Mensual"},
    {"codigo": "ipc", "label": "IPC", "unidad": "%", "detalle": "Variación mensual"},
    {"codigo": "uta", "label": "UTA", "unidad": "$", "detalle": "Unidad Tributaria Anual"},
    {"codigo": "tpm", "label": "TPM", "unidad": "%", "detalle": "Tasa de Política Monetaria"},
    {"codigo": "imacec", "label": "Imacec", "unidad": "%", "detalle": "Variación anual"},
]

_CACHE = {"data": None, "fetched_at": 0, "error": None}


def _fetch_indicadores():
    """Trae los indicadores desde mindicador.cl, con caché en memoria.
    Si la API externa falla y hay un dato en caché (aunque esté vencido),
    se sigue mostrando ese dato con un aviso — mejor un valor levemente
    desactualizado que una pantalla en blanco."""
    ahora = time.time()
    if _CACHE["data"] is not None and (ahora - _CACHE["fetched_at"]) < CACHE_TTL_SEGUNDOS:
        return _CACHE["data"], None

    try:
        resp = requests.get(MINDICADOR_URL, timeout=6)
        resp.raise_for_status()
        data = resp.json()
        _CACHE["data"] = data
        _CACHE["fetched_at"] = ahora
        _CACHE["error"] = None
        return data, None
    except Exception as exc:  # noqa: BLE001 — cualquier falla de red/parseo cae aquí
        if _CACHE["data"] is not None:
            return _CACHE["data"], f"No se pudo actualizar (usando el último valor conocido): {exc}"
        return None, f"No se pudo obtener los indicadores: {exc}"


def _formatear(valor, unidad):
    """Formato chileno (punto de miles, coma decimal). Los valores en $
    llevan 2 decimales solo si no son enteros (UF/dólar/euro/UTM suelen
    traer decimales; UTM a veces es un entero exacto)."""
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    si_decimales = unidad == "%" or (n != int(n))
    texto = f"{n:,.2f}" if si_decimales else f"{n:,.0f}"
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"${texto}" if unidad == "$" else f"{texto}%"


@indicadores_bp.route("/", methods=["GET"])
@pagina_required("indicadores.index")
def index():
    data, error = _fetch_indicadores()
    filas = []
    if data:
        for item in INDICADORES_MOSTRADOS:
            info = data.get(item["codigo"])
            if not info:
                continue
            filas.append({
                **item,
                "valor_fmt": _formatear(info.get("valor"), item["unidad"]),
                "fecha": info.get("fecha"),
            })
    return render_template("indicadores.html", filas=filas, error=error, fecha_api=(data or {}).get("fecha") if data else None)
