-- El asiento de baja por VENTA es distinto según la modalidad (el usuario
-- corrigió el modelo con un ejemplo real, 11-09-2026):
--
--   - Contrato de compraventa: UN asiento con todo (Depreciación
--     Acumulada, Cuentas por Cobrar por el monto de la venta, Utilidad o
--     Pérdida, Activo Fijo) — como ya estaba.
--   - Factura: el asiento de la BAJA solo reconoce el valor libro como
--     "Costo Venta Activo Fijo" (Depreciación Acumulada + Costo Venta =
--     Activo Fijo) — sin Cuentas por Cobrar ni Utilidad/Pérdida, porque
--     esas quedan en el asiento de la factura de venta en sí (aparte, no
--     lo genera esta app).
--
-- Hace falta una 4ª cuenta (solo para la modalidad "factura").

alter table depreciacion_config_baja add column if not exists cuenta_costo_venta_codigo text;
