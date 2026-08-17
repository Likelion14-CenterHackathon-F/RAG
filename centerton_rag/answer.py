"""Answer generation and the guardrails around it.

Two invariants live here.

ADR-0016: when no document clears `RAG_MIN_SIMILARITY`, the generator is not
called at all. `should_generate()` is the single place that decides this, so the
contract can be tested without an OpenAI client.

ADR-0017: this path now runs for every non-emergency question, which is what
makes it the second safety layer. The developer prompt therefore has to handle
danger signals the rulebook did not catch, instead of assuming triage already
filtered them out.
"""

from __future__ import annotations

from typing import Any, Sequence

from .config import Settings
from .retrieval import RetrievedDocument

INSUFFICIENT_EVIDENCE_ANSWER = "\n".join([
    "현재 질문과 충분히 관련된 검증된 사후관리 근거를 찾지 못했습니다.",
    "근거가 부족한 상태에서 일반적인 추측으로 답변하지 않겠습니다.",
    "시술명, 시술 부위, 시술 후 경과일, 증상의 변화와 체온을 포함해 다시 문의하거나 시술 병원에 사진과 함께 확인해 주세요.",
    "증상이 빠르게 악화되거나 호흡 불편, 의식 저하, 멈추지 않는 출혈, 시야 이상이 있으면 즉시 병원 또는 응급실에 연락해 주세요.",
    "의료진 진료를 대체하지 않는 안내입니다.",
])

INSUFFICIENT_EVIDENCE_ACTION = "시술 병원에 사진과 증상 정보를 함께 전달해 확인해 주세요."

DEVELOPER_PROMPT = """
당신은 피부과/성형외과 시술 후 사후관리 챗봇입니다.

근거 사용 원칙
- 제공된 RAG 근거 안에서만 답변하세요. 근거에 없는 처치, 약 복용, 항생제, 시술 필요 여부, 확정 진단을 만들지 마세요.
- 근거가 환자 상황과 어긋나면 근거를 억지로 적용하지 말고 확인이 필요하다고 안내하세요.
- 사진만으로 진단을 확정하지 마세요.
- 병원에서 받은 개별 지침이 있으면 병원 지침을 우선하도록 안내하세요.

위험 신호 처리
- 응급 룰셋은 이미 통과한 문의입니다. 그러나 룰셋이 모든 표현을 잡지는 못합니다.
- 근거에 없더라도 환자 입력이나 이미지에서 위험 신호가 의심되면 일반 사후관리 안내로 마무리하지 말고 병원 또는 응급실 확인을 권하세요.
- 위험 신호 예: 멈추지 않는 출혈, 호흡 불편, 의식 저하, 급격한 부종, 참기 어려운 통증, 고름이나 악취, 고열, 시야 이상, 피부색이 하얗게 또는 파랗게 변함.
- 괜찮다고 단정하지 마세요. 정상 범위로 보인다는 설명은 근거가 뒷받침할 때만 하세요.

답변 구성
1) 입력된 상태와 경과 요약
2) 근거에 따른 관리 방향
3) 관찰할 변화와 병원에 연락해야 하는 기준
4) 사용한 근거 문서 제목

마지막에 의료진 진료를 대체하지 않는다는 문장을 포함하세요.
""".strip()


def should_generate(documents: Sequence[RetrievedDocument]) -> bool:
    """ADR-0016 gate. No evidence means no generation."""
    if not documents:
        return False
    # A row with empty content or no source cannot ground anything, so treating
    # it as evidence would reintroduce ungrounded generation through the back door.
    return any(document.content.strip() for document in documents)


def truncate(value: str | None, max_length: int) -> str:
    if not value:
        return ""
    if len(value) <= max_length:
        return value
    return value[:max_length]


def build_user_prompt(
    question: str,
    documents: Sequence[RetrievedDocument],
    previous_messages: Sequence[tuple[str, str]] = (),
    has_image: bool = False,
) -> str:
    parts: list[str] = []

    if previous_messages:
        parts.append("이전 대화:")
        for role, content in previous_messages[-10:]:
            label = "AI" if role.upper() == "ASSISTANT" else "환자"
            parts.append(f"{label}: {truncate(content, 500)}")
        parts.append("")

    parts.append("현재 문의:")
    parts.append(question.strip())

    if has_image:
        parts.append("")
        parts.append("첨부된 이미지를 함께 참고하되 확정 진단하지 마세요.")

    parts.append("")
    parts.append("RAG 검색 근거:")
    for index, document in enumerate(documents, 1):
        parts.append(f"[{index}] {document.title}")
        parts.append(f"- doc_id: {document.doc_id}")
        parts.append(f"- source: {document.source or '없음'}")
        parts.append(f"- dataset_type: {document.dataset_type or '없음'}")
        parts.append(f"- retrieval_use: {document.retrieval_use or '없음'}")
        parts.append(f"- risk_level: {document.risk_level or '없음'}")
        parts.append(f"- similarity: {document.similarity:.3f}")
        parts.append(f"- content: {truncate(document.content, 900)}")
        if document.answer_template:
            parts.append(f"- answer_template: {truncate(document.answer_template, 500)}")

    return "\n".join(parts)


def build_openai_input(
    question: str,
    documents: Sequence[RetrievedDocument],
    previous_messages: Sequence[tuple[str, str]] = (),
    image_url: str | None = None,
) -> list[dict[str, Any]]:
    user_content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": build_user_prompt(
                question, documents, previous_messages, has_image=bool(image_url)
            ),
        }
    ]
    if image_url:
        user_content.append(
            {"type": "input_image", "image_url": image_url, "detail": "high"}
        )

    return [
        {
            "role": "developer",
            "content": [{"type": "input_text", "text": DEVELOPER_PROMPT}],
        },
        {"role": "user", "content": user_content},
    ]


class GenerationUnavailable(RuntimeError):
    pass


def generate_answer(
    question: str,
    documents: Sequence[RetrievedDocument],
    settings: Settings,
    previous_messages: Sequence[tuple[str, str]] = (),
    image_url: str | None = None,
) -> str:
    if not should_generate(documents):
        # Defensive: callers must check first. Reaching here would mean the
        # ADR-0016 gate was bypassed.
        raise GenerationUnavailable("refusing to generate without evidence")
    if not settings.openai_api_key:
        raise GenerationUnavailable("OPENAI_API_KEY is missing")

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - deployment concern
        raise GenerationUnavailable("openai package is not installed") from exc

    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
    try:
        response = client.responses.create(
            model=settings.openai_model,
            input=build_openai_input(question, documents, previous_messages, image_url),
            max_output_tokens=settings.openai_max_output_tokens,
        )
    except Exception as exc:  # pragma: no cover - upstream failure
        raise GenerationUnavailable("OpenAI response generation failed") from exc

    answer = getattr(response, "output_text", None)
    if answer and answer.strip():
        return answer.strip()
    raise GenerationUnavailable("OpenAI response text is empty")
