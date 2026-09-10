-- Tipos de Documento (10-09-2026): mapeo configurable de texto ("FAC-EL",
-- "FAC-EE", "BOL-HE", etc., tal como vienen en los archivos de Clientes/
-- Proveedores/Honorarios de "Empresas Caja") a un código numérico, que es
-- lo que exige la columna "Tipo De Documento" del archivo de salida.
-- Editable desde el panel Administrador → Tipos de Documento, para que el
-- usuario pueda agregar más códigos sin pedir un redespliegue.
-- Ejecutar UNA vez en el proyecto Supabase de esta app (Supabase
-- Dashboard → SQL Editor → New query → pegar todo → Run).

create table if not exists tipos_documento (
    texto       text primary key,
    codigo      integer not null,
    updated_at  timestamptz not null default now()
);

alter table tipos_documento enable row level security;
-- Sin policies a propósito, igual que el resto de las tablas de esta app:
-- solo la service-role key (usada server-side por la app Flask, nunca
-- expuesta al navegador) puede leer/escribir.

-- Códigos de partida confirmados por el usuario. Mientras la tabla esté
-- vacía la app usa estos mismos valores por defecto (ver
-- `app/data/tipos_documento_repo.py:DEFAULTS`), pero conviene dejarlos
-- creados aquí para que aparezcan de entrada en el panel de Administrador.
insert into tipos_documento (texto, codigo) values
    ('FAC-EL', 33),
    ('FAC-EE', 34),
    ('BOL-HE', 99)
on conflict (texto) do nothing;
