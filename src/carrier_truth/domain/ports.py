"""Puertos: los contratos que el dominio le exige al mundo exterior.

Se declaran como `Protocol` (structural typing) para que los adaptadores no
tengan que heredar de nada del dominio. La dependencia apunta hacia adentro.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import ExtractedDocument, QuoteRequest


@runtime_checkable
class DocumentTextExtractor(Protocol):
    """Convierte los bytes de un documento en texto con coordenadas.

    Hoy lo implementa pypdf. Mañana podría ser un OCR o un servicio de
    document AI, y el motor de reconciliación no cambia una línea.
    """

    def extract(self, document_id: str, content: bytes) -> ExtractedDocument: ...


@runtime_checkable
class QuoteRequestRepository(Protocol):
    """Las solicitudes de cotización (lo pedido + lo que mostró la UI)."""

    def list_all(self) -> list[QuoteRequest]: ...

    def get(self, case_id: str) -> QuoteRequest | None: ...


@runtime_checkable
class CarrierDocumentRepository(Protocol):
    """Los documentos del carrier, sin interpretar."""

    def get_bytes(self, case_id: str) -> bytes | None: ...

    def document_id_for(self, case_id: str) -> str: ...
