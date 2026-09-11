"""
Clientes HTTP para las dos integraciones con el SII de esta app:

  - API Gateway (apigateway.cl): consulta de situación tributaria de un
    RUT (razón social, actividades, documentos timbrados, observaciones
    de irregularidad). NO requiere credenciales del contribuyente
    consultado, solo el token propio de la cuenta de API Gateway
    (`SII_APIGATEWAY_TOKEN`). Contrato verificado contra su página de
    producto: https://www.apigateway.cl/products/sii/contribuyentes

  - SimpleAPI RCV (simpleapi.cl): descarga del Registro de Compra y Venta
    de una empresa. A diferencia de lo anterior, SÍ requiere la clave del
    SII de esa empresa (o certificado digital), porque el servicio entra
    al sitio del SII en su nombre — ver `app/sii/crypto.py` para cómo se
    guarda cifrada. Producto: https://www.simpleapi.cl/Productos/SimpleRCV

    OJO — a diferencia de API Gateway, no fue posible confirmar el
    contrato exacto de este endpoint (URL/parámetros/formato de
    respuesta) sin una cuenta activa: la documentación detallada vive en
    documentacion.simpleapi.cl, protegida de la lectura automática. Lo de
    acá (`SIMPLEAPI_RCV_URL` y el body de `consultar_rcv`) es la mejor
    aproximación posible a partir de su documentación pública, NO un
    contrato confirmado — revísalo contra la documentación real (o
    contra soporte de SimpleAPI) apenas exista una cuenta, antes de
    confiar en esta función en producción.

Todas las funciones devuelven (dato, error): si algo falla (config
faltante, RUT inválido, sin red, HTTP de error, etc.) se devuelve
(None, "mensaje legible") en vez de levantar una excepción — mismo patrón
que `app/reuniones/graph_client.py`. `error == "config_pendiente"` es un
valor especial: significa "falta configurar la variable de entorno", para
que la ruta Flask pueda mostrar instrucciones en vez de un error.
"""

import requests

from app.sii.rut import normalizar_rut

API_GATEWAY_BASE_URL = "https://apigateway.cl/api/v2"
SIMPLEAPI_RCV_URL = "https://api.simpleapi.cl/api/v1/rcv"  # ver OJO arriba
TIMEOUT_SEGUNDOS = 20  # apigateway.cl avisa que en hora punta puede tardar hasta 20s


def _error_http_legible(resp):
    try:
        data = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}"
    if isinstance(data, dict):
        msg = data.get("error") or data.get("detail") or data.get("message")
        if msg:
            return str(msg)
    return f"HTTP {resp.status_code}"


def consultar_contribuyente(cfg, rut: str):
    """Situación tributaria de `rut` vía API Gateway. Devuelve
    (dict_con_los_datos, None) o (None, mensaje_de_error)."""
    token = cfg.get("SII_APIGATEWAY_TOKEN")
    if not token:
        return None, "config_pendiente"

    rut_norm = normalizar_rut(rut)
    if not rut_norm:
        return None, f"'{rut}' no es un RUT válido."

    url = f"{API_GATEWAY_BASE_URL}/sii/contribuyentes/situacion_tributaria/tercero/{rut_norm}"
    try:
        resp = requests.get(
            url, headers={"Authorization": f"Token {token}"}, timeout=TIMEOUT_SEGUNDOS,
        )
    except requests.RequestException as exc:
        return None, f"No se pudo conectar a API Gateway: {exc}"

    if resp.status_code == 401:
        return None, "Token de API Gateway inválido o vencido (revisa SII_APIGATEWAY_TOKEN)."
    if resp.status_code == 404:
        return None, f"API Gateway no encontró datos para el RUT {rut_norm}."
    if not resp.ok:
        return None, _error_http_legible(resp)

    try:
        data = resp.json()
    except ValueError:
        return None, "API Gateway devolvió una respuesta que no es JSON."
    return data.get("data", data), None


def consultar_rcv(cfg, rut_empresa: str, clave_sii: str, periodo: str, tipo: str):
    """RCV de `rut_empresa` para `periodo` ('YYYY-MM') vía SimpleAPI.
    `tipo`: 'compra' o 'venta'. Ver el OJO sobre el contrato en el
    docstring del módulo antes de usar esto en producción."""
    apikey = cfg.get("SIMPLEAPI_KEY")
    if not apikey:
        return None, "config_pendiente"

    rut_norm = normalizar_rut(rut_empresa)
    if not rut_norm:
        return None, f"'{rut_empresa}' no es un RUT válido."
    if tipo not in ("compra", "venta"):
        return None, f"Tipo de RCV inválido: '{tipo}' (debe ser 'compra' o 'venta')."
    if not clave_sii:
        return None, "Esta empresa no tiene clave del SII guardada (ver 'Empresas SII')."

    body = {"apikey": apikey, "rut": rut_norm, "clave": clave_sii, "periodo": periodo, "tipo": tipo}
    try:
        resp = requests.post(SIMPLEAPI_RCV_URL, json=body, timeout=TIMEOUT_SEGUNDOS)
    except requests.RequestException as exc:
        return None, f"No se pudo conectar a SimpleAPI: {exc}"

    if resp.status_code == 401:
        return None, "apikey de SimpleAPI inválida (revisa SIMPLEAPI_KEY)."
    if resp.status_code == 403:
        return None, (
            "SimpleAPI rechazó la clave del SII de esta empresa — revisa "
            "que esté vigente y bien escrita en 'Empresas SII'."
        )
    if not resp.ok:
        return None, _error_http_legible(resp)

    try:
        data = resp.json()
    except ValueError:
        return None, "SimpleAPI devolvió una respuesta que no es JSON."
    return data, None
