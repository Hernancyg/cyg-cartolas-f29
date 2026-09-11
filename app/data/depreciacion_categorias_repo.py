"""
CRUD de la tabla `depreciacion_categorias` en Supabase — el catálogo de
"tipo de bien -> años de vida útil normal" que usa la pestaña
"Depreciación" para sugerir la vida útil de cada activo fijo nuevo (el
contador siempre puede sobrescribirla a mano en el activo mismo, ver
`depreciacion_activos_repo.py`).

Semilla (`DEFAULTS`) transcrita de la tabla oficial vigente del SII:
https://www.sii.cl/valores_y_fechas/tabla_vida_util_activo_inmovilizado.html
("Nueva Tabla de Vida Útil... según Resolución N°43, de 26-12-2002, con
vigencia a partir del 01-01-2003"), columna "Vida útil normal" — la
columna de depreciación ACELERADA no se incluyó porque el usuario pidió
solo depreciación lineal normal (11-09-2026).

Se incluyeron las secciones de uso más común para los clientes de un
estudio contable general (Activos Genéricos, Construcción, Transporte
Terrestre, Agricultura, Otras) y se dejaron fuera a propósito las
secciones muy específicas de industrias reguladas grandes (Minería,
Transporte Marítimo, Sector Eléctrico, Petróleo y Gas, Telecomunicaciones)
— si algún cliente las llegara a necesitar, se agregan a mano desde
"Depreciación → Categorías SII" (mismo criterio que `tipos_documento_repo.
DEFAULTS`: son solo el punto de partida, la tabla real vive en Supabase
en cuanto el admin guarda algún cambio).

Algunos bienes de la tabla oficial no tienen un número fijo de años (ej.
viñedos: "11 a 23 años según variedad") o no son depreciables por tener
duración indefinida (ej. tranques, canales sin revestimiento) — esos
quedan con `vida_util_anios=None` y una `nota` explicando el caso; el
formulario de "agregar activo" exige tipear la vida útil a mano cuando la
categoría elegida no trae una sugerida.

Mismo patrón tolerante/fail-safe que `tipos_documento_repo.py`: caché en
memoria por poco tiempo, y si Supabase falla o la tabla todavía no tiene
ninguna fila propia, se sigue con `DEFAULTS` en vez de romper la pestaña.
"""

import logging
import time
from typing import List, Optional

from app.extensions import get_supabase

logger = logging.getLogger(__name__)

TABLE = "depreciacion_categorias"
_CACHE_TTL_SEGUNDOS = 30

