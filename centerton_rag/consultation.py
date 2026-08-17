"""Consultation CTA and risk level derived from retrieved evidence.

ADR-0023 replaced the pre-RAG LLM classifier with this. Previously a classifier
decided `video_consult` *before* retrieval and returned early, so the very
documents written for that case — `SYM-RHINO-ASYMMETRY-ANXIETY`,
`COMMON-LOW-CONFIDENCE-PHOTO` — could never be retrieved.

Deriving the CTA from evidence keeps the decision deterministic, costs no extra
model call, and reuses `risk_level` and `dataset_type` that curation already
assigned.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .retrieval import RetrievedDocument

CTA_URGENT_CLINIC = "urgent_clinic"
CTA_VIDEO_CONSULT = "video_consult"

VIDEO_CONSULT_DATASET_TYPES = frozenset({"video_consult_trigger"})
URGENT_RISK_LEVELS = frozenset({"urgent"})
WATCH_RISK_LEVELS = frozenset({"watch"})

# Ordered from most to least conservative.
RISK_LEVEL_ORDER = ("urgent", "watch", "normal")


def _normalise(value: str | None) -> str:
    return (value or "").strip().lower()


def derive_consultation_cta(documents: Sequence[RetrievedDocument]) -> str | None:
    """Return the CTA implied by the evidence, or None.

    `urgent_clinic` outranks `video_consult`: if any grounding document is marked
    urgent, pointing the patient at a scheduled video call would understate it.
    """
    has_video_consult = False
    for document in documents:
        if _normalise(document.risk_level) in URGENT_RISK_LEVELS:
            return CTA_URGENT_CLINIC
        if _normalise(document.dataset_type) in VIDEO_CONSULT_DATASET_TYPES:
            has_video_consult = True
        elif _normalise(document.risk_level) in WATCH_RISK_LEVELS:
            has_video_consult = True
    return CTA_VIDEO_CONSULT if has_video_consult else None


def derive_risk_level(documents: Sequence[RetrievedDocument]) -> str:
    """Highest risk level present in the evidence.

    `unknown` when nothing was retrieved or nothing carried a level, so the
    response never implies a reassuring assessment we cannot support.
    """
    levels = {_normalise(document.risk_level) for document in documents}
    for level in RISK_LEVEL_ORDER:
        if level in levels:
            return level
    return "unknown"


def recommended_action(cta: str | None) -> str | None:
    if cta == CTA_URGENT_CLINIC:
        return "시술 병원 또는 가까운 병원에 빠르게 문의해 주세요."
    if cta == CTA_VIDEO_CONSULT:
        return "정확한 상태 확인을 위해 화상 상담 예약을 권장드립니다."
    return None


def source_references(documents: Iterable[RetrievedDocument]) -> list[str]:
    seen: list[str] = []
    for document in documents:
        if document.source and document.source not in seen:
            seen.append(document.source)
    return seen
