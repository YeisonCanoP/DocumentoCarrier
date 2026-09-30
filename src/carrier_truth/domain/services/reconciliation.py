"""El motor: convierte un documento + una solicitud en veredictos con procedencia.

Tres invariantes gobiernan todo este módulo.

1. El documento del carrier es la fuente de verdad para dinero y cobertura.
   La solicitud y la UI son hipótesis, no evidencia.
2. Un dato solo se presenta como verificado si hay una razón *positiva* para
   hacerlo. El silencio, la ambigüedad y el "no sé" caen del lado de no
   verificado.
3. Coincidir no es verificar. Si la fuente no es válida, dos números iguales
   siguen sin estar verificados (C006).
"""

from __future__ import annotations

from decimal import Decimal

from ..model import (
    Candidate,
    CaseReport,
    DocumentAuthority,
    ExtractedDocument,
    FieldVerdict,
    Money,
    QuoteRequest,
    Reason,
    ReasonCode,
    VerificationStatus,
)
from . import field_rules as rules
from .authority_policy import assess_authority

# --------------------------------------------------------------------------
# Umbrales. Explícitos y con nombre, para poder discutirlos en una revisión.
# --------------------------------------------------------------------------

#: Ninguna póliza de vida real se emite por debajo de esto. Un face amount
#: menor delata un dato truncado o corrupto, no una póliza barata.
MIN_PLAUSIBLE_FACE_AMOUNT = Decimal("10000")

#: Si el documento y lo solicitado difieren por más de este factor, no es un
#: ajuste de suscripción: es otro dato. Atrapa dígitos perdidos (C001).
MAX_COVERAGE_RATIO = Decimal("20")
MIN_COVERAGE_RATIO = Decimal("0.05")

#: Tolerancia al comparar dinero, en dólares.
MONEY_TOLERANCE = Decimal("0.01")

#: Un ratio pegado a una potencia de diez (×10, ÷10, ×100…) es la firma de un
#: dígito corrido o perdido al capturar o al leer el documento, no una decisión
#: de suscripción. Se detecta aparte del rango de ratio a propósito: ensanchar
#: el rango para atrapar esto marcaría como implausible una reducción legítima
#: (un carrier que aprueba 100k de 500k solicitados es un conflicto a resolver,
#: no un dato corrupto).
DECIMAL_SHIFT_EXPONENTS = (-3, -2, -1, 1, 2, 3)
DECIMAL_SHIFT_TOLERANCE = Decimal("0.001")


def _looks_like_decimal_shift(ratio: Decimal) -> int | None:
    """Devuelve el exponente si el ratio es ~una potencia de diez, o None."""
    for exponent in DECIMAL_SHIFT_EXPONENTS:
        power = Decimal(10) ** exponent
        if abs(ratio - power) <= DECIMAL_SHIFT_TOLERANCE * power:
            return exponent
    return None

#: Campos cuya fuente de verdad es el documento del carrier.
MONEY_FIELDS = frozenset({"cobertura", "premium"})


def reconcile(document: ExtractedDocument, request: QuoteRequest) -> CaseReport:
    """Punto de entrada del dominio. Función pura: mismo input, mismo reporte."""

    authority = assess_authority(document)

    applicant = rules.find_applicant(document)
    carrier = rules.find_carrier(document)
    face = rules.find_face_amount(document)
    premiums = rules.find_premiums(document)

    integrity_warnings = _check_document_integrity(face)

    fields: dict[str, FieldVerdict] = {
        "cliente": _verify_client(applicant, request),
        "carrier": _verify_carrier(carrier),
        "cobertura": _verify_coverage(face, request),
        "premium": _verify_premium(premiums, request),
    }

    # Un documento con un monto corrupto es sospechoso *completo*: si una cifra
    # salió mal, no podemos afirmar que las otras salieron bien.
    if integrity_warnings:
        for name in MONEY_FIELDS:
            fields[name] = _degrade_for_integrity(fields[name], integrity_warnings)

    # El gate de autoridad se aplica al final y sobre TODO: es un veto, no un
    # factor más en la ponderación.
    if not authority.can_ground_money:
        fields = {
            name: _override_as_untrusted(verdict, authority)
            for name, verdict in fields.items()
        }

    return CaseReport(
        case_id=request.case_id,
        document_id=document.document_id,
        authority=authority,
        fields=fields,
        integrity_warnings=integrity_warnings,
    )


