-- Tabla para la pestaña "Planificación AT 2027": el Excel de seguimiento
-- que hoy se lleva a mano (empresa, analista, prioridad, quién quedó
-- asignado cada mes, frecuencia de actualización del balance, etc.).
-- Tabla plana, sin relaciones a otras tablas — se edita fila por fila
-- desde la pestaña (Administrador → Pestañas la puede abrir a todos los
-- usuarios si se quiere) y se puede reemplazar completa subiendo un Excel
-- nuevo desde Administrador → Planificación AT 2027 (17-09-2026, pedido
-- por el usuario).
-- Ejecutar UNA vez en el proyecto Supabase (SQL Editor → New query →
-- pegar todo → Run), igual que las demás migraciones de esta carpeta.

create table if not exists planificacion_at2027 (
    id                          uuid primary key default gen_random_uuid(),
    numero                      integer,
    empresa                     text not null,
    analista                    text,
    prioridad                   integer,
    caja_banco                  text,
    mes_septiembre              text,
    mes_octubre                 text,
    mes_noviembre               text,
    mes_diciembre               text,
    mes_enero                   text,
    mes_febrero                 text,
    actualizacion_balance       text,
    reunion_cat1_1              text,
    reunion_cat2                text,
    reunion_cat3                text,
    reunion_cat1_2              text,
    grupo                       text,
    estado_balance_ultimo_mes   text,
    orden                       integer not null default 0,
    created_at                  timestamptz not null default now(),
    updated_at                  timestamptz not null default now()
);

alter table planificacion_at2027 enable row level security;
-- Sin policies a propósito, mismo criterio que el resto de las tablas:
-- solo la service-role key (usada server-side por la app Flask) puede
-- leer o escribir.
