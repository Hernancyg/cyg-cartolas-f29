-- "Generar asiento contable" para Depreciación:
--   - 3 cuentas por activo (Gasto Depreciación / Depreciación Acumulada /
--     Corrección Monetaria), elegidas del plan de cuentas
--     (app/conciliacion/plan_cuentas.py) y guardadas en el activo mismo.
--   - `depreciacion_asientos`: la "memoria" de qué períodos de qué activo
--     YA se registraron en un comprobante — permite generar de nuevo más
--     adelante y que solo se incluyan los períodos nuevos, nunca
--     duplicar uno ya asentado. Se guarda por (activo_id, fecha) y no por
--     el id de `depreciacion_periodos` porque el kardex se guarda
--     "borra todo y reinserta" (ver depreciacion_periodos_repo.
--     guardar_todos) — el id de una fila cambia cada vez que se edita el
--     kardex, pero su fecha no.

alter table depreciacion_activos add column if not exists cuenta_gasto_codigo text;
alter table depreciacion_activos add column if not exists cuenta_acumulada_codigo text;
alter table depreciacion_activos add column if not exists cuenta_correccion_codigo text;

create table if not exists depreciacion_asientos (
    id                uuid primary key default gen_random_uuid(),
    activo_id         uuid not null references depreciacion_activos(id) on delete cascade,
    fecha             date not null,
    monto_ejercicio   numeric not null,
    monto_correccion  numeric not null default 0,
    created_at        timestamptz not null default now(),
    unique (activo_id, fecha)
);

create index if not exists depreciacion_asientos_activo_id_idx on depreciacion_asientos(activo_id);

alter table depreciacion_asientos enable row level security;
-- Sin policies a propósito, mismo criterio que el resto de las tablas.