# --------------------------------------------------------------------------
# Verificadores por campo
# --------------------------------------------------------------------------


def _verify_client(
    applicant: rules.TextFinding | None, request: QuoteRequest
) -> FieldVerdict:
    if applicant is None:
        return FieldVerdict(
            name="cliente",
            display_value=None,
            status=VerificationStatus.UNVERIFIED_MISSING,
            requested_value=request.requested_name,
            reasons=[
                Reason(
                    ReasonCode.FIELD_NOT_FOUND,
                    "El documento no declara un solicitante.",
                )
            ],
        )

    if rules.is_placeholder_name(applicant.raw):
        return FieldVerdict(
            name="cliente",
            display_value=applicant.raw,
            status=VerificationStatus.UNVERIFIED_NO_IDENTITY,
            evidence=applicant.evidence,
            requested_value=request.requested_name,
            reasons=[
                Reason(
                    ReasonCode.PLACEHOLDER_IDENTITY,
                    f"El documento dice «{applicant.raw}», que es un valor de "
                    f"plantilla y no identifica a una persona. No se puede "
                    f"afirmar que este documento corresponda a "
                    f"{request.requested_name}.",
                )
            ],
        )

    if rules.normalize_name(applicant.raw) != rules.normalize_name(
        request.requested_name
    ):
        return FieldVerdict(
            name="cliente",
            display_value=applicant.raw,
            status=VerificationStatus.UNVERIFIED_CONFLICT,
            evidence=applicant.evidence,
            requested_value=request.requested_name,
            reasons=[
                Reason(
                    ReasonCode.NAME_MISMATCH,
                    f"El documento está a nombre de «{applicant.raw}» pero la "
                    f"solicitud es de «{request.requested_name}».",
                )
            ],
        )

    return FieldVerdict(
        name="cliente",
        display_value=applicant.raw,
        status=VerificationStatus.VERIFIED,
        evidence=applicant.evidence,
        requested_value=request.requested_name,
        reasons=[
            Reason(
                ReasonCode.MATCHES_REQUEST,
                "El solicitante del documento coincide con el de la solicitud.",
            )
        ],
    )


def _verify_carrier(carrier: rules.TextFinding | None) -> FieldVerdict:
    if carrier is None:
        return FieldVerdict(
            name="carrier",
            display_value=None,
            status=VerificationStatus.UNVERIFIED_MISSING,
            reasons=[
                Reason(
                    ReasonCode.FIELD_NOT_FOUND,
                    "El documento no declara un carrier.",
                )
            ],
        )

    # El carrier no se contrasta contra nada: el documento *es* la autoridad
    # sobre su propia identidad. Se verifica porque está declarado y localizado.
    return FieldVerdict(
        name="carrier",
        display_value=carrier.raw,
        status=VerificationStatus.VERIFIED,
        evidence=carrier.evidence,
        reasons=[
            Reason(
                ReasonCode.MATCHES_REQUEST,
                "Declarado por el documento del carrier, que es la autoridad "
                "sobre su propia identidad.",
            )
        ],
    )


