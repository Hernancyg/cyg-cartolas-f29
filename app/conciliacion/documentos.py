"""
Documentos auxiliares (Clientes/Proveedores/Honorarios) para la nueva
conciliación asistida (14-09-2026) — el usuario pidió poder cargar los
mismos 3 archivos que ya se suben en "Empresas Caja" (`app/caja_empresas/
parsers.py`, sin duplicar el parseo) para que cada movimiento de la
cartola se pueda proponer/emparejar contra un documento pendiente de
cobro o pago, en vez de solo buscar una cuenta suelta del plan de
cuentas.

Mismo criterio de cuenta fija y bloque de Tipo Auxiliar que "Empresas
Caja" (`app/caja_empresas/routes.py:DOCUMENTO_MODULOS`) — Clientes/
Proveedores usan el bloque "A" (Rut/Razón Social/Tipo Doc/Folio/Monto/
Fecha), Honorarios el bloque "H" — se duplica aquí (en vez de importar el
dict de `caja_empresas`) para no acoplar un módulo al otro; ambos
terminan reutilizando el mismo `app/conciliacion/plan_cuentas.py`.
"""

from app.caja_empresas import parsers as caja_parsers

AUXILIAR_MODULOS = {
    "clientes": {
        "parser": caja_parsers.parsear_clientes,
        "titulo": "Clientes",
        "cuenta_codigo": "1104-01",
        "tipo_auxiliar": "A",
        "direccion": "abono",  # cobro: se emparienta contra un movimiento que ENTRA (abono)
        "error_archivo": "¿Es el Excel de “Estado de Cuentas - Pendientes” de Clientes?",
    },
    "proveedores": {
        "parser": caja_parsers.parsear_proveedores,
        "titulo": "Proveedores",
        "cuenta_codigo": "2105-01",
        "tipo_auxiliar": "A",
        "direccion": "cargo",  # pago: se emparienta contra un movimiento que SALE (cargo)
        "error_archivo": "¿Es el Excel de “Estado de Cuentas - Pendientes” de Proveedores?",
    },
    "honorarios": {
        "parser": caja_parsers.parsear_honorarios,
        "titulo": "Honorarios",
        "cuenta_codigo": "2105-04",
        "tipo_auxiliar": "H",
        "direccion": "cargo",
        "error_archivo": "¿Es el Excel de “Estado de Cuentas de Honorario - Pendientes”?",
    },
}
