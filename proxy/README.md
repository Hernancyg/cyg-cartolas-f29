# Proxy Squid para API Gateway (SII)

API Gateway (apigateway.cl) reparte sus consultas al SII entre las IPs de
todos sus clientes — si otro cliente hace un volumen muy alto, el SII
puede limitar esa IP y afectar también a esta app. Este proxy hace que
**tus** consultas salgan siempre desde **tu propia IP**, para no depender
de ese pool compartido. Es un servicio separado de esta app Flask: corre
en su propio servidor, con su propia IP pública, y **no** se despliega en
Render.

Referencia oficial: https://www.apigateway.cl/docs/tutoriales/proxy

## 1. Consigue un servidor con IP pública

Cualquier VPS chico sirve — este proxy no necesita CPU/RAM ni ancho de
banda serios. Opciones simples y baratas:

- **[Hetzner Cloud](https://www.hetzner.com/cloud/)** — plan CX22 (~€3.9/mes), buena relación precio/confiabilidad.
- **[DigitalOcean](https://www.digitalocean.com/)** — Droplet básico (~US$6/mes), UI muy simple para partir.
- **Oracle Cloud Free Tier** — tiene una VM gratis "para siempre", pero el proceso de aprovisionamiento es más propenso a errores de "sin capacidad" en algunas regiones.

Elige la imagen **Ubuntu 22.04 o 24.04**.

## 2. Instala Docker en el servidor

```bash
curl -fsSL https://get.docker.com | sh
```

## 3. Copia estos 3 archivos al servidor

`docker-compose.yml` y `squid.conf` (de esta carpeta) van tal cual. Falta
generar `passwords` (NO se sube a git — ver `.gitignore`):

```bash
sudo apt-get install -y apache2-utils   # para el comando htpasswd
htpasswd -c passwords <usuario> <contraseña-de-al-menos-12-caracteres>
```

Estructura final en el servidor:

```
proxy/
  docker-compose.yml
  squid.conf
  passwords   <- generado en el paso anterior, nunca en git
```

## 4. Levanta el proxy

```bash
docker compose up -d
docker compose ps        # debe mostrar squid "Up"
docker compose logs squid # si algo falla, revisar acá
```

## 5. Abre el puerto 3128 en el firewall del servidor

```bash
sudo ufw allow 3128/tcp
```

(o el equivalente en el panel del proveedor — Hetzner/DigitalOcean suelen
tener su propio firewall de red además del del sistema operativo).

## 6. Configura la URL del proxy en API Gateway

En el panel de tu cuenta de apigateway.cl, ingresa:

```
http://<usuario>:<contraseña>@<ip_publica_del_servidor>:3128
```

## Notas de seguridad

- `squid.conf` ya restringe el proxy a los dominios `.sii.cl`,
  `.amazonaws.com` (eBoleta) y `.previred.com` — aunque alguien obtenga
  las credenciales, no puede usarlo como proxy abierto para navegar a
  cualquier sitio, solo a esos tres dominios.
- Aun así, usa una contraseña larga y aleatoria (no la reutilices de
  otro sistema) — es lo único que protege el acceso.
- El archivo `passwords` contiene el hash de esa contraseña: nunca lo
  subas a git (ya está en `.gitignore`).
- Esta app Flask (`cyg-cartolas-f29`) **no necesita saber nada de este
  proxy** — la URL del proxy se configura del lado de apigateway.cl, no
  en `SII_APIGATEWAY_TOKEN` ni en ninguna variable de este repo.
