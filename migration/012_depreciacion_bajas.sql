-- "Dar de baja" un activo (pérdida total o venta) con utilidad/pérdida y
-- asiento contable automático:
--
--   - depreciacion_config_baja: las 3 cuentas de resultado que hacen
--     falta para el asiento de baja (Caja/Cliente por la venta, Pérdida
--     en Baja, Utilidad en Venta) — una vez POR EMPRESA (son cuentas
--     genéricas, no cambian según el grupo/clase de activo). La cuenta
--     de "Activo Fijo" (el código del grupo contable del activo mismo) y
--     "Depreciación Acumulada" ya se sacan del Grupo Contable del activo
--     (ver depreciacion_grupos_contables).
--   - depreciacion_bajas: el registro histórico de cada baja generada
--     (para consulta/auditoría — no es una "memoria" que bloquee nada,
--     un activo solo se da de baja una vez porque después queda con
--     activo=false y desaparece de los flujos de depreciación).

create table if not exists depreciacion_config_baja (
    empresa_id                 uuid primary key references depreciacion_empresas(id) on delete cascade,
    cuenta_caja_cliente_codigo text,
    cuenta_perdida_codigo      text,
    cuenta_utilidad_codigo     text,
    created_at                 timestamptz not null default now(),
    updated_at                 timestamptz not null default now()
);

create table if not exists depreciacion_bajas (
    id               uuid primary key default gen_random_uuid(),
    activo_id        uuid not null references depreciacion_activos(id) on delete cascade,
    fecha_baja       date not null,
    tipo_baja        text not null check (tipo_baja in ('perdida_total', 'venta')),
    modalidad_venta  text check (modalidad_venta in ('factura', 'contrato')),
    monto_venta      numeric not null default 0,
    valor_actualizado numeric not null,
    deprec_acumulada numeric not null,
    valor_libro      numeric not null,
    resultado        numeric not null,
    created_at       timestamptz not null default now()
);

create index if not exists depreciacion_bajas_activo_id_idx on depreciacion_bajas(activo_id);

alter table depreciacion_config_baja enable row level security;
alter table depreciacion_bajas enable row level security;
-- Sin policies a propósito, mismo criterio que el resto de las tablas.
