-- Los grupos contables eran GLOBALES (un mismo código de grupo, ej.
-- "1204-01", compartía cuentas entre TODAS las empresas) — el usuario
-- confirmó que deben ser propios de cada empresa (11-09-2026): dos
-- empresas pueden usar el mismo código de grupo pero necesitar cuentas
-- de depreciación distintas.

alter table depreciacion_grupos_contables add column if not exists empresa_id uuid references depreciacion_empresas(id) on delete cascade;

-- Filas de antes de este cambio (sin empresa_id) no tienen a qué empresa
-- pertenecer — se eliminan (no había uso real en producción todavía).
delete from depreciacion_grupos_contables where empresa_id is null;

alter table depreciacion_grupos_contables alter column empresa_id set not null;

alter table depreciacion_grupos_contables drop constraint if exists depreciacion_grupos_contables_pkey;
alter table depreciacion_grupos_contables add primary key (empresa_id, codigo);

create index if not exists depreciacion_grupos_contables_empresa_id_idx on depreciacion_grupos_contables(empresa_id);
