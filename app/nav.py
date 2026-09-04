"""Ítems del menú lateral, en un solo lugar para que `base.html` y las
rutas que resaltan el ítem activo (`request.endpoint`) usen la misma
fuente de verdad."""

PAGINAS = [
    {"endpoint": "cartolas.index", "icon": "cloud", "label": "Subir Cartolas", "admin_only": False},
    {"endpoint": "f29.index", "icon": "invoice", "label": "Generar F29", "admin_only": False},
    {"endpoint": "global_igc.index", "icon": "calculator", "label": "Calcular Global", "admin_only": False},
    {"endpoint": "admin.cuentas", "icon": "gear", "label": "Administrador", "admin_only": True},
]
