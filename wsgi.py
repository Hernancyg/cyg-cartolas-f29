"""
Punto de entrada WSGI. En Render, el Start Command es:

    gunicorn wsgi:app

En local, con las variables de entorno cargadas desde `.env`
(python-dotenv) o exportadas manualmente:

    flask --app wsgi run --debug
"""

import os

from dotenv import load_dotenv

load_dotenv()  # no falla si no existe .env (producción usa env vars reales)

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=app.config.get("DEBUG", False))