def _verify_coverage(
    face: tuple[Money, object] | None, request: QuoteRequest
) -> FieldVerdict:
    requested = Money(request.requested_coverage)

    if face is None:
        return FieldVerdict(
            name="cobertura",
            display_value=None,
            status=VerificationStatus.UNVERIFIED_MISSING,
            requested_value=str(requested),
            reasons=[
                Reason(
                    ReasonCode.FIELD_NOT_FOUND,
                    "El documento no declara un face amount.",
                )
            ],
        )

    money, evidence = face
    reasons: list[Reason] = []
    implausible = False

    if money.amount < MIN_PLAUSIBLE_FACE_AMOUNT:
        implausible = True
        reasons.append(
            Reason(
                ReasonCode.IMPLAUSIBLE_AMOUNT,
                f"{money} es implausible como face amount: está por debajo del "
                f"mínimo razonable de {Money(MIN_PLAUSIBLE_FACE_AMOUNT)}. "
                f"Sugiere un dato truncado o mal leído, no una cobertura real.",
            )
        )

    if request.requested_coverage > 0:
        ratio = money.amount / request.requested_coverage

        if ratio < MIN_COVERAGE_RATIO or ratio > MAX_COVERAGE_RATIO:
            implausible = True
            reasons.append(
                Reason(
                    ReasonCode.IMPLAUSIBLE_AMOUNT,
                    f"El documento indica {money} frente a {requested} "
                    f"solicitados: un factor de {ratio:.4f}. La diferencia es "
                    f"demasiado grande para ser un ajuste de suscripción.",
                )
            )
        elif (exponent := _looks_like_decimal_shift(ratio)) is not None:
            implausible = True
            factor = (
                f"÷{10 ** -exponent}" if exponent < 0 else f"×{10 ** exponent}"
            )
            reasons.append(
                Reason(
                    ReasonCode.IMPLAUSIBLE_AMOUNT,
                    f"El documento indica {money} y se solicitó {requested}: "
                    f"exactamente {factor}. Un factor de diez exacto delata un "
                    f"dígito corrido al capturar o al leer el documento, no una "
                    f"decisión de suscripción.",
                )
            )

    differs = abs(money.amount - request.requested_coverage) > MONEY_TOLERANCE

    if implausible:
        status = VerificationStatus.UNVERIFIED_IMPLAUSIBLE
    elif differs:
        status = VerificationStatus.UNVERIFIED_CONFLICT
        reasons.append(
            Reason(
                ReasonCode.CONFLICTS_WITH_REQUEST,
                f"El documento indica {money} pero se solicitó {requested}. "
                f"Manda el documento, pero la discrepancia debe resolverse "
                f"antes de presentar la cifra como verificada.",
            )
        )
    else:
        status = VerificationStatus.VERIFIED
        reasons.append(
            Reason(
                ReasonCode.MATCHES_REQUEST,
                f"El face amount del documento coincide con la cobertura "
                f"solicitada ({requested}).",
            )
        )

    return FieldVerdict(
        name="cobertura",
        display_value=str(money),
        status=status,
        evidence=evidence,  # type: ignore[arg-type]
        requested_value=str(requested),
        reasons=reasons,
    )


