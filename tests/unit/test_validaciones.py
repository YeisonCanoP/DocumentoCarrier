"""Validaciones de entrada, en el dominio y en la frontera HTTP.

El criterio: el dominio se protege solo (un `QuoteRequest` que exista es
comparable) y la capa HTTP traduce esas invariantes a códigos y mensajes
útiles. Los tests cubren las dos capas porque protegen de cosas distintas: el
dominio, de un bug interno; HTTP, de un cliente hostil.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from carrier_truth.adapters.inbound.http.app import create_app
from carrier_truth.adapters.outbound.pypdf_extractor import (
    PyPdfTextExtractor,
    UnreadableDocument,
)
from carrier_truth.domain.model import InvalidQuoteRequest, QuoteRequest

DOCS = (
    Path(__file__).resolve().parents[2]
    / "datos_prueba"
    / "carrier-truth"
    / "documents"
)


# --------------------------------------------------------------------------
# Invariantes del dominio
# --------------------------------------------------------------------------


def _request(**overrides) -> QuoteRequest:
    kwargs = {
        "case_id": "T001",
        "requested_name": "Ana Rivera",
        "requested_coverage": Decimal("250000"),
        "ui_premium": Decimal("50.00"),
    }
    return QuoteRequest(**{**kwargs, **overrides})


def test_solicitud_valida_se_construye() -> None:
    assert _request().requested_coverage == Decimal("250000")


@pytest.mark.parametrize("valor", ["NaN", "nan", "sNaN"])
def test_nan_se_rechaza(valor: str) -> None:
    """El caso peligroso: `Decimal('NaN')` se construye sin error y *toda*
    comparación con él es False, así que se colaría como «coincide» en vez de
    fallar. Tiene que morir en la frontera del dominio."""
    sospechoso = Decimal(valor)
    assert sospechoso.is_nan()  # Decimal lo acepta...
    with pytest.raises(InvalidQuoteRequest, match="NaN"):  # ...el dominio no
        _request(requested_coverage=sospechoso)


@pytest.mark.parametrize("valor", ["Infinity", "-Infinity", "inf"])
def test_infinitos_se_rechazan(valor: str) -> None:
    with pytest.raises(InvalidQuoteRequest, match="infinito"):
        _request(ui_premium=Decimal(valor))


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("requested_coverage", Decimal("0")),
        ("requested_coverage", Decimal("-1")),
        ("ui_premium", Decimal("0")),
        ("ui_premium", Decimal("-50")),
    ],
)
def test_montos_no_positivos_se_rechazan(campo: str, valor: Decimal) -> None:
    with pytest.raises(InvalidQuoteRequest, match="mayor que cero"):
        _request(**{campo: valor})


def test_montos_absurdamente_grandes_se_rechazan() -> None:
    with pytest.raises(InvalidQuoteRequest, match="máximo representable"):
        _request(requested_coverage=Decimal("999999999999"))


@pytest.mark.parametrize("nombre", ["", "   ", "\t\n"])
def test_nombre_vacio_se_rechaza(nombre: str) -> None:
    with pytest.raises(InvalidQuoteRequest, match="requested_name"):
        _request(requested_name=nombre)


def test_nombre_demasiado_largo_se_rechaza() -> None:
    with pytest.raises(InvalidQuoteRequest, match="excede"):
        _request(requested_name="A" * 201)


def test_case_id_vacio_se_rechaza() -> None:
    with pytest.raises(InvalidQuoteRequest, match="case_id"):
        _request(case_id="  ")


def test_float_se_rechaza() -> None:
    """Aceptar float silenciosamente reintroduciría el error de precisión que
    `Decimal` existe para evitar."""
    with pytest.raises(InvalidQuoteRequest, match="Decimal"):
        _request(requested_coverage=250000.0)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Extractor: qué archivos se rechazan y con qué mensaje
# --------------------------------------------------------------------------


def test_extractor_rechaza_lo_que_no_es_pdf() -> None:
    with pytest.raises(UnreadableDocument, match="no es un PDF"):
        PyPdfTextExtractor().extract("x.pdf", b"<html>hola</html>")


def test_extractor_rechaza_vacio() -> None:
    with pytest.raises(UnreadableDocument, match="vac"):
        PyPdfTextExtractor().extract("x.pdf", b"")


def test_extractor_rechaza_pdf_truncado() -> None:
    """Firma correcta pero contenido roto: el mensaje debe seguir siendo claro."""
    with pytest.raises(UnreadableDocument):
        PyPdfTextExtractor().extract("x.pdf", b"%PDF-1.7\nbasura sin xref")


def test_extractor_respeta_el_tope_de_paginas() -> None:
    contenido = (DOCS / "C001.pdf").read_bytes()
    with pytest.raises(UnreadableDocument, match="máximo"):
        PyPdfTextExtractor(max_pages=0).extract("C001.pdf", contenido)


def test_extractor_numera_paginas_y_lineas_desde_uno() -> None:
    doc = PyPdfTextExtractor().extract(
        "C001.pdf", (DOCS / "C001.pdf").read_bytes()
    )
    assert doc.pages[0].number == 1
    assert doc.pages[0].lines[0].number == 1


# --------------------------------------------------------------------------
# Frontera HTTP
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _upload(client: TestClient, **overrides):
    data = {
        "requested_name": "Ana Rivera",
        "requested_coverage": "450000",
        "ui_premium": "62.00",
    }
    data.update({k: v for k, v in overrides.items() if k != "content"})
    content = overrides.get("content", (DOCS / "C001.pdf").read_bytes())
    return client.post(
        "/api/verify",
        files={"document": ("C001.pdf", content, "application/pdf")},
        data=data,
    )


def test_subida_valida_responde_200(client: TestClient) -> None:
    assert _upload(client).status_code == 200


@pytest.mark.parametrize(
    "valor", ["NaN", "inf", "-Infinity", "abc", "", "   ", "1.2.3"]
)
def test_montos_invalidos_responden_422(client: TestClient, valor: str) -> None:
    res = _upload(client, requested_coverage=valor)
    assert res.status_code == 422, res.text


@pytest.mark.parametrize("valor", ["0", "-100"])
def test_montos_no_positivos_responden_422(client: TestClient, valor: str) -> None:
    assert _upload(client, ui_premium=valor).status_code == 422


def test_se_aceptan_montos_con_formato_humano(client: TestClient) -> None:
    """`$450,000.00` es lo que una persona copia y pega de una pantalla."""
    res = _upload(client, requested_coverage="$450,000.00")
    assert res.status_code == 200, res.text


def test_archivo_que_no_es_pdf_responde_422(client: TestClient) -> None:
    res = _upload(client, content=b"no soy un pdf")
    assert res.status_code == 422
    assert "PDF" in res.json()["detail"]


def test_archivo_vacio_responde_422(client: TestClient) -> None:
    assert _upload(client, content=b"").status_code == 422


def test_nombre_vacio_responde_422(client: TestClient) -> None:
    assert _upload(client, requested_name="   ").status_code == 422


@pytest.mark.parametrize(
    "ruta",
    [
        "/api/cases/..%2F..%2Fetc%2Fpasswd",  # barra codificada
        "/api/cases/C001%2F..%2FC002",
        "/api/cases/%2E%2E%2FC002",  # punto codificado
        "/api/cases/a/b",  # dos segmentos
    ],
)
def test_el_traversal_no_alcanza_el_filesystem(client: TestClient, ruta: str) -> None:
    """Un `case_id` con separadores de ruta no puede resolver a un archivo.

    Lo bloquea el enrutador: un parámetro de ruta no abarca `/`, ni literal ni
    codificado, así que estas peticiones no llegan al handler. La regex de
    `CASE_ID_PATTERN` y la comprobación de contención del repositorio son
    defensa en profundidad para cuando alguien refactorice el enrutado.
    """
    assert client.get(ruta).status_code == 404


def test_los_puntos_en_la_ruta_los_normaliza_el_cliente(client: TestClient) -> None:
    """Documenta por qué `/api/cases/C001/../C002` devuelve 200.

    No es un traversal: el cliente HTTP colapsa `..` *antes* de enviar, así que
    el servidor recibe una petición legítima de C002. Lo dejamos como test para
    que nadie lo confunda con un agujero al leer los logs.
    """
    res = client.get("/api/cases/C001/../C002")
    assert res.status_code == 200
    assert res.json()["case_id"] == "C002"


# Nota: "." y ".." no entran aquí porque el cliente los colapsa y la petición
# acaba en el endpoint de listado, no en este handler (ver el test de arriba).
@pytest.mark.parametrize("case_id", ["a" * 40, "C 001", "C001;ls", "C001$", "C@001"])
def test_case_id_mal_formado_responde_422(client: TestClient, case_id: str) -> None:
    """Un solo segmento pero con forma inválida: lo rechaza la validación, y el
    mensaje dice qué se admite en vez de un 404 ambiguo."""
    res = client.get(f"/api/cases/{case_id}")
    assert res.status_code == 422, res.text
    assert "case_id" in res.json()["detail"]


def test_caso_inexistente_responde_404(client: TestClient) -> None:
    assert client.get("/api/cases/C999").status_code == 404


def test_health_reporta_los_datos_encontrados(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["quote_requests_found"] is True


def test_catalogo_de_reglas_se_expone(client: TestClient) -> None:
    """El motor tiene que poder auditarse a sí mismo."""
    body = client.get("/api/rules").json()
    assert {r["rule_id"] for r in body["extraction_rules"]} == {
        "applicant_v1",
        "carrier_v1",
        "face_amount_v1",
        "premium_v1",
    }
    assert body["authority_vetoes"], "los vetos de autoridad deben ser visibles"
    # Solo dos de los ocho estados permiten presentar un dato como verificado.
    presentables = [s for s in body["statuses"] if s["presentable_as_verified"]]
    assert len(presentables) == 2
    assert all(s["next_action"] for s in body["statuses"])


def test_todos_los_casos_responden_con_procedencia(client: TestClient) -> None:
    casos = client.get("/api/cases").json()
    assert len(casos) == 6
    for caso in casos:
        for campo in caso["fields"]:
            if campo["value"] is None:
                continue
            ev = campo["evidence"]
            assert ev is not None
            a, b = ev["char_span"]
            # El span tiene que apuntar a algo real dentro de la línea citada.
            assert 0 <= a < b <= len(ev["snippet"])
            assert ev["snippet"][a:b] == ev["matched_text"]
