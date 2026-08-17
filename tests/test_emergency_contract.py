"""The service must implement the rulebook contract, not its own version of it.

This is the test that would have caught the drift described in ADR-0022: the
previous in-service matcher failed 18 of these 66 cases. It runs the Rag-Lab
regression suite against the code the service actually calls, so the rulebook and
the service can no longer disagree silently.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from centerton_rag.emergency import load_gate

REPO_ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = REPO_ROOT / "rag_rulebook" / "rules" / "emergency_rules.json"
SUITE_PATH = REPO_ROOT / "rag_rulebook" / "test_cases" / "emergency_rule_regression.json"


def load_suite() -> dict:
    return json.loads(SUITE_PATH.read_text(encoding="utf-8"))


class EmergencyContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = load_gate(RULES_PATH)
        cls.suite = load_suite()

    def test_suite_pins_the_deployed_rulebook(self) -> None:
        rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            self.suite["rulebook_version"],
            rules["version"],
            "regression suite and rulebook versions have diverged",
        )

    def test_every_regression_case(self) -> None:
        failures: list[str] = []

        for case in self.suite["cases"]:
            decision = self.gate.check(case["user_input"])
            fired = set(decision.rule_ids)

            if case["expect"] == "hard_stop" and not decision.blocked:
                failures.append(f"{case['id']}: expected a hard stop, nothing matched")
            if case["expect"] == "no_match" and decision.blocked:
                failures.append(
                    f"{case['id']}: expected no match, got {sorted(fired)} "
                    f"({list(decision.matched_signals)})"
                )

            required = set(case.get("expected_rule_ids", []))
            if required and not required.issubset(fired):
                failures.append(
                    f"{case['id']}: missing {sorted(required - fired)}, got {sorted(fired)}"
                )

            forbidden = set(case.get("forbidden_rule_ids", [])) & fired
            if forbidden:
                failures.append(f"{case['id']}: forbidden rules fired {sorted(forbidden)}")

        self.assertEqual(
            [], failures, f"{len(failures)} contract violation(s):\n" + "\n".join(failures)
        )

    def test_blocked_decision_carries_a_message_for_every_rule(self) -> None:
        """A hard stop must tell the patient what to do.

        The previous implementation returned on the first matching rule, so a
        filler vascular warning (RISK-07) was answered with the generic
        breathing and vision message from RISK-05.
        """
        decision = self.gate.check("필러 후 피부가 하얗게 변하고 시야가 흐려요")
        self.assertTrue(decision.blocked)
        self.assertIn("RISK-07", decision.rule_ids)
        self.assertTrue(decision.answer().strip())
        self.assertEqual(
            len(decision.messages),
            len({*decision.messages}),
            "duplicate guidance messages",
        )

    def test_hard_stop_requests_chatbot_stop(self) -> None:
        decision = self.gate.check("수술 부위에서 고름이 나와요")
        self.assertIn("stop_chatbot", decision.system_actions)

    def test_non_emergency_is_not_blocked(self) -> None:
        for text in [
            "약을 먹고 열이 내렸어요",
            "세안은 언제부터 가능한가요",
            "진물이 나지 않아요",
        ]:
            with self.subTest(text=text):
                self.assertFalse(self.gate.check(text).blocked)


if __name__ == "__main__":
    unittest.main()