def _verify_premium(
    premiums: list[rules.PremiumFinding], request: QuoteRequest
) -> FieldVerdict:
    ui_premium = Money(request.ui_premium)

    if not premiums:
        return FieldVerdict(
            name="premium",
            display_value=None,
            status=VerificationStatus.UNVERIFIED_MISSING,
            requested_value=f"{ui_premium} mensual (mostrado por la UI)",
            reasons=[
                Reason(
                    ReasonCode.FIELD_NOT_FOUND,
                    "El documento no declara una prima.",
                )
            ],
        )

    chosen, alternatives, selection_reasons = _select_premium(premiums)

    if chosen is None:
        return FieldVerdict(
            name="premium",
            display_value=None,
            status=VerificationStatus.UNVERIFIED_AMBIGUOUS,
            requested_value=f"{ui_premium} mensual (mostrado por la UI)",
            alternatives=alternatives,
            reasons=selection_reasons,
        )

    reasons = list(selection_reasons)
    caveats: list[str] = []

    monthly = chosen.premium.to_monthly()
    if monthly is None:
        return FieldVerdict(
            name="premium",
            display_value=str(chosen.premium.money),
            status=VerificationStatus.UNVERIFIED_AMBIGUOUS,
            evidence=chosen.evidence,
            requested_value=f"{ui_premium} mensual (mostrado por la UI)",
            alternatives=alternatives,
            reasons=reasons
            + [
                Reason(
                    ReasonCode.CADENCE_NOT_DECLARED,
                    f"El documento indica {chosen.premium.money} sin declarar "
                    f"la periodicidad, así que no se puede comparar con el "
                    f"valor mensual de la UI.",
                )
            ],
        )

    normalization = None
    if chosen.premium.cadence.name != "MONTHLY":
        normalization = (
            f"{chosen.premium.money} {chosen.premium.cadence.label_es} "
            f"× {chosen.premium.cadence.periods_per_year} ÷ 12 = {monthly} mensual"
        )
        reasons.append(
            Reason(
                ReasonCode.NORMALIZED_CADENCE,
                f"El documento expresa la prima como {chosen.premium}. "
                f"Normalizada a mensual: {monthly}.",
            )
        )
        caveats.append(
            f"El documento no dice «{monthly} mensual»: dice "
            f"«{chosen.premium}». La cifra mensual es un cálculo nuestro."
        )

    # ¿Hay más de un monto mensual distinto en juego? Entonces el documento es
    # ambiguo por diseño y hay que declararlo aunque hayamos elegido bien.
    distinct = {
        p.premium.to_monthly().amount
        for p in premiums
        if p.premium.to_monthly() is not None
    }
    if len(distinct) > 1:
        todas = "; ".join(f"«{p.label}» {p.premium}" for p in premiums)
        reasons.append(
            Reason(
                ReasonCode.MULTIPLE_CANDIDATES,
                f"El documento ofrece varias primas ({todas}). Se tomó la "
                f"etiquetada «{chosen.label}» como prima contractual.",
            )
        )
        # Para el caveat solo importan las que difieren del monto elegido:
        # repetir la prima elegida entre las "alternativas" confundiría.
        divergentes = [
            p
            for p in premiums
            if (m := p.premium.to_monthly()) is not None
            and abs(m.amount - monthly.amount) > MONEY_TOLERANCE
        ]
        if divergentes:
            caveats.append(
                f"El documento también ofrece primas que NO son la contratada: "
                f"{'; '.join(f'«{p.label}» {p.premium}' for p in divergentes)}. "
                f"Presentar solo {monthly} mensual sin esta aclaración "
                f"induciría a error por omisión."
            )

    if abs(monthly.amount - request.ui_premium) > MONEY_TOLERANCE:
        reasons.append(
            Reason(
                ReasonCode.CONFLICTS_WITH_REQUEST,
                f"La prima del documento normalizada a mensual es {monthly}, "
                f"pero la interfaz muestra {ui_premium}. Manda el documento.",
            )
        )
        status = VerificationStatus.UNVERIFIED_CONFLICT
    else:
        reasons.append(
            Reason(
                ReasonCode.MATCHES_REQUEST,
                f"La prima del documento equivale a {monthly} mensual, que "
                f"coincide con lo mostrado por la interfaz.",
            )
        )
        status = (
            VerificationStatus.VERIFIED_WITH_CAVEAT
            if caveats
            else VerificationStatus.VERIFIED
        )

    return FieldVerdict(
        name="premium",
        display_value=f"{monthly} mensual",
        status=status,
        evidence=chosen.evidence,
        requested_value=f"{ui_premium} mensual (mostrado por la UI)",
        reasons=reasons,
        caveats=caveats,
        alternatives=alternatives,
        normalization=normalization,
    )


