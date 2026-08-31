"""Run agent evals: assignment + critical remarks."""

from __future__ import annotations

import json
from pathlib import Path

from tickets.agent.criticality import CRITICALITY_LABELS, classify_criticality, valid_criticality
from tickets.routing import assign_sme_from_tags, route_ticket

EVAL_DIR = Path(__file__).resolve().parent
ASSIGN_PATH = EVAL_DIR / "assign_cases.json"
CRITICAL_PATH = EVAL_DIR / "critical_remark_cases.json"

REQUIRED_CRITICAL_KEYS = (
    "id",
    "student_description",
    "question_text",
    "question_type",
    "question_tags",
    "org_assessment_title",
    "programme",
    "category",
    "sub_category",
    "expected_criticality",
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def eval_assign(cases: list[dict]) -> list[str]:
    failures: list[str] = []
    for case in cases:
        got = assign_sme_from_tags(case["question_tags"])
        routed = route_ticket(case["org_assessment_title"], case["question_tags"])
        if got != case["expected_sme"] or routed["sme_name"] != case["expected_sme"]:
            failures.append(
                f"{case['id']}: expected {case['expected_sme']!r}, "
                f"got {got!r} / route={routed['sme_name']!r}"
            )
    return failures


def eval_critical_remarks(cases: list[dict]) -> list[str]:
    failures: list[str] = []
    for case in cases:
        missing = [key for key in REQUIRED_CRITICAL_KEYS if key not in case]
        if missing:
            failures.append(f"{case.get('id', '?')}: missing keys {missing}")
            continue
        if not valid_criticality(case["expected_criticality"]):
            failures.append(
                f"{case['id']}: expected_criticality must be one of "
                f"{' / '.join(CRITICALITY_LABELS)}"
            )
            continue
        got, _ = classify_criticality(case)
        if got != case["expected_criticality"]:
            failures.append(
                f"{case['id']}: expected {case['expected_criticality']!r}, got {got!r}"
            )
    return failures


def main() -> int:
    assign_cases = load_json(ASSIGN_PATH)
    critical_cases = load_json(CRITICAL_PATH)
    failures: list[str] = []
    failures.extend(eval_assign(assign_cases))
    failures.extend(eval_critical_remarks(critical_cases))
    if failures:
        print("FAILED")
        for line in failures:
            print("-", line)
        return 1
    print(
        "PASSED "
        f"assign={len(assign_cases)} "
        f"critical_remarks={len(critical_cases)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
