"""ADR-0023: the consultation CTA is derived from evidence, deterministically."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from centerton_rag.consultation import (
    CTA_URGENT_CLINIC,
    CTA_VIDEO_CONSULT,
    derive_consultation_cta,
    derive_risk_level,
    recommended_action,
)
from centerton_rag.retrieval import RetrievedDocument

REPO_ROOT = Path(__file__).resolve().parents[1]
CURATED_PATH = REPO_ROOT / "rag_rulebook" / "rag" / "mvp_care_knowledge.jsonl"


def document(doc_id: str, dataset_type: str = "post_care_guide", risk_level: str = "normal"):
    return RetrievedDocument(
        doc_id=doc_id,
        title=doc_id,
        content="내용",
        answer_template=None,
        source="curated_mvp_rulebook",
        dataset_type=dataset_type,
        retrieval_use=None,
        risk_level=risk_level,
        similarity=0.7,
        distance=0.3,
    )


class ConsultationCtaTest(unittest.TestCase):
    def test_no_cta_for_ordinary_guidance(self) -> None:
        self.assertIsNone(derive_consultation_cta([document("GUIDE-1")]))

    def test_video_consult_trigger_dataset_type(self) -> None:
        docs = [document("SYM-RHINO", dataset_type="video_consult_trigger", risk_level="watch")]
        self.assertEqual(CTA_VIDEO_CONSULT, derive_consultation_cta(docs))

    def test_watch_risk_level_alone_is_enough(self) -> None:
        docs = [document("GUIDE-RHINO", risk_level="watch")]
        self.assertEqual(CTA_VIDEO_CONSULT, derive_consultation_cta(docs))

    def test_urgent_outranks_video_consult(self) -> None:
        docs = [
            document("SYM-RHINO", dataset_type="video_consult_trigger", risk_level="watch"),
            document("SYM-OOZING", risk_level="urgent"),
        ]
        self.assertEqual(CTA_URGENT_CLINIC, derive_consultation_cta(docs))

    def test_no_documents_means_no_cta(self) -> None:
        self.assertIsNone(derive_consultation_cta([]))

    def test_risk_level_is_the_most_conservative_present(self) -> None:
        docs = [document("a"), document("b", risk_level="watch")]
        self.assertEqual("watch", derive_risk_level(docs))

    def test_risk_level_unknown_without_evidence(self) -> None:
        self.assertEqual("unknown", derive_risk_level([]))

    def test_recommended_action_matches_cta(self) -> None:
        self.assertIn("화상 상담", recommended_action(CTA_VIDEO_CONSULT) or "")
        self.assertIn("병원", recommended_action(CTA_URGENT_CLINIC) or "")
        self.assertIsNone(recommended_action(None))


class CuratedDataAlignmentTest(unittest.TestCase):
    """The CTA rules must match the metadata curation actually assigned.

    ADR-0023 relies on `dataset_type` and `risk_level` already present in
    mvp_care_knowledge.jsonl. If curation stops using those values the derivation
    silently produces no CTA, so the coupling is asserted here.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.curated = [
            json.loads(line)
            for line in CURATED_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_video_consult_trigger_documents_exist(self) -> None:
        triggers = [
            doc for doc in self.curated if doc.get("dataset_type") == "video_consult_trigger"
        ]
        self.assertTrue(triggers, "no video_consult_trigger documents in the curated index")

    def test_rhinoplasty_asymmetry_document_yields_video_consult(self) -> None:
        """TC-RHINO-01 is the revenue scenario. Under the previous pre-RAG
        classifier this document could never be retrieved at all."""
        source = next(
            doc for doc in self.curated if doc["doc_id"] == "SYM-RHINO-ASYMMETRY-ANXIETY"
        )
        retrieved = document(
            source["doc_id"],
            dataset_type=source["dataset_type"],
            risk_level=source["risk_level"],
        )
        self.assertEqual(CTA_VIDEO_CONSULT, derive_consultation_cta([retrieved]))

    def test_every_document_flagged_video_consult_produces_a_cta(self) -> None:
        missing: list[str] = []
        for source in self.curated:
            if not source.get("video_consult"):
                continue
            retrieved = document(
                source["doc_id"],
                dataset_type=source.get("dataset_type", ""),
                risk_level=source.get("risk_level", ""),
            )
            if derive_consultation_cta([retrieved]) is None:
                missing.append(source["doc_id"])
        self.assertEqual(
            [], missing, f"documents marked video_consult produced no CTA: {missing}"
        )


if __name__ == "__main__":
    unittest.main()