def _select_premium(
    premiums: list[rules.PremiumFinding],
) -> tuple[rules.PremiumFinding | None, list[Candidate], list[Reason]]:
    """Resuelve cuál de las primas del documento es la contractual.

    Prioridad: la etiquetada exactamente «Premium», luego «Base Premium», y si
    no hay ninguna etiqueta canónica y hay varias, nos negamos a elegir.
    """

    def as_candidate(finding: rules.PremiumFinding) -> Candidate:
        return Candidate(
            label=finding.label,
            display_value=str(finding.premium),
            evidence=finding.evidence,
        )

    canonical = [
        p
        for p in premiums
        if p.label.strip().lower() == rules.CANONICAL_PREMIUM_LABEL
    ]
    base = [
        p for p in premiums if p.label.strip().lower() == rules.BASE_PREMIUM_LABEL
    ]

    if canonical:
        chosen = canonical[0]
        reason = Reason(
            ReasonCode.CANONICAL_LABEL_SELECTED,
            "Se tomó la línea etiquetada «Premium», que es la prima "
            "contractual del carrier.",
        )
    elif base:
        chosen = base[0]
        reason = Reason(
            ReasonCode.CANONICAL_LABEL_SELECTED,
            "Sin una línea «Premium» simple, se tomó «Base Premium» como "
            "prima contractual.",
        )
    elif len(premiums) == 1:
        chosen = premiums[0]
        reason = Reason(
            ReasonCode.CANONICAL_LABEL_SELECTED,
            f"El documento declara una sola prima, etiquetada "
            f"«{premiums[0].label}».",
        )
    else:
        return (
            None,
            [as_candidate(p) for p in premiums],
            [
                Reason(
                    ReasonCode.MULTIPLE_CANDIDATES,
                    "El documento ofrece varias primas y ninguna tiene la "
                    "etiqueta canónica. Elegir una sería adivinar, así que no "
                    "se presenta ninguna como verificada.",
                )
            ],
        )

    return chosen, [as_candidate(p) for p in premiums if p is not chosen], [reason]


# --------------------------------------------------------------------------
# Modificadores transversales
# --------------------------------------------------------------------------


def _check_document_integrity(
    face: tuple[Money, object] | None,
) -> list[Reason]:
    """Señales de que el documento entero es poco fiable, no solo un campo."""
    warnings: list[Reason] = []
    if face is not None and face[0].amount < MIN_PLAUSIBLE_FACE_AMOUNT:
        warnings.append(
            Reason(
                ReasonCode.DOCUMENT_INTEGRITY_SUSPECT,
                f"Este documento contiene un monto implausible "
                f"(face amount {face[0]}). Si una cifra se extrajo mal o "
                f"llegó corrupta, no podemos afirmar que las demás estén bien.",
            )
        )
    return warnings


def _degrade_for_integrity(
    verdict: FieldVerdict, warnings: list[Reason]
) -> FieldVerdict:
    """Baja un campo verificado a «verificado con reserva» cuando el documento
    que lo respalda tiene su integridad en duda."""
    if verdict.status is not VerificationStatus.VERIFIED:
        return verdict
    verdict.status = VerificationStatus.VERIFIED_WITH_CAVEAT
    verdict.reasons = verdict.reasons + warnings
    verdict.caveats = verdict.caveats + [
        "El documento que respalda este dato contiene otra cifra monetaria "
        "implausible, así que su integridad está en duda."
    ]
    return verdict


def _override_as_untrusted(
    verdict: FieldVerdict, authority: DocumentAuthority
) -> FieldVerdict:
    """Aplica el veto de autoridad.

    Conservamos el valor y la evidencia a propósito: ocultarlos no ayudaría a
    nadie. Lo que cambia es la afirmación, que pasa de «esto es así» a «esto es
    lo que dice un documento en el que no nos podemos apoyar».
    """
    coincidia = verdict.is_presentable_as_verified
    verdict.status = VerificationStatus.UNVERIFIED_UNTRUSTED_SOURCE
    verdict.reasons = list(authority.reasons) + verdict.reasons
    if coincidia:
        verdict.caveats = verdict.caveats + [
            "El valor coincide con la solicitud, pero coincidir no es "
            "verificar: la fuente no es un documento emitido por el carrier. "
            "Hace falta la ilustración emitida."
        ]
    return verdict
