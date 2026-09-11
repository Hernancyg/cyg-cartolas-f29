-- Los grupos contables eran GLOBALES (un mismo código de grupo, ej.
-- "1204-01", compartía cuentas entre TODAS las empresas) — el usuario
-- confirmó que deben ser propios de cada empresa (11-09-2026): dos
-- empresas pueden usar el mismo código de grupo pero necesitar cuentas
-- de depreciación distintas.
--
-- A diferencia de la primera versión de este archivo, esta sí preserva
-- los datos reales que ya existían (un activo real quedó apuntando a un
-- grupo antes de este cambio) — el empresa_id de cada grupo existente se
-- rellena a partir de CUALQUIER activo que ya lo esté usando.

-- 1) La FK vieja (solo por código) hay que sacarla antes de poder
--    cambiar la llave primaria de la tabla que referencia.
alter table depreciacion_activos drop constraint if exists depreciacion_activos_grupo_contable_codigo_fkey;

-- 2) Nueva columna.
alter table depreciacion_grupos_contables add column if not exists empresa_id uuid references depreciacion_empresas(id) on delete cascade;

-- 3) Rellena el empresa_id de cada grupo existente a partir de cualquier
--    activo real que ya lo tenga asignado (antes de este cambio, un
--    mismo código de grupo solo podía significar una empresa a la vez
--    en la práctica, aunque la tabla no lo obligara).
update depreciacion_grupos_contables g
set empresa_id = sub.empresa_id
from (
    select distinct on (grupo_contable_codigo) grupo_contable_codigo, empresa_id
    from depreciacion_activos
    where grupo_contable_codigo is not null
    order by grupo_contable_codigo, created_at
) sub
where g.codigo = sub.grupo_contable_codigo and g.empresa_id is null;

-- 4) Un grupo que a esta altura siga sin empresa_id es uno que ningún
--    activo real está usando todavía — no hay de dónde inferir a qué
--    empresa pertenece, así que se elimina (se puede volver a crear
--    desde la empresa correspondiente).
delete from depreciacion_grupos_contables where empresa_id is null;

alter table depreciacion_grupos_contables alter column empresa_id set not null;

alter table depreciacion_grupos_contables drop constraint if exists depreciacion_grupos_contables_pkey;
alter table depreciacion_grupos_contables add primary key (empresa_id, codigo);

create index if not exists depreciacion_grupos_contables_empresa_id_idx on depreciacion_grupos_contables(empresa_id);

-- 5) FK compuesta nueva: el grupo de un activo tiene que ser de la MISMA
--    empresa que el activo (no de cualquier empresa). Con
--    grupo_contable_codigo en NULL (activo sin grupo todavía) Postgres
--    no exige la restricción, así que sigue permitido dejarlo vacío.
alter table depreciacion_activos add constraint depreciacion_activos_grupo_fkey
    foreign key (empresa_id, grupo_contable_codigo) references depreciacion_grupos_contables(empresa_id, codigo) on delete set null;
