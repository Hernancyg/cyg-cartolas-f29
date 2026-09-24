"""
"EERR Dinámico" (24-09-2026): Estado de Resultados por conceptos definidos
por empresa. Flujo en una sola página (`templates/eerr/index.html` +
`static/js/eerr.js`): sistema contable → empresa y período → conceptos →
asignar cuentas → informe, con exportación a Excel y PDF.

- Nubox: empresas y datos salen del puente Nubox -> repo
  (`app/data/nubox_importado_repo.py`), según las empresas seleccionadas
  en el conector NuboxMCP.
- Softland / Defontana: empresas agregadas a mano en Administrador →
  Sistemas contables (`app/data/eerr_repo.py`). La importación de sus
  datos (libros mayores o balances) todavía está por definir.

El cálculo vive en `app/eerr/calculo.py` y es el mismo para la pantalla y
para las exportaciones.
"""

import json
import logging
import re

from flask import Blueprint, jsonify, render_template, request, send_file

from app.auth.decorators import pagina_required
from app.data import eerr_repo, nubox_importado_repo
from app.eerr import calculo
from app.eerr.exportar import generar_excel, generar_pdf

logger = logging.getLogger(__name__)

eerr_bp = Blueprint("eerr", __name__, url_prefix="/eerr")

_AVISO_MIGRACION = (
    "No se pudo guardar la configuración en la base de datos (¿falta ejecutar "
    "migration/015_eerr.sql en Supabase?). El informe se calculó igual, pero la "
    "asignación de cuentas no quedará guardada."
)


def _empresas_por_sistema():
    """{sistema: [{codigo, razon_social, rut, anios}]} para el paso 1 y 2."""
    empresas = {s: [] for s in eerr_repo.SISTEMAS}
    for e in nubox_importado_repo.listar_empresas_nubox():
        empresas["nubox"].append({
            "codigo": e["alias"], "razon_social": e["razon_social"], "rut": e["rut"],
            "anios": nubox_importado_repo.eerr_anios_disponibles(e["alias"]),
        })
    aviso = None
    try:
        for e in eerr_repo.listar_empresas_manuales():
            if e.get("sistema") in eerr_repo.SISTEMAS_MANUALES:
                empresas[e["sistema"]].append({
                    "codigo": e.get("codigo") or "", "razon_social": e.get("razon_social") or "",
                    "rut": e.get("rut") or "", "anios": [],
                })
    except Exception:  # noqa: BLE001 — Supabase caído o tabla sin crear
        logger.exception("No se pudieron leer las empresas de Softland/Defontana")
        aviso = "No se pudieron leer las empresas de Softland/Defontana desde la base de datos."
    return empresas, aviso


def _empresa(sistema, codigo):
    empresas, _ = _empresas_por_sistema()
    return next((e for e in empresas.get(sistema, []) if e["codigo"] == codigo), None)


def _cargar_datos(sistema, codigo, anio):
    """(empresa, datos_leidos, error)."""
    if sistema not in eerr_repo.SISTEMAS:
        return None, None, "Sistema contable desconocido."
    empresa = _empresa(sistema, codigo)
    if not empresa:
        return None, None, "La empresa no está disponible para ese sistema contable."
    if sistema != "nubox":
        return empresa, None, (
            f"La importación desde {eerr_repo.SISTEMAS[sistema]} aún no está disponible: "
            "se trabajará con archivos (libros mayores o balances)."
        )
    ruta = nubox_importado_repo.ruta_eerr(codigo, anio)
    if not ruta:
        return empresa, None, f"No hay Estado de Resultados de Nubox importado para {codigo} en {anio}."
    return empresa, calculo.leer_eerr_csv(ruta), None


def _config_guardada(sistema, codigo):
    try:
        return eerr_repo.obtener_config(eerr_repo.clave_empresa(sistema, codigo)), None
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo leer eerr_config")
        return None, "No se pudo leer la configuración guardada de la empresa; se usa la plantilla de conceptos."


def _fuente(sistema, datos):
    nombre = eerr_repo.SISTEMAS.get(sistema, sistema)
    generado = (datos or {}).get("generado_en") or ""
    if len(generado) >= 10:
        a, m, d = generado[:10].split("-")
        return f"{nombre}, datos al {d}-{m}-{a}"
    return nombre


def _anio(valor):
    texto = str(valor or "")
    return int(texto) if re.fullmatch(r"\d{4}", texto) else None


@eerr_bp.route("/", methods=["GET"])
@pagina_required("eerr.index")
def index():
    empresas, aviso = _empresas_por_sistema()
    return render_template(
        "eerr/index.html",
        sistemas=eerr_repo.SISTEMAS, empresas=empresas, aviso=aviso,
        secciones={k: v[0] for k, v in calculo.SECCIONES.items()}, meses=calculo.MESES,
    )


