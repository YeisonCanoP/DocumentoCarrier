"""Casos de uso: orquestan puertos y delegan todo el criterio al dominio.

Esta capa es deliberadamente delgada. Si aquí apareciera un `if` sobre montos o
sobre la validez de un documento, estaría en el lugar equivocado.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..domain.model import CaseReport, QuoteRequest
from ..domain.ports import (
    CarrierDocumentRepository,
    DocumentTextExtractor,
    QuoteRequestRepository,
)
from ..domain.services.reconciliation import reconcile


class CaseNotFound(Exception):
    """No existe la solicitud de cotización pedida."""


class DocumentNotFound(Exception):
    """Existe la solicitud pero no su documento del carrier."""


@dataclass(frozen=True, slots=True)
class VerifyCase:
    """Verifica un caso del paquete de datos."""

    requests: QuoteRequestRepository
    documents: CarrierDocumentRepository
    extractor: DocumentTextExtractor

    def __call__(self, case_id: str) -> CaseReport:
        request = self.requests.get(case_id)
        if request is None:
            raise CaseNotFound(case_id)

        content = self.documents.get_bytes(case_id)
        if content is None:
            raise DocumentNotFound(case_id)

        document = self.extractor.extract(
            self.documents.document_id_for(case_id), content
        )
        return reconcile(document, request)


@dataclass(frozen=True, slots=True)
class VerifyAllCases:
    verify_case: VerifyCase
    requests: QuoteRequestRepository

    def __call__(self) -> list[CaseReport]:
        reports: list[CaseReport] = []
        for request in self.requests.list_all():
            try:
                reports.append(self.verify_case(request.case_id))
            except DocumentNotFound:
                continue
        return reports


@dataclass(frozen=True, slots=True)
class VerifyUploadedDocument:
    """Verifica un PDF arbitrario contra valores dados a mano.

    Existe para que la demo no dependa del paquete de datos: se puede subir
    cualquier ilustración y ver el veredicto. Es la prueba de que el motor no
    está afinado a los 6 casos de prueba.
    """

    extractor: DocumentTextExtractor

    def __call__(
        self,
        *,
        filename: str,
        content: bytes,
        requested_name: str,
        requested_coverage: Decimal,
        ui_premium: Decimal,
        case_id: str = "UPLOAD",
    ) -> CaseReport:
        document = self.extractor.extract(filename, content)
        request = QuoteRequest(
            case_id=case_id,
            requested_name=requested_name,
            requested_coverage=requested_coverage,
            ui_premium=ui_premium,
        )
        return reconcile(document, request)
