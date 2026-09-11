-- Ajuste al kardex (11-09-2026): se saca "Adiciones" (no se va a usar) y
-- se agrega "Factor CCMM" (corrección monetaria) — un factor editable por
-- período que actualiza el costo y la depreciación acumulada de apertura;
-- el valor actualizado de cada fila pasa a ser la base de la fila
-- siguiente (ver app/depreciacion/calculo.calcular_kardex).

alter table depreciacion_periodos drop column if exists adiciones;
alter table depreciacion_periodos add column if not exists factor_ccmm numeric not null default 1;