@eerr_bp.route("/datos", methods=["GET"])
@pagina_required("eerr.index")
def datos():
    sistema = request.args.get("sistema", "")
    codigo = request.args.get("codigo", "")
    anio = _anio(request.args.get("anio"))
    if anio is None:
        return jsonify(error="Año inválido."), 400
    empresa, leidos, error = _cargar_datos(sistema, codigo, anio)
    if error:
        return jsonify(error=error), 404
    config, aviso = _config_guardada(sistema, codigo)
    conceptos = calculo.normalizar_conceptos((config or {}).get("conceptos"))
    asignaciones = calculo.normalizar_asignaciones((config or {}).get("asignaciones"), conceptos)
    return jsonify(
        empresa=empresa, anio=anio, fuente=_fuente(sistema, leidos),
        meses_con_datos=leidos["meses_con_datos"],
        cuentas=[{"codigo": c["codigo"], "nombre": c["nombre"], "tipo": c["tipo"], "meses": c["meses"]}
                 for c in leidos["cuentas"]],
        conceptos=conceptos, asignaciones=asignaciones, config_guardada=bool(config), aviso=aviso,
    )


def _leer_peticion(fuente):
    """Parámetros comunes de /informe (JSON) y /exportar (formulario)."""
    sistema = str(fuente.get("sistema") or "")
    codigo = str(fuente.get("codigo") or "")
    anio = _anio(fuente.get("anio"))
    try:
        desde = int(fuente.get("desde") or 1)
        hasta = int(fuente.get("hasta") or 12)
    except (TypeError, ValueError):
        desde, hasta = 1, 12
    conceptos = fuente.get("conceptos")
    asignaciones = fuente.get("asignaciones")
    if isinstance(conceptos, str):
        try:
            conceptos = json.loads(conceptos)
        except ValueError:
            conceptos = None
    if isinstance(asignaciones, str):
        try:
            asignaciones = json.loads(asignaciones)
        except ValueError:
            asignaciones = None
    conceptos = calculo.normalizar_conceptos(conceptos)
    asignaciones = calculo.normalizar_asignaciones(asignaciones, conceptos)
    return sistema, codigo, anio, desde, hasta, conceptos, asignaciones


@eerr_bp.route("/informe", methods=["POST"])
@pagina_required("eerr.index")
def informe():
    """Guarda conceptos y asignación de la empresa (si `guardar`) y devuelve
    el informe calculado para el rango pedido."""
    cuerpo = request.get_json(silent=True) or {}
    sistema, codigo, anio, desde, hasta, conceptos, asignaciones = _leer_peticion(cuerpo)
    if anio is None:
        return jsonify(error="Año inválido."), 400
    _empresa_, leidos, error = _cargar_datos(sistema, codigo, anio)
    if error:
        return jsonify(error=error), 404

    aviso = None
    if cuerpo.get("guardar"):
        try:
            eerr_repo.guardar_config(eerr_repo.clave_empresa(sistema, codigo), conceptos, asignaciones)
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo guardar eerr_config")
            aviso = _AVISO_MIGRACION

    resultado = calculo.calcular(leidos["cuentas"], conceptos, asignaciones, desde, hasta)
    return jsonify(informe=resultado, conceptos=conceptos, asignaciones=asignaciones,
                   guardado=bool(cuerpo.get("guardar")) and aviso is None, aviso=aviso)


@eerr_bp.route("/exportar", methods=["POST"])
@pagina_required("eerr.index")
def exportar():
    sistema, codigo, anio, desde, hasta, conceptos, asignaciones = _leer_peticion(request.form)
    formato = request.form.get("formato", "xlsx")
    con_cuentas = request.form.get("con_cuentas", "1") == "1"
    if anio is None:
        return render_template("error.html", codigo=400, mensaje="Año inválido."), 400
    empresa, leidos, error = _cargar_datos(sistema, codigo, anio)
    if error:
        return render_template("error.html", codigo=404, mensaje=error), 404

    resultado = calculo.calcular(leidos["cuentas"], conceptos, asignaciones, desde, hasta)
    rango = calculo.rango_legible(resultado["meses"][0], resultado["meses"][-1], anio)
    fuente = _fuente(sistema, leidos)
    base = f"EERR_{codigo}_{anio}{resultado['meses'][0]:02d}-{resultado['meses'][-1]:02d}"
    if formato == "pdf":
        archivo = generar_pdf(resultado, empresa, anio, rango, fuente, con_cuentas)
        return send_file(archivo, as_attachment=True, download_name=f"{base}.pdf", mimetype="application/pdf")
    archivo = generar_excel(resultado, empresa, anio, rango, fuente, con_cuentas)
    return send_file(
        archivo, as_attachment=True, download_name=f"{base}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

