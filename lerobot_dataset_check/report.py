"""Report rendering: PASS/WARN/FAIL/INFO findings, sections, exit codes.

Same design language as a linter: FAIL means the dataset is provably
inconsistent with itself, WARN means something looks off but might be
intentional, INFO is context. Exit code 0 when there are no FAILs,
1 when there is at least one, 2 for usage errors.
"""
from __future__ import annotations

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
INFO = "INFO"

_ORDER = {PASS: 0, INFO: 1, WARN: 2, FAIL: 3}


class Section:
    def __init__(self, title: str) -> None:
        self.title = title
        self.findings = []  # list of (status, message)

    def add(self, status: str, message: str) -> None:
        self.findings.append((status, message))


def render(sections, header: str) -> str:
    lines = ["=" * 70, f" lerobot-dataset-check", f" {header}", "=" * 70, ""]
    counts = {PASS: 0, WARN: 0, FAIL: 0, INFO: 0}
    for sec in sections:
        lines.append(f"[ {sec.title} ]")
        for status, msg in sec.findings:
            counts[status] += 1
            lines.append(f"  [{status}] {msg}")
        lines.append("")
    result = "FAIL" if counts[FAIL] else "PASS"
    lines.append("=" * 70)
    lines.append(
        f" SUMMARY: {counts[PASS]} PASS, {counts[WARN]} WARN, "
        f"{counts[FAIL]} FAIL, {counts[INFO]} INFO"
    )
    lines.append(
        f" RESULT: {result}  "
        f"({'at least one FAIL finding' if counts[FAIL] else 'no FAIL findings; WARN does not fail the build'})"
    )
    lines.append("=" * 70)
    return "\n".join(lines)


def has_failure(sections) -> bool:
    return any(status == FAIL for sec in sections for status, _ in sec.findings)
