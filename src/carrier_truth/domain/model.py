"""Modelo del dominio: vocabulario de la verificación.

Este módulo no importa nada fuera de la librería estándar. Es deliberado: el
núcleo debe poder razonarse y testearse sin PDFs, sin HTTP y sin disco.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


# --------------------------------------------------------------------------
# Value objects
# --------------------------------------------------------------------------


class Cadence(str, Enum):
    """Periodicidad con la que se cobra una prima."""

    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMIANNUAL = "SEMIANNUAL"
    ANNUAL = "ANNUAL"
    UNKNOWN = "UNKNOWN"

    @property
    def periods_per_year(self) -> int | None:
        return {
            Cadence.MONTHLY: 12,
            Cadence.QUARTERLY: 4,
            Cadence.SEMIANNUAL: 2,
            Cadence.ANNUAL: 1,
        }.get(self)

    @property
    def label_es(self) -> str:
        return {
            Cadence.MONTHLY: "mensual",
            Cadence.QUARTERLY: "trimestral",
            Cadence.SEMIANNUAL: "semestral",
            Cadence.ANNUAL: "anual",
            Cadence.UNKNOWN: "periodicidad no declarada",
        }[self]


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str = "USD"

    def __str__(self) -> str:
        return f"${self.amount:,.2f}"


@dataclass(frozen=True, slots=True)
class Premium:
    """Una prima es un monto *más* su periodicidad. Separarlos invita al error
    que este reto pone a prueba en C003 ($720 anual == $60 mensual)."""

    money: Money
    cadence: Cadence

    def to_monthly(self) -> Money | None:
        periods = self.cadence.periods_per_year
        if periods is None:
            return None
        annual = self.money.amount * periods
        return Money(
            (annual / 12).quantize(Decimal("0.01")),
            self.money.currency,
        )

    def __str__(self) -> str:
        return f"{self.money} {self.cadence.label_es}"


# --------------------------------------------------------------------------
# Procedencia
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Evidence:
    """De dónde salió exactamente un dato.

    `char_span` es relativo a `snippet` (la línea completa), no al documento:
    así la evidencia se puede renderizar sola, sin volver a abrir el PDF.
    """

    document_id: str
    page: int
    line: int
    char_span: tuple[int, int]
    snippet: str
    rule_id: str

    @property
    def matched_text(self) -> str:
        start, end = self.char_span
        return self.snippet[start:end]

    @property
    def locator(self) -> str:
        return f"{self.document_id} · pág. {self.page} · línea {self.line} · car. {self.char_span[0]}-{self.char_span[1]}"


# --------------------------------------------------------------------------
# Veredictos
# --------------------------------------------------------------------------


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    VERIFIED_WITH_CAVEAT = "verified_with_caveat"
    UNVERIFIED_CONFLICT = "unverified_conflict"
    UNVERIFIED_IMPLAUSIBLE = "unverified_implausible"
    UNVERIFIED_AMBIGUOUS = "unverified_ambiguous"
    UNVERIFIED_NO_IDENTITY = "unverified_no_identity"
    UNVERIFIED_UNTRUSTED_SOURCE = "unverified_untrusted_source"
    UNVERIFIED_MISSING = "unverified_missing"

    @property
    def is_presentable_as_verified(self) -> bool:
        """La única pregunta que le importa al consumidor: ¿puedo mostrar esto
        como un dato verificado? Cualquier cosa que no sea un sí explícito
        es un no."""
        return self in (
            VerificationStatus.VERIFIED,
            VerificationStatus.VERIFIED_WITH_CAVEAT,
        )


class ReasonCode(str, Enum):
    MATCHES_REQUEST = "matches_request"
    NORMALIZED_CADENCE = "normalized_cadence"
    CONFLICTS_WITH_REQUEST = "conflicts_with_request"
    IMPLAUSIBLE_AMOUNT = "implausible_amount"
    PLACEHOLDER_IDENTITY = "placeholder_identity"
    NAME_MISMATCH = "name_mismatch"
    NON_AUTHORITATIVE_DOCUMENT = "non_authoritative_document"
    MULTIPLE_CANDIDATES = "multiple_candidates"
    CANONICAL_LABEL_SELECTED = "canonical_label_selected"
    DOCUMENT_INTEGRITY_SUSPECT = "document_integrity_suspect"
    FIELD_NOT_FOUND = "field_not_found"
    CADENCE_NOT_DECLARED = "cadence_not_declared"


@dataclass(frozen=True, slots=True)
class Reason:
    code: ReasonCode
    message: str


@dataclass(frozen=True, slots=True)
class Candidate:
    """Un valor que el documento ofrece para un campo, con su etiqueta original.
    Guardamos los descartados para poder explicar por qué ganó otro."""

    label: str
    display_value: str
    evidence: Evidence


@dataclass(slots=True)
class FieldVerdict:
    """El resultado para un campo. Nunca un booleano suelto: valor + estado +
    procedencia + por qué."""

    name: str
    display_value: str | None
    status: VerificationStatus
    evidence: Evidence | None = None
    reasons: list[Reason] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    alternatives: list[Candidate] = field(default_factory=list)
    normalization: str | None = None
    requested_value: str | None = None

    @property
    def is_presentable_as_verified(self) -> bool:
        return self.status.is_presentable_as_verified


class AuthorityLevel(str, Enum):
    AUTHORITATIVE = "authoritative"
    NOT_AUTHORITATIVE = "not_authoritative"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class DocumentAuthority:
    """¿Es este documento una fuente de verdad, o una captura de pantalla con
    membrete? El reto exige distinguirlo (C006)."""

    level: AuthorityLevel
    reasons: list[Reason] = field(default_factory=list)
    evidence: Evidence | None = None

    @property
    def can_ground_money(self) -> bool:
        return self.level is AuthorityLevel.AUTHORITATIVE


class OverallOutcome(str, Enum):
    VERIFIED = "verified"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"
    REQUIRES_AUTHORITATIVE_DOCUMENT = "requires_authoritative_document"


@dataclass(slots=True)
class CaseReport:
    case_id: str
    document_id: str
    authority: DocumentAuthority
    fields: dict[str, FieldVerdict]
    integrity_warnings: list[Reason] = field(default_factory=list)

    @property
    def outcome(self) -> OverallOutcome:
        if not self.authority.can_ground_money:
            return OverallOutcome.REQUIRES_AUTHORITATIVE_DOCUMENT
        if all(f.is_presentable_as_verified for f in self.fields.values()):
            return OverallOutcome.VERIFIED
        return OverallOutcome.REQUIRES_HUMAN_REVIEW

    @property
    def unverified_fields(self) -> list[str]:
        return [
            name
            for name, verdict in self.fields.items()
            if not verdict.is_presentable_as_verified
        ]


# --------------------------------------------------------------------------
# Entrada
# --------------------------------------------------------------------------


class InvalidQuoteRequest(ValueError):
    """La solicitud de cotización no es representable."""


#: Topes de sanidad. No son reglas de negocio de la aseguradora: son el límite
#: entre "una cifra" y "un dato corrupto o un intento de abuso".
MAX_REPRESENTABLE_COVERAGE = Decimal("1000000000")  # mil millones
MAX_REPRESENTABLE_PREMIUM = Decimal("1000000")
MAX_NAME_LENGTH = 200


@dataclass(frozen=True, slots=True)
class QuoteRequest:
    """Lo que el cliente pidió y lo que la interfaz mostró. Ninguno de los dos
    es fuente de verdad: son la hipótesis que el documento confirma o rompe.

    Valida en construcción: un `QuoteRequest` que exista es un `QuoteRequest`
    comparable. Así el motor de reconciliación no tiene que defenderse de NaN
    ni de negativos, y no hay forma de colar basura saltándose la capa HTTP.
    """

    case_id: str
    requested_name: str
    requested_coverage: Decimal
    ui_premium: Decimal

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise InvalidQuoteRequest("case_id no puede estar vacío.")
        if not self.requested_name.strip():
            raise InvalidQuoteRequest("requested_name no puede estar vacío.")
        if len(self.requested_name) > MAX_NAME_LENGTH:
            raise InvalidQuoteRequest(
                f"requested_name excede {MAX_NAME_LENGTH} caracteres."
            )
        _validate_money(
            self.requested_coverage,
            "requested_coverage",
            MAX_REPRESENTABLE_COVERAGE,
        )
        _validate_money(
            self.ui_premium, "ui_premium", MAX_REPRESENTABLE_PREMIUM
        )


def _validate_money(value: Decimal, name: str, maximum: Decimal) -> None:
    """Rechaza lo que `Decimal` acepta pero el dominio no puede comparar.

    `Decimal("NaN")` y `Decimal("Infinity")` se construyen sin error, y NaN
    rompe toda comparación en silencio: `Decimal("NaN") > 0` es False y
    `abs(NaN - x) > tolerancia` también, así que un NaN se colaría como
    «coincide» en vez de fallar. Se ataja aquí, en la frontera del dominio.
    """
    if not isinstance(value, Decimal):
        raise InvalidQuoteRequest(f"{name} debe ser Decimal, no {type(value).__name__}.")
    if value.is_nan():
        raise InvalidQuoteRequest(f"{name} no puede ser NaN.")
    if value.is_infinite():
        raise InvalidQuoteRequest(f"{name} no puede ser infinito.")
    if value <= 0:
        raise InvalidQuoteRequest(f"{name} debe ser mayor que cero, no {value}.")
    if value > maximum:
        raise InvalidQuoteRequest(f"{name} excede el máximo representable ({maximum}).")


@dataclass(frozen=True, slots=True)
class DocumentLine:
    number: int
    text: str


@dataclass(frozen=True, slots=True)
class DocumentPage:
    number: int
    lines: tuple[DocumentLine, ...]


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    """Texto de un PDF preservando la estructura de página/línea, porque la
    procedencia se cita en esas coordenadas."""

    document_id: str
    pages: tuple[DocumentPage, ...]

    def iter_lines(self):
        for page in self.pages:
            for line in page.lines:
                yield page.number, line

    @property
    def full_text(self) -> str:
        return "\n".join(
            line.text for _, line in self.iter_lines()
        )
