"""Wiring: el único lugar donde el dominio se conecta con el mundo real.

Sin framework de inyección de dependencias a propósito. Con cuatro objetos, un
contenedor mágico añade indirección sin resolver nada; una función explícita se
lee de un vistazo y es lo que se muestra en el video.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .adapters.outbound.filesystem import (
    FilesystemCarrierDocumentRepository,
    JsonQuoteRequestRepository,
)
from .adapters.outbound.pypdf_extractor import PyPdfTextExtractor
from .application.use_cases import VerifyAllCases, VerifyCase, VerifyUploadedDocument

#: Raíz por defecto del paquete de datos sintéticos. Se puede sobrescribir con
#: la variable de entorno CARRIER_DATA_DIR, que es como la configura Docker.
DEFAULT_DATA_DIR = (
    Path(__file__).resolve().parents[2] / "datos_prueba" / "carrier-truth"
)


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path

    @property
    def quote_requests_path(self) -> Path:
        return self.data_dir / "quote_requests.json"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @classmethod
    def from_env(cls) -> Settings:
        raw = os.environ.get("CARRIER_DATA_DIR")
        return cls(data_dir=Path(raw).resolve() if raw else DEFAULT_DATA_DIR)


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    verify_case: VerifyCase
    verify_all_cases: VerifyAllCases
    verify_upload: VerifyUploadedDocument


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings.from_env()

    extractor = PyPdfTextExtractor()
    requests = JsonQuoteRequestRepository(settings.quote_requests_path)
    documents = FilesystemCarrierDocumentRepository(settings.documents_dir)

    verify_case = VerifyCase(
        requests=requests, documents=documents, extractor=extractor
    )

    return Container(
        settings=settings,
        verify_case=verify_case,
        verify_all_cases=VerifyAllCases(verify_case=verify_case, requests=requests),
        verify_upload=VerifyUploadedDocument(extractor=extractor),
    )


@cache
def get_container() -> Container:
    """Contenedor por proceso, para que FastAPI lo inyecte como dependencia."""
    return build_container()
