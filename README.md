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

## Consulta SII (Contribuyente + RCV)

La pestaña "Consulta SII" (solo admin por defecto, configurable como las
demás) tiene tres sub-pestañas:

- **Contribuyente**: situación tributaria de cualquier RUT (razón social,
  actividades, documentos timbrados, observaciones), vía
  [API Gateway](https://www.apigateway.cl/products/sii/contribuyentes) —
  no requiere las credenciales del contribuyente consultado.
- **RCV**: Registro de Compra y Venta de una empresa cliente, vía
  [SimpleAPI](https://www.simpleapi.cl/Productos/SimpleRCV) — a
  diferencia de lo anterior, sí requiere la clave del SII de esa empresa
  (ver "Empresas SII" más abajo).
- **Empresas SII**: alta/baja de las empresas clientes y su clave del SII,
  guardada siempre cifrada (nunca en texto plano) y solo usada
  server-side para llamar a SimpleAPI.

Para activarla:

1. Crea una cuenta en [apigateway.cl](https://www.apigateway.cl/), copia
   tu token y configúralo como `SII_APIGATEWAY_TOKEN`.
2. Crea una cuenta en [simpleapi.cl](https://www.simpleapi.cl/), copia tu
   apikey y configúrala como `SIMPLEAPI_KEY`.
3. Genera una llave de cifrado propia de esta app (para la clave del SII
   de cada empresa, nunca reutilices una llave de otro sistema):
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   y configúrala como `SII_CREDENTIALS_KEY`.
4. Ejecuta `migration/005_sii_empresas.sql` en Supabase (SQL Editor) para
   crear la tabla `sii_empresas`.
5. Agrega las 3 variables en Render y vuelve a desplegar. Si se dejan
   vacías, cada sub-pestaña muestra un aviso de "falta configurar" en vez
   de romper la app.

**Proxy de API Gateway (opcional, recomendado si el volumen de consultas
crece)**: API Gateway reparte las consultas de todos sus clientes entre
un pool de IPs compartidas — para no depender de eso, se puede levantar
un proxy propio (Docker + Squid, con IP pública propia) y configurarlo en
el panel de apigateway.cl. Ver `proxy/README.md` para el paso a paso
completo; es infraestructura separada de esta app (no se despliega en
Render).

**Nota sobre RCV**: el contrato exacto del endpoint de SimpleAPI
(`app/sii/client.py:SIMPLEAPI_RCV_URL` y el body de `consultar_rcv`) se
armó a partir de su documentación pública, sin poder confirmarlo contra
una cuenta real — revísalo contra `documentacion.simpleapi.cl` (o con su
soporte) apenas tengas acceso, antes de confiar en él en producción.

## Depreciación

La pestaña "Depreciación" (solo admin por defecto, configurable como las
demás) genera la tabla de depreciación **lineal normal** (Art. 31 N°5 LIR)
de los activos fijos de cada empresa cliente, según la vida útil que fija
el SII por tipo de bien.

- **Empresas**: registro propio de esta pestaña (RUT opcional + nombre),
  sin relación con "Empresas SII" de "Consulta SII".
- Dentro de cada empresa: se agregan sus activos fijos (persisten en
  Supabase — quedan disponibles mes a mes, no hay que volver a cargarlos),
  eligiendo una categoría del catálogo SII (autocompleta la vida útil
  sugerida, editable) o ingresando la vida útil a mano. Un activo se
  puede dar de baja (deja de sumarse hacia adelante, pero sigue apareciendo
  en la tabla de los meses ya pasados) o eliminar del todo.
- Dentro de la ficha de un activo: su **kardex de depreciación** — una
  fila por período (normalmente un año) con los "meses utilizados"
  editables a mano (botón "Agregar período" para cerrar cada año, con
  fecha/meses sugeridos que se pueden ajustar libremente). El resto de
  las columnas (costo total, vida útil restante, depreciación del
  ejercicio, acumulada de apertura/cierre, valor libro) se recalculan
  solas al guardar, encadenando cada fila desde la anterior — mismo
  formato que la planilla de referencia que usa el estudio (ver
  `app/depreciacion/calculo.calcular_kardex`, validado fila por fila
  contra un caso real el 11-09-2026). Una "adición" en un período sube el
  costo del activo (y su depreciación mensual) desde esa fila en
  adelante. Descargable en Excel.
- Además, en el detalle de la empresa hay una vista rápida "todos los
  activos en un mes elegido" (independiente del kardex por activo, para
  una foto mensual sin entrar a cada ficha) — mismo cálculo lineal normal,
  sin valor residual, valor libro en $1 una vez agotada la vida útil.
- **Categorías SII**: catálogo editable de "tipo de bien → años de vida
  útil normal", con una semilla tomada de la
  [tabla oficial del SII](https://www.sii.cl/valores_y_fechas/tabla_vida_util_activo_inmovilizado.html)
  (Resolución N°43 de 2002) — se incluyeron las secciones de uso más común
  (activos genéricos, construcción, transporte terrestre, agricultura,
  otras) y se dejaron fuera las muy específicas de industrias reguladas
  grandes (minería, transporte marítimo, sector eléctrico, petróleo y
  gas, telecomunicaciones); se agregan a mano desde esta misma pantalla
  si algún cliente las llegara a necesitar. Ver
  `app/data/depreciacion_categorias_repo.py` para el detalle completo.

Ejecuta `migration/006_depreciacion.sql` y `migration/007_depreciacion_
periodos.sql` en Supabase (SQL Editor) para crear las tablas la primera
vez.

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
  sii/         ruta "Consulta SII" (Contribuyente, RCV, Empresas SII)
  depreciacion/ ruta "Depreciación" (Empresas, Activos, Categorías SII)
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
