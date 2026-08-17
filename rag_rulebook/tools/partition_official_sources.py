#!/usr/bin/env python3
"""Partition official source text files by product use.

The product scope is cosmetic surgery / dermatology / skin-aesthetic aftercare.
Raw snapshots remain in sources/raw_official. This script creates a derived
by-use folder so embedding jobs can avoid broad general medicine content.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = PROJECT_ROOT / "sources" / "raw_official"
RAW_MANIFEST = RAW_ROOT / "manifests" / "official_sources_manifest.json"
OUTPUT_ROOT = PROJECT_ROOT / "sources" / "official_by_use"


PARTITION: dict[str, dict[str, str]] = {
    "kdca_wound_scar_care": {
        "bucket": "rag_candidate",
        "reason": "피부 손상, 상처 세척, 드레싱, 흉터 예방, 병원 방문 기준이 성형/피부미용 사후관리와 직접 연결됨.",
        "embedding_policy": "allow",
    },
    "kdca_urticaria": {
        "bucket": "rag_candidate",
        "reason": "피부 알레르기/혈관부종/호흡곤란 경고가 시술 후 이상반응 안내와 연결됨.",
        "embedding_policy": "allow_with_safety_filters",
    },
    "easylaw_emergency_medical": {
        "bucket": "safety_only",
        "reason": "응급증상 및 이에 준하는 증상 기준은 hard-stop 룰 근거로만 사용.",
        "embedding_policy": "deny",
    },
    "law_emergency_rule_article2": {
        "bucket": "safety_only",
        "reason": "응급환자 법령 원문/시행일 확인용. 일반 답변 생성용 RAG에는 넣지 않음.",
        "embedding_policy": "deny",
    },
    "kdca_cpr": {
        "bucket": "safety_only",
        "reason": "의식 없음/호흡 없음/심정지 의심 시 119, 가슴압박, AED hard-stop 근거.",
        "embedding_policy": "deny",
    },
    "kdca_emergency_info": {
        "bucket": "safety_only",
        "reason": "E-Gen 응급처치/응급실 찾기 연결 포털. CTA와 출처 연결용.",
        "embedding_policy": "deny",
    },
    "egen_emergency_treat": {
        "bucket": "safety_only",
        "reason": "응급상황 대처 행동 지침. hard-stop 응답 템플릿 근거.",
        "embedding_policy": "deny",
    },
    "egen_first_aid_basics": {
        "bucket": "safety_only",
        "reason": "기본 응급처치 행동 지침. 서비스 답변보다 안전 룰 근거에 적합.",
        "embedding_policy": "deny",
    },
    "119_sososim_cpr": {
        "bucket": "safety_only",
        "reason": "119 신고/CPR 보조 근거. 응급 CTA용.",
        "embedding_policy": "deny",
    },
    "mois_rescue_first_aid": {
        "bucket": "safety_only",
        "reason": "구급차 도착 전 준비와 환자정보 전달 근거. 응급 CTA 보조용.",
        "embedding_policy": "deny",
    },
    "kdca_acute_mi": {
        "bucket": "out_of_scope",
        "reason": "심근경색 상세 정보는 성형/피부미용 사후관리 RAG 범위를 벗어남. 흉통 hard-stop은 법령/응급 기준으로 충분.",
        "embedding_policy": "deny",
    },
    "kdca_stroke_119": {
        "bucket": "out_of_scope",
        "reason": "뇌졸중 상세 정보는 현재 서비스 범위 밖. 편측마비 등은 일반 응급 룰 키워드로만 관리.",
        "embedding_policy": "deny",
    },
    "egen_heat_illness": {
        "bucket": "out_of_scope",
        "reason": "열사병/일사병은 피부미용 사후관리와 직접 연결성이 낮음.",
        "embedding_policy": "deny",
    },
    "egen_foreign_body_throat": {
        "bucket": "out_of_scope",
        "reason": "목 이물질/기도 폐쇄는 현재 서비스 도메인 밖. 일반 응급 룰로만 처리.",
        "embedding_policy": "deny",
    },
    "kdca_openapi_data_go": {
        "bucket": "api_reference",
        "reason": "질병관리청 OpenAPI 전환 검토용 메타자료.",
        "embedding_policy": "deny",
    },
    "open_law_api_guide": {
        "bucket": "api_reference",
        "reason": "법령 Open API 전환 검토용 메타자료.",
        "embedding_policy": "deny",
    },
}


def load_manifest() -> dict[str, Any]:
    with RAW_MANIFEST.open("r", encoding="utf-8") as f:
        return json.load(f)


def clean_output() -> None:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    for bucket in {"rag_candidate", "safety_only", "out_of_scope", "api_reference"}:
        (OUTPUT_ROOT / bucket).mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "manifests").mkdir(parents=True, exist_ok=True)


def main() -> None:
    manifest = load_manifest()
    clean_output()

    output: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "product_scope": "cosmetic surgery, dermatology, skin-aesthetic aftercare chatbot",
        "source_manifest": str(RAW_MANIFEST.relative_to(PROJECT_ROOT)),
        "buckets": {
            "rag_candidate": "벡터DB 후보. 답변 본문 근거로 사용 가능하되, 문장 생성 시 진단 확정 금지.",
            "safety_only": "벡터DB 제외. hard-stop 응급 룰과 CTA 근거로만 사용.",
            "out_of_scope": "현재 서비스 범위 밖. 보관만 하고 기본 파이프라인에서는 제외.",
            "api_reference": "향후 API 수집 전환 검토용. 임베딩 제외.",
        },
        "sources": [],
    }

    for source in manifest.get("sources", []):
        slug = source["slug"]
        partition = PARTITION.get(slug)
        if not partition:
            partition = {
                "bucket": "out_of_scope",
                "reason": "명시 분류가 없어 기본 제외.",
                "embedding_policy": "deny",
            }
        bucket = partition["bucket"]
        text_path = PROJECT_ROOT / source["text_path"]
        copied_text_path = OUTPUT_ROOT / bucket / f"{slug}.txt"
        if text_path.exists():
            shutil.copy2(text_path, copied_text_path)

        output["sources"].append(
            {
                "slug": slug,
                "title": source["title"],
                "institution": source["institution"],
                "url": source["url"],
                "bucket": bucket,
                "reason": partition["reason"],
                "embedding_policy": partition["embedding_policy"],
                "raw_html_path": source["html_path"],
                "raw_text_path": source["text_path"],
                "partitioned_text_path": str(copied_text_path.relative_to(PROJECT_ROOT)),
                "text_sha256": source.get("text_sha256", ""),
            }
        )

    for bucket in {"rag_candidate", "safety_only", "out_of_scope", "api_reference"}:
        bucket_sources = [s for s in output["sources"] if s["bucket"] == bucket]
        index_path = OUTPUT_ROOT / bucket / "_index.json"
        index_path.write_text(json.dumps(bucket_sources, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = OUTPUT_ROOT / "manifests" / "official_sources_by_use.json"
    manifest_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    readme_path = OUTPUT_ROOT / "README.md"
    readme_path.write_text(
        """# Official Sources By Use

성형/피부미용 사후관리 챗봇 범위에 맞춰 공식 원본 텍스트를 용도별로 나눈 폴더입니다.

- `rag_candidate/`: 벡터DB 적재 후보
- `safety_only/`: 임베딩 제외, 응급 hard-stop 룰/CTA 근거
- `out_of_scope/`: 현재 도메인 밖 보관 자료
- `api_reference/`: 향후 API 수집 전환 참고 자료
- `manifests/official_sources_by_use.json`: 전체 분류 사유와 원본 경로

원본 HTML과 원본 텍스트는 `sources/raw_official/`에 그대로 보존합니다.
""",
        encoding="utf-8",
    )

    counts = {bucket: 0 for bucket in output["buckets"]}
    for source in output["sources"]:
        counts[source["bucket"]] += 1
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
    print(manifest_path)


if __name__ == "__main__":
    main()
