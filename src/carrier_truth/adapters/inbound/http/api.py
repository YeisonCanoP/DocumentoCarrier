"""Adaptador HTTP entrante. Traduce peticiones a casos de uso y veredictos a DTOs.

No hay una sola regla de negocio en este archivo. Si hiciera falta añadir un
criterio de verificación, no es aquí.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ....application.use_cases import CaseNotFound, DocumentNotFound
from ....composition import Container, get_container
from ....domain.model import InvalidQuoteRequest
from ...outbound.pypdf_extractor import UnreadableDocument
from ..http.presentation import CaseReportDTO, to_dto
from ..http.rules_catalog import RulesCatalogDTO, build_catalog

router = APIRouter(prefix="/api", tags=["verificación"])

ContainerDep = Annotated[Container, Depends(get_container)]

#: Tope defensivo para la subida. Una ilustración son kilobytes; megabytes
#: significa que alguien se equivocó de archivo o está probando el límite.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: Un `case_id` viaja en la URL y se convierte en nombre de archivo. Solo
#: alfanumérico, guion y guion bajo: ni separadores de ruta ni `..`.
CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _parse_money(raw: str, field: str) -> Decimal:
    """Convierte texto a `Decimal` rechazando lo que `Decimal` sí acepta.

    `Decimal("nan")` y `Decimal("inf")` se construyen sin error. Un NaN es
    especialmente peligroso porque *toda* comparación con él es False, así que
    se colaría silenciosamente por las validaciones ingenuas y por la
    comparación de tolerancia del motor.
    """
    texto = raw.replace(",", "").replace("$", "").strip()
    if not texto:
        raise HTTPException(422, f"{field} no puede estar vacío.")
    try:
        value = Decimal(texto)
    except InvalidOperation:
        raise HTTPException(
            422, f"{field} no es un número válido: {raw!r}."
        ) from None
    if not value.is_finite():
        raise HTTPException(
            422, f"{field} debe ser un número finito, no {texto!r}."
        )
    return value


@router.get("/health", summary="Sonda de vida para Docker")
def health(container: ContainerDep) -> dict[str, object]:
    data_ok = container.settings.quote_requests_path.is_file()
    return {
        "status": "ok" if data_ok else "degraded",
        "data_dir": str(container.settings.data_dir),
        "quote_requests_found": data_ok,
    }


@router.get(
    "/cases",
    response_model=list[CaseReportDTO],
    summary="Verifica todos los casos del paquete de datos",
)
def list_cases(container: ContainerDep) -> list[CaseReportDTO]:
    return [to_dto(report) for report in container.verify_all_cases()]


@router.get(
    "/rules",
    response_model=RulesCatalogDTO,
    summary="Reglas, umbrales y estados que aplica el motor",
)
def get_rules() -> RulesCatalogDTO:
    """El motor se audita a sí mismo.

    Si exigimos demostrar de dónde vino cada dato, también hay que poder
    demostrar con qué criterio se juzgó. Se lee del código real, así que no
    puede desincronizarse de lo que de verdad se ejecuta.
    """
    return build_catalog()


@router.get(
    "/cases/{case_id}",
    response_model=CaseReportDTO,
    summary="Verifica un caso y devuelve la procedencia de cada dato",
)
def get_case(case_id: str, container: ContainerDep) -> CaseReportDTO:
    # El case_id termina como nombre de archivo: se valida su forma antes de
    # que llegue al repositorio, que además comprueba que no salga del
    # directorio. Dos barreras, porque una se puede olvidar al refactorizar.
    if not CASE_ID_PATTERN.match(case_id):
        raise HTTPException(
            422,
            "case_id inválido: solo se admiten letras, dígitos, guion y guion "
            "bajo, hasta 32 caracteres.",
        )
    try:
        return to_dto(container.verify_case(case_id))
    except CaseNotFound:
        raise HTTPException(404, f"No existe la solicitud {case_id!r}.") from None
    except DocumentNotFound:
        raise HTTPException(
            404, f"No hay documento del carrier para {case_id!r}."
        ) from None
    except UnreadableDocument as exc:
        raise HTTPException(422, f"El documento no se pudo leer: {exc}") from None


@router.post(
    "/verify",
    response_model=CaseReportDTO,
    summary="Verifica un PDF arbitrario contra los valores que se le indiquen",
)
async def verify_upload(
    container: ContainerDep,
    document: Annotated[UploadFile, File(description="Ilustración en PDF")],
    requested_name: Annotated[str, Form()],
    requested_coverage: Annotated[str, Form()],
    ui_premium: Annotated[str, Form()],
) -> CaseReportDTO:
    """Existe para demostrar que el motor no está afinado a los 6 casos de
    prueba: acepta cualquier ilustración."""
    # El tamaño se comprueba antes de leer todo en memoria cuando el cliente
    # declara Content-Length; el chequeo de después cubre al que no lo declara.
    if document.size is not None and document.size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"El archivo excede {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    content = await document.read()
    if not content:
        raise HTTPException(422, "El archivo llegó vacío.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"El archivo excede {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    coverage = _parse_money(requested_coverage, "requested_coverage")
    premium = _parse_money(ui_premium, "ui_premium")

    try:
        report = container.verify_upload(
            # El nombre del archivo lo elige el cliente y se refleja en la
            # respuesta: se saneteliza para que no pueda inyectar rutas.
            filename=_safe_filename(document.filename),
            content=content,
            requested_name=requested_name.strip(),
            requested_coverage=coverage,
            ui_premium=premium,
        )
    except UnreadableDocument as exc:
        raise HTTPException(422, f"El documento no se pudo leer: {exc}") from None
    except InvalidQuoteRequest as exc:
        # Las invariantes del dominio se traducen a 422 con su propio mensaje:
        # el dominio ya explicó qué está mal, no hace falta reescribirlo.
        raise HTTPException(422, str(exc)) from None

    return to_dto(report)


def _safe_filename(raw: str | None) -> str:
    """Deja solo el nombre base y caracteres inocuos."""
    if not raw:
        return "documento.pdf"
    base = PurePosixPath(raw.replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    return cleaned[:120] or "documento.pdf"
