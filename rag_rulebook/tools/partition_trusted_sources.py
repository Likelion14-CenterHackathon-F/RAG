#!/usr/bin/env python3
"""Partition trusted aftercare sources by retrieval use."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = PROJECT_ROOT / "sources" / "raw_trusted"
RAW_MANIFEST = RAW_ROOT / "manifests" / "trusted_sources_manifest.json"
OUTPUT_ROOT = PROJECT_ROOT / "sources" / "trusted_by_use"


PARTITION: dict[str, dict[str, str]] = {
    "mfds_filler_safety_guide": {
        "bucket": "rag_candidate",
        "reason": "필러 시술 후 음주/흡연, 강한 마사지, 강한 열·추위 회피와 부작용 발생 시 병원 연락 기준이 직접 연결됨.",
        "embedding_policy": "allow_with_safety_filters",
    },
    "mfds_filler_device_info": {
        "bucket": "rag_candidate",
        "reason": "성형용 필러 정의와 사용 전 주의사항이 필러 문의의 맥락 보강에 필요함.",
        "embedding_policy": "allow_with_safety_filters",
    },
    "mfds_laser_safety_guide": {
        "bucket": "rag_candidate",
        "reason": "피부 레이저 후 통증, 물집, 붉음, 붓기, 피부손상 발생 시 병의원 문의 기준과 일반 관리 기준이 있음.",
        "embedding_policy": "allow_with_safety_filters",
    },
    "mfds_laser_device_info": {
        "bucket": "rag_candidate",
        "reason": "레이저 치료 후 사우나/찜질방, 자극적 화장품, 마사지, 자외선, 추가 시술 회피 기준이 직접 연결됨.",
        "embedding_policy": "allow",
    },
    "aad_acne_scar_aftercare": {
        "bucket": "rag_candidate",
        "reason": "흉터 치료 후 메이크업 중단, 자외선 차단, 세안, 감염 예방 등 환자용 사후관리 문서임.",
        "embedding_policy": "allow",
    },
    "aad_laser_scar_treatment": {
        "bucket": "rag_candidate",
        "reason": "흉터 레이저 전후 자외선 차단, 레티노이드/글리콜릭산 중단, 헤르페스 병력 확인, 자택 관리 필요성이 있음.",
        "embedding_policy": "allow",
    },
    "asps_dermal_filler_recovery": {
        "bucket": "rag_candidate",
        "reason": "필러 후 붓기/멍/일시적 저림/붉음, 활동 제한, 즉시 진료 신호가 함께 정리된 회복 문서임.",
        "embedding_policy": "allow_with_safety_filters",
    },
    "asps_rhinoplasty_recovery": {
        "bucket": "rag_candidate",
        "reason": "코성형 회복 중 부목/패킹, 붓기 경과, follow-up, 개별 병원 지침 우선 원칙과 연결됨.",
        "embedding_policy": "allow",
    },
    "fda_dermal_filler_dos_donts": {
        "bucket": "rag_candidate",
        "reason": "필러 일반 부작용, 승인 범위, 직접 구매/자가주입 금지, 보툴리눔 톡신과의 차이를 설명하는 소비자용 안전 정보임.",
        "embedding_policy": "allow_with_safety_filters",
    },
    "asps_botulinum_toxin_recovery": {
        "bucket": "rag_candidate",
        "reason": "보툴리눔 톡신 후 일상 복귀와 시술 부위 마사지/문지르기 회피 기준이 직접 연결됨.",
        "embedding_policy": "allow",
    },
    "asps_dermal_filler_safety": {
        "bucket": "safety_only",
        "reason": "필러 혈류 차단, 피부괴사, 시야 상실 등 중대 위험 신호 중심이므로 hard-stop 룰 근거로 사용.",
        "embedding_policy": "deny",
    },
    "fda_dermal_fillers_soft_tissue": {
        "bucket": "safety_only",
        "reason": "필러 혈관 주입, 시야 이상, 뇌졸중 징후, 즉시 진료 기준 등 중대 안전 기준 중심이므로 hard-stop 룰 근거로 사용.",
        "embedding_policy": "deny",
    },
    "asps_botulinum_toxin_safety": {
        "bucket": "safety_only",
        "reason": "보툴리눔 톡신 확산 의심 증상인 호흡 문제, 삼킴 곤란, 근력 약화, 말 어눌함은 즉시 진료 룰 근거로 사용.",
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
            "rag_candidate": "벡터DB 적재 후보. 환자 답변 근거로 사용하되 진단 확정 금지.",
            "safety_only": "벡터DB 제외. hard-stop 응급/즉시 진료 룰과 CTA 근거로만 사용.",
            "out_of_scope": "현재 도메인 밖. 보관만 하고 기본 파이프라인에서는 제외.",
            "api_reference": "향후 API 수집 전환 검토용. 임베딩 제외.",
        },
        "sources": [],
    }

    for source in manifest.get("sources", []):
        slug = source["slug"]
        partition = PARTITION.get(
            slug,
            {
                "bucket": "out_of_scope",
                "reason": "명시 분류가 없어 기본 제외.",
                "embedding_policy": "deny",
            },
        )
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
                "source_type": source["source_type"],
                "url": source["url"],
                "department": source.get("department", "dermatology"),
                "procedure": source.get("procedure", "common"),
                "recommended_use": source.get("recommended_use", ""),
                "bucket": bucket,
                "reason": partition["reason"],
                "embedding_policy": partition["embedding_policy"],
                "raw_html_path": source.get("html_path", ""),
                "raw_pdf_path": source.get("pdf_path", ""),
                "raw_text_path": source["text_path"],
                "partitioned_text_path": str(copied_text_path.relative_to(PROJECT_ROOT)),
                "text_sha256": source.get("text_sha256", ""),
            }
        )

    for bucket in {"rag_candidate", "safety_only", "out_of_scope", "api_reference"}:
        bucket_sources = [s for s in output["sources"] if s["bucket"] == bucket]
        index_path = OUTPUT_ROOT / bucket / "_index.json"
        index_path.write_text(json.dumps(bucket_sources, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = OUTPUT_ROOT / "manifests" / "trusted_sources_by_use.json"
    manifest_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    readme_path = OUTPUT_ROOT / "README.md"
    readme_path.write_text(
        """# Trusted Sources By Use

성형/피부미용 사후관리 챗봇 범위에 맞춰 식약처, FDA, AAD, ASPS 원본 텍스트를 용도별로 나눈 폴더입니다.

- `rag_candidate/`: 벡터DB 적재 후보
- `safety_only/`: 임베딩 제외, 즉시 진료/hard-stop 룰 근거
- `out_of_scope/`: 현재 도메인 밖 보관 자료
- `api_reference/`: 향후 API 수집 전환 참고 자료
- `manifests/trusted_sources_by_use.json`: 전체 분류 사유와 원본 경로

원본 HTML/PDF와 추출 텍스트는 `sources/raw_trusted/`에 그대로 보존합니다.
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
