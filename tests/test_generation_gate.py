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

    def test_prompt_allows_reassurance_only_under_all_three_conditions(self) -> None:
        """정상 경과 단정은 조건부로만 허용된다.

        이전에는 "괜찮다고 단정하지 마세요" 라는 무조건 금지였다. 그 결과 근거가
        해당 시기의 정상 반응을 명시하고 위험 신호도 없는 문의에도 "사진이나 현재
        정보만으로 단정할 수 없습니다" 가 붙어, 안심시켜야 하는 상황에서 오히려
        불안을 남겼다.

        금지를 조건부 허용으로 바꾸되 조건 세 개를 모두 요구한다. 이 테스트는
        조건이 프롬프트에서 사라지지 않도록 고정한다.
        """
        prompt = answer_module.DEVELOPER_PROMPT
        for condition in [
            # (1) 근거가 그 시기의 정상 반응임을 명시해야 한다
            "근거가 해당 시술과 경과 시기",
            # (2) 환자가 말한 시술과 시기가 근거 범위와 일치해야 한다
            "근거의 범위와 일치",
            # (3) 위험 신호가 없어야 한다
            "위험 신호가 없다",
        ]:
            with self.subTest(condition=condition):
                self.assertIn(condition, prompt)

    def test_prompt_forbids_reassurance_when_conditions_are_unmet(self) -> None:
        """조건이 어긋나면 단정을 금지한다. 특히 시술명과 경과 시기가 없는 경우다.

        시기를 모르면 어떤 근거도 특정 시점에 적용할 수 없다. 이 금지가 빠지면
        "얼굴이 붉어요" 처럼 맥락 없는 문의에도 정상이라고 답할 수 있다.
        """
        prompt = answer_module.DEVELOPER_PROMPT
        self.assertIn("정상이라고 단정하지 말고", prompt)
        self.assertIn("시술명이나", prompt)
        self.assertIn("경과 시기를 밝히지 않았다면", prompt)

    def test_prompt_keeps_escalation_criteria_even_when_reassuring(self) -> None:
        """정상이라고 답하는 경우에도 병원 연락 기준은 함께 안내해야 한다."""
        prompt = answer_module.DEVELOPER_PROMPT
        self.assertIn("정상이라고 전달하는 경우에도", prompt)
        self.assertIn("병원에 연락할 기준", prompt)

    def test_prompt_scopes_the_photo_limit_to_diagnosis(self) -> None:
        """사진 제한은 병명 확정에만 적용된다.

        이전 문구("사진만으로 진단을 확정하지 마세요")가 안심 설명까지 번져
        "사진이나 현재 정보만으로는" 이라는 유보를 만들었다.
        """
        prompt = answer_module.DEVELOPER_PROMPT
        self.assertIn("사진만으로 병명이나 합병증을 확정하지 마세요", prompt)

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
