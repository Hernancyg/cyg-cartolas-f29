-- Esquema de Supabase para C&G Group — Cartolas Bancarias + F29.
-- Ejecutar UNA vez en el proyecto Supabase nuevo, en SQL Editor
-- (Supabase Dashboard → SQL Editor → New query → pegar todo → Run).

create extension if not exists pgcrypto;

create table if not exists usuarios (
    id          uuid primary key default gen_random_uuid(),
    usuario     text unique not null,
    nombre      text not null,
    rol         text not null check (rol in ('admin','trabajador')),
    salt        text not null,
    hash        text not null,
    activo      boolean not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create table if not exists cuentas_config (
    id           uuid primary key default gen_random_uuid(),
    codigo_f29   text not null unique,
    cuenta       text not null,
    descripcion  text,
    tipo         text not null check (tipo in ('DEBE','HABER')),
    texto_ancla  text not null,
    operador     text not null default '' check (operador in ('+','-','=','')),
    orden        integer not null default 0,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

alter table usuarios enable row level security;
alter table cuentas_config enable row level security;
-- Sin policies a propósito: solo la service-role key (usada server-side
-- por la app Flask, nunca expuesta al navegador) puede leer/escribir.
-- Si en algún momento se usa la clave "anon" desde el navegador, con RLS
-- activado y sin policies esa clave no podrá leer ni escribir nada.