# (sección, descripción, vida_util_anios normal, nota)
DEFAULTS_RAW = [
    ("A.- Activos genéricos", "Construcciones con estructuras de acero, cubierta y entrepisos de perfiles acero o losas hormigón armado.", 80, None),
    ("A.- Activos genéricos", "Edificios, casas y otras construcciones, con muros de ladrillos o de hormigón, con cadenas, pilares y vigas hormigón armado, con o sin losas.", 50, None),
    ("A.- Activos genéricos", "Edificios fábricas de material sólido albañilería de ladrillo, de concreto armado y estructura metálica.", 40, None),
    ("A.- Activos genéricos", "Construcciones de adobe o madera en general.", 30, None),
    ("A.- Activos genéricos", "Galpones de madera o estructura metálica.", 20, None),
    ("A.- Activos genéricos", "Otras construcciones definitivas (ejemplos: caminos, puentes, túneles, vías férreas, etc.).", 20, None),
    ("A.- Activos genéricos", "Construcciones provisorias.", 10, None),
    ("A.- Activos genéricos", "Instalaciones en general (ejemplos: eléctricas, de oficina, etc.).", 10, None),
    ("A.- Activos genéricos", "Camiones de uso general.", 7, None),
    ("A.- Activos genéricos", "Camionetas y jeeps.", 7, None),
    ("A.- Activos genéricos", "Automóviles.", 7, None),
    ("A.- Activos genéricos", "Microbuses, taxibuses, furgones y similares.", 7, None),
    ("A.- Activos genéricos", "Motos en general.", 7, None),
    ("A.- Activos genéricos", "Remolques, semirremolques y carros de arrastre.", 7, None),
    ("A.- Activos genéricos", "Maquinarias y equipos en general.", 15, None),
    ("A.- Activos genéricos", "Balanzas, hornos microondas, refrigeradores, conservadoras, vitrinas refrigeradas y cocinas.", 9, None),
    ("A.- Activos genéricos", "Equipos de aire y cámaras de refrigeración.", 10, None),
    ("A.- Activos genéricos", "Herramientas pesadas.", 8, None),
    ("A.- Activos genéricos", "Herramientas livianas.", 3, None),
    ("A.- Activos genéricos", "Letreros camineros y luminosos.", 10, None),
    ("A.- Activos genéricos", "Útiles de oficina (ejemplos: máquina de escribir, fotocopiadora, etc.).", 3, None),
    ("A.- Activos genéricos", "Muebles y enseres.", 7, None),
    ("A.- Activos genéricos", "Sistemas computacionales, computadores, periféricos, y similares (ejemplos: cajeros automáticos, cajas registradoras, etc.).", 6, None),
    ("A.- Activos genéricos", "Estanques.", 10, None),
    ("A.- Activos genéricos", "Equipos médicos en general.", 8, None),
    ("A.- Activos genéricos", "Equipos de vigilancia y detección y control de incendios, alarmas.", 7, None),
    ("A.- Activos genéricos", "Envases en general.", 6, None),
    ("A.- Activos genéricos", "Equipo de audio y video.", 6, None),
    ("A.- Activos genéricos", "Material de audio y video.", 5, None),

    ("B.- Industria de la construcción", "Maquinaria destinada a la construcción pesada (motoniveladoras, bulldozers, tractores, dragas, excavadoras, pavimentadoras, chancadoras, betoneras, vibradoras, torres elevadoras, tolvas, etc.).", 8, None),
    ("B.- Industria de la construcción", "Bombas, perforadoras, carros remolques, motores a gasolina, grupos electrógenos, soldadoras.", 6, None),

    ("D.- Transporte terrestre", "Tolvas, mecanismo de volteo.", 9, None),
    ("D.- Transporte terrestre", "Carros portacontenedores en general.", 7, None),

    ("G.- Agricultura", "Tractores, segadoras, cultivadoras, fumigadoras, motobombas, pulverizadoras.", 8, None),
    ("G.- Agricultura", "Cosechadoras, arados, esparcidoras de abono y de cal, máquinas de ordeñar.", 11, None),
    ("G.- Agricultura", "Esquiladoras mecánicas y maquinarias no comprendidas en la categoría anterior.", 11, None),
    ("G.- Agricultura", "Vehículos de carga motorizados (camiones trailers, camiones fudres y acoplados, colosos de tiro animal).", 10, None),
    ("G.- Agricultura", "Carretas, carretones, carretelas, etc.", 15, None),
    ("G.- Agricultura", "Camiones de carga y camionetas de uso intensivo en la actividad agrícola.", 6, None),
    ("G.- Agricultura", "Tuberías para agua potable instaladas en predios agrícolas.", 18, None),
    ("G.- Agricultura", "Construcciones de material sólido (silos, casas patronales y de inquilinos, lagares, etc.).", 50, None),
    ("G.- Agricultura", "Construcciones de adobe y madera, estructuras metálicas.", 20, None),
    ("G.- Agricultura", "Animales de trabajo.", 8, None),
    ("G.- Agricultura", "Toros, carneros, cabríos, verracos, potros y otros reproductores.", 5, None),
    ("G.- Agricultura", "Gallos y pavos reproductores.", 3, None),
    ("G.- Agricultura", "Nogales, paltos, ciruelos, manzanos, almendros.", 18, None),
    ("G.- Agricultura", "Viñedos.", None, "Variable según variedad: de 11 a 23 años — ingresa la vida útil a mano."),
    ("G.- Agricultura", "Limoneros.", 12, None),
    ("G.- Agricultura", "Duraznos.", 10, None),
    ("G.- Agricultura", "Otras plantaciones frutales (no nogales/paltos/ciruelos/manzanos/almendros, viñedos, limoneros ni duraznos).", 13, None),
    ("G.- Agricultura", "Olivos.", 40, None),
    ("G.- Agricultura", "Naranjos.", 30, None),
    ("G.- Agricultura", "Perales.", 25, None),
    ("G.- Agricultura", "Orégano.", 9, None),
    ("G.- Agricultura", "Alfalfa.", 4, None),
    ("G.- Agricultura", "Animales de lechería (vacas).", 7, None),
    ("G.- Agricultura", "Gallinas.", 3, None),
    ("G.- Agricultura", "Ovejas.", 5, None),
    ("G.- Agricultura", "Yeguas.", 12, None),
    ("G.- Agricultura", "Porcinos de reproducción (hembras).", 6, None),
    ("G.- Agricultura", "Conejos machos y hembras.", 3, None),
    ("G.- Agricultura", "Caprinos.", 5, None),
    ("G.- Agricultura", "Asnales.", 5, None),
    ("G.- Agricultura", "Postes y alambradas para viñas.", 10, None),
    ("G.- Agricultura", "Tranque propiamente tal (obra de captación de aguas).", None, "No depreciable: duración indefinida."),
    ("G.- Agricultura", "Instalaciones anexas al tranque (bombas extractoras de agua, estanques e instalaciones similares).", 10, None),
    ("G.- Agricultura", "Canal de riego sin aplicación de concreto u otro material de construcción.", None, "No depreciable: duración indefinida."),
    ("G.- Agricultura", "Canal de riego con aplicación de concreto.", 70, None),
    ("G.- Agricultura", "Canal de riego con aplicación de fierro pesado.", 45, None),
    ("G.- Agricultura", "Canal de riego con aplicación de madera.", 25, None),
    ("G.- Agricultura", "Pozo de riego/bebida — refuerzos e instalaciones de cemento u hormigón armado.", 20, None),
    ("G.- Agricultura", "Pozo de riego/bebida — refuerzos e instalaciones de ladrillo.", 15, None),
    ("G.- Agricultura", "Pozo de riego/bebida — bomba elevadora de agua.", 20, None),
    ("G.- Agricultura", "Puente de cemento.", 75, None),
    ("G.- Agricultura", "Puente metálico.", 45, None),
    ("G.- Agricultura", "Puente de madera.", 30, None),

    ("H.- Otras", "Enseres, artículos de porcelana, loza, vidrio, cuchillería, mantelería, ropa de cama y similares, utilizados en hoteles, moteles y restaurantes.", 3, None),
    ("H.- Otras", "Redes utilizadas en la pesca.", 3, None),
    ("H.- Otras", "Sistemas o estructuras físicas para criaderos de especies hidrobiológicas.", 3, None),
    ("H.- Otras", "Pupitres, sillas, bancos, escritorios, pizarrones, laboratorios de química, gabinetes de física, equipos de gimnasia y atletismo, utilizados en establecimientos educacionales.", 5, None),
    ("H.- Otras", "Aviones monomotores con cabida hasta seis personas.", 10, None),
]

