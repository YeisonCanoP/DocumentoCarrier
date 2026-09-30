"""Tests del dominio sin tocar un PDF, un disco ni un servidor.

Este archivo es la demostración de que el núcleo está aislado: se construye un
`ExtractedDocument` a mano y se afirma el veredicto. Si mañana la extracción
cambia a OCR o a un LLM, estos tests siguen siendo válidos sin tocarlos.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from carrier_truth.domain.model import (
    DocumentLine,
    DocumentPage,
    ExtractedDocument,
    QuoteRequest,
    VerificationStatus as S,
)
from carrier_truth.domain.services.reconciliation import reconcile


def doc(*lines: str, document_id: str = "test.pdf") -> ExtractedDocument:
    return ExtractedDocument(
        document_id=document_id,
        pages=(
            DocumentPage(
                number=1,
                lines=tuple(
                    DocumentLine(number=i, text=t)
                    for i, t in enumerate(lines, start=1)
                ),
            ),
        ),
    )


def request(
    *,
    name: str = "Ana Rivera",
    coverage: str = "250000",
    premium: str = "50.00",
) -> QuoteRequest:
    return QuoteRequest(
        case_id="T001",
        requested_name=name,
        requested_coverage=Decimal(coverage),
        ui_premium=Decimal(premium),
    )


ILUSTRACION = "Carrier Illustration"


def test_camino_feliz() -> None:
    report = reconcile(
        doc(
            ILUSTRACION,
            "Applicant: Ana Rivera",
            "Carrier: Northstar Life",
            "Face Amount: $250,000.00",
            "Premium: $50.00 MONTHLY",
        ),
        request(),
    )
    assert all(v.status is S.VERIFIED for v in report.fields.values())


@pytest.mark.parametrize(
    "linea_veto",
    [
        "This page is a portal preview and is NOT an issued illustration document.",
        "Portal Print View",
        "SPECIMEN - not for distribution",
        "For illustrative purposes only",
    ],
)
def test_el_veto_de_autoridad_invalida_todo_aunque_coincida(linea_veto: str) -> None:
    """Coincidir no es verificar: con la fuente equivocada, nada se verifica."""
    report = reconcile(
        doc(
            "Applicant: Ana Rivera",
            "Carrier: Northstar Life",
            "Face Amount: $250,000.00",
            "Premium: $50.00 MONTHLY",
            linea_veto,
        ),
        request(),
    )
    assert not report.authority.can_ground_money
    assert all(v.status is S.UNVERIFIED_UNTRUSTED_SOURCE for v in report.fields.values())
    # El valor se sigue mostrando: ocultarlo no ayudaría a nadie.
    assert report.fields["cobertura"].display_value == "$250,000.00"


def test_documento_sin_encabezado_no_presume_autoridad() -> None:
    """Un 'no sé' sobre la fuente se trata como falta de fuente."""
    report = reconcile(
        doc("Applicant: Ana Rivera", "Face Amount: $250,000.00"), request()
    )
    assert not report.authority.can_ground_money


@pytest.mark.parametrize(
    ("cadencia", "monto", "esperado"),
    [
        ("MONTHLY", "50.00", S.VERIFIED),
        ("ANNUAL", "600.00", S.VERIFIED_WITH_CAVEAT),  # 600/12 = 50
        ("QUARTERLY", "150.00", S.VERIFIED_WITH_CAVEAT),  # 150*4/12 = 50
        ("SEMIANNUAL", "300.00", S.VERIFIED_WITH_CAVEAT),  # 300*2/12 = 50
        ("ANNUAL", "700.00", S.UNVERIFIED_CONFLICT),  # 58.33 != 50
    ],
)
def test_normalizacion_de_periodicidad(cadencia, monto, esperado) -> None:
    report = reconcile(
        doc(
            ILUSTRACION,
            "Applicant: Ana Rivera",
            "Carrier: Northstar Life",
            "Face Amount: $250,000.00",
            f"Premium: ${monto} {cadencia}",
        ),
        request(),
    )
    assert report.fields["premium"].status is esperado


def test_prima_sin_periodicidad_no_se_verifica() -> None:
    """Sin cadencia no hay comparación posible, así que no hay verificación."""
    report = reconcile(
        doc(
            ILUSTRACION,
            "Applicant: Ana Rivera",
            "Carrier: Northstar Life",
            "Face Amount: $250,000.00",
            "Premium: $50.00",
        ),
        request(),
    )
    assert report.fields["premium"].status is S.UNVERIFIED_AMBIGUOUS


def test_varias_primas_sin_etiqueta_canonica_es_ambiguo() -> None:
    """Ante dos respuestas y ningún criterio, el sistema no adivina."""
    report = reconcile(
        doc(
            ILUSTRACION,
            "Applicant: Ana Rivera",
            "Carrier: Northstar Life",
            "Face Amount: $250,000.00",
            "Illustrated Premium: $50.00 MONTHLY",
            "Guaranteed Premium: $95.00 MONTHLY",
        ),
        request(),
    )
    assert report.fields["premium"].status is S.UNVERIFIED_AMBIGUOUS
    assert len(report.fields["premium"].alternatives) == 2


@pytest.mark.parametrize(
    "nombre_plantilla", ["Client", "INSURED", "n/a", "TBD", "John Doe", "-"]
)
def test_nombres_de_plantilla_no_identifican(nombre_plantilla: str) -> None:
    report = reconcile(
        doc(
            ILUSTRACION,
            f"Applicant: {nombre_plantilla}",
            "Carrier: Northstar Life",
            "Face Amount: $250,000.00",
            "Premium: $50.00 MONTHLY",
        ),
        request(),
    )
    assert report.fields["cliente"].status is S.UNVERIFIED_NO_IDENTITY


@pytest.mark.parametrize(
    ("en_documento", "solicitado"),
    [
        ("José Pérez", "Jose Perez"),  # acentos
        ("ANA RIVERA", "ana rivera"),  # mayúsculas
        ("Ana  Rivera", "Ana Rivera"),  # espacios dobles
        ("Ana Rivera-Gomez", "Ana Rivera Gomez"),  # puntuación
    ],
)
def test_la_comparacion_de_nombres_normaliza(en_documento, solicitado) -> None:
    report = reconcile(
        doc(
            ILUSTRACION,
            f"Applicant: {en_documento}",
            "Carrier: Northstar Life",
            "Face Amount: $250,000.00",
            "Premium: $50.00 MONTHLY",
        ),
        request(name=solicitado),
    )
    assert report.fields["cliente"].status is S.VERIFIED


def test_nombre_distinto_es_contradiccion() -> None:
    report = reconcile(
        doc(
            ILUSTRACION,
            "Applicant: Marco Diaz",
            "Carrier: Northstar Life",
            "Face Amount: $250,000.00",
            "Premium: $50.00 MONTHLY",
        ),
        request(name="Ana Rivera"),
    )
    assert report.fields["cliente"].status is S.UNVERIFIED_CONFLICT


@pytest.mark.parametrize(
    ("face", "solicitado", "esperado"),
    [
        ("$250,000.00", "250000", S.VERIFIED),
        ("$50.00", "450000", S.UNVERIFIED_IMPLAUSIBLE),  # truncado (C001)
        ("$45,000.00", "450000", S.UNVERIFIED_IMPLAUSIBLE),  # dígito perdido
        ("$240,000.00", "250000", S.UNVERIFIED_CONFLICT),  # diferencia real
    ],
)
def test_plausibilidad_y_conflicto_de_cobertura(face, solicitado, esperado) -> None:
    report = reconcile(
        doc(
            ILUSTRACION,
            "Applicant: Ana Rivera",
            "Carrier: Northstar Life",
            f"Face Amount: {face}",
            "Premium: $50.00 MONTHLY",
        ),
        request(coverage=solicitado),
    )
    assert report.fields["cobertura"].status is esperado


def test_campos_ausentes_no_se_inventan() -> None:
    report = reconcile(doc(ILUSTRACION, "Carrier: Northstar Life"), request())
    assert report.fields["cliente"].status is S.UNVERIFIED_MISSING
    assert report.fields["cobertura"].status is S.UNVERIFIED_MISSING
    assert report.fields["premium"].status is S.UNVERIFIED_MISSING
    assert report.fields["cliente"].display_value is None


def test_reconcile_es_puro() -> None:
    """Mismo input, mismo veredicto. Requisito para poder auditar."""
    documento = doc(
        ILUSTRACION,
        "Applicant: Ana Rivera",
        "Carrier: Northstar Life",
        "Face Amount: $250,000.00",
        "Premium: $50.00 MONTHLY",
    )
    peticion = request()
    primero = reconcile(documento, peticion)
    segundo = reconcile(documento, peticion)
    assert {k: v.status for k, v in primero.fields.items()} == {
        k: v.status for k, v in segundo.fields.items()
    }
