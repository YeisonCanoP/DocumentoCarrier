"""Adaptador entrante de línea de comandos.

Existe por dos razones. Una práctica: permite ver los veredictos sin levantar el
servidor (`docker compose run --rm api carrier-truth`). Y una arquitectónica: es
la prueba de que el dominio no depende de HTTP. Dos adaptadores distintos, el
mismo núcleo, cero duplicación de criterio.
"""

from __future__ import annotations

import argparse
import sys

from ...application.use_cases import CaseNotFound, DocumentNotFound
from ...composition import build_container
from ...domain.model import CaseReport

_RESET = "\033[0m"
_COLORS = {"ok": "\033[32m", "warn": "\033[33m", "danger": "\033[31m"}
_MARKS = {"ok": "✓", "warn": "!", "danger": "✕"}


def _severity(status_value: str) -> str:
    if status_value == "verified":
        return "ok"
    if status_value == "verified_with_caveat":
        return "warn"
    return "danger"


def _render(report: CaseReport, *, color: bool) -> str:
    from ..inbound.http.presentation import to_dto

    dto = to_dto(report)

    def paint(severity: str, text: str) -> str:
        if not color:
            return text
        return f"{_COLORS[severity]}{text}{_RESET}"

    lines: list[str] = []
    head = f"{dto.case_id} · {dto.document} · {dto.outcome_label}"
    lines.append(paint(dto.outcome_severity, f"── {head} "))
    lines.append(f"   {dto.outcome_detail}")
    lines.append(f"   Fuente: {dto.authority.label}")
    lines.append("")

    for field in dto.fields:
        mark = _MARKS[field.severity]
        value = field.value if field.value is not None else "—"
        lines.append(
            paint(field.severity, f"   {mark} {field.label}: {value}")
            + paint(field.severity, f"  [{field.status_label}]")
        )
        if field.evidence:
            lines.append(f"       procedencia: {field.evidence.locator}")
            lines.append(f"       cita: «{field.evidence.snippet}»")
            lines.append(f"       regla: {field.evidence.rule_id}")
        if field.normalization:
            lines.append(f"       normalización: {field.normalization}")
        for reason in field.reasons:
            lines.append(f"       · {reason.message}")
        for caveat in field.caveats:
            lines.append(paint("warn", f"       ⚠ {caveat}"))
        if not field.verified:
            lines.append(paint(field.severity, f"       → {field.next_action}"))
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="carrier-truth",
        description=(
            "Verifica ilustraciones de carriers contra las solicitudes de "
            "cotización y muestra la procedencia de cada dato."
        ),
    )
    parser.add_argument(
        "case_ids",
        nargs="*",
        help="Casos a verificar. Sin argumentos, verifica todos.",
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Salida sin códigos ANSI."
    )
    args = parser.parse_args(argv)

    container = build_container()
    color = not args.no_color and sys.stdout.isatty()

    if args.case_ids:
        reports: list[CaseReport] = []
        for case_id in args.case_ids:
            try:
                reports.append(container.verify_case(case_id))
            except (CaseNotFound, DocumentNotFound) as exc:
                print(f"No se pudo verificar {exc}", file=sys.stderr)
                return 1
    else:
        reports = container.verify_all_cases()

    for report in reports:
        print(_render(report, color=color))

    # Código de salida distinto de cero si algún caso no quedó verificado: así
    # se puede usar en un pipeline como control de calidad.
    return 0 if all(r.outcome.value == "verified" for r in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
