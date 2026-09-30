"""Adaptadores de repositorio sobre el paquete de datos sintéticos en disco."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from ...domain.model import QuoteRequest


class JsonQuoteRequestRepository:
    """Lee `quote_requests.json`.

    Carga una vez y cachea: el paquete de datos es estático y son 6 registros.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._cache: dict[str, QuoteRequest] | None = None

    def _load(self) -> dict[str, QuoteRequest]:
        if self._cache is None:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._cache = {
                item["case_id"]: QuoteRequest(
                    case_id=item["case_id"],
                    requested_name=item["requested_name"],
                    # str() antes de Decimal: pasar por float perdería precisión
                    # justo en los datos monetarios que hay que verificar.
                    requested_coverage=Decimal(str(item["requested_coverage"])),
                    ui_premium=Decimal(str(item["ui_premium"])),
                )
                for item in raw
            }
        return self._cache

    def list_all(self) -> list[QuoteRequest]:
        return list(self._load().values())

    def get(self, case_id: str) -> QuoteRequest | None:
        return self._load().get(case_id)


class FilesystemCarrierDocumentRepository:
    """Los documentos del carrier, como `<case_id>.pdf` en un directorio."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def document_id_for(self, case_id: str) -> str:
        return f"{case_id}.pdf"

    def _path_for(self, case_id: str) -> Path:
        # Resolvemos y comprobamos que siga dentro del directorio: `case_id`
        # llega desde la URL y `../` no debe poder salirse.
        candidate = (self._directory / self.document_id_for(case_id)).resolve()
        if not candidate.is_relative_to(self._directory.resolve()):
            raise ValueError(f"case_id inválido: {case_id!r}")
        return candidate

    def get_bytes(self, case_id: str) -> bytes | None:
        try:
            path = self._path_for(case_id)
        except ValueError:
            return None
        if not path.is_file():
            return None
        return path.read_bytes()
