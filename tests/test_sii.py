"""
Verificación de "Consulta SII" (RUT, cifrado de claves, clientes HTTP y
rutas), en el mismo estilo sin-pytest que `tests/run_verification.py`
(reusa su bootstrap — `flask_app` + `FakeSupabase` — importándolo como
módulo; importar NO corre sus pruebas, que están tras
`if __name__ == "__main__":`).

Las llamadas a API Gateway / SimpleAPI se mockean (`unittest.mock.patch`)
— no se necesita `SII_APIGATEWAY_TOKEN` ni `SIMPLEAPI_KEY` reales.

Uso:
    python tests/test_sii.py
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.fernet import Fernet  # noqa: E402

from tests.run_verification import flask_app, FAKE, seed_data  # noqa: E402
from app.sii.rut import normalizar_rut, validar_rut  # noqa: E402
from app.sii.crypto import cifrar, descifrar  # noqa: E402
from app.sii import client as sii_client  # noqa: E402

PASSED, FAILED = [], []


def check(label, condition, extra=""):
    if condition:
        PASSED.append(label)
        print(f"  OK  {label}")
    else:
        FAILED.append(label)
        print(f" FAIL {label} {extra}")


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


def test_rut():
    check("normaliza RUT con puntos y guión", normalizar_rut("76.192.083-9") == "76192083-9")
    check("normaliza RUT sin separadores", normalizar_rut("761920839") == "76192083-9")
    check("normaliza RUT con dv 'k' minúscula", normalizar_rut("12345678-k") == "12345678-K")
    check("rut vacío -> None", normalizar_rut("") is None)
    check("rut de un solo carácter -> None", normalizar_rut("9") is None)
    check("valida un RUT con DV correcto", validar_rut("76192083-9") is True)
    check("rechaza un RUT con DV incorrecto", validar_rut("76192083-0") is False)


def test_crypto():
    key = Fernet.generate_key().decode()
    cifrado = cifrar(key, "mi-clave-sii-secreta")
    check("cifrar produce un valor distinto al texto plano", cifrado != "mi-clave-sii-secreta")
    check("descifrar recupera el texto original", descifrar(key, cifrado) == "mi-clave-sii-secreta")

    otra_key = Fernet.generate_key().decode()
    check("descifrar con otra llave -> None (no revienta)", descifrar(otra_key, cifrado) is None)
    check("descifrar un valor corrupto -> None (no revienta)", descifrar(key, "no-es-un-token-valido") is None)


def test_client_consultar_contribuyente():
    dato, error = sii_client.consultar_contribuyente({}, "76192083-9")
    check("sin SII_APIGATEWAY_TOKEN -> config_pendiente", dato is None and error == "config_pendiente")

    cfg = {"SII_APIGATEWAY_TOKEN": "tok"}
    dato, error = sii_client.consultar_contribuyente(cfg, "no-es-un-rut")
    check("RUT inválido -> error legible sin llamar a la red", dato is None and bool(error) and "válido" in error)

    with patch.object(sii_client.requests, "get", return_value=_FakeResponse(200, {"data": {"razon_social": "ACME SPA"}})) as mock_get:
        dato, error = sii_client.consultar_contribuyente(cfg, "76.192.083-9")
        check("200 con 'data' -> devuelve el contenido de 'data'", dato == {"razon_social": "ACME SPA"} and error is None)
        check("arma la URL con el RUT normalizado", "76192083-9" in mock_get.call_args.args[0])
        check("manda el token en el header Authorization", mock_get.call_args.kwargs["headers"]["Authorization"] == "Token tok")

    with patch.object(sii_client.requests, "get", return_value=_FakeResponse(401)):
        dato, error = sii_client.consultar_contribuyente(cfg, "76192083-9")
        check("401 -> mensaje sobre el token, no revienta", dato is None and "token" in error.lower())

    with patch.object(sii_client.requests, "get", return_value=_FakeResponse(404)):
        dato, error = sii_client.consultar_contribuyente(cfg, "76192083-9")
        check("404 -> mensaje de 'no encontró datos'", dato is None and "no encontró" in error.lower())

    with patch.object(sii_client.requests, "get", side_effect=sii_client.requests.RequestException("boom")):
        dato, error = sii_client.consultar_contribuyente(cfg, "76192083-9")
        check("error de red -> mensaje legible, sin excepción sin capturar", dato is None and "conectar" in error.lower())


def test_client_consultar_rcv():
    dato, error = sii_client.consultar_rcv({}, "76192083-9", "clave123", "2026-08", "venta")
    check("sin SIMPLEAPI_KEY -> config_pendiente", dato is None and error == "config_pendiente")

    cfg = {"SIMPLEAPI_KEY": "ak"}
    dato, error = sii_client.consultar_rcv(cfg, "76192083-9", "clave123", "2026-08", "otra-cosa")
    check("tipo inválido -> error legible sin llamar a la red", dato is None and "Tipo de RCV" in error)

    dato, error = sii_client.consultar_rcv(cfg, "76192083-9", "", "2026-08", "venta")
    check("sin clave del SII -> error legible", dato is None and "clave del SII" in error)

    with patch.object(sii_client.requests, "post", return_value=_FakeResponse(200, [{"folio": 1}])) as mock_post:
        dato, error = sii_client.consultar_rcv(cfg, "76192083-9", "clave123", "2026-08", "venta")
        check("200 -> devuelve el JSON tal cual", dato == [{"folio": 1}] and error is None)
        check(
            "manda apikey, rut normalizado, clave y período en el body",
            mock_post.call_args.kwargs["json"] == {
                "apikey": "ak", "rut": "76192083-9", "clave": "clave123", "periodo": "2026-08", "tipo": "venta",
            },
        )

    with patch.object(sii_client.requests, "post", return_value=_FakeResponse(403)):
        dato, error = sii_client.consultar_rcv(cfg, "76192083-9", "clave123", "2026-08", "venta")
        check("403 -> mensaje sobre la clave del SII rechazada", dato is None and "clave del SII" in error)


def test_routes_empresas_y_rcv():
    client = flask_app.test_client()
    r = client.post("/login", data={"usuario": "", "clave": "test_local_only_1234"}, follow_redirects=True)
    check("login admin ok (fixture)", r.status_code == 200)

    r = client.get("/sii/contribuyente")
    check("GET /sii/contribuyente -> 200", r.status_code == 200)
    check("sin token -> avisa configuración pendiente", "Falta conectar API Gateway" in r.get_data(as_text=True))

    r = client.get("/sii/rcv")
    check("GET /sii/rcv -> 200", r.status_code == 200)
    check("sin apikey -> avisa configuración pendiente", "Falta conectar SimpleAPI" in r.get_data(as_text=True))

    r = client.get("/sii/empresas")
    check("GET /sii/empresas -> 200", r.status_code == 200)

    r = client.post(
        "/sii/empresas/crear", data={"rut": "76192083-9", "nombre": "ACME SPA", "clave_sii": ""}, follow_redirects=True,
    )
    check("crear empresa sin clave -> ok", r.status_code == 200 and "ACME SPA" in r.get_data(as_text=True))

    filas = FAKE.table("sii_empresas").select("*").execute().data
    check("la empresa quedó guardada sin clave cifrada", len(filas) == 1 and filas[0]["clave_sii_cifrada"] is None)
    empresa_id = filas[0]["id"]

    flask_app.config["SII_CREDENTIALS_KEY"] = Fernet.generate_key().decode()
    r = client.post(f"/sii/empresas/{empresa_id}/clave", data={"clave_sii": "mi-clave-secreta"}, follow_redirects=True)
    check("actualizar clave -> ok", r.status_code == 200 and "actualizada" in r.get_data(as_text=True))

    empresa = FAKE.table("sii_empresas").select("*").eq("id", empresa_id).execute().data[0]
    check(
        "la clave quedó cifrada (no en texto plano) en la 'base de datos'",
        bool(empresa["clave_sii_cifrada"]) and empresa["clave_sii_cifrada"] != "mi-clave-secreta",
    )
    check(
        "se puede descifrar de vuelta con la misma llave",
        descifrar(flask_app.config["SII_CREDENTIALS_KEY"], empresa["clave_sii_cifrada"]) == "mi-clave-secreta",
    )

    flask_app.config["SIMPLEAPI_KEY"] = "ak-test"
    with patch.object(sii_client.requests, "post", return_value=_FakeResponse(200, [{"folio": 1, "monto": 1000}])):
        r = client.post("/sii/rcv", data={"empresa_id": empresa_id, "periodo": "2026-08", "tipo": "venta"}, follow_redirects=True)
        check("consultar RCV con la clave guardada -> 200 y muestra la tabla", r.status_code == 200 and "folio" in r.get_data(as_text=True))

    r = client.post(f"/sii/empresas/{empresa_id}/eliminar", follow_redirects=True)
    check("eliminar empresa -> ok", r.status_code == 200 and "eliminada" in r.get_data(as_text=True))
    check("la empresa ya no está en la 'base de datos'", FAKE.table("sii_empresas").select("*").execute().data == [])


def test_trabajador_no_puede_ver_sii():
    client = flask_app.test_client()
    r = client.post("/login", data={"usuario": "testuser", "clave": "trabajador123"}, follow_redirects=True)
    check("login trabajador ok (fixture)", r.status_code == 200)
    r = client.get("/sii/contribuyente")
    check("trabajador NO puede ver Consulta SII por defecto (403)", r.status_code == 403)


def main():
    seed_data()
    test_rut()
    test_crypto()
    test_client_consultar_contribuyente()
    test_client_consultar_rcv()
    test_routes_empresas_y_rcv()
    test_trabajador_no_puede_ver_sii()

    print(f"\n{len(PASSED)} OK, {len(FAILED)} FAIL")
    if FAILED:
        print("Fallaron:", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    main()
