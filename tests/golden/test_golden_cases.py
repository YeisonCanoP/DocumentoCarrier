"""Tests dorados: congelan el veredicto esperado de los 6 casos del paquete.

Qué se congela y qué no, a propósito:

- **Sí**: el estado de cada campo, el outcome del caso y la procedencia (página
  y línea). Es el contrato del sistema: si cambia, hay que justificarlo.
- **No**: el texto de las razones ni de los caveats. Son redacción, y bloquear
  la redacción con tests hace que nadie la mejore.
"""

from __future__ import annotations

import pytest

from carrier_truth.composition import build_container
from carrier_truth.domain.model import OverallOutcome, VerificationStatus as S

# case_id → (outcome, {campo: estado})
EXPECTED: dict[str, tuple[OverallOutcome, dict[str, S]]] = {
    # Camino feliz: documento emitido y todo coincide.
    "C002": (
        OverallOutcome.VERIFIED,
        {
            "cliente": S.VERIFIED,
            "carrier": S.VERIFIED,
            "cobertura": S.VERIFIED,
            "premium": S.VERIFIED,
        },
    ),
    "C004": (
        OverallOutcome.VERIFIED,
        {
            "cliente": S.VERIFIED,
            "carrier": S.VERIFIED,
            "cobertura": S.VERIFIED,
            "premium": S.VERIFIED,
        },
    ),
    # Face amount de $50.00 contra 450.000 solicitados: implausible. Y el
    # premium, que coincide, queda con reserva porque el documento que lo
    # respalda tiene una cifra corrupta.
    "C001": (
        OverallOutcome.REQUIRES_HUMAN_REVIEW,
        {
            "cliente": S.VERIFIED,
            "carrier": S.VERIFIED,
            "cobertura": S.UNVERIFIED_IMPLAUSIBLE,
            "premium": S.VERIFIED_WITH_CAVEAT,
        },
    ),
    # Applicant "Client" es plantilla, no identidad. La prima está en anual y
    # se verifica tras normalizar (720/12 = 60), declarando el cálculo.
    "C003": (
        OverallOutcome.REQUIRES_HUMAN_REVIEW,
        {
            "cliente": S.UNVERIFIED_NO_IDENTITY,
            "carrier": S.VERIFIED,
            "cobertura": S.VERIFIED,
            "premium": S.VERIFIED_WITH_CAVEAT,
        },
    ),
    # Tres primas en el documento: gana la etiquetada "Premium", y el rider se
    # declara como alternativa no contratada.
    "C005": (
        OverallOutcome.VERIFIED,
        {
            "cliente": S.VERIFIED,
            "carrier": S.VERIFIED,
            "cobertura": S.VERIFIED,
            "premium": S.VERIFIED_WITH_CAVEAT,
        },
    ),
    # El caso discriminante: TODOS los valores coinciden con la solicitud, pero
    # el documento es una impresión del portal. Nada se verifica.
    "C006": (
        OverallOutcome.REQUIRES_AUTHORITATIVE_DOCUMENT,
        {
            "cliente": S.UNVERIFIED_UNTRUSTED_SOURCE,
            "carrier": S.UNVERIFIED_UNTRUSTED_SOURCE,
            "cobertura": S.UNVERIFIED_UNTRUSTED_SOURCE,
            "premium": S.UNVERIFIED_UNTRUSTED_SOURCE,
        },
    ),
}


@pytest.fixture(scope="module")
def verify():
    return build_container().verify_case


@pytest.mark.parametrize("case_id", sorted(EXPECTED))
def test_outcome_del_caso(verify, case_id: str) -> None:
    expected_outcome, _ = EXPECTED[case_id]
    assert verify(case_id).outcome is expected_outcome


@pytest.mark.parametrize("case_id", sorted(EXPECTED))
def test_estado_de_cada_campo(verify, case_id: str) -> None:
    _, expected_fields = EXPECTED[case_id]
    report = verify(case_id)
    actual = {name: verdict.status for name, verdict in report.fields.items()}
    assert actual == expected_fields


@pytest.mark.parametrize("case_id", sorted(EXPECTED))
def test_todo_campo_con_valor_trae_procedencia(verify, case_id: str) -> None:
    """La invariante central del reto: no hay dato sin fuente demostrable."""
    for verdict in verify(case_id).fields.values():
        if verdict.display_value is None:
            continue
        assert verdict.evidence is not None, f"{verdict.name} sin evidencia"
        assert verdict.evidence.page >= 1
        assert verdict.evidence.line >= 1
        assert verdict.evidence.rule_id
        # El fragmento citado tiene que existir de verdad en la línea citada.
        assert verdict.evidence.matched_text.strip()
        assert verdict.evidence.matched_text in verdict.evidence.snippet


@pytest.mark.parametrize("case_id", sorted(EXPECTED))
def test_todo_campo_no_verificado_explica_por_que(verify, case_id: str) -> None:
    """Negarse no basta: hay que decir por qué y qué hace falta."""
    for verdict in verify(case_id).fields.values():
        if verdict.is_presentable_as_verified:
            continue
        assert verdict.reasons, f"{verdict.name} se niega sin explicar"


def test_c006_no_verifica_aunque_los_valores_coincidan(verify) -> None:
    """El corazón del reto, como aserción explícita.

    En C006 el face amount y la prima del documento coinciden exactamente con
    lo solicitado y con lo que muestra la UI. Aun así, nada se presenta como
    verificado, porque la fuente no es una ilustración emitida.
    """
    report = verify("C006")

    assert not report.authority.can_ground_money
    assert report.fields["cobertura"].display_value == "$300,000.00"
    assert report.fields["premium"].display_value == "$66.00 mensual"
    assert not any(
        v.is_presentable_as_verified for v in report.fields.values()
    )
    # Y la explicación tiene que mencionar la fuente, no la cifra.
    assert any(
        "portal" in r.message.lower() or "emitid" in r.message.lower()
        for r in report.fields["cobertura"].reasons
    )


def test_c003_normaliza_anual_a_mensual(verify) -> None:
    premium = verify("C003").fields["premium"]
    assert premium.display_value == "$60.00 mensual"
    assert premium.normalization is not None
    assert "720" in premium.normalization and "60" in premium.normalization
    # El documento dice 720 anual: la evidencia debe citar eso, no el cálculo.
    assert "720" in premium.evidence.snippet
    assert premium.caveats, "hay que declarar que la cifra mensual es calculada"


def test_c005_elige_la_prima_base_y_declara_el_rider(verify) -> None:
    premium = verify("C005").fields["premium"]
    assert premium.display_value == "$58.00 mensual"
    assert any("73" in c for c in premium.caveats), "el rider debe declararse"
    assert any("73" in a.display_value for a in premium.alternatives)
