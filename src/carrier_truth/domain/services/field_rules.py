"""Extracción de campos: de texto con coordenadas a candidatos con procedencia.

Cada regla es explícita, versionada por `rule_id` y devuelve *siempre* la
evidencia junto al valor. No existe forma de obtener un valor de este módulo
sin saber de qué línea salió: es una decisión de diseño, no una convención.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ..model import (
    Cadence,
    Evidence,
    ExtractedDocument,
    Money,
    Premium,
)

# Montos tipo $1,234.56 — el grupo captura el número sin el signo.
_AMOUNT = r"\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"

_CADENCE_WORDS = {
    "MONTHLY": Cadence.MONTHLY,
    "QUARTERLY": Cadence.QUARTERLY,
    "SEMIANNUAL": Cadence.SEMIANNUAL,
    "SEMI-ANNUAL": Cadence.SEMIANNUAL,
    "ANNUAL": Cadence.ANNUAL,
    "ANNUALLY": Cadence.ANNUAL,
    "YEARLY": Cadence.ANNUAL,
}


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None


@dataclass(frozen=True, slots=True)
class TextFinding:
    """Un valor crudo localizado en el documento."""

    raw: str
    label: str
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class PremiumFinding:
    premium: Premium
    label: str
    evidence: Evidence
    cadence_declared: bool


def _scan(
    document: ExtractedDocument,
    pattern: re.Pattern[str],
    rule_id: str,
    group: int = 1,
) -> list[TextFinding]:
    """Recorre el documento línea por línea y devuelve cada coincidencia con su
    posición exacta."""
    findings: list[TextFinding] = []
    for page_number, line in document.iter_lines():
        match = pattern.search(line.text)
        if not match:
            continue
        findings.append(
            TextFinding(
                raw=match.group(group).strip(),
                label=(match.groupdict().get("label") or "").strip()
                or match.group(0).split(":")[0].strip(),
                evidence=Evidence(
                    document_id=document.document_id,
                    page=page_number,
                    line=line.number,
                    char_span=(match.start(group), match.end(group)),
                    snippet=line.text,
                    rule_id=rule_id,
                ),
            )
        )
    return findings


# --------------------------------------------------------------------------
# Reglas por campo
# --------------------------------------------------------------------------

_APPLICANT = re.compile(r"Applicant\s*:\s*(.+?)\s*$", re.IGNORECASE)
_CARRIER = re.compile(r"Carrier\s*:\s*(.+?)\s*$", re.IGNORECASE)
_FACE_AMOUNT = re.compile(
    rf"Face\s+Amount\s*:\s*{_AMOUNT}", re.IGNORECASE
)
_PREMIUM = re.compile(
    rf"(?P<label>[^:\n]*?Premium[^:\n]*?)\s*:\s*{_AMOUNT}"
    rf"(?:\s+(?P<cadence>MONTHLY|QUARTERLY|SEMI-?ANNUAL|ANNUALLY|ANNUAL|YEARLY))?",
    re.IGNORECASE,
)

RULE_APPLICANT = "applicant_v1"
RULE_CARRIER = "carrier_v1"
RULE_FACE_AMOUNT = "face_amount_v1"
RULE_PREMIUM = "premium_v1"

# Nombres que un carrier deja en plantilla y que NO identifican a nadie.
PLACEHOLDER_NAMES = frozenset(
    {
        "client",
        "insured",
        "applicant",
        "n/a",
        "na",
        "tbd",
        "unknown",
        "sample",
        "specimen",
        "john doe",
        "jane doe",
        "test",
        "-",
        "--",
    }
)

# La etiqueta que el carrier usa para la prima contractual. Si un documento
# ofrece varias primas, esta es la que manda (ver C005: base vs rider).
CANONICAL_PREMIUM_LABEL = "premium"
BASE_PREMIUM_LABEL = "base premium"


def find_applicant(document: ExtractedDocument) -> TextFinding | None:
    findings = _scan(document, _APPLICANT, RULE_APPLICANT)
    return findings[0] if findings else None


def find_carrier(document: ExtractedDocument) -> TextFinding | None:
    findings = _scan(document, _CARRIER, RULE_CARRIER)
    return findings[0] if findings else None


def find_face_amount(
    document: ExtractedDocument,
) -> tuple[Money, Evidence] | None:
    findings = _scan(document, _FACE_AMOUNT, RULE_FACE_AMOUNT)
    if not findings:
        return None
    amount = _to_decimal(findings[0].raw)
    if amount is None:
        return None
    return Money(amount), findings[0].evidence


def find_premiums(document: ExtractedDocument) -> list[PremiumFinding]:
    """Devuelve *todas* las primas del documento. Resolver la ambigüedad no es
    tarea de la extracción sino de la reconciliación."""
    results: list[PremiumFinding] = []
    for page_number, line in document.iter_lines():
        for match in _PREMIUM.finditer(line.text):
            amount = _to_decimal(match.group(2))
            if amount is None:
                continue
            word = (match.group("cadence") or "").upper()
            cadence = _CADENCE_WORDS.get(word, Cadence.UNKNOWN)
            results.append(
                PremiumFinding(
                    premium=Premium(Money(amount), cadence),
                    label=match.group("label").strip(),
                    evidence=Evidence(
                        document_id=document.document_id,
                        page=page_number,
                        line=line.number,
                        char_span=(match.start(2), match.end(2)),
                        snippet=line.text,
                        rule_id=RULE_PREMIUM,
                    ),
                    cadence_declared=bool(word),
                )
            )
    return results


def is_placeholder_name(name: str) -> bool:
    return name.strip().lower() in PLACEHOLDER_NAMES


def normalize_name(name: str) -> str:
    """Normaliza para comparar: sin acentos, sin puntuación, sin dobles
    espacios, en minúsculas. 'José  Pérez-Gómez' == 'jose perez gomez'."""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", ascii_only)
    return re.sub(r"\s+", " ", cleaned).strip().lower()
