"""Adaptador de `DocumentTextExtractor` sobre pypdf.

Único punto del sistema que sabe qué es un PDF. El dominio solo ve
`ExtractedDocument`.
"""

from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ...domain.model import DocumentLine, DocumentPage, ExtractedDocument


class UnreadableDocument(Exception):
    """El archivo no se pudo abrir como PDF."""


#: Firma de un PDF. Comprobarla antes de entregárselo a pypdf da un mensaje de
#: error útil ("esto no es un PDF") en vez de un fallo del parser, y evita
#: gastar trabajo en un archivo que no lo es.
PDF_MAGIC = b"%PDF-"

#: Una ilustración de carrier tiene una o dos páginas. Un PDF de cientos es un
#: error del usuario o un intento de agotar CPU: se rechaza antes de parsear.
MAX_PAGES = 50


class PyPdfTextExtractor:
    """Extrae texto preservando la estructura de página y línea.

    La numeración de páginas y de líneas empieza en 1, porque la evidencia se
    cita para que la lea una persona que va a abrir el PDF y buscar la línea.
    """

    def __init__(self, max_pages: int = MAX_PAGES) -> None:
        self._max_pages = max_pages

    def extract(self, document_id: str, content: bytes) -> ExtractedDocument:
        if not content:
            raise UnreadableDocument("El archivo está vacío.")
        if not content.startswith(PDF_MAGIC):
            raise UnreadableDocument(
                "El archivo no es un PDF: no empieza con la firma %PDF-."
            )

        try:
            reader = PdfReader(io.BytesIO(content))
            page_count = len(reader.pages)
        except (PdfReadError, OSError, ValueError, RecursionError) as exc:
            raise UnreadableDocument(str(exc)) from exc

        if reader.is_encrypted:
            raise UnreadableDocument(
                "El PDF está cifrado: no se puede leer su texto para citarlo."
            )
        if page_count == 0:
            raise UnreadableDocument("El PDF no tiene páginas.")
        if page_count > self._max_pages:
            raise UnreadableDocument(
                f"El PDF tiene {page_count} páginas y el máximo es "
                f"{self._max_pages}. Una ilustración de carrier tiene una o dos."
            )

        pages: list[DocumentPage] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # pypdf lanza de todo ante PDFs corruptos
                raise UnreadableDocument(
                    f"No se pudo extraer texto de la página {index}: {exc}"
                ) from exc
            lines = tuple(
                DocumentLine(number=n, text=raw.rstrip())
                for n, raw in enumerate(text.splitlines(), start=1)
                if raw.strip()
            )
            pages.append(DocumentPage(number=index, lines=lines))

        return ExtractedDocument(document_id=document_id, pages=tuple(pages))
