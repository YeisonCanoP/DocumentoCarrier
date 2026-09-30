# Multi-etapa sin dependencias de sistema.
#
# Decisión: la extracción es `pypdf` puro (nada de poppler ni tesseract), así que
# la imagen es slim y el build no depende de apt. Eso es lo que hace que
# `docker compose up --build` sea reproducible en cualquier máquina.
#
# Dos etapas finales:
#   runtime  → lo que se despliega. Sin pytest ni httpx.
#   testing  → añade las dependencias de desarrollo y los tests, para poder
#              demostrar la reproducibilidad dentro del contenedor.
# La imagen de producción no debe cargar con el instrumental de pruebas, y los
# tests no sirven de nada si corren contra un entorno distinto al que se
# despliega: las etapas comparten `base`, así que verifican lo mismo que corre.

# --------------------------------------------------------------------------
FROM python:3.13-slim AS base

# uv resuelve desde uv.lock, así que la imagen instala exactamente las mismas
# versiones que se probaron en local. Reproducibilidad, no "la última que haya".
COPY --from=ghcr.io/astral-sh/uv:0.11.20 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    CARRIER_DATA_DIR=/app/datos_prueba/carrier-truth

WORKDIR /app

# Capa de dependencias separada del código: cambiar una línea de Python no
# invalida la instalación de paquetes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY src/ ./src/
RUN uv sync --locked --no-dev

# Los datos sintéticos viajan en la imagen para que la demo arranque sin montar
# nada. `docker compose` los sobreescribe con un bind mount de solo lectura.
COPY datos_prueba/ ./datos_prueba/

# Usuario sin privilegios: la app solo necesita leer.
RUN useradd --create-home --uid 10001 carrier && chown -R carrier:carrier /app

# --------------------------------------------------------------------------
FROM base AS runtime

USER carrier
EXPOSE 8000

# El healthcheck consulta /api/health, que reporta si encontró el paquete de
# datos: un contenedor arriba pero con los datos ausentes debe verse como
# degradado, no como sano.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "carrier_truth.adapters.inbound.http.app:app", \
     "--host", "0.0.0.0", "--port", "8000"]

# --------------------------------------------------------------------------
FROM base AS testing

# Ahora sí las dependencias de desarrollo (pytest, httpx).
RUN uv sync --locked

COPY tests/ ./tests/
RUN chown -R carrier:carrier /app

USER carrier
# Sin `-q`: `pyproject.toml` ya lo pone en addopts, y sumar dos lo vuelve `-qq`,
# que esconde la línea del total. Ese total es lo que hay que poder mostrar.
CMD ["python", "-m", "pytest", "/app/tests", "--no-header"]
