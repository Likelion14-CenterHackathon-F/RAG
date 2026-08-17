#!/usr/bin/env python3
"""Compare retrieval quality across embedding providers for the RAG rulebook."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAG_ROOT = REPO_ROOT / "rag_rulebook"
DEFAULT_SECRET_FILE = REPO_ROOT / ".env"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build/rag-eval"


EVAL_QUERIES: list[dict[str, Any]] = [
    {
        "id": "pico_wash_makeup",
        "query": "피코 프락셀 오늘 받았는데 세안이랑 화장은 언제부터 해도 돼요?",
        "expected_doc_ids": ["GUIDE-DERM-PICO-D0-D1-WASH"],
    },
    {
        "id": "pico_redness_heat",
        "query": "피코레이저 다음날 얼굴이 빨갛고 열감이 있는데 정상인가요?",
        "expected_doc_ids": ["GUIDE-DERM-PICO-D1-D3-REDNESS"],
    },
    {
        "id": "pico_peeling",
        "query": "프락셀 5일째 각질이 벗겨지는데 손으로 밀어도 되나요?",
        "expected_doc_ids": ["GUIDE-DERM-PICO-D3-D7-PEELING"],
    },
    {
        "id": "pico_sunscreen",
        "query": "레이저 일주일 지났는데 자외선 차단은 어느 정도로 해야 하나요?",
        "expected_doc_ids": ["GUIDE-DERM-PICO-D7-D14-SUN"],
        "expected_prefixes": ["TRUSTED-AAD_LASER_SCAR_TREATMENT"],
    },
    {
        "id": "pico_dryness",
        "query": "레이저 하고 피부가 너무 건조하고 당겨요. 보습제를 많이 발라도 될까요?",
        "expected_doc_ids": ["SYM-DERM-PICO-DRYNESS"],
    },
    {
        "id": "laser_blister_oozing",
        "query": "레이저 후 물집이 생기고 진물이 나요. 병원에 가야 할까요?",
        "expected_doc_ids": ["SYM-DERM-PICO-OOSING-BLISTERS"],
        "expected_prefixes": ["TRUSTED-MFDS_LASER_SAFETY_GUIDE"],
    },
    {
        "id": "rhinoplasty_splint_water",
        "query": "코성형하고 부목 붙어 있는데 물 닿아도 괜찮아요? 실밥은 언제쯤 보나요?",
        "expected_doc_ids": ["GUIDE-RHINO-D0-D7-SPLINT"],
        "expected_prefixes": ["TRUSTED-ASPS_RHINOPLASTY_RECOVERY"],
    },
    {
        "id": "rhinoplasty_swelling_shape",
        "query": "코수술 2주차인데 붓기 때문에 모양이 이상해 보여서 걱정돼요.",
        "expected_doc_ids": ["GUIDE-RHINO-D8-D21-SWELLING"],
        "expected_prefixes": ["TRUSTED-ASPS_RHINOPLASTY_RECOVERY"],
    },
    {
        "id": "rhinoplasty_morning_swelling",
        "query": "코성형 한 달 됐는데 아침마다 코가 더 부어 보여요.",
        "expected_doc_ids": ["GUIDE-RHINO-D22-D90-MORNING-SWELLING"],
        "expected_prefixes": ["TRUSTED-ASPS_RHINOPLASTY_RECOVERY"],
    },
    {
        "id": "rhinoplasty_final_shape",
        "query": "코수술 최종 모양은 몇 개월 지나야 알 수 있나요?",
        "expected_doc_ids": ["GUIDE-RHINO-D90-D365-FINAL-SHAPE"],
        "expected_prefixes": ["TRUSTED-ASPS_RHINOPLASTY_RECOVERY"],
    },
    {
        "id": "rhinoplasty_asymmetry",
        "query": "코가 비대칭인 것 같아서 너무 불안한데 사진만 보고 판단 가능한가요?",
        "expected_doc_ids": ["SYM-RHINO-ASYMMETRY-ANXIETY", "COMMON-LOW-CONFIDENCE-PHOTO"],
    },
    {
        "id": "rhinoplasty_obstruction",
        "query": "코성형 후 코막힘이 심하고 답답해요. 숨쉬기 불편한데 괜찮나요?",
        "expected_doc_ids": ["SYM-RHINO-NASAL-OBSTRUCTION"],
        "expected_prefixes": ["TRUSTED-ASPS_RHINOPLASTY_RECOVERY"],
    },
    {
        "id": "image_low_confidence",
        "query": "사진이 흐릿한데 이거 염증인지 괴사인지 정확히 말해줄 수 있어요?",
        "expected_doc_ids": ["COMMON-LOW-CONFIDENCE-PHOTO", "COMMON-BOUNDARY-NO-DIAGNOSIS"],
    },
    {
        "id": "high_anxiety",
        "query": "괜찮다고 해도 너무 무서워요. 계속 불안해서 상담받고 싶어요.",
        "expected_doc_ids": ["COMMON-HIGH-ANXIETY"],
    },
    {
        "id": "no_diagnosis_boundary",
        "query": "사진 보고 정확히 무슨 병인지 진단명 확정해 주세요.",
        "expected_doc_ids": ["COMMON-BOUNDARY-NO-DIAGNOSIS", "COMMON-LOW-CONFIDENCE-PHOTO"],
    },
    {
        "id": "acne_makeup",
        "query": "화농성 여드름이 있는데 피부 자극 적은 메이크업은 어떻게 해야 해요?",
        "expected_doc_ids": ["SKIN-ACNE-MAKEUP-SENSITIVE"],
        "expected_prefixes": ["TRUSTED-AAD_ACNE_SCAR_AFTERCARE"],
    },
    {
        "id": "seborrheic_makeup",
        "query": "지루성 피부염처럼 붉고 예민한 피부인데 화장품 선택이 걱정돼요.",
        "expected_doc_ids": ["SKIN-SEBORRHEIC-SENSITIVE"],
    },
    {
        "id": "filler_swelling_bruise",
        "query": "필러 맞고 붓기랑 멍이 있는데 회복 기간 동안 뭘 조심해야 해요?",
        "expected_prefixes": [
            "TRUSTED-ASPS_DERMAL_FILLER_RECOVERY",
            "TRUSTED-MFDS_FILLER_SAFETY_GUIDE",
        ],
    },
    {
        "id": "filler_massage_sauna",
        "query": "필러 시술 후 마사지하거나 사우나 가도 되나요?",
        "expected_prefixes": [
            "TRUSTED-MFDS_FILLER_SAFETY_GUIDE",
            "TRUSTED-ASPS_DERMAL_FILLER_RECOVERY",
        ],
    },
    {
        "id": "filler_vision_skin_color",
        "query": "필러 맞고 갑자기 앞이 흐리고 피부가 하얗게 변했어요.",
        "expected_prefixes": [
            "TRUSTED-FDA_DERMAL_FILLER_DOS_DONTS",
            "TRUSTED-MFDS_FILLER_SAFETY_GUIDE",
            "TRUSTED-ASPS_DERMAL_FILLER_RECOVERY",
        ],
    },
    {
        "id": "botox_rubbing",
        "query": "보톡스 맞고 나서 얼굴 문지르거나 마사지해도 괜찮나요?",
        "expected_prefixes": ["TRUSTED-ASPS_BOTULINUM_TOXIN_RECOVERY"],
    },
    {
        "id": "urticaria_after_procedure",
        "query": "시술 후 두드러기처럼 전신에 발진이 올라와요.",
        "expected_prefixes": ["OFFICIAL-KDCA_URTICARIA"],
    },
    {
        "id": "wound_scar_infection",
        "query": "상처 부위가 벌어지고 냄새 나는 진물이 나는데 흉터 관리보다 병원 가야 하나요?",
        "expected_prefixes": ["OFFICIAL-KDCA_WOUND_SCAR_CARE"],
        "expected_doc_ids": ["SYM-DERM-PICO-OOSING-BLISTERS"],
    },
    {
        "id": "acne_scar_aftercare",
        "query": "여드름 흉터 치료 후 세안, 메이크업, 자외선 차단은 어떻게 해야 하나요?",
        "expected_prefixes": ["TRUSTED-AAD_ACNE_SCAR_AFTERCARE"],
        "expected_doc_ids": ["GUIDE-DERM-PICO-D0-D1-WASH", "GUIDE-DERM-PICO-D7-D14-SUN"],
    },
    {
        "id": "laser_scar_retinoid",
        "query": "흉터 레이저 받기 전후에 레티노이드나 글리콜릭산 제품을 써도 되나요?",
        "expected_prefixes": ["TRUSTED-AAD_LASER_SCAR_TREATMENT"],
    },
]


@dataclass
class RagDocument:
    doc_id: str
    title: str
    content: str
    answer_template: str | None
    metadata: dict[str, Any]

    @property
    def embedding_text(self) -> str:
        parts = [self.title, self.content, self.answer_template]
        return "\n\n".join(str(part).strip() for part in parts if part and str(part).strip())


def load_properties(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    properties: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        properties[key.strip()] = value.strip()
    return properties


def config_value(properties: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = properties.get(key)
        if value and not (value.startswith("${") and value.endswith("}")):
            return value
    for key in keys:
        env_key = key.replace(".", "_").replace("-", "_").upper()
        value = os.environ.get(env_key)
        if value:
            return value
    return None


def load_documents(rag_root: Path) -> tuple[str, list[RagDocument]]:
    manifest = json.loads((rag_root / "derived/retriever_index_manifest.json").read_text(encoding="utf-8"))
    docs: list[RagDocument] = []

    for entry in manifest["default_patient_answer_index"]:
        path = rag_root / entry["path"]
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            metadata = dict(metadata)
            metadata["trust_level"] = entry["trust_level"]
            metadata["manifest_path"] = entry["path"]
            docs.append(
                RagDocument(
                    doc_id=raw["doc_id"],
                    title=raw.get("title") or metadata.get("title") or raw["doc_id"],
                    content=raw["content"],
                    answer_template=raw.get("answer_template"),
                    metadata=metadata,
                )
            )

    return manifest["version"], docs


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return matrix / norms


def request_openai_embeddings(api_key: str, base_url: str, model: str, inputs: list[str], batch_size: int) -> np.ndarray:
    all_embeddings: list[list[float]] = []
    endpoint = f"{base_url.rstrip('/')}/v1/embeddings"

    for start in range(0, len(inputs), batch_size):
        batch = inputs[start : start + batch_size]
        body = json.dumps({"model": model, "input": batch}).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                all_embeddings.extend(item["embedding"] for item in sorted(payload["data"], key=lambda item: item["index"]))
                print(f"OpenAI embedded {min(start + batch_size, len(inputs))}/{len(inputs)}")
                break
            except urllib.error.HTTPError as error:
                message = error.read().decode("utf-8", errors="replace")[:500]
                raise RuntimeError(f"OpenAI embeddings HTTP {error.code}: {message}") from error
            except Exception:
                if attempt >= 3:
                    raise
                time.sleep(2**attempt)

    return l2_normalize(np.array(all_embeddings, dtype=np.float32))


def request_kure_embeddings(model_name: str, inputs: list[str], batch_size: int) -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    embeddings = model.encode(
        inputs,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    return np.array(embeddings, dtype=np.float32)


def matches_expected(doc_id: str, query: dict[str, Any]) -> bool:
    if doc_id in query.get("expected_doc_ids", []):
        return True
    return any(doc_id.startswith(prefix) for prefix in query.get("expected_prefixes", []))


def evaluate(provider: str, doc_embeddings: np.ndarray, query_embeddings: np.ndarray, docs: list[RagDocument], top_k: int) -> dict[str, Any]:
    similarities = query_embeddings @ doc_embeddings.T
    rows: list[dict[str, Any]] = []

    for query_index, query in enumerate(EVAL_QUERIES):
        top_indices = np.argsort(-similarities[query_index])[:top_k]
        hits = []
        top_results = []
        for rank, doc_index in enumerate(top_indices, 1):
            doc = docs[int(doc_index)]
            matched = matches_expected(doc.doc_id, query)
            hits.append(matched)
            top_results.append(
                {
                    "rank": rank,
                    "doc_id": doc.doc_id,
                    "title": doc.title,
                    "score": float(similarities[query_index][doc_index]),
                    "matched_expected": matched,
                }
            )

        rows.append(
            {
                "id": query["id"],
                "query": query["query"],
                "hit_at_1": bool(any(hits[:1])),
                "hit_at_3": bool(any(hits[:3])),
                "hit_at_5": bool(any(hits[:5])),
                "top_results": top_results,
            }
        )

    summary = {
        "provider": provider,
        "queries": len(EVAL_QUERIES),
        "hit_at_1": sum(row["hit_at_1"] for row in rows),
        "hit_at_3": sum(row["hit_at_3"] for row in rows),
        "hit_at_5": sum(row["hit_at_5"] for row in rows),
    }
    for key in ["hit_at_1", "hit_at_3", "hit_at_5"]:
        summary[f"{key}_rate"] = round(summary[key] / len(EVAL_QUERIES), 4)

    return {"summary": summary, "rows": rows}


def markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Embedding Retrieval Evaluation",
        "",
        f"- Index version: `{payload['index_version']}`",
        f"- Document count: `{payload['document_count']}`",
        f"- Query count: `{len(EVAL_QUERIES)}`",
        "",
        "## Summary",
        "",
        "| Provider | Hit@1 | Hit@3 | Hit@5 |",
        "| --- | ---: | ---: | ---: |",
    ]

    for provider, result in payload["results"].items():
        summary = result["summary"]
        lines.append(
            f"| {provider} | {summary['hit_at_1']}/{summary['queries']} ({summary['hit_at_1_rate']:.0%}) "
            f"| {summary['hit_at_3']}/{summary['queries']} ({summary['hit_at_3_rate']:.0%}) "
            f"| {summary['hit_at_5']}/{summary['queries']} ({summary['hit_at_5_rate']:.0%}) |"
        )

    lines.extend(["", "## Per Query Top 3", ""])
    for query in EVAL_QUERIES:
        lines.append(f"### {query['id']}")
        lines.append("")
        lines.append(f"> {query['query']}")
        lines.append("")
        lines.append("| Provider | Hit@3 | Top 3 |")
        lines.append("| --- | --- | --- |")
        for provider, result in payload["results"].items():
            row = next(item for item in result["rows"] if item["id"] == query["id"])
            top_three = "<br>".join(
                f"{item['rank']}. `{item['doc_id']}` ({item['score']:.3f})"
                for item in row["top_results"][:3]
            )
            lines.append(f"| {provider} | {'Y' if row['hit_at_3'] else 'N'} | {top_three} |")
        lines.append("")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["openai", "kure", "all"], default="all")
    parser.add_argument("--rag-root", type=Path, default=DEFAULT_RAG_ROOT)
    parser.add_argument("--secret-file", type=Path, default=DEFAULT_SECRET_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--openai-model", default=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
    parser.add_argument("--openai-batch-size", type=int, default=16)
    parser.add_argument("--kure-model", default=os.environ.get("KURE_MODEL", "nlpai-lab/KURE-v1"))
    parser.add_argument("--kure-batch-size", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    index_version, docs = load_documents(args.rag_root)
    doc_texts = [doc.embedding_text for doc in docs]
    query_texts = [query["query"] for query in EVAL_QUERIES]
    results: dict[str, Any] = {}

    if args.provider in {"openai", "all"}:
        properties = load_properties(args.secret_file)
        api_key = config_value(properties, "OPENAI_API_KEY", "openai.api-key")
        base_url = config_value(properties, "OPENAI_BASE_URL", "openai.base-url") or "https://api.openai.com"
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing")
        combined = request_openai_embeddings(
            api_key=api_key,
            base_url=base_url,
            model=args.openai_model,
            inputs=doc_texts + query_texts,
            batch_size=args.openai_batch_size,
        )
        doc_embeddings = combined[: len(docs)]
        query_embeddings = combined[len(docs) :]
        provider_name = f"openai/{args.openai_model}"
        results[provider_name] = evaluate(provider_name, doc_embeddings, query_embeddings, docs, args.top_k)

    if args.provider in {"kure", "all"}:
        combined = request_kure_embeddings(args.kure_model, doc_texts + query_texts, args.kure_batch_size)
        doc_embeddings = combined[: len(docs)]
        query_embeddings = combined[len(docs) :]
        provider_name = f"kure/{args.kure_model}"
        results[provider_name] = evaluate(provider_name, doc_embeddings, query_embeddings, docs, args.top_k)

    payload = {
        "index_version": index_version,
        "document_count": len(docs),
        "results": results,
    }

    json_path = args.output_dir / "embedding_retrieval_eval.json"
    md_path = args.output_dir / "embedding_retrieval_eval.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(payload), encoding="utf-8")

    print(markdown_report(payload).split("## Per Query Top 3", 1)[0])
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")


if __name__ == "__main__":
    main()
