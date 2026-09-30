"""Traducción dominio → presentación.

Todo lo que tenga que ver con *cómo se ve* un veredicto vive aquí: etiquetas en
español, severidad para el color del badge, la frase que resume el caso. La UI
no interpreta estados; los pinta. Así un cliente nuevo (otra web, un CRM, un
correo) hereda el mismo lenguaje sin reimplementar el criterio.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ....domain.model import (
    AuthorityLevel,
    Candidate,
    CaseReport,
    DocumentAuthority,
    Evidence,
    FieldVerdict,
    OverallOutcome,
    Reason,
    VerificationStatus,
)

# --------------------------------------------------------------------------
# Vocabulario de presentación
# --------------------------------------------------------------------------

#: estado → (etiqueta, severidad para CSS, si se puede citar como verificado)
_STATUS: dict[VerificationStatus, tuple[str, str]] = {
    VerificationStatus.VERIFIED: ("Verificado", "ok"),
    VerificationStatus.VERIFIED_WITH_CAVEAT: ("Verificado con reserva", "warn"),
    VerificationStatus.UNVERIFIED_CONFLICT: ("Contradicción", "danger"),
    VerificationStatus.UNVERIFIED_IMPLAUSIBLE: ("Dato implausible", "danger"),
    VerificationStatus.UNVERIFIED_AMBIGUOUS: ("Ambiguo", "danger"),
    VerificationStatus.UNVERIFIED_NO_IDENTITY: ("Sin identidad", "danger"),
    VerificationStatus.UNVERIFIED_UNTRUSTED_SOURCE: ("Fuente no válida", "danger"),
    VerificationStatus.UNVERIFIED_MISSING: ("Ausente", "danger"),
}

#: Qué debe hacer una persona ante cada estado. La API no solo dice que algo
#: falló: dice cuál es el siguiente paso.
_NEXT_ACTION: dict[VerificationStatus, str] = {
    VerificationStatus.VERIFIED: "Ninguna acción requerida.",
    VerificationStatus.VERIFIED_WITH_CAVEAT: (
        "Leer la reserva antes de citar la cifra ante el cliente."
    ),
    VerificationStatus.UNVERIFIED_CONFLICT: (
        "Resolver la discrepancia con el carrier antes de cotizar."
    ),
    VerificationStatus.UNVERIFIED_IMPLAUSIBLE: (
        "Solicitar de nuevo el documento: la cifra no puede ser real."
    ),
    VerificationStatus.UNVERIFIED_AMBIGUOUS: (
        "Confirmar con el carrier cuál de los valores aplica."
    ),
    VerificationStatus.UNVERIFIED_NO_IDENTITY: (
        "Solicitar una ilustración nominativa, a nombre del cliente."
    ),
    VerificationStatus.UNVERIFIED_UNTRUSTED_SOURCE: (
        "Solicitar la ilustración emitida por el carrier."
    ),
    VerificationStatus.UNVERIFIED_MISSING: (
        "Solicitar el documento completo al carrier."
    ),
}

_FIELD_LABELS = {
    "cliente": "Cliente",
    "carrier": "Carrier",
    "cobertura": "Cobertura (monto asegurado)",
    "premium": "Prima",
}

#: Orden de presentación, de identidad a dinero.
_FIELD_ORDER = ("cliente", "carrier", "cobertura", "premium")

_OUTCOME: dict[OverallOutcome, tuple[str, str]] = {
    OverallOutcome.VERIFIED: ("Verificado", "ok"),
    OverallOutcome.REQUIRES_HUMAN_REVIEW: ("Requiere revisión humana", "warn"),
    OverallOutcome.REQUIRES_AUTHORITATIVE_DOCUMENT: (
        "Requiere documento del carrier",
        "danger",
    ),
}

_AUTHORITY_LABELS = {
    AuthorityLevel.AUTHORITATIVE: "Ilustración emitida por el carrier",
    AuthorityLevel.NOT_AUTHORITATIVE: "No es un documento emitido por el carrier",
    AuthorityLevel.UNKNOWN: "Tipo de documento no reconocido",
}


# --------------------------------------------------------------------------
# DTOs
# --------------------------------------------------------------------------


class EvidenceDTO(BaseModel):
    """La procedencia, autosuficiente: se puede resaltar sin abrir el PDF."""

    document: str
    page: int
    line: int
    char_span: tuple[int, int]
    snippet: str = Field(description="La línea completa del documento.")
    matched_text: str = Field(description="El fragmento exacto que se extrajo.")
    rule_id: str = Field(description="Regla versionada que lo extrajo.")
    locator: str = Field(description="Cita legible para una persona.")


class ReasonDTO(BaseModel):
    code: str
    message: str


class CandidateDTO(BaseModel):
    label: str
    value: str
    evidence: EvidenceDTO


class FieldDTO(BaseModel):
    field: str
    label: str
    value: str | None
    requested: str | None
    status: str
    status_label: str
    severity: str
    verified: bool = Field(
        description="Si es false, el dato NO debe presentarse como verificado."
    )
    next_action: str
    reasons: list[ReasonDTO]
    caveats: list[str]
    alternatives: list[CandidateDTO]
    normalization: str | None
    evidence: EvidenceDTO | None


class AuthorityDTO(BaseModel):
    level: str
    label: str
    is_authoritative: bool
    reasons: list[ReasonDTO]
    evidence: EvidenceDTO | None


class CaseReportDTO(BaseModel):
    case_id: str
    document: str
    outcome: str
    outcome_label: str
    outcome_severity: str
    outcome_detail: str
    authority: AuthorityDTO
    fields: list[FieldDTO]
    unverified_fields: list[str]
    integrity_warnings: list[ReasonDTO]
    verified_count: int
    total_fields: int


# --------------------------------------------------------------------------
# Mappers
# --------------------------------------------------------------------------


def _evidence(evidence: Evidence | None) -> EvidenceDTO | None:
    if evidence is None:
        return None
    return EvidenceDTO(
        document=evidence.document_id,
        page=evidence.page,
        line=evidence.line,
        char_span=evidence.char_span,
        snippet=evidence.snippet,
        matched_text=evidence.matched_text,
        rule_id=evidence.rule_id,
        locator=evidence.locator,
    )


def _reason(reason: Reason) -> ReasonDTO:
    return ReasonDTO(code=reason.code.value, message=reason.message)


def _candidate(candidate: Candidate) -> CandidateDTO:
    return CandidateDTO(
        label=candidate.label,
        value=candidate.display_value,
        evidence=_evidence(candidate.evidence),  # type: ignore[arg-type]
    )


def _field(verdict: FieldVerdict) -> FieldDTO:
    label, severity = _STATUS[verdict.status]
    return FieldDTO(
        field=verdict.name,
        label=_FIELD_LABELS.get(verdict.name, verdict.name.capitalize()),
        value=verdict.display_value,
        requested=verdict.requested_value,
        status=verdict.status.value,
        status_label=label,
        severity=severity,
        verified=verdict.is_presentable_as_verified,
        next_action=_NEXT_ACTION[verdict.status],
        reasons=[_reason(r) for r in verdict.reasons],
        caveats=list(verdict.caveats),
        alternatives=[_candidate(c) for c in verdict.alternatives],
        normalization=verdict.normalization,
        evidence=_evidence(verdict.evidence),
    )


def _authority(authority: DocumentAuthority) -> AuthorityDTO:
    return AuthorityDTO(
        level=authority.level.value,
        label=_AUTHORITY_LABELS[authority.level],
        is_authoritative=authority.can_ground_money,
        reasons=[_reason(r) for r in authority.reasons],
        evidence=_evidence(authority.evidence),
    )


def _outcome_detail(report: CaseReport) -> str:
    """La frase que resume el caso. Es lo que se lee en el video, así que dice
    qué falta, no solo que algo falló."""
    outcome = report.outcome
    if outcome is OverallOutcome.VERIFIED:
        return (
            f"Los {len(report.fields)} campos están respaldados por la "
            f"ilustración emitida del carrier."
        )
    if outcome is OverallOutcome.REQUIRES_AUTHORITATIVE_DOCUMENT:
        return (
            "Ningún dato se presenta como verificado: la fuente no es una "
            "ilustración emitida por el carrier. Los valores pueden incluso "
            "coincidir con la solicitud, pero coincidir no es verificar."
        )
    pendientes = ", ".join(
        _FIELD_LABELS.get(name, name) for name in report.unverified_fields
    )
    return (
        f"{len(report.unverified_fields)} de {len(report.fields)} campos no se "
        f"pueden presentar como verificados: {pendientes}."
    )


def to_dto(report: CaseReport) -> CaseReportDTO:
    ordered = [
        report.fields[name] for name in _FIELD_ORDER if name in report.fields
    ]
    ordered += [v for k, v in report.fields.items() if k not in _FIELD_ORDER]

    label, severity = _OUTCOME[report.outcome]
    return CaseReportDTO(
        case_id=report.case_id,
        document=report.document_id,
        outcome=report.outcome.value,
        outcome_label=label,
        outcome_severity=severity,
        outcome_detail=_outcome_detail(report),
        authority=_authority(report.authority),
        fields=[_field(v) for v in ordered],
        unverified_fields=[
            _FIELD_LABELS.get(n, n) for n in report.unverified_fields
        ],
        integrity_warnings=[_reason(r) for r in report.integrity_warnings],
        verified_count=sum(
            1 for v in report.fields.values() if v.is_presentable_as_verified
        ),
        total_fields=len(report.fields),
    )
