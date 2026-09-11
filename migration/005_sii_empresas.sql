-- Tabla para la pestaña "Consulta SII" → "Empresas SII": empresas
-- clientes con su RUT y, opcionalmente, la clave del SII guardada
-- CIFRADA (nunca en texto plano — ver app/sii/crypto.py y
-- SII_CREDENTIALS_KEY en el README), usada por "RCV" para llamar a
-- SimpleAPI en nombre de esa empresa.
-- Ejecutar UNA vez en el proyecto Supabase (SQL Editor → New query →
-- pegar todo → Run), igual que 001_schema.sql.

create table if not exists sii_empresas (
    id                  uuid primary key default gen_random_uuid(),
    rut                 text not null unique,
    nombre              text not null,
    clave_sii_cifrada   text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

alter table sii_empresas enable row level security;
-- Sin policies a propósito, mismo criterio que el resto de las tablas:
-- solo la service-role key (usada server-side por la app Flask) puede
-- leer o escribir.