DEFAULTS: List[dict] = [
    {"seccion": seccion, "descripcion": descripcion, "vida_util_anios": vida_util, "nota": nota, "orden": i}
    for i, (seccion, descripcion, vida_util, nota) in enumerate(DEFAULTS_RAW)
]

_cache: Optional[List[dict]] = None
_cache_at = 0.0


def listar_categorias() -> List[dict]:
    """Lista completa, ordenada. Nunca lanza — si Supabase falla o la
    tabla está vacía/no existe, devuelve `DEFAULTS`."""
    global _cache, _cache_at
    ahora = time.monotonic()
    if _cache is not None and (ahora - _cache_at) < _CACHE_TTL_SEGUNDOS:
        return _cache
    try:
        resp = get_supabase().table(TABLE).select("*").order("orden").execute()
        filas = resp.data or []
        _cache = filas if filas else [dict(d) for d in DEFAULTS]
        _cache_at = ahora
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "No se pudo leer depreciacion_categorias (¿falta ejecutar "
            "migration/006_depreciacion.sql en Supabase?): %s. Se sigue "
            "con las categorías por defecto.", exc,
        )
        if _cache is None:
            return [dict(d) for d in DEFAULTS]
    return _cache


def obtener_categoria(categoria_id: str) -> Optional[dict]:
    return next((c for c in listar_categorias() if c.get("id") == categoria_id), None)


def guardar_todas(filas: List[dict]) -> None:
    """Reemplaza el contenido completo de la tabla (mismo patrón de
    "borrar todo e insertar de nuevo" que `tipos_documento_repo.
    guardar_todos`) e invalida el caché en memoria."""
    global _cache, _cache_at
    sb = get_supabase()
    sb.table(TABLE).delete().neq("descripcion", "__never__").execute()
    payload = [
        {
            "seccion": f["seccion"].strip(),
            "descripcion": f["descripcion"].strip(),
            "vida_util_anios": f.get("vida_util_anios"),
            "nota": (f.get("nota") or "").strip() or None,
            "orden": i,
        }
        for i, f in enumerate(filas)
        if (f.get("seccion") or "").strip() and (f.get("descripcion") or "").strip()
    ]
    if payload:
        sb.table(TABLE).insert(payload).execute()
    _cache = payload if payload else [dict(d) for d in DEFAULTS]
    _cache_at = time.monotonic()
