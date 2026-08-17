"""ADR-0016: no evidence means the generator is never called.

The point of these tests is the negative: proving that the OpenAI call does not
happen. A test that only checked the returned text would still pass if the model
were called and its output discarded.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from centerton_rag import answer as answer_module
from centerton_rag.config import build_settings
from centerton_rag.retrieval import RetrievedDocument


def document(doc_id: str = "GUIDE-1", content: str = "내용", similarity: float = 0.8):
    return RetrievedDocument(
        doc_id=doc_id,
        title="제목",
        content=content,
        answer_template=None,
        source="curated_mvp_rulebook",
        dataset_type="post_care_guide",
        retrieval_use=None,
        risk_level="normal",
        similarity=similarity,
        distance=1.0 - similarity,
    )


class GenerationGateTest(unittest.TestCase):
    def test_no_documents_blocks_generation(self) -> None:
        self.assertFalse(answer_module.should_generate([]))

    def test_documents_with_only_blank_content_block_generation(self) -> None:
        """A row that clears the threshold but carries no text is not evidence."""
        self.assertFalse(answer_module.should_generate([document(content="   ")]))

    def test_documents_with_content_allow_generation(self) -> None:
        self.assertTrue(answer_module.should_generate([document()]))

    def test_generate_answer_refuses_without_evidence(self) -> None:
        settings = replace(build_settings(), openai_api_key="test-key")
        with self.assertRaises(answer_module.GenerationUnavailable):
            answer_module.generate_answer("질문", [], settings)

    def test_generate_answer_does_not_reach_openai_without_evidence(self) -> None:
        """Fail before any client construction, not during the request."""
        settings = replace(build_settings(), openai_api_key="test-key")
        calls: list[str] = []
        original = answer_module.build_openai_input

        def spy(*args, **kwargs):
            calls.append("built")
            return original(*args, **kwargs)

        answer_module.build_openai_input = spy  # type: ignore[assignment]
        try:
            with self.assertRaises(answer_module.GenerationUnavailable):
                answer_module.generate_answer("질문", [], settings)
        finally:
            answer_module.build_openai_input = original  # type: ignore[assignment]

        self.assertEqual([], calls, "prompt was built despite having no evidence")


class InsufficientEvidenceCopyTest(unittest.TestCase):
    def test_fixed_answer_asks_for_the_fields_adr_0016_requires(self) -> None:
        text = answer_module.INSUFFICIENT_EVIDENCE_ANSWER
        for required in ["시술명", "경과일", "체온", "병원"]:
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_fixed_answer_does_not_reassure(self) -> None:
        text = answer_module.INSUFFICIENT_EVIDENCE_ANSWER
        for forbidden in ["괜찮습니다", "정상입니다", "안심"]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)


class DeveloperPromptTest(unittest.TestCase):
    """ADR-0017 layer two lives in this prompt now that every non-emergency
    question reaches the answer path."""

    def test_prompt_handles_signals_the_rulebook_missed(self) -> None:
        prompt = answer_module.DEVELOPER_PROMPT
        self.assertIn("룰셋이 모든 표현을 잡지는 못", prompt)
        self.assertIn("근거에 없더라도", prompt)

    def test_prompt_forbids_reassuring_certainty(self) -> None:
        self.assertIn("괜찮다고 단정하지 마세요", answer_module.DEVELOPER_PROMPT)

    def test_prompt_forbids_inventing_treatment(self) -> None:
        prompt = answer_module.DEVELOPER_PROMPT
        self.assertIn("근거에 없는", prompt)
        self.assertIn("확정 진단", prompt)


class PromptBuildingTest(unittest.TestCase):
    def test_evidence_is_passed_with_doc_id_and_similarity(self) -> None:
        prompt = answer_module.build_user_prompt("붉은 기", [document("GUIDE-X")])
        self.assertIn("GUIDE-X", prompt)
        self.assertIn("similarity", prompt)

    def test_image_note_warns_against_diagnosis(self) -> None:
        prompt = answer_module.build_user_prompt("질문", [document()], has_image=True)
        self.assertIn("확정 진단하지 마세요", prompt)


if __name__ == "__main__":
    unittest.main()
