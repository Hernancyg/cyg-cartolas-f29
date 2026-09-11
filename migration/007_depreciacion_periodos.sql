-- Kardex de depreciación por activo: una fila por período (normalmente un
-- año) con los meses efectivamente utilizados ese período — editable a
-- mano por el contador (ver "Agregar período" en la ficha del activo,
-- app/depreciacion/routes.py). El resto de las columnas de la planilla
-- del usuario (Costo total, Vida útil restante, Depreciación del
-- ejercicio, Depreciación acumulada, Valor libro) se CALCULAN al vuelo
-- encadenando estas filas (ver app/depreciacion/calculo.calcular_kardex)
-- y no se guardan — así nunca quedan desincronizadas de lo que el
-- contador edite.

create table if not exists depreciacion_periodos (
    id                uuid primary key default gen_random_uuid(),
    activo_id         uuid not null references depreciacion_activos(id) on delete cascade,
    fecha             date not null,
    meses_utilizados  integer not null,
    adiciones         numeric not null default 0,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

create index if not exists depreciacion_periodos_activo_id_idx on depreciacion_periodos(activo_id);

alter table depreciacion_periodos enable row level security;
-- Sin policies a propósito, mismo criterio que el resto de las tablas.
