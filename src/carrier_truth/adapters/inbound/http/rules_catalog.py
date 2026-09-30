"""Catálogo de reglas: el motor se audita a sí mismo.

Si el sistema exige demostrar de dónde vino cada dato, tiene que poder
demostrar también con qué criterio lo juzgó. Este endpoint expone las reglas
de extracción, los umbrales y el significado de cada estado, leídos **del
código real** y no de una lista escrita a mano que se desincroniza.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ....domain.model import VerificationStatus
from ....domain.services import authority_policy as authority
from ....domain.services import field_rules as rules
from ....domain.services import reconciliation as engine
from .presentation import _NEXT_ACTION, _STATUS


class ExtractionRuleDTO(BaseModel):
    rule_id: str
    field: str
    pattern: str
    description: str


class ThresholdDTO(BaseModel):
    name: str
    value: str
    rationale: str


class StatusDTO(BaseModel):
    status: str
    label: str
    presentable_as_verified: bool
    next_action: str


class RulesCatalogDTO(BaseModel):
    principle: str
    extraction_rules: list[ExtractionRuleDTO]
    authority_vetoes: list[str] = Field(
        description="Frases que descalifican un documento como fuente de verdad."
    )
    authority_qualifier: str
    placeholder_names: list[str]
    thresholds: list[ThresholdDTO]
    statuses: list[StatusDTO]


PRINCIPLE = (
    "La fuente de verdad para dinero y cobertura es el documento del carrier, "
    "nunca el valor solicitado ni el que muestra una interfaz. Un dato solo se "
    "presenta como verificado si existe una razón positiva para hacerlo: la "
    "ambigüedad y el desconocimiento caen del lado de no verificado."
)


def build_catalog() -> RulesCatalogDTO:
    return RulesCatalogDTO(
        principle=PRINCIPLE,
        extraction_rules=[
            ExtractionRuleDTO(
                rule_id=rules.RULE_APPLICANT,
                field="cliente",
                pattern=rules._APPLICANT.pattern,
                description=(
                    "Nombre del solicitante. Se compara con el nombre pedido "
                    "tras normalizar acentos, mayúsculas, puntuación y espacios."
                ),
            ),
            ExtractionRuleDTO(
                rule_id=rules.RULE_CARRIER,
                field="carrier",
                pattern=rules._CARRIER.pattern,
                description=(
                    "Aseguradora emisora. No se contrasta contra nada: el "
                    "documento es la autoridad sobre su propia identidad."
                ),
            ),
            ExtractionRuleDTO(
                rule_id=rules.RULE_FACE_AMOUNT,
                field="cobertura",
                pattern=rules._FACE_AMOUNT.pattern,
                description=(
                    "Face amount. Es la cobertura real, mande lo que mande la "
                    "solicitud. Se somete a chequeos de plausibilidad."
                ),
            ),
            ExtractionRuleDTO(
                rule_id=rules.RULE_PREMIUM,
                field="premium",
                pattern=rules._PREMIUM.pattern,
                description=(
                    "Todas las primas del documento con su periodicidad. La "
                    "prima contractual es la etiquetada «Premium»; el resto se "
                    "reportan como alternativas no contratadas. Si hay varias "
                    "y ninguna es canónica, el sistema se niega a elegir."
                ),
            ),
        ],
        authority_vetoes=[
            pattern.pattern for pattern, _ in authority._DISQUALIFYING
        ],
        authority_qualifier=authority._QUALIFYING.pattern,
        placeholder_names=sorted(rules.PLACEHOLDER_NAMES),
        thresholds=[
            ThresholdDTO(
                name="MIN_PLAUSIBLE_FACE_AMOUNT",
                value=str(engine.MIN_PLAUSIBLE_FACE_AMOUNT),
                rationale=(
                    "Ninguna póliza de vida se emite por debajo de esta cifra. "
                    "Un face amount menor delata un dato truncado o corrupto."
                ),
            ),
            ThresholdDTO(
                name="MIN_COVERAGE_RATIO / MAX_COVERAGE_RATIO",
                value=(
                    f"{engine.MIN_COVERAGE_RATIO} – {engine.MAX_COVERAGE_RATIO}"
                ),
                rationale=(
                    "Rango documento/solicitado admisible. Fuera de él la "
                    "diferencia es demasiado grande para ser un ajuste de "
                    "suscripción."
                ),
            ),
            ThresholdDTO(
                name="DECIMAL_SHIFT_EXPONENTS",
                value=str(list(engine.DECIMAL_SHIFT_EXPONENTS)),
                rationale=(
                    "Un ratio pegado a una potencia de diez delata un dígito "
                    "corrido. Se detecta aparte del rango porque ensanchar el "
                    "rango marcaría como corrupta una reducción legítima de "
                    "suscripción."
                ),
            ),
            ThresholdDTO(
                name="MONEY_TOLERANCE",
                value=str(engine.MONEY_TOLERANCE),
                rationale=(
                    "Tolerancia al comparar dinero, en dólares. Los montos se "
                    "manejan con Decimal, nunca con float."
                ),
            ),
        ],
        statuses=[
            StatusDTO(
                status=status.value,
                label=_STATUS[status][0],
                presentable_as_verified=status.is_presentable_as_verified,
                next_action=_NEXT_ACTION[status],
            )
            for status in VerificationStatus
        ],
    )
