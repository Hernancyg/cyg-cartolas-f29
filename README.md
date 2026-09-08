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
4. En **Environment**, agrega las mismas variables que en `.env`
   (`SUPABASE_URL`, `SUPABASE_KEY`, `ADMIN_PASSWORD`, `FLASK_SECRET_KEY`) —
   además, `FLASK_DEBUG` no debe estar configurada (o en `0`).
5. Opcional: `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT_ID`, `MS_USER_UPN`
   para la pestaña "Reuniones" — ver sección dedicada más abajo. Si se
   dejan vacías, esa pestaña muestra un aviso de configuración pendiente en
   vez de fallar.

## Reuniones (Microsoft Graph)

La pestaña "Reuniones" (solo visible para el rol admin) lee de verdad el
calendario de Outlook de una casilla fija, vía Microsoft Graph API, sin
login interactivo (flujo *client credentials*: la app entra "como sí
misma"). Para activarla:

1. Entra a [portal.azure.com](https://portal.azure.com) → **Microsoft Entra
   ID** → **Registros de aplicaciones** → **Nuevo registro**. Dale un nombre
   (p. ej. "CyG Cartolas - Reuniones") y deja el resto por defecto.
2. Copia de la pantalla de "Introducción": **Id. de aplicación (cliente)**
   → `MS_CLIENT_ID`, y **Id. de directorio (inquilino)** → `MS_TENANT_ID`.
3. **Certificados y secretos** → **Nuevo secreto de cliente** → copia el
   **valor** (no el Id.) apenas se genera, no se vuelve a mostrar →
   `MS_CLIENT_SECRET`.
4. **Permisos de API** → **Agregar un permiso** → **Microsoft Graph** →
   **Permisos de aplicación** (no "delegados") → busca `Calendars.Read` →
   agrégalo.
5. En esa misma pantalla, botón **"Conceder consentimiento de
   administrador para \<tu organización\>"** — sin este paso el permiso
   queda pedido pero no autorizado, y la API va a rechazar las
   solicitudes. Necesitas ser administrador global (o que alguien que lo
   sea haga este clic).
6. `MS_USER_UPN` es el correo de la casilla de Outlook cuyo calendario se
   va a leer (por ejemplo `hhernandez@cyggroup.cl`) — tiene que ser una
   casilla real del mismo tenant de Microsoft 365.
7. Agrega las 4 variables en Render (Environment) y vuelve a desplegar.

Los enlaces de Zoom se extraen automáticamente del cuerpo de la invitación
(cuando el organizador pega el link de Zoom en la descripción de la
reunión); los enlaces de Teams vienen directo del campo `onlineMeeting`
de Graph cuando la reunión se creó como "Teams meeting" desde Outlook.

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
