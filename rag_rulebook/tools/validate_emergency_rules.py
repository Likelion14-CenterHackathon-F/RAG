#!/usr/bin/env python3
"""Regression suite for the emergency hard-stop rulebook.

Two independent layers are checked:

  Schema   `rules/emergency_rules.json` is internally consistent: unique ids,
           required fields, compilable patterns, a `match_policy` that actually
           matches the trigger sets present, and hard-stop semantics intact.

  Behaviour Every case in `test_cases/emergency_rule_regression.json` resolves
           the way it is pinned, including the negative cases that guard against
           over-broad triggers and the `negation_true_positive` cases that guard
           against over-broad suppression.

Exit code 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))

from emergency_matcher import (  # noqa: E402
    POLICY_KEYWORD_ONLY,
    POLICY_KEYWORD_OR_PATTERN,
    EmergencyMatcher,
)

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "rules" / "emergency_rules.json"
REGRESSION_PATH = ROOT / "test_cases" / "emergency_rule_regression.json"

REQUIRED_RULE_FIELDS = (
    "id",
    "name",
    "scope",
    "trigger_keywords",
    "risk_level",
    "match_policy",
    "system_actions",
    "frontend_message",
    "llm_policy",
    "source_refs",
)

VALID_POLICIES = (POLICY_KEYWORD_ONLY, POLICY_KEYWORD_OR_PATTERN)

# The syllable 안 must never appear in a negation guard. In Korean it negates
# the following verb, and after an emergency trigger that means the symptom
# persists: "열이 안 떨어져요", "피가 안 멈춰요", "눈이 안 보여요" are all
# emergencies. The morphemes the guards legitimately need are 없, 않 and 아니,
# none of which contain the character 안 (U+C548 vs 않 U+C54A).
FORBIDDEN_GUARD_CHAR = "안"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class Report:
    def __init__(self) -> None:
        self.failures: List[str] = []
        self.lines: List[str] = []

    def ok(self, label: str, detail: str = "") -> None:
        self.lines.append(f"  PASS  {label}" + (f" — {detail}" if detail else ""))

    def fail(self, label: str, detail: str) -> None:
        self.lines.append(f"  FAIL  {label} — {detail}")
        self.failures.append(f"{label}: {detail}")

    def note(self, text: str) -> None:
        self.lines.append(f"        {text}")

    def section(self, title: str) -> None:
        self.lines.append("")
        self.lines.append(title)

    def render(self) -> str:
        return "\n".join(self.lines)


def check_schema(report: Report, rules_doc: Dict[str, Any]) -> None:
    report.section("[1] rulebook schema")
    rules = rules_doc["rules"]

    ids = [rule.get("id") for rule in rules]
    duplicates = {rid for rid in ids if ids.count(rid) > 1}
    if duplicates:
        report.fail("unique rule ids", f"duplicated {sorted(duplicates)}")
    else:
        report.ok("unique rule ids", f"{len(ids)} rules")

    missing: List[str] = []
    for rule in rules:
        for field in REQUIRED_RULE_FIELDS:
            if field not in rule or rule[field] in (None, "", []):
                missing.append(f"{rule.get('id', '?')}.{field}")
    if missing:
        report.fail("required fields present", ", ".join(missing))
    else:
        report.ok("required fields present")

    bad_policy = [
        f"{r['id']}={r['match_policy']}" for r in rules if r["match_policy"] not in VALID_POLICIES
    ]
    if bad_policy:
        report.fail("match_policy is recognised", ", ".join(bad_policy))
    else:
        report.ok("match_policy is recognised")

    # A rule that ships patterns but keeps the keyword-only policy silently
    # ignores those patterns. That is exactly the defect found in step 1.
    ignored = [
        r["id"]
        for r in rules
        if r.get("trigger_patterns") and r["match_policy"] != POLICY_KEYWORD_OR_PATTERN
    ]
    if ignored:
        report.fail(
            "patterns are reachable",
            f"{ignored} declare trigger_patterns but match_policy is not {POLICY_KEYWORD_OR_PATTERN}",
        )
    else:
        report.ok("patterns are reachable")

    pointless = [
        r["id"]
        for r in rules
        if r["match_policy"] == POLICY_KEYWORD_OR_PATTERN and not r.get("trigger_patterns")
    ]
    if pointless:
        report.fail("policy matches trigger sets", f"{pointless} allow patterns but declare none")
    else:
        report.ok("policy matches trigger sets")

    uncompilable: List[str] = []
    for rule in rules:
        for raw in rule.get("trigger_patterns", []) or []:
            try:
                re.compile(raw)
            except re.error as exc:
                uncompilable.append(f"{rule['id']}: {raw!r} ({exc})")
    if uncompilable:
        report.fail("trigger_patterns compile", "; ".join(uncompilable))
    else:
        report.ok("trigger_patterns compile")

    not_blocking = [
        r["id"]
        for r in rules
        if r["llm_policy"] != "block_freeform_generation" or "stop_chatbot" not in r["system_actions"]
    ]
    if not_blocking:
        report.fail("hard-stop semantics intact", f"{not_blocking} do not stop generation")
    else:
        report.ok("hard-stop semantics intact", "all rules block free-form generation")


def check_normalization_contract(report: Report, rules_doc: Dict[str, Any]) -> None:
    report.section("[2] normalization and negation contract")
    norm = rules_doc.get("normalization", {})

    if norm.get("keyword_text_form") == "compact" and norm.get("pattern_text_form") == "spaced":
        report.ok("text forms declared", "keywords=compact, patterns=spaced")
    else:
        report.fail(
            "text forms declared",
            "normalization must declare keyword_text_form=compact and pattern_text_form=spaced",
        )

    guards = rules_doc.get("negation_guards", {}) or {}
    patterns = guards.get("patterns", []) or []
    if not patterns:
        report.fail("negation guards present", "no guard patterns declared")
        return

    uncompilable = []
    unanchored = []
    for raw in patterns:
        try:
            re.compile(raw)
        except re.error as exc:
            uncompilable.append(f"{raw!r} ({exc})")
            continue
        if not raw.startswith("^"):
            unanchored.append(raw)

    if uncompilable:
        report.fail("negation guards compile", "; ".join(uncompilable))
    else:
        report.ok("negation guards compile", f"{len(patterns)} guards")

    # Unanchored guards let a negation elsewhere in the sentence cancel a real
    # emergency, e.g. "고름이 나오고 통증은 없어요".
    if unanchored:
        report.fail("negation guards anchored", f"not anchored at ^: {unanchored}")
    else:
        report.ok("negation guards anchored")

    risky = [p for p in patterns if FORBIDDEN_GUARD_CHAR in p]
    if risky:
        report.fail(
            "no 안 in negation guards",
            f"{risky} contain {FORBIDDEN_GUARD_CHAR!r} and would suppress persistence "
            "phrasings like '열이 안 떨어져요'",
        )
    else:
        report.ok("no 안 in negation guards")


def check_version_alignment(
    report: Report, rules_doc: Dict[str, Any], suite: Dict[str, Any]
) -> None:
    report.section("[3] version alignment")
    rules_version = rules_doc.get("version")
    pinned = suite.get("rulebook_version")
    if pinned != rules_version:
        report.fail(
            "regression suite pins the current rulebook",
            f"suite pins {pinned!r} but rulebook is {rules_version!r}",
        )
    else:
        report.ok("regression suite pins the current rulebook", str(rules_version))


def check_cases(report: Report, matcher: EmergencyMatcher, suite: Dict[str, Any]) -> Set[str]:
    cases = suite["cases"]
    by_category: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_category[case.get("category", "uncategorised")].append(case)

    seen_ids: Set[str] = set()
    covered_rules: Set[str] = set()

    for category in suite.get("categories", by_category).keys():
        group = by_category.get(category, [])
        if not group:
            continue
        report.section(f"[4] {category} ({len(group)} cases)")
        for case in group:
            cid = case["id"]
            if cid in seen_ids:
                report.fail(cid, "duplicate case id")
            seen_ids.add(cid)

            hits = matcher.match(case["user_input"])
            got = [h.rule_id for h in hits]
            expect = case["expect"]
            problems: List[str] = []

            if expect == "hard_stop" and not hits:
                problems.append("expected a hard stop but no rule matched")
            if expect == "no_match" and hits:
                evidence = ", ".join(f"{h.rule_id} via {h.matched_by} {h.matched_text!r}" for h in hits)
                problems.append(f"expected no match but got {evidence}")

            required = set(case.get("expected_rule_ids", []))
            if required and not required.issubset(set(got)):
                problems.append(
                    f"missing rules {sorted(required - set(got))} (got {got or '-'})"
                )
            if expect == "hard_stop":
                covered_rules |= required or set(got)

            forbidden = set(case.get("forbidden_rule_ids", []))
            hit_forbidden = forbidden & set(got)
            if hit_forbidden:
                problems.append(f"forbidden rules fired: {sorted(hit_forbidden)}")

            status = "FAIL" if problems else "PASS"
            detail = ",".join(got) if got else "-"
            report.lines.append(f"  {status}  {cid:<7} {detail:<24} {case['user_input']}")
            for problem in problems:
                report.note(f"-> {problem}")
                report.failures.append(f"{cid}: {problem}")

    return covered_rules


def check_rule_coverage(report: Report, matcher: EmergencyMatcher, covered: Set[str]) -> None:
    report.section("[5] rule coverage")
    uncovered = [rid for rid in matcher.rule_ids if rid not in covered]
    if uncovered:
        report.fail("every rule has a positive case", f"uncovered {uncovered}")
    else:
        report.ok("every rule has a positive case", f"{len(matcher.rule_ids)} rules")


def main() -> None:
    rules_doc = load_json(RULES_PATH)
    suite = load_json(REGRESSION_PATH)
    matcher = EmergencyMatcher(rules_doc)

    report = Report()
    report.lines.append(f"rulebook  : {matcher.version}")
    report.lines.append(f"suite     : {suite['version']} ({len(suite['cases'])} cases)")

    check_schema(report, rules_doc)
    check_normalization_contract(report, rules_doc)
    check_version_alignment(report, rules_doc, suite)
    covered = check_cases(report, matcher, suite)
    check_rule_coverage(report, matcher, covered)

    print(report.render())
    print()
    if report.failures:
        print(f"RESULT: FAIL ({len(report.failures)} problem(s))")
        for failure in report.failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print(f"RESULT: PASS ({len(suite['cases'])} cases, {len(matcher.rule_ids)} rules)")


if __name__ == "__main__":
    main()
