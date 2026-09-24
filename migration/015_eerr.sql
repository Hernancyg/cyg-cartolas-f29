-- Tablas del "EERR Dinámico" (24-09-2026).
--
-- eerr_empresas: empresas que se trabajan con Softland o Defontana,
--   agregadas desde Administrador → Sistemas contables. Las de Nubox NO van
--   acá: salen del conector NuboxMCP vía el puente Nubox -> repo
--   (nubox_importado/empresas.csv).
-- eerr_config: por empresa ("<sistema>:<código>"), los conceptos del informe
--   y en qué concepto va cada cuenta, para no asignarlas cada vez.
--
-- Ejecutar UNA vez en el proyecto Supabase (SQL Editor → New query →
-- pegar todo → Run), igual que las demás migraciones de esta carpeta.

create table if not exists eerr_empresas (
    id            uuid primary key default gen_random_uuid(),
    codigo        text not null,
    razon_social  text not null,
    rut           text,
    sistema       text not null check (sistema in ('softland', 'defontana')),
    created_at    timestamptz not null default now(),
    unique (sistema, codigo)
);

create table if not exists eerr_config (
    clave         text primary key,
    conceptos     jsonb not null default '[]'::jsonb,
    asignaciones  jsonb not null default '{}'::jsonb,
    updated_at    timestamptz not null default now()
);

alter table eerr_empresas enable row level security;
alter table eerr_config enable row level security;
-- Sin policies a propósito, mismo criterio que el resto de las tablas:
-- solo la service-role key (usada server-side por la app Flask) puede
-- leer o escribir.
