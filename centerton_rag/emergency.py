"""Emergency hard-stop check.

This module deliberately contains no matching logic. ADR-0022 makes
`rag_rulebook.tools.emergency_matcher` the single implementation of the rulebook
contract, because a second implementation in the service drifted and produced 18
false positives out of 66 regression cases: patterns were evaluated on the
whitespace-stripped form (ADR-0018) and the negation guards were missing
entirely (ADR-0019).

Anything beyond loading the rulebook and shaping the result belongs in the
matcher, not here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from rag_rulebook.tools.emergency_matcher import EmergencyMatcher, RuleHit


@dataclass(frozen=True)
class EmergencyDecision:
    """Outcome of the hard-stop check for one patient message."""

    blocked: bool
    rulebook_version: str
    rule_ids: tuple[str, ...] = ()
    matched_signals: tuple[str, ...] = ()
    messages: tuple[str, ...] = ()
    system_actions: tuple[str, ...] = ()
    hits: tuple[RuleHit, ...] = field(default=(), repr=False)

    @property
    def primary_rule_id(self) -> str | None:
        return self.rule_ids[0] if self.rule_ids else None

    def answer(self) -> str:
        return "\n".join(self.messages)


class EmergencyGate:
    def __init__(self, matcher: EmergencyMatcher, rules: Sequence[dict[str, Any]]) -> None:
        self._matcher = matcher
        self._rules_by_id = {rule["id"]: rule for rule in rules}

    @property
    def version(self) -> str:
        return self._matcher.version

    def check(self, text: str) -> EmergencyDecision:
        hits = self._matcher.match(text)
        if not hits:
            return EmergencyDecision(blocked=False, rulebook_version=self.version)

        messages: list[str] = []
        actions: list[str] = []
        for hit in hits:
            rule = self._rules_by_id.get(hit.rule_id, {})
            message = rule.get("frontend_message", "").strip()
            # Several rules can fire at once. Keeping every distinct message is
            # what stops a filler vascular warning (RISK-07) from being replaced
            # by whichever rule happens to be declared first.
            if message and message not in messages:
                messages.append(message)
            for action in rule.get("system_actions", []) or []:
                if action not in actions:
                    actions.append(action)

        return EmergencyDecision(
            blocked=True,
            rulebook_version=self.version,
            rule_ids=tuple(hit.rule_id for hit in hits),
            matched_signals=tuple(
                f"{hit.rule_id}:{hit.matched_text}" for hit in hits
            ),
            messages=tuple(messages),
            system_actions=tuple(actions),
            hits=tuple(hits),
        )


def load_gate(rules_path: Path) -> EmergencyGate:
    if not rules_path.exists():
        raise RuntimeError(f"emergency rules not found: {rules_path}")
    matcher = EmergencyMatcher.from_path(rules_path)
    payload = json.loads(rules_path.read_text(encoding="utf-8"))
    return EmergencyGate(matcher, payload.get("rules", []))
