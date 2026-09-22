# nubox_importado

Esta carpeta contiene reportes contables exportados automáticamente desde Nubox
(vía el conector MCP de solo lectura) hacia este repositorio, en formato CSV,
para respaldo y trazabilidad histórica.

Estructura:

- `balance_general/<alias>_<periodo>.csv`: reporte Balance General por empresa y período (YYYYMM).
- `libro_mayor/<alias>_<periodo>.csv`: reporte Libro Mayor (todas las cuentas) por empresa y período (YYYYMM).

Cada archivo se sobrescribe en corridas posteriores para la misma empresa y período.
Los archivos de otras empresas/períodos ya presentes en estas carpetas no se
modifican salvo que una corrida futura los incluya explícitamente en su alcance.

## Última corrida

- **Fecha/hora**: 2026-09-22 01:52 UTC
- **Alcance**: SOLO la empresa con alias `626` (SOCIEDAD AGRICOLA Y COMERCIAL ACEVEDO Y COMPANIA SPA, RUT 76.353.060-4).
- **Período procesado**: 202608 (agosto 2026), el último período calendario completamente cerrado respecto a la fecha de la corrida (22-09-2026).

### Balance General (`balance_general/626_202608.csv`)
- Filas exportadas: **1427**
- Paginación: 3 páginas (offset 0, 500, 1000). Última página con `truncado=false` → **reporte completo**.

### Libro Mayor (`libro_mayor/626_202608.csv`)
- Filas exportadas: **434**
- Paginación: 1 página (offset 0), `truncado=false` desde el inicio → **reporte completo**.

## Notas

- Los datos se obtienen tal cual los entrega la API de Nubox (todas las columnas, sin transformación de valores).
- Se eliminó `.push_test`, un archivo usado para validar permisos de push en una corrida anterior; ya no es necesario.
