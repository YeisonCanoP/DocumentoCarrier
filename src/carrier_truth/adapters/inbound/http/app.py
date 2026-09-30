"""Fábrica de la aplicación FastAPI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router

STATIC_DIR = Path(__file__).resolve().parent / "static"

DESCRIPTION = """
Extrae **cliente, carrier, cobertura y prima** de ilustraciones de carriers y
demuestra de dónde salió cada dato: documento, página, línea y offset de
caracteres, más la regla versionada que lo extrajo.

La fuente de verdad para dinero y cobertura es **el documento del carrier**,
nunca el valor solicitado ni el que muestra una interfaz. Cuando existe una
contradicción importante, el sistema **se niega a presentar el dato como
verificado** y explica qué hace falta para resolverlo.
"""


def create_app() -> FastAPI:
    app = FastAPI(
        title="La Verdad del Documento del Carrier",
        description=DESCRIPTION,
        version="1.0.0",
    )
    app.include_router(router)

    if STATIC_DIR.is_dir():
        app.mount(
            "/static", StaticFiles(directory=STATIC_DIR), name="static"
        )

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
