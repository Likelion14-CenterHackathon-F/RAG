"""Similarity cutoff and data-tier boundary for retrieval."""

from __future__ import annotations

import unittest
from dataclasses import replace

from centerton_rag.config import build_settings
from centerton_rag.retrieval import (
    build_retrieval_use_clause,
    retrieve_documents,
    select_documents,
    to_vector_literal,
)


def row(doc_id: str, distance: float, **overrides) -> dict:
    base = {
        "doc_id": doc_id,
        "title": f"title-{doc_id}",
        "content": f"content of {doc_id}",
        "answer_template": None,
        "source": "curated_mvp_rulebook",
        "dataset_type": "post_care_guide",
        "retrieval_use": None,
        "risk_level": "normal",
        "distance": distance,
    }
    base.update(overrides)
    return base


class SimilarityCutoffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = replace(build_settings(), rag_min_similarity=0.50, rag_top_k=5)

    def test_boundary_is_inclusive(self) -> None:
        """0.50 is kept, 0.49 is dropped.

        The threshold decides whether a document may ground an answer, so the
        boundary itself has to be pinned rather than left to a comparison
        operator nobody rechecks.
        """
        kept = select_documents([row("exact", 0.50)], 0.50, 5)
        self.assertEqual(["exact"], [document.doc_id for document in kept])

        dropped = select_documents([row("below", 0.51)], 0.50, 5)
        self.assertEqual([], dropped)

    def test_documents_below_threshold_are_removed_not_ranked(self) -> None:
        rows = [row("strong", 0.10), row("weak", 0.80), row("mid", 0.40)]
        kept = select_documents(rows, 0.50, 5)
        self.assertEqual(["strong", "mid"], [document.doc_id for document in kept])

    def test_top_k_limit(self) -> None:
        rows = [row(f"d{index}", 0.10 + index * 0.01) for index in range(10)]
        kept = select_documents(rows, 0.50, 3)
        self.assertEqual(3, len(kept))
        self.assertEqual(["d0", "d1", "d2"], [document.doc_id for document in kept])

    def test_similarity_is_clamped(self) -> None:
        kept = select_documents([row("negative", 1.40)], 0.0, 5)
        self.assertEqual(0.0, kept[0].similarity)

    def test_empty_result_is_empty_not_an_error(self) -> None:
        self.assertEqual([], select_documents([], 0.50, 5))


class TierBoundaryTest(unittest.TestCase):
    """Only the 90-document default index may ground a patient answer.

    `index_version` alone spans the expanded reference corpus and the evaluation
    holdout, so the query needs an explicit retrieval_use restriction.
    """

    def test_clause_requires_explicit_values_by_default(self) -> None:
        """Nothing in the deployed index has a NULL tier, so NULL is not allowed."""
        clause = build_retrieval_use_clause(build_settings())
        self.assertNotIn("IS NULL", clause)
        self.assertIn("ANY(%s)", clause)

    def test_clause_can_allow_null_when_asked(self) -> None:
        settings = replace(build_settings(), rag_allow_null_retrieval_use=True)
        clause = build_retrieval_use_clause(settings)
        self.assertIn("d.retrieval_use IS NULL", clause)

    def test_default_allowlist_excludes_expanded_and_holdout(self) -> None:
        allowed = set(build_settings().rag_allowed_retrieval_use)
        for excluded in [
            "ingredient_and_skin_care_reference_only",
            "makeup_and_skin_reference_only",
            "reference_only_not_postop_instruction",
        ]:
            with self.subTest(retrieval_use=excluded):
                self.assertNotIn(excluded, allowed)

    def test_default_allowlist_covers_all_three_tiers(self) -> None:
        """The allowlist must name every tier of the 90-document index.

        Omitting `curated` removed the 17 documents that carry the reviewed
        answer_template and left every expected document unreachable, so this
        assertion exists to keep that from recurring silently.
        """
        allowed = set(build_settings().rag_allowed_retrieval_use)
        self.assertIn("curated", allowed)
        self.assertIn("official_rag_candidate", allowed)
        self.assertIn("trusted_rag_candidate", allowed)

    def test_curated_tier_is_reachable(self) -> None:
        settings = build_settings()
        rows = [
            row("GUIDE-DERM-PICO-D1-D3-REDNESS", 0.30, retrieval_use="curated"),
            row("TRUSTED-X-0001", 0.35, retrieval_use="trusted_rag_candidate"),
        ]
        kept = select_documents(rows, settings.rag_min_similarity, settings.rag_top_k)
        self.assertIn("GUIDE-DERM-PICO-D1-D3-REDNESS", [d.doc_id for d in kept])


class PipelineWiringTest(unittest.TestCase):
    def test_retrieve_documents_uses_injected_embed_and_fetcher(self) -> None:
        settings = replace(build_settings(), rag_min_similarity=0.50, rag_top_k=2)
        seen: dict = {}

        def fake_embed(question: str) -> list[float]:
            seen["question"] = question
            return [0.1, 0.2, 0.3]

        def fake_fetch(vector_literal, _settings, candidate_limit):
            seen["vector"] = vector_literal
            seen["limit"] = candidate_limit
            return [row("a", 0.10), row("b", 0.20), row("c", 0.90)]

        documents = retrieve_documents(
            "붉은 기가 있어요", settings, embed=fake_embed, row_fetcher=fake_fetch
        )

        self.assertEqual("붉은 기가 있어요", seen["question"])
        self.assertEqual("[0.100000000,0.200000000,0.300000000]", seen["vector"])
        self.assertEqual(4, seen["limit"])
        self.assertEqual(["a", "b"], [document.doc_id for document in documents])

    def test_vector_literal_format(self) -> None:
        self.assertEqual("[1.000000000,-0.500000000]", to_vector_literal([1.0, -0.5]))


if __name__ == "__main__":
    unittest.main()
