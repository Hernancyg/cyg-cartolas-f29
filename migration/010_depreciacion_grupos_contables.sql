-- Rediseño del modelo de cuentas de "Generar asiento" (11-09-2026): en vez
-- de elegir 3 cuentas POR CADA activo individual, se configuran una vez
-- por "grupo contable" (la cuenta del activo fijo en sí, ej.
-- "1204-01 VEHICULOS" — agrupa todos los activos de esa clase) y cada
-- activo solo elige a qué grupo pertenece. "Generar asiento" consolida
-- todos los activos de un mismo grupo en una sola línea por cuenta.

create table if not exists depreciacion_grupos_contables (
    codigo                    text primary key,
    cuenta_gasto_codigo       text not null,
    cuenta_acumulada_codigo   text not null,
    cuenta_correccion_codigo  text,
    created_at                timestamptz not null default now(),
    updated_at                timestamptz not null default now()
);

alter table depreciacion_activos add column if not exists grupo_contable_codigo text references depreciacion_grupos_contables(codigo);
alter table depreciacion_activos drop column if exists cuenta_gasto_codigo;
alter table depreciacion_activos drop column if exists cuenta_acumulada_codigo;
alter table depreciacion_activos drop column if exists cuenta_correccion_codigo;

alter table depreciacion_grupos_contables enable row level security;
-- Sin policies a propósito, mismo criterio que el resto de las tablas.
