-- Tema visual por usuario (25-09-2026): paleta que el admin asigna desde
-- Administrador → Usuarios (NULL = el de siempre; 'rosa' = tema Rosa). Es
-- independiente del claro/oscuro, que sigue eligiéndolo cada persona.
-- Ejecutar UNA vez en el proyecto Supabase (SQL Editor → New query →
-- pegar todo → Run), igual que las demás migraciones de esta carpeta.

alter table usuarios add column if not exists tema text;
