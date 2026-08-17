"""Request and response schemas. Pydantic is confined to this module."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PreviousMessage(BaseModel):
    role: str
    content: str = ""


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    analysisImageUrl: str | None = None
    previousMessages: list[PreviousMessage] = Field(default_factory=list)

    def history(self) -> list[tuple[str, str]]:
        return [(message.role, message.content) for message in self.previousMessages]


class RagDocumentResponse(BaseModel):
    docId: str
    title: str
    source: str | None = None
    datasetType: str | None = None
    retrievalUse: str | None = None
    riskLevel: str | None = None
    similarity: float
    contentPreview: str


class AnswerResponse(BaseModel):
    answer: str
    route: str
    riskLevel: str
    indexVersion: str
    emergencyRuleVersion: str
    emergencyRuleId: str | None = None
    emergencyRuleIds: list[str] = Field(default_factory=list)
    blockedByEmergencyRule: bool = False
    allowRagAnswer: bool = True
    # ADR-0023: consultation is an attribute of a grounded answer, not a route
    # that skips retrieval.
    consultationCta: str | None = None
    triageReason: str | None = None
    matchedSignals: list[str] = Field(default_factory=list)
    recommendedAction: str | None = None
    systemActions: list[str] = Field(default_factory=list)
    confidence: float | None = None
    sourceRefs: list[str] = Field(default_factory=list)
    ragDocuments: list[RagDocumentResponse] = Field(default_factory=list)
