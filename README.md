# C&G Group — Cartolas Bancarias + Centralización F29 (Flask + Supabase)

App web (Flask, sin JavaScript framework) que reúne dos herramientas de
C&G Group detrás de un único inicio de sesión (usuarios + roles):

- **Subir Cartolas**: convierte cartolas bancarias (PDF o Excel) de Banco de
  Chile, BancoEstado, Bci, Santander, Itaú, Scotiabank, Falabella, Security,
  Banco Internacional o Consorcio al formato estándar de la planilla
  "Banco".
- **Generar CSV F29**: extrae los montos de un Formulario 29 (SII) en PDF y
  genera el CSV de comprobantes unificados listo para importar.
- **Administrador** (solo rol admin): configura las cuentas contables
  asociadas a cada código del F29 y administra los usuarios de la app —
  todo directo contra Supabase, sin descargar/subir JSON a GitHub.

Es la migración de la app de Streamlit (`cartolas-bancarias`) a una stack
propia (Flask + Supabase + Render), para poder controlar el HTML/CSS al
100% y lograr el diseño exacto del mockup del cliente.

## Correr en local

1. `pip install -r requirements.txt`
2. Sigue `migration/README.md` para crear las tablas en Supabase y migrar
   los datos existentes.
3. Copia `.env.example` a `.env` y completa `SUPABASE_URL`, `SUPABASE_KEY`,
   `ADMIN_PASSWORD` y `FLASK_SECRET_KEY` (ver `.env.example` para el detalle
   de cada una — nunca subas este archivo a GitHub).
4. `flask --app wsgi run --debug`

## Deploy en Render

1. Crea un nuevo **Web Service** en Render, conectado a este repositorio.
2. **Build Command**: `pip install -r requirements.txt`
3. **Start Command**: `gunicorn wsgi:app`
4. En **Environment**, agrega las mismas 4 variables que en `.env`
   (`SUPABASE_URL`, `SUPABASE_KEY`, `ADMIN_PASSWORD`, `FLASK_SECRET_KEY`) —
   además, `FLASK_DEBUG` no debe estar configurada (o en `0`).

## Estructura del proyecto

```
app/
  auth/        login, logout, hashing de contraseñas (PBKDF2), decoradores
  data/        acceso a Supabase (usuarios, cuentas_config)
  parsers/     lógica de negocio SIN CAMBIOS respecto a la app de Streamlit
               (bank_parsers.py, output_writer.py, f29_parser.py,
               config_manager.py)
  cartolas/    ruta "Subir Cartolas"
  f29/         ruta "Generar CSV F29"
  admin/       ruta "Administrador" (cuentas F29 + usuarios)
  templates/   HTML (Jinja2), estilo pixel-perfect al mockup
  static/      CSS, JS (agregar/quitar filas), logos de banco, íconos
wsgi.py        punto de entrada para gunicorn
migration/     SQL para crear las tablas y migrar los datos existentes
```

## Notas de seguridad

- Las contraseñas se guardan con PBKDF2-HMAC-SHA256 (100.000 iteraciones,
  salt aleatorio por usuario) — igual que en la app de Streamlit.
- La tabla `usuarios` tiene Row Level Security activado y sin policies: solo
  la **service-role key** de Supabase (usada por el servidor, nunca por el
  navegador) puede leer o escribir.
- `ADMIN_PASSWORD` es la llave maestra: siempre permite entrar como
  administrador, incluso si todavía no se ha creado ningún usuario en
  Supabase.
