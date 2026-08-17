#!/usr/bin/env python3
"""Retrieval quality probe. Answers Q13 through Q22 of VERIFICATION_REQUEST.md.

NOT VERIFIED. Written in a sandbox with no database, no KURE-v1 and no network,
so this script has never been executed. If it fails, the traceback is itself a
useful answer: paste it into VERIFICATION_RESULT.md rather than fixing it
silently, because a failure here usually means the schema differs from what
`centerton_rag/retrieval.py` assumes.

    python verification/probe_retrieval.py --sanity
    python verification/probe_retrieval.py --out verification/retrieval_result.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from centerton_rag.config import build_settings  # noqa: E402
from centerton_rag.retrieval import (  # noqa: E402
    build_retrieval_use_clause,
    select_documents,
    to_vector_literal,
)

# Every probe was checked against the emergency rulebook and none of them
# triggers a hard stop, so all of them reach retrieval.
#
# R* expect specific curated documents. N* are out of scope for the 90-document
# default index and must end in insufficient_evidence. N03 and N04 are the tier
# boundary tests: they look like the expanded reference corpus, so if that corpus
# is reachable they will pull ingredient or makeup documents.
PROBES: list[dict] = [
    {"id": "R01", "procedure": "피코 프락셀", "days": 2,
     "q": "레이저 시술 2일 됐는데 얼굴이 붉고 화끈거려요. 세안 언제부터 가능한가요?",
     "expect": ["GUIDE-DERM-PICO-D1-D3-REDNESS", "GUIDE-DERM-PICO-D0-D1-WASH"]},
    {"id": "R02", "procedure": "피코 프락셀", "days": 4,
     "q": "각질이 일어나는데 뜯어도 되나요?",
     "expect": ["GUIDE-DERM-PICO-D3-D7-PEELING"]},
    {"id": "R03", "procedure": "피코 프락셀", "days": 4,
     "q": "피부가 너무 건조하고 당겨요. 수분크림 발라도 되나요?",
     "expect": ["SYM-DERM-PICO-DRYNESS"]},
    {"id": "R04", "procedure": "피코 프락셀", "days": 10,
     "q": "선크림은 언제부터 바를 수 있나요?",
     "expect": ["GUIDE-DERM-PICO-D7-D14-SUN"]},
    {"id": "R05", "procedure": "피코 프락셀", "days": 3,
     "q": "작은 물집이 생겼는데 괜찮은 건가요?",
     "expect": ["SYM-DERM-PICO-OOSING-BLISTERS"]},
    {"id": "R06", "procedure": "코성형 (융비술)", "days": 14,
     "q": "코 수술 2주차인데 코끝이 약간 휜 것 같아요. 재수술해야 하나요?",
     "expect": ["SYM-RHINO-ASYMMETRY-ANXIETY", "GUIDE-RHINO-D8-D21-SWELLING"]},
    {"id": "R07", "procedure": "코성형 (융비술)", "days": 5,
     "q": "실밥 제거 전에 세수해도 되나요?",
     "expect": ["GUIDE-RHINO-D0-D7-SPLINT"]},
    {"id": "R08", "procedure": "코성형 (융비술)", "days": 40,
     "q": "아침에 코가 더 부어 보이는데 정상인가요?",
     "expect": ["GUIDE-RHINO-D22-D90-MORNING-SWELLING"]},
    {"id": "R09", "procedure": "코성형 (융비술)", "days": 120,
     "q": "코 최종 모양은 언제쯤 나오나요?",
     "expect": ["GUIDE-RHINO-D90-D365-FINAL-SHAPE"]},
    {"id": "R10", "procedure": "코성형 (융비술)", "days": 10,
     "q": "코 한쪽이 막힌 느낌이고 답답해요",
     "expect": ["SYM-RHINO-NASAL-OBSTRUCTION"]},
    {"id": "R11", "procedure": "코성형 (융비술)", "days": 14,
     "q": "사진이 어두운데 이걸로 판단 가능한가요?",
     "expect": ["COMMON-LOW-CONFIDENCE-PHOTO"]},
    {"id": "R12", "procedure": "코성형 (융비술)", "days": 14,
     "q": "너무 불안해요. 괜찮은 거 맞나요?",
     "expect": ["COMMON-HIGH-ANXIETY"]},
    {"id": "N01", "procedure": None, "days": None,
     "q": "자동차 보험 청구는 어떻게 하나요?", "expect": []},
    {"id": "N02", "procedure": None, "days": None,
     "q": "임플란트 가격 알려주세요", "expect": []},
    {"id": "N03", "procedure": None, "days": None,
     "q": "여드름 피부에 맞는 프라이머 추천해주세요", "expect": []},
    {"id": "N04", "procedure": None, "days": None,
     "q": "나이아신아마이드 효능이 뭐예요?", "expect": []},
    {"id": "N05", "procedure": None, "days": None,
     "q": "시술 후 비행기는 언제 탈 수 있나요?", "expect": []},
]

SANITY_PAIRS = [
    ("시술 후 얼굴이 붉고 화끈거려요", "레이저 시술 후 붉은기와 열감은 흔하게 나타납니다", "관련"),
    ("코끝이 휜 것 같아요", "코성형 후 부기로 비대칭처럼 보일 수 있습니다", "관련"),
    ("시술 후 얼굴이 붉고 화끈거려요", "자동차 보험 청구 절차를 안내합니다", "무관"),
    ("각질이 일어나요", "임플란트 시술 비용은 다음과 같습니다", "무관"),
]

# Anything outside the default patient-answer index. Appearing in a result is a
# tier boundary violation, not a ranking problem.
FORBIDDEN_RETRIEVAL_USE = {
    "ingredient_and_skin_care_reference_only",
    "makeup_and_skin_reference_only",
    "reference_only_not_postop_instruction",
}


def load_model(settings):
    from sentence_transformers import SentenceTransformer

    started = time.time()
    model = SentenceTransformer(settings.kure_model)
    return model, time.time() - started


def encode(model, text: str) -> list[float]:
    vector = model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
    return [float(value) for value in vector]


def run_sanity(settings) -> dict:
    model, load_seconds = load_model(settings)
    probe = encode(model, "시술 후 붉은 기가 있어요")
    norm = sum(value * value for value in probe) ** 0.5

    repeat_a = encode(model, "동일 문장 임베딩 확인")
    repeat_b = encode(model, "동일 문장 임베딩 확인")
    deterministic = repeat_a == repeat_b
    max_delta = max(abs(a - b) for a, b in zip(repeat_a, repeat_b))

    pairs = []
    for left, right, label in SANITY_PAIRS:
        a, b = encode(model, left), encode(model, right)
        cosine = sum(x * y for x, y in zip(a, b))
        pairs.append({"query": left, "document": right, "label": label,
                      "cosine": round(cosine, 4)})

    result = {
        "model": settings.kure_model,
        "load_seconds": round(load_seconds, 2),
        "dimension": len(probe),
        "l2_norm": round(norm, 6),
        "deterministic": deterministic,
        "max_delta_between_runs": max_delta,
        "pairs": pairs,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def fetch(settings, vector_literal: str, limit: int) -> list[dict]:
    """Same query shape as the service, but without the top-k cut so the whole
    candidate window is visible."""
    import psycopg
    from psycopg.rows import dict_row

    sql = f"""
    WITH query_embedding AS (SELECT %s::vector AS embedding)
    SELECT d.doc_id, d.title, d.content, d.answer_template, d.source,
           d.dataset_type, d.retrieval_use, d.risk_level,
           d.embedding <=> query_embedding.embedding AS distance
    FROM rag_documents d, query_embedding
    WHERE d.index_version = %s
      AND d.embedding_storage = 'pgvector'
      AND d.embedding IS NOT NULL
      AND ({build_retrieval_use_clause(settings)})
    ORDER BY d.embedding <=> query_embedding.embedding
    LIMIT %s
    """
    params = [vector_literal, settings.rag_index_version,
              list(settings.rag_allowed_retrieval_use), limit]
    from centerton_rag.config import database_kwargs

    with psycopg.connect(**database_kwargs(settings), autocommit=True) as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(sql, tuple(params))
            return list(cursor.fetchall())


def run_probes(settings, window: int) -> dict:
    model, load_seconds = load_model(settings)
    results = []

    for probe in PROBES:
        started = time.time()
        vector = encode(model, probe["q"])
        embed_ms = (time.time() - started) * 1000

        started = time.time()
        rows = fetch(settings, to_vector_literal(vector), window)
        query_ms = (time.time() - started) * 1000

        ranked = select_documents(rows, 0.0, window)
        kept = select_documents(rows, settings.rag_min_similarity, settings.rag_top_k)

        expected_ranks = {}
        for doc_id in probe["expect"]:
            position = next(
                (index for index, document in enumerate(ranked, 1)
                 if document.doc_id == doc_id),
                None,
            )
            similarity = next(
                (document.similarity for document in ranked if document.doc_id == doc_id),
                None,
            )
            expected_ranks[doc_id] = {
                "rank": position,
                "similarity": round(similarity, 4) if similarity is not None else None,
                "cleared_threshold": bool(
                    similarity is not None and similarity >= settings.rag_min_similarity
                ),
            }

        leaks = [
            {"doc_id": document.doc_id, "retrieval_use": document.retrieval_use,
             "similarity": round(document.similarity, 4)}
            for document in ranked[: settings.rag_top_k]
            if document.retrieval_use in FORBIDDEN_RETRIEVAL_USE
        ]

        results.append({
            "id": probe["id"],
            "question": probe["q"],
            "procedure": probe["procedure"],
            "days_after_procedure": probe["days"],
            "expected_docs": probe["expect"],
            "expected_ranks": expected_ranks,
            "top": [
                {"rank": index, "doc_id": document.doc_id,
                 "similarity": round(document.similarity, 4),
                 "retrieval_use": document.retrieval_use,
                 "dataset_type": document.dataset_type,
                 "risk_level": document.risk_level,
                 "title": document.title[:70]}
                for index, document in enumerate(ranked[: settings.rag_top_k], 1)
            ],
            "kept_after_threshold": [document.doc_id for document in kept],
            "would_be_insufficient_evidence": not kept,
            "tier_violations": leaks,
            "embed_ms": round(embed_ms, 1),
            "query_ms": round(query_ms, 1),
        })

        marker = "!" if leaks else " "
        top_line = results[-1]["top"][0]["doc_id"] if results[-1]["top"] else "-"
        print(f"{marker} {probe['id']}  top1={top_line:<38} "
              f"kept={len(kept)}  {probe['q'][:40]}")

    return {
        "model": settings.kure_model,
        "model_load_seconds": round(load_seconds, 2),
        "index_version": settings.rag_index_version,
        "min_similarity": settings.rag_min_similarity,
        "top_k": settings.rag_top_k,
        "allowed_retrieval_use": list(settings.rag_allowed_retrieval_use),
        "allow_null_retrieval_use": settings.rag_allow_null_retrieval_use,
        "candidate_window": window,
        "probes": results,
        "summary": summarise(results, settings),
    }


def summarise(results: list[dict], settings) -> dict:
    relevant = [r for r in results if r["id"].startswith("R")]
    unrelated = [r for r in results if r["id"].startswith("N")]

    def best(entry: dict) -> float | None:
        return entry["top"][0]["similarity"] if entry["top"] else None

    relevant_best = [value for value in (best(r) for r in relevant) if value is not None]
    unrelated_best = [value for value in (best(r) for r in unrelated) if value is not None]

    missed = [
        {"id": r["id"], "doc_id": doc_id, **info}
        for r in relevant
        for doc_id, info in r["expected_ranks"].items()
        if not info["cleared_threshold"]
    ]

    return {
        "relevant_top1_similarity": {
            "min": min(relevant_best) if relevant_best else None,
            "max": max(relevant_best) if relevant_best else None,
        },
        "unrelated_top1_similarity": {
            "min": min(unrelated_best) if unrelated_best else None,
            "max": max(unrelated_best) if unrelated_best else None,
        },
        # If the relevant floor sits below the unrelated ceiling, no single
        # threshold separates them and the fix is index quality or metadata
        # filtering, not tuning RAG_MIN_SIMILARITY.
        "threshold_separates_relevant_from_unrelated": bool(
            relevant_best and unrelated_best and min(relevant_best) > max(unrelated_best)
        ),
        "expected_docs_below_threshold": missed,
        "unrelated_that_would_answer": [
            r["id"] for r in unrelated if not r["would_be_insufficient_evidence"]
        ],
        "probes_with_tier_violations": [
            r["id"] for r in results if r["tier_violations"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sanity", action="store_true", help="embedding checks only")
    parser.add_argument("--window", type=int, default=20,
                        help="candidate rows to inspect per probe")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    settings = build_settings()
    payload = run_sanity(settings) if args.sanity else run_probes(settings, args.window)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nwrote {args.out}")
    if not args.sanity:
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
