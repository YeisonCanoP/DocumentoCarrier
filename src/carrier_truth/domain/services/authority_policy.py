"""¿Es este documento una fuente de verdad?

El reto lo dice explícitamente: la fuente de verdad para dinero y cobertura es
*el documento del carrier*. De ahí se sigue algo que es fácil pasar por alto:
un PDF que resultó de imprimir una pantalla del portal **no es** el documento
del carrier, aunque tenga los mismos números y el mismo logo.

Esta política corre ANTES que cualquier comparación de valores. Si el documento
no es autoridad, que los números coincidan es irrelevante: no hay nada contra
lo cual verificarlos.
"""

from __future__ import annotations

import re

from ..model import (
    AuthorityLevel,
    DocumentAuthority,
    Evidence,
    ExtractedDocument,
    Reason,
    ReasonCode,
)

# Frases que descalifican al documento como fuente de verdad. La primera que
# aparezca gana: es una lista de vetos, no un puntaje.
_DISQUALIFYING = (
    (
        re.compile(r"NOT\s+an?\s+issued\s+illustration", re.IGNORECASE),
        "el documento declara explícitamente que NO es una ilustración emitida",
    ),
    (
        re.compile(r"portal\s+(print\s+view|preview)", re.IGNORECASE),
        "es una impresión de la vista del portal, no un documento emitido por el carrier",
    ),
    (
        re.compile(r"\b(specimen|draft|sample\s+only|unofficial)\b", re.IGNORECASE),
        "el documento está marcado como borrador o muestra",
    ),
    (
        re.compile(r"for\s+illustrative\s+purposes\s+only", re.IGNORECASE),
        "el documento se declara meramente ilustrativo",
    ),
)

# Señal positiva: el encabezado propio de una ilustración emitida.
_QUALIFYING = re.compile(r"carrier\s+illustration", re.IGNORECASE)


def assess_authority(document: ExtractedDocument) -> DocumentAuthority:
    """Clasifica el documento. Ante la duda, NO se asume autoridad."""

    for page_number, line in document.iter_lines():
        for pattern, explanation in _DISQUALIFYING:
            match = pattern.search(line.text)
            if not match:
                continue
            return DocumentAuthority(
                level=AuthorityLevel.NOT_AUTHORITATIVE,
                reasons=[
                    Reason(
                        ReasonCode.NON_AUTHORITATIVE_DOCUMENT,
                        f"No se acepta como fuente de verdad: {explanation}.",
                    )
                ],
                evidence=Evidence(
                    document_id=document.document_id,
                    page=page_number,
                    line=line.number,
                    char_span=(match.start(), match.end()),
                    snippet=line.text,
                    rule_id="authority_veto_v1",
                ),
            )

    for page_number, line in document.iter_lines():
        match = _QUALIFYING.search(line.text)
        if match:
            return DocumentAuthority(
                level=AuthorityLevel.AUTHORITATIVE,
                reasons=[],
                evidence=Evidence(
                    document_id=document.document_id,
                    page=page_number,
                    line=line.number,
                    char_span=(match.start(), match.end()),
                    snippet=line.text,
                    rule_id="authority_header_v1",
                ),
            )

    # Ni veto ni confirmación: no se presume autoridad. Es un "no sé", y un
    # "no sé" sobre la fuente se trata como falta de fuente.
    return DocumentAuthority(
        level=AuthorityLevel.UNKNOWN,
        reasons=[
            Reason(
                ReasonCode.NON_AUTHORITATIVE_DOCUMENT,
                "No se encontró el encabezado de una ilustración emitida; "
                "no se presume autoridad sobre dinero ni cobertura.",
            )
        ],
    )
