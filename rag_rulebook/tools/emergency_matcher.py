#!/usr/bin/env python3
"""Reference implementation of the emergency hard-stop matching contract.

`rules/emergency_rules.json` declares how patient text must be matched. This
module is the single source of truth for that behaviour so the validator, the
regression suite and the FastAPI/Spring services cannot drift apart.

Two normalised forms
--------------------
Korean patients space words inconsistently, so keywords are matched against a
whitespace-free form. Regular expressions, however, need word boundaries to
stay correct, therefore they are matched against a whitespace-preserving form.

  ``compact``  NFC -> lowercase -> remove all whitespace -> number aliases
               Used for ``trigger_keywords``.

  ``spaced``   NFC -> lowercase -> collapse whitespace to a single space ->
               trim -> number aliases
               Used for ``trigger_patterns``.

Why the split matters
---------------------
Removing whitespace destroys clause boundaries and silently creates tokens that
the patient never wrote. ``약을 먹고 열이 내렸어요`` ("I took medicine and the
fever came down") collapses to ``약을먹고열이내렸어요``, which contains the
substring ``고열이`` ("high fever"). A rule looking for 고열 then hard-stops a
reassuring message, blocking retrieval and generation entirely. Because the
boundary is already gone, no lookbehind can repair it, so patterns must run on
text where the space between ``먹고`` and ``열이`` still exists.

Patterns are therefore authored against ``spaced`` text: use ``\\s*`` where a
space is optional, and rely on the absence of ``\\s`` where adjacency is
required (``고열`` must be one word, ``열\\s*이`` may be split).
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "emergency_rules.json"

POLICY_KEYWORD_ONLY = "any_keyword"
POLICY_KEYWORD_OR_PATTERN = "any_keyword_or_pattern"


class RuleHit(NamedTuple):
    """A single rule that fired, with the evidence that triggered it."""

    rule_id: str
    name: str
    risk_level: str
    matched_by: str  # "keyword" or "pattern"
    evidence: str
    matched_text: str  # the span of normalised input that fired, for logging


class NormalizedInput(NamedTuple):
    compact: str
    spaced: str


class EmergencyMatcher:
    def __init__(self, rules: Dict[str, Any]) -> None:
        self.version: str = rules.get("version", "unknown")
        self._normalization: Dict[str, Any] = rules.get("normalization", {})
        self._number_aliases: Dict[str, str] = self._normalization.get("number_aliases", {}) or {}
        self._rules: List[Dict[str, Any]] = rules["rules"]
        self._compiled: Dict[str, List[re.Pattern[str]]] = {}

        guards = rules.get("negation_guards", {}) or {}
        self._negation_guards: List[re.Pattern[str]] = [
            re.compile(p) for p in guards.get("patterns", []) or []
        ]

        for rule in self._rules:
            compiled: List[re.Pattern[str]] = []
            for raw_pattern in rule.get("trigger_patterns", []) or []:
                try:
                    compiled.append(re.compile(raw_pattern))
                except re.error as exc:  # pragma: no cover - surfaced by validators
                    raise ValueError(
                        f"rule {rule['id']} has an invalid trigger_pattern {raw_pattern!r}: {exc}"
                    ) from exc
            self._compiled[rule["id"]] = compiled

    # ---------------------------------------------------------------- loading

    @classmethod
    def from_path(cls, path: Path = DEFAULT_RULES_PATH) -> "EmergencyMatcher":
        with path.open("r", encoding="utf-8") as handle:
            return cls(json.load(handle))

    # ----------------------------------------------------------- normalisation

    def _apply_aliases(self, text: str, collapse: bool) -> str:
        for alias, canonical in self._number_aliases.items():
            alias_norm = unicodedata.normalize("NFC", alias).lower()
            alias_norm = (
                re.sub(r"\s+", "", alias_norm) if collapse else re.sub(r"\s+", " ", alias_norm)
            )
            if alias_norm:
                text = text.replace(alias_norm, canonical)
        return text

    def normalize_compact(self, text: str) -> str:
        """Whitespace-free form used for ``trigger_keywords``."""
        if self._normalization.get("normalize_korean", True):
            text = unicodedata.normalize("NFC", text)
        if self._normalization.get("case", "lower") == "lower":
            text = text.lower()
        text = re.sub(r"\s+", "", text)
        return self._apply_aliases(text, collapse=True)

    def normalize_spaced(self, text: str) -> str:
        """Whitespace-preserving form used for ``trigger_patterns``."""
        if self._normalization.get("normalize_korean", True):
            text = unicodedata.normalize("NFC", text)
        if self._normalization.get("case", "lower") == "lower":
            text = text.lower()
        text = re.sub(r"\s+", " ", text).strip()
        return self._apply_aliases(text, collapse=False)

    def normalize(self, text: str) -> str:
        """Backwards-compatible alias for the compact form."""
        return self.normalize_compact(text)

    def normalize_both(self, text: str) -> NormalizedInput:
        return NormalizedInput(
            compact=self.normalize_compact(text),
            spaced=self.normalize_spaced(text),
        )

    # -------------------------------------------------- negation suppression

    def is_negated(self, remainder: str) -> bool:
        """True when the text right after a trigger reports the symptom as absent.

        ``search`` is used rather than ``match`` so that the anchoring lives in
        the rulebook itself: every guard is authored with a leading ``^`` and
        `validate_emergency_rules.py` enforces that. Anchoring is not cosmetic.
        An unanchored guard would let a later, unrelated negation cancel a real
        emergency: in ``고름이 나오고 통증은 없어요`` the 없 belongs to 통증,
        not to 고름, and suppressing the pus trigger there would hide a genuine
        infection signal.
        """
        return any(guard.search(remainder) for guard in self._negation_guards)

    # -------------------------------------------------------------- matching

    def _keyword_hit(
        self, rule: Dict[str, Any], compact: str
    ) -> Optional[RuleHit]:
        """First keyword occurrence that is not cancelled by a negation guard.

        Every occurrence is scanned, not just the first, so that
        ``고름은 없지만 다른 곳에서 고름이 나와요`` still fires.
        """
        for keyword in rule.get("trigger_keywords", []) or []:
            needle = self.normalize_compact(keyword)
            if not needle:
                continue
            start = compact.find(needle)
            while start != -1:
                end = start + len(needle)
                if not self.is_negated(compact[end:]):
                    return RuleHit(
                        rule_id=rule["id"],
                        name=rule.get("name", ""),
                        risk_level=rule.get("risk_level", "high"),
                        matched_by="keyword",
                        evidence=keyword,
                        matched_text=needle,
                    )
                start = compact.find(needle, start + 1)
        return None

    def _pattern_hit(self, rule: Dict[str, Any], spaced: str) -> Optional[RuleHit]:
        for pattern in self._compiled[rule["id"]]:
            for found in pattern.finditer(spaced):
                if not self.is_negated(spaced[found.end():]):
                    return RuleHit(
                        rule_id=rule["id"],
                        name=rule.get("name", ""),
                        risk_level=rule.get("risk_level", "high"),
                        matched_by="pattern",
                        evidence=pattern.pattern,
                        matched_text=found.group(0),
                    )
        return None

    def match(self, user_input: str) -> List[RuleHit]:
        """Return every rule that fires for ``user_input``, in rulebook order."""
        forms = self.normalize_both(user_input)
        hits: List[RuleHit] = []

        for rule in self._rules:
            hit = self._keyword_hit(rule, forms.compact)

            if hit is None and rule.get("match_policy", POLICY_KEYWORD_ONLY) == (
                POLICY_KEYWORD_OR_PATTERN
            ):
                hit = self._pattern_hit(rule, forms.spaced)

            if hit is not None:
                hits.append(hit)

        return hits

    def matched_rule_ids(self, user_input: str) -> List[str]:
        return [hit.rule_id for hit in self.match(user_input)]

    def is_hard_stop(self, user_input: str) -> bool:
        """Kept as the Python side of the contract mirrored by
        ``EmergencyRuleMatcher.isHardStop`` in Java. The Spring regression suite
        asserts against it, so removing it here would let the two implementations
        drift on the exact question the suite is meant to pin down.
        """
        return bool(self.match(user_input))

    @property
    def rule_ids(self) -> List[str]:
        return [rule["id"] for rule in self._rules]


def load_matcher(path: Path = DEFAULT_RULES_PATH) -> EmergencyMatcher:
    return EmergencyMatcher.from_path(path)


if __name__ == "__main__":
    import sys

    matcher = load_matcher()
    if len(sys.argv) < 2:
        print(f"rulebook {matcher.version}, {len(matcher.rule_ids)} rules: {matcher.rule_ids}")
        print("usage: emergency_matcher.py '환자 입력 문장'")
        raise SystemExit(0)

    text = " ".join(sys.argv[1:])
    forms = matcher.normalize_both(text)
    print(f"input   : {text}")
    print(f"compact : {forms.compact}")
    print(f"spaced  : {forms.spaced}")
    found = matcher.match(text)
    if not found:
        print("result  : no hard-stop rule matched")
    else:
        print("result  : HARD STOP")
        for hit in found:
            print(f"  - {hit.rule_id} ({hit.name}) via {hit.matched_by}")
            print(f"      evidence : {hit.evidence}")
            print(f"      matched  : {hit.matched_text}")
