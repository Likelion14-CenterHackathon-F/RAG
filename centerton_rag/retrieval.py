"""pgvector retrieval over the default patient-answer index.

The selection rules are kept as pure functions so the similarity cutoff and the
tier boundary can be verified without a database or an embedding model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from .config import Settings, database_kwargs

# `answer_template` is intentionally retrieved: for curated documents it carries
# the reviewed phrasing. `dataset_type` and `risk_level` drive the consultation
# CTA (ADR-0023), so they must stay in the projection.
SELECT_SQL = """
WITH query_embedding AS (
  SELECT %s::vector AS embedding
)
SELECT
  d.doc_id,
  d.title,
  d.content,
  d.answer_template,
  d.source,
  d.dataset_type,
  d.retrieval_use,
  d.risk_level,
  d.embedding <=> query_embedding.embedding AS distance
FROM rag_documents d, query_embedding
WHERE d.index_version = %s
  AND d.embedding_storage = 'pgvector'
  AND d.embedding IS NOT NULL
  AND ({retrieval_use_clause})
ORDER BY d.embedding <=> query_embedding.embedding
LIMIT %s
"""


class RetrievalUnavailable(RuntimeError):
    """Raised when retrieval cannot run at all, as opposed to finding nothing."""


@dataclass(frozen=True)
class RetrievedDocument:
    doc_id: str
    title: str
    content: str
    answer_template: str | None
    source: str | None
    dataset_type: str | None
    retrieval_use: str | None
    risk_level: str | None
    similarity: float
    distance: float


def build_retrieval_use_clause(settings: Settings) -> str:
    """Restrict retrieval to the default patient-answer index.

    Without this clause the query spans whatever shares `index_version`, which
    for `2026-08-15-expanded-corpus` includes the 19,661 reference documents and
    the 2,436 evaluation holdout rows. Ingredient and makeup reference material
    must not become aftercare evidence, and holdout rows must never reach a
    patient answer at all.
    """
    clause = "d.retrieval_use = ANY(%s)"
    if settings.rag_allow_null_retrieval_use:
        return f"d.retrieval_use IS NULL OR {clause}"
    return clause


def to_retrieved_document(row: dict[str, Any]) -> RetrievedDocument:
    distance = float(row["distance"])
    # KURE embeddings are stored normalised, so pgvector cosine distance is
    # 1 - cosine_similarity. The clamp hides negative similarity, which we never
    # want to surface as evidence anyway.
    similarity = max(0.0, min(1.0, 1.0 - distance))
    return RetrievedDocument(
        doc_id=row["doc_id"],
        title=row["title"] or "",
        content=row["content"] or "",
        answer_template=row.get("answer_template"),
        source=row.get("source"),
        dataset_type=row.get("dataset_type"),
        retrieval_use=row.get("retrieval_use"),
        risk_level=row.get("risk_level"),
        similarity=similarity,
        distance=distance,
    )


def select_documents(
    rows: Iterable[dict[str, Any]],
    min_similarity: float,
    top_k: int,
) -> list[RetrievedDocument]:
    """Apply the similarity cutoff and the top-k limit.

    Documents below `min_similarity` are removed rather than down-weighted, so a
    weak match can never be handed to the generator as if it were evidence.
    """
    documents = [to_retrieved_document(row) for row in rows]
    kept = [document for document in documents if document.similarity >= min_similarity]
    kept.sort(key=lambda document: document.similarity, reverse=True)
    return kept[:top_k]


def fetch_rows(
    vector_literal: str,
    settings: Settings,
    candidate_limit: int,
) -> list[dict[str, Any]]:
    if not settings.database_url:
        raise RetrievalUnavailable("DATABASE_URL is missing")

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - deployment concern
        raise RetrievalUnavailable("psycopg is not installed") from exc

    sql = SELECT_SQL.format(retrieval_use_clause=build_retrieval_use_clause(settings))
    params: list[Any] = [vector_literal, settings.rag_index_version]
    params.append(list(settings.rag_allowed_retrieval_use))
    params.append(candidate_limit)

    try:
        with psycopg.connect(**database_kwargs(settings), autocommit=True) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(sql, tuple(params))
                return list(cursor.fetchall())
    except Exception as exc:  # pragma: no cover - infrastructure failure
        raise RetrievalUnavailable("RAG retrieval failed") from exc


def to_vector_literal(embedding: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.9f}" for value in embedding) + "]"


def retrieve_documents(
    question: str,
    settings: Settings,
    embed: Callable[[str], Sequence[float]],
    row_fetcher: Callable[[str, Settings, int], list[dict[str, Any]]] = fetch_rows,
) -> list[RetrievedDocument]:
    """Retrieve grounding documents for `question`.

    `embed` and `row_fetcher` are injected so the pipeline can be exercised
    without loading KURE or reaching the database.
    """
    vector_literal = to_vector_literal(embed(question))
    candidate_limit = max(settings.rag_top_k * 2, settings.rag_top_k)
    rows = row_fetcher(vector_literal, settings, candidate_limit)
    return select_documents(rows, settings.rag_min_similarity, settings.rag_top_k)
