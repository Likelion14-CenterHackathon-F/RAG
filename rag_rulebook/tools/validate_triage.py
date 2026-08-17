#!/usr/bin/env python3
"""Validate the MVP triage rule flow against integration scenarios.

Emergency matching is delegated to `emergency_matcher.EmergencyMatcher` so this
script always evaluates the full rulebook contract (keywords *and*
`trigger_patterns` *and* `number_aliases`), not just the keyword list.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from emergency_matcher import EmergencyMatcher  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "rules" / "emergency_rules.json"
TESTS_PATH = ROOT / "test_cases" / "integration_scenarios.json"

IMAGE_CONFIDENCE_FLOOR = 0.65

VIDEO_KEYWORDS = [
    "비대칭",
    "짝짝이",
    "휜",
    "코끝",
    "재수술",
    "망한",
    "불안",
    "무서워",
    "괜찮은 거 맞",
]


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def route_case(case: Dict[str, Any], matcher: EmergencyMatcher) -> Tuple[str, List[str]]:
    """Resolve the expected route for an integration scenario.

    Ordering mirrors the target architecture: the emergency rulebook runs before
    anything else and, when it fires, no retrieval or generation may happen.
    """
    hits = matcher.matched_rule_ids(case["user_input"])
    if hits:
        return "hard_stop", hits

    image = case.get("image") or {}
    confidence = image.get("confidence")
    if isinstance(confidence, (int, float)) and confidence <= IMAGE_CONFIDENCE_FLOOR:
        return "video_consult", []

    normalized = matcher.normalize(case["user_input"])
    if case.get("department") == "rhinoplasty":
        if any(matcher.normalize(keyword) in normalized for keyword in VIDEO_KEYWORDS):
            return "video_consult", []

    return "rag_answer", []


def main() -> None:
    matcher = EmergencyMatcher(load_json(RULES_PATH))
    tests = load_json(TESTS_PATH)
    failures: List[str] = []

    print(f"rulebook: {matcher.version} ({len(matcher.rule_ids)} rules)")
    print(f"scenarios: {TESTS_PATH.relative_to(ROOT)} ({len(tests['cases'])} cases)")
    print()

    for case in tests["cases"]:
        route, rule_ids = route_case(case, matcher)
        expected = case["expected_route"]
        case_failures: List[str] = []

        if route != expected:
            case_failures.append(f"expected route {expected}, got {route}")

        expected_rule_ids = set(case.get("expected_rule_ids", []))
        if expected_rule_ids and not expected_rule_ids.issubset(set(rule_ids)):
            missing = sorted(expected_rule_ids - set(rule_ids))
            case_failures.append(
                f"expected rules {sorted(expected_rule_ids)}, got {rule_ids} (missing {missing})"
            )

        status = "FAIL" if case_failures else "PASS"
        detail = f" [{', '.join(rule_ids)}]" if rule_ids else ""
        print(f"  {status}  {case['id']:<12} route={route}{detail}")
        for problem in case_failures:
            print(f"        -> {problem}")
        failures.extend(f"{case['id']}: {problem}" for problem in case_failures)

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} problem(s))")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print(f"RESULT: PASS ({len(tests['cases'])} scenarios validated)")


if __name__ == "__main__":
    main()
