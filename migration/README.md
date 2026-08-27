# Migración de datos a Supabase

Estos archivos migran `usuarios.json` y `cuentas_config.json` (de la app de
Streamlit) a las tablas de Supabase que usa la nueva app Flask. No requieren
que nadie —ni Claude, ni nadie más que tú— ingrese la clave de Supabase en
ningún lado: todo se hace pegando SQL directamente en el editor de Supabase.

**`002_seed_data.sql` NO está en este repositorio a propósito**: contiene el
usuario y el hash de la contraseña (salt + PBKDF2, no la contraseña en texto
plano, pero de todas formas es un dato de tus 15 trabajadores) de cada
cuenta existente. Como este repo es **público**, ese archivo se entregó
aparte directamente en la conversación — búscalo ahí, pégalo una vez en
Supabase y luego bórralo de donde lo hayas guardado. Si lo necesitas de
nuevo, pídeselo a Claude — no lo subas a este repositorio.

## Pasos

1. Crea un proyecto nuevo en [supabase.com](https://supabase.com) (o usa uno
   existente, si prefieres no crear uno separado del piloto de
   `cyg-flask-pilot`).
2. Ve a **SQL Editor → New query**.
3. Pega el contenido completo de `001_schema.sql` y presiona **Run**. Esto
   crea las tablas `usuarios` y `cuentas_config`, con RLS activado y sin
   policies (solo la service-role key podrá leer/escribir).
4. En una nueva query, pega el contenido completo de `002_seed_data.sql`
   (el archivo que Claude te entregó aparte, no el de este repo — ver nota
   arriba) y presiona **Run**. Esto inserta los 15 usuarios y las 9 cuentas
   contables ya configuradas — las contraseñas actuales de cada trabajador
   siguen funcionando exactamente igual (los hashes se copiaron tal cual,
   sin volver a calcularlos).
5. Ve a **Project Settings → API** y copia:
   - **Project URL** → esto es `SUPABASE_URL`.
   - **service_role** key (⚠️ no la "anon" key) → esto es `SUPABASE_KEY`.

   Guarda esos dos valores para configurarlos tú mismo como variables de
   entorno en Render (ver `../README.md`) — no se los envíes a Claude ni los
   pegues en ningún chat; son la llave maestra de tu base de datos.
