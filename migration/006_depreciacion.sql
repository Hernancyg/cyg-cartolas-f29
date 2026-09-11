-- Tablas para la pestaña "Depreciación": empresas (registro propio, sin
-- relación con `sii_empresas`), la tabla de categorías/vida útil del SII
-- (editable desde la app — ver DEFAULTS en
-- app/data/depreciacion_categorias_repo.py, semilla tomada de
-- https://www.sii.cl/valores_y_fechas/tabla_vida_util_activo_inmovilizado.html)
-- y los activos fijos de cada empresa.
-- Ejecutar UNA vez en el proyecto Supabase (SQL Editor → New query →
-- pegar todo → Run), igual que las migraciones anteriores.

create table if not exists depreciacion_empresas (
    id          uuid primary key default gen_random_uuid(),
    rut         text,
    nombre      text not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

-- Vacía hasta que el admin guarde cambios desde "Depreciación →
-- Categorías SII" — mientras tanto la app usa los DEFAULTS en memoria
-- (mismo patrón que `tipos_documento_repo.py`).
create table if not exists depreciacion_categorias (
    id                uuid primary key default gen_random_uuid(),
    seccion           text not null,
    descripcion       text not null,
    vida_util_anios   integer,
    nota              text,
    orden             integer not null default 0,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

create table if not exists depreciacion_activos (
    id                 uuid primary key default gen_random_uuid(),
    empresa_id         uuid not null references depreciacion_empresas(id) on delete cascade,
    categoria_id       uuid references depreciacion_categorias(id) on delete set null,
    nombre_activo      text not null,
    fecha_adquisicion  date not null,
    valor_adquisicion  numeric not null,
    vida_util_anios    integer not null,
    activo             boolean not null default true,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

create index if not exists depreciacion_activos_empresa_id_idx on depreciacion_activos(empresa_id);

alter table depreciacion_empresas enable row level security;
alter table depreciacion_categorias enable row level security;
alter table depreciacion_activos enable row level security;
-- Sin policies a propósito, mismo criterio que el resto de las tablas:
-- solo la service-role key (usada server-side por la app Flask) puede
-- leer o escribir.
