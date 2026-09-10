"""Ítems del menú lateral, en un solo lugar para que `base.html` y las
rutas que resaltan el ítem activo (`request.endpoint`) usen la misma
fuente de verdad.

`admin_only` es el valor por defecto (usado si Supabase está caído, si la
tabla `visibilidad_pestanas` está vacía, o si la pestaña no es
`configurable`). Las pestañas con `configurable: True` pueden
sobreescribir ese valor desde el panel Administrador → Pestañas (09-09-2026,
ver `app/admin/routes.py` y `app/data/visibilidad_repo.py`) sin tocar
código ni redesplegar. "Administrador" queda fuera a propósito: es la
pantalla que administra usuarios y esta misma configuración, así que sigue
siempre solo-admin, sin excepción.
"""

PAGINAS = [
    {"endpoint": "cartolas.index", "icon": "cloud", "label": "Subir Cartolas", "admin_only": False, "configurable": True},
    {"endpoint": "f29.index", "icon": "invoice", "label": "Generar F29", "admin_only": False, "configurable": True},
    {"endpoint": "global_igc.index", "icon": "calculator", "label": "Calcular Global", "admin_only": False, "configurable": True},
    {"endpoint": "indicadores.index", "icon": "trending", "label": "Indicadores", "admin_only": False, "configurable": True},
    {"endpoint": "reuniones.index", "icon": "calendar", "label": "Reuniones", "admin_only": True, "configurable": True},
    {"endpoint": "conciliacion.index", "icon": "reconcile", "label": "Conciliación", "admin_only": True, "configurable": True},
    {"endpoint": "caja_empresas.index", "icon": "cash", "label": "Empresas Caja", "admin_only": True, "configurable": True},
    {"endpoint": "admin.cuentas", "icon": "gear", "label": "Administrador", "admin_only": True, "configurable": False},
]


def paginas_con_visibilidad():
    """`PAGINAS` con el `admin_only` de cada pestaña `configurable`
    sobreescrito según lo que haya guardado el admin (si nunca lo tocó,
    queda el valor por defecto de arriba). La usan tanto `base.html` (para
    dibujar el menú) como el panel Administrador → Pestañas (para mostrar
    el estado actual de cada fila)."""
    from app.data import visibilidad_repo
    overrides = visibilidad_repo.obtener_mapa()
    resultado = []
    for p in PAGINAS:
        p2 = dict(p)
        if p["configurable"] and p["endpoint"] in overrides:
            p2["admin_only"] = overrides[p["endpoint"]]
        resultado.append(p2)
    return resultado


def es_admin_only(endpoint_pagina: str) -> bool:
    """Si `endpoint_pagina` requiere rol admin en este momento (con la
    configuración guardada, o el valor por defecto si no la hay). La usa
    `app.auth.decorators.pagina_required` para controlar el acceso a cada
    ruta, no solo para dibujar el menú."""
    for p in paginas_con_visibilidad():
        if p["endpoint"] == endpoint_pagina:
            return p["admin_only"]
    # No debería pasar (toda pestaña real está en PAGINAS) — por
    # seguridad, ante una clave desconocida se exige admin en vez de
    # abrir algo por accidente.
    return True
