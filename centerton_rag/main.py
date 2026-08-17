"""Centerton aftercare RAG service.

Flow, per ADR-0022 and ADR-0023:

    질문
      -> 응급 룰 검사 (rag_rulebook 단일 구현)
         -> 매칭: 고정 안내 반환. 임베딩/검색/생성 금지
         -> 미매칭: 항상 검색
      -> pgvector 기본 색인(90개) 검색, RAG_MIN_SIMILARITY 컷오프
         -> 0건: insufficient_evidence. OpenAI 호출 금지 (ADR-0016)
         -> 있으면: 근거 기반 생성 + 근거에서 도출한 상담 CTA

There is no pre-RAG classifier. Retrieval gathers evidence; it is not a
judgement that may be skipped because a question looks risky.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Sequence

from fastapi import FastAPI, HTTPException

from . import answer as answer_module
from .config import Settings, get_settings
from .consultation import (
    derive_consultation_cta,
    derive_risk_level,
    recommended_action,
    source_references,
)
from .emergency import EmergencyGate, load_gate
from .models import AnswerRequest, AnswerResponse, RagDocumentResponse
from .retrieval import (
    RetrievalUnavailable,
    RetrievedDocument,
    retrieve_documents,
)

app = FastAPI(title="Centerton Aftercare RAG Service")


@lru_cache
def get_gate() -> EmergencyGate:
    return load_gate(get_settings().rules_path)


@lru_cache
def get_embedding_model() -> Any:  # pragma: no cover - model load
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(get_settings().kure_model)


def embed_query(question: str) -> list[float]:  # pragma: no cover - model load
    model = get_embedding_model()
    embedding = model.encode(
        [question],
        batch_size=1,
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]
    return [float(value) for value in embedding]


def to_document_response(document: RetrievedDocument) -> RagDocumentResponse:
    return RagDocumentResponse(
        docId=document.doc_id,
        title=document.title,
        source=document.source,
        datasetType=document.dataset_type,
        retrievalUse=document.retrieval_use,
        riskLevel=document.risk_level,
        similarity=document.similarity,
        contentPreview=document.content.replace("\n", " ")[:240],
    )


@app.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    gate = get_gate()
    return {
        "status": "ok",
        "indexVersion": settings.rag_index_version,
        "embeddingModel": settings.kure_model,
        "emergencyRuleVersion": gate.version,
        "minSimilarity": settings.rag_min_similarity,
        "topK": settings.rag_top_k,
        "allowedRetrievalUse": list(settings.rag_allowed_retrieval_use),
        "allowNullRetrievalUse": settings.rag_allow_null_retrieval_use,
    }


@app.post("/v1/aftercare/answer", response_model=AnswerResponse)
def answer_aftercare_question(request: AnswerRequest) -> AnswerResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    settings = get_settings()
    gate = get_gate()

    decision = gate.check(question)
    if decision.blocked:
        return build_emergency_response(decision, settings)

    try:
        documents = retrieve_documents(question, settings, embed=embed_query)
    except RetrievalUnavailable as exc:
        # Surfaced as 503 on purpose: an outage must stay visible to monitoring
        # and to Spring, which fails closed with a conservative message. Silently
        # returning insufficient_evidence would hide the outage.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not answer_module.should_generate(documents):
        return build_insufficient_evidence_response(settings, gate.version)

    try:
        generated = answer_module.generate_answer(
            question,
            documents,
            settings,
            previous_messages=request.history(),
            image_url=request.analysisImageUrl,
        )
    except answer_module.GenerationUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return build_grounded_response(generated, documents, settings, gate.version)


def build_emergency_response(decision: Any, settings: Settings) -> AnswerResponse:
    return AnswerResponse(
        answer=decision.answer(),
        route="hard_stop",
        riskLevel="high",
        indexVersion=settings.rag_index_version,
        emergencyRuleVersion=decision.rulebook_version,
        emergencyRuleId=decision.primary_rule_id,
        emergencyRuleIds=list(decision.rule_ids),
        blockedByEmergencyRule=True,
        allowRagAnswer=False,
        triageReason="응급 hard-stop 룰에 매칭되었습니다.",
        matchedSignals=list(decision.matched_signals),
        recommendedAction=decision.answer(),
        systemActions=list(decision.system_actions),
        confidence=1.0,
        ragDocuments=[],
    )


def build_insufficient_evidence_response(
    settings: Settings, rulebook_version: str
) -> AnswerResponse:
    return AnswerResponse(
        answer=answer_module.INSUFFICIENT_EVIDENCE_ANSWER,
        route="insufficient_evidence",
        riskLevel="unknown",
        indexVersion=settings.rag_index_version,
        emergencyRuleVersion=rulebook_version,
        allowRagAnswer=False,
        triageReason=(
            f"유사도 {settings.rag_min_similarity:.2f} 이상인 RAG 근거 문서를 찾지 못했습니다."
        ),
        recommendedAction=answer_module.INSUFFICIENT_EVIDENCE_ACTION,
        confidence=0.0,
        ragDocuments=[],
    )


def build_grounded_response(
    generated: str,
    documents: Sequence[RetrievedDocument],
    settings: Settings,
    rulebook_version: str,
) -> AnswerResponse:
    cta = derive_consultation_cta(documents)
    return AnswerResponse(
        answer=generated,
        route="rag_answer",
        riskLevel=derive_risk_level(documents),
        indexVersion=settings.rag_index_version,
        emergencyRuleVersion=rulebook_version,
        allowRagAnswer=True,
        consultationCta=cta,
        recommendedAction=recommended_action(cta),
        confidence=max(document.similarity for document in documents),
        sourceRefs=source_references(documents),
        ragDocuments=[to_document_response(document) for document in documents],
    )
