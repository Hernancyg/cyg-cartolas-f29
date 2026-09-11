"""
"Consulta SII": pestaña nueva con dos herramientas contra el SII vía
API's de terceros (ver `app/sii/client.py` para el detalle de cada
integración y sus limitaciones):

  - "Contribuyente": situación tributaria de cualquier RUT (razón social,
    actividades, documentos timbrados, observaciones), vía API Gateway.
    No requiere credenciales del contribuyente consultado.
  - "RCV": Registro de Compra y Venta de una empresa cliente, vía
    SimpleAPI — SÍ requiere la clave del SII de esa empresa, guardada
    cifrada (ver `app/sii/crypto.py`) en "Empresas SII".
  - "Empresas SII": alta/baja de las empresas clientes y su clave del
    SII, separado de "RCV" porque tocar esa clave es una operación más
    sensible (aparte de la clave nunca se muestra de vuelta, solo se
    reemplaza).

Si `SII_APIGATEWAY_TOKEN` / `SIMPLEAPI_KEY` / `SII_CREDENTIALS_KEY` no
están configuradas, la pestaña correspondiente muestra instrucciones en
vez de fallar (mismo criterio que "Reuniones", ver
`app/reuniones/routes.py`).
"""

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.auth.decorators import pagina_required
from app.data import sii_empresas_repo
from app.sii import client
from app.sii.crypto import cifrar, descifrar

sii_bp = Blueprint("sii", __name__, url_prefix="/sii")


@sii_bp.route("/", methods=["GET"])
@pagina_required("sii.contribuyente")
def index():
    return redirect(url_for("sii.contribuyente"))


# ---------------------------------------------------------------------------
# Contribuyente
# ---------------------------------------------------------------------------

@sii_bp.route("/contribuyente", methods=["GET", "POST"])
@pagina_required("sii.contribuyente")
def contribuyente():
    resultado, error, rut_consultado = None, None, ""
    config_pendiente = not current_app.config.get("SII_APIGATEWAY_TOKEN")

    if request.method == "POST":
        rut_consultado = (request.form.get("rut") or "").strip()
        if not rut_consultado:
            flash("Ingresa un RUT para consultar.", "error")
        else:
            resultado, error = client.consultar_contribuyente(current_app.config, rut_consultado)
            if error == "config_pendiente":
                config_pendiente = True
                error = None

    return render_template(
        "sii/contribuyente.html",
        resultado=resultado, error=error, rut_consultado=rut_consultado,
        config_pendiente=config_pendiente,
    )


# ---------------------------------------------------------------------------
# RCV
# ---------------------------------------------------------------------------

@sii_bp.route("/rcv", methods=["GET", "POST"])
@pagina_required("sii.contribuyente")
def rcv():
    empresas = sii_empresas_repo.listar_empresas()
    resultado, error = None, None
    config_pendiente = not current_app.config.get("SIMPLEAPI_KEY")
    empresa_id, periodo, tipo = "", "", "venta"

    if request.method == "POST":
        empresa_id = request.form.get("empresa_id") or ""
        periodo = request.form.get("periodo") or ""
        tipo = request.form.get("tipo") or "venta"
        empresa = next((e for e in empresas if e["id"] == empresa_id), None)

        if not empresa:
            flash("Elige una empresa (agrégala primero en 'Empresas SII' si no aparece).", "error")
        elif not periodo:
            flash("Elige un período (mes/año).", "error")
        elif not empresa.get("clave_sii_cifrada"):
            flash(f"'{empresa['nombre']}' no tiene clave del SII guardada — agrégala en 'Empresas SII'.", "error")
        else:
            clave_sii = descifrar(current_app.config.get("SII_CREDENTIALS_KEY", ""), empresa["clave_sii_cifrada"])
            if clave_sii is None:
                flash(
                    f"No se pudo leer la clave del SII de '{empresa['nombre']}' "
                    "(SII_CREDENTIALS_KEY cambió o el dato está corrupto) — vuelve a guardarla.",
                    "error",
                )
            else:
                resultado, error = client.consultar_rcv(
                    current_app.config, empresa["rut"], clave_sii, periodo, tipo,
                )
                if error == "config_pendiente":
                    config_pendiente = True
                    error = None

    return render_template(
        "sii/rcv.html",
        empresas=empresas, resultado=resultado, error=error, config_pendiente=config_pendiente,
        empresa_id=empresa_id, periodo=periodo, tipo=tipo,
    )


# ---------------------------------------------------------------------------
# Empresas SII (RUT + clave, para "RCV")
# ---------------------------------------------------------------------------

@sii_bp.route("/empresas", methods=["GET"])
@pagina_required("sii.contribuyente")
def empresas():
    return render_template("sii/empresas.html", empresas=sii_empresas_repo.listar_empresas())


@sii_bp.route("/empresas/crear", methods=["POST"])
@pagina_required("sii.contribuyente")
def empresas_crear():
    rut = (request.form.get("rut") or "").strip()
    nombre = (request.form.get("nombre") or "").strip()
    clave_sii = request.form.get("clave_sii") or ""

    if not rut or not nombre:
        flash("RUT y nombre son obligatorios.", "error")
        return redirect(url_for("sii.empresas"))

    clave_cifrada = None
    if clave_sii:
        clave_cifrado_key = current_app.config.get("SII_CREDENTIALS_KEY", "")
        if not clave_cifrado_key:
            flash(
                "No se puede guardar la clave del SII: falta configurar "
                "SII_CREDENTIALS_KEY en el servidor. Se creó la empresa sin clave.",
                "error",
            )
        else:
            clave_cifrada = cifrar(clave_cifrado_key, clave_sii)

    sii_empresas_repo.crear_empresa(rut, nombre, clave_cifrada)
    flash(f"Empresa '{nombre}' agregada.", "success")
    return redirect(url_for("sii.empresas"))


@sii_bp.route("/empresas/<empresa_id>/clave", methods=["POST"])
@pagina_required("sii.contribuyente")
def empresas_actualizar_clave(empresa_id):
    clave_sii = request.form.get("clave_sii") or ""
    if not clave_sii:
        flash("Ingresa la nueva clave del SII.", "error")
        return redirect(url_for("sii.empresas"))

    empresa = sii_empresas_repo.obtener_empresa(empresa_id)
    if not empresa:
        flash("Esa empresa ya no existe.", "error")
        return redirect(url_for("sii.empresas"))

    clave_cifrado_key = current_app.config.get("SII_CREDENTIALS_KEY", "")
    if not clave_cifrado_key:
        flash("Falta configurar SII_CREDENTIALS_KEY en el servidor — no se puede guardar la clave.", "error")
        return redirect(url_for("sii.empresas"))

    clave_cifrada = cifrar(clave_cifrado_key, clave_sii)
    sii_empresas_repo.actualizar_empresa(empresa_id, empresa["nombre"], clave_cifrada, actualizar_clave=True)
    flash(f"Clave del SII de '{empresa['nombre']}' actualizada.", "success")
    return redirect(url_for("sii.empresas"))


@sii_bp.route("/empresas/<empresa_id>/eliminar", methods=["POST"])
@pagina_required("sii.contribuyente")
def empresas_eliminar(empresa_id):
    empresa = sii_empresas_repo.obtener_empresa(empresa_id)
    sii_empresas_repo.eliminar_empresa(empresa_id)
    if empresa:
        flash(f"Empresa '{empresa['nombre']}' eliminada.", "success")
    return redirect(url_for("sii.empresas"))
