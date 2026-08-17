#!/usr/bin/env python3
"""Extract readable text and metadata from collected official source HTML.

The raw HTML snapshots are kept as provenance. This script creates plain-text
companions and a manifest that can feed the later RAG preprocessing step.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "sources" / "raw_official"
HTML_DIR = SOURCE_ROOT / "html"
TEXT_DIR = SOURCE_ROOT / "text"
MANIFEST_DIR = SOURCE_ROOT / "manifests"


SOURCES: list[dict[str, str]] = [
    {
        "slug": "kdca_emergency_info",
        "title": "질병관리청 국가건강정보포털 응급상황정보",
        "institution": "질병관리청",
        "source_type": "official_portal",
        "url": "https://health.kdca.go.kr/healthinfo/biz/health/gnrlzHealthInfo/healthInfo/emgncySittnInfoMain.do",
        "recommended_use": "E-Gen 응급처치, 응급실 찾기, 응급상황정보 연결 근거",
    },
    {
        "slug": "kdca_acute_mi",
        "title": "질병관리청 국가건강정보포털 급성 심근경색증",
        "institution": "질병관리청",
        "source_type": "official_health_content",
        "url": "https://health.kdca.go.kr/healthinfo/biz/health/gnrlzHealthInfo/gnrlzHealthInfo/gnrlzHealthInfoView.do?cntnts_sn=6770",
        "recommended_use": "흉통, 식은땀, 호흡곤란, 즉시 119 안내 근거",
    },
    {
        "slug": "kdca_cpr",
        "title": "질병관리청 국가건강정보포털 심폐소생술",
        "institution": "질병관리청",
        "source_type": "official_health_content",
        "url": "https://health.kdca.go.kr/healthinfo/biz/health/gnrlzHealthInfo/gnrlzHealthInfo/gnrlzHealthInfoView.do?cntnts_sn=6226",
        "recommended_use": "반응 확인, 119 신고, 가슴압박, AED 사용 근거",
    },
    {
        "slug": "kdca_stroke_119",
        "title": "질병관리청 뇌졸중 조기증상 의심되면 즉시 119",
        "institution": "질병관리청",
        "source_type": "official_education_material",
        "url": "https://www.kdca.go.kr/bbs/kdca/47/218748/artclView.do",
        "recommended_use": "편측마비, 시각장애, 언어장애, 심한 두통, 어지럼증 red flag 근거",
    },
    {
        "slug": "kdca_wound_scar_care",
        "title": "질병관리청 국가건강정보포털 상처관리와 흉터예방",
        "institution": "질병관리청",
        "source_type": "official_health_content",
        "url": "https://health.kdca.go.kr/healthinfo/biz/health/gnrlzHealthInfo/gnrlzHealthInfo/gnrlzHealthInfoView.do?cntnts_sn=5696",
        "recommended_use": "피부 손상, 상처 세척, 드레싱, 흉터 예방, 병원 방문 기준 RAG 후보",
    },
    {
        "slug": "kdca_urticaria",
        "title": "질병관리청 국가건강정보포털 두드러기",
        "institution": "질병관리청",
        "source_type": "official_health_content",
        "url": "https://health.kdca.go.kr/healthinfo/biz/health/gnrlzHealthInfo/gnrlzHealthInfo/gnrlzHealthInfoView.do?cntnts_sn=6581",
        "recommended_use": "피부 알레르기, 혈관부종, 호흡곤란 동반 시 응급실 안내 근거",
    },
    {
        "slug": "easylaw_emergency_medical",
        "title": "찾기쉬운 생활법령정보 응급의료의 개념 등",
        "institution": "법제처/생활법령정보",
        "source_type": "legal_explanation",
        "url": "https://www.easylaw.go.kr/CSP/CnpClsMain.laf?ccfNo=1&cciNo=1&cnpClsNo=1&csmSeq=906&menuType=cnpcls&popMenu=ov",
        "recommended_use": "응급증상 및 이에 준하는 증상 rule-base 설계",
    },
    {
        "slug": "law_emergency_rule_article2",
        "title": "응급의료에 관한 법률 시행규칙 제2조",
        "institution": "국가법령정보센터",
        "source_type": "law_original",
        "url": "https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joBrNo=00&joNo=0002&lsiSeq=283863&urlMode=lsScJoRltInfoR",
        "recommended_use": "응급환자 법령 원문 및 시행일 확인",
    },
    {
        "slug": "egen_emergency_treat",
        "title": "E-Gen 응급상황시 대처요령",
        "institution": "중앙응급의료센터 E-Gen",
        "source_type": "official_emergency_guidance",
        "url": "https://www.e-gen.or.kr/egen/emergency_treat.do",
        "recommended_use": "응급상황 대처 행동 지침",
    },
    {
        "slug": "egen_first_aid_basics",
        "title": "E-Gen 기본 응급처치",
        "institution": "중앙응급의료센터 E-Gen",
        "source_type": "official_first_aid_guidance",
        "url": "https://www.e-gen.or.kr/egen/first_aid_basics.do",
        "recommended_use": "기본 응급처치 행동 지침",
    },
    {
        "slug": "egen_heat_illness",
        "title": "E-Gen 열사병/일사병 응급처치",
        "institution": "중앙응급의료센터 E-Gen",
        "source_type": "official_first_aid_guidance",
        "url": "https://www.e-gen.or.kr/egen/heat_iced_damage.do?contentsno=35",
        "recommended_use": "열사병 red flag 및 119 신고, 냉각 응급처치 근거",
    },
    {
        "slug": "egen_foreign_body_throat",
        "title": "E-Gen 목 이물질 응급처치",
        "institution": "중앙응급의료센터 E-Gen",
        "source_type": "official_first_aid_guidance",
        "url": "https://www.e-gen.or.kr/egen/foreign_material.do?contentsno=29",
        "recommended_use": "기도 폐쇄 위험, 목 이물질 119 신고 근거",
    },
    {
        "slug": "119_sososim_cpr",
        "title": "119 안전신고센터 소소심 캠페인",
        "institution": "소방청 119 안전신고센터",
        "source_type": "official_public_safety_guidance",
        "url": "https://www.119.go.kr/Center119/mobile/sense02.do",
        "recommended_use": "심폐소생술, 119 신고, AED 요청 보조 근거",
    },
    {
        "slug": "mois_rescue_first_aid",
        "title": "행정안전부 안전 배움터 구조·구급",
        "institution": "행정안전부",
        "source_type": "official_public_safety_guidance",
        "url": "https://mois.go.kr/chd/sub/a06/rescue_2/screen.do",
        "recommended_use": "119 구급차 도착 전 준비, 환자 정보 전달 근거",
    },
    {
        "slug": "kdca_openapi_data_go",
        "title": "공공데이터포털 질병관리청 국가건강정보포털 OpenAPI",
        "institution": "공공데이터포털/질병관리청",
        "source_type": "api_metadata",
        "url": "https://www.data.go.kr/data/15087442/openapi.do",
        "recommended_use": "향후 API 수집 전환 여부와 이용조건 확인",
    },
    {
        "slug": "open_law_api_guide",
        "title": "국가법령정보 공동활용 Open API 가이드",
        "institution": "법제처",
        "source_type": "api_metadata",
        "url": "https://open.law.go.kr/LSO/openApi/guideList.do",
        "recommended_use": "향후 법령 API 수집 전환 여부 확인",
    },
]


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
        if tag in {"p", "br", "li", "tr", "div", "section", "article", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        if tag in {"p", "li", "tr", "div", "section", "article", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        raw = html.unescape(" ".join(self.parts))
        raw = raw.replace("\ufeff", "")
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s+", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip() + "\n"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_text(html_path: Path) -> str:
    parser = TextExtractor()
    parser.feed(html_path.read_text(encoding="utf-8", errors="replace"))
    return parser.text()


def main() -> None:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "collection_method": "static_html_snapshot_via_curl",
        "api_note": "질병관리청 OpenAPI와 법령 OpenAPI는 인증키/OC 설정 후 별도 수집기로 전환 가능. 현재는 접근 가능한 공식 HTML 원문을 보관.",
        "sources": [],
    }

    for source in SOURCES:
        slug = source["slug"]
        html_path = HTML_DIR / f"{slug}.html"
        text_path = TEXT_DIR / f"{slug}.txt"

        status = "missing_html"
        if html_path.exists():
            text_path.write_text(extract_text(html_path), encoding="utf-8")
            status = "ok"

        record = {
            **source,
            "status": status,
            "html_path": str(html_path.relative_to(PROJECT_ROOT)),
            "text_path": str(text_path.relative_to(PROJECT_ROOT)),
            "html_size_bytes": html_path.stat().st_size if html_path.exists() else 0,
            "text_size_bytes": text_path.stat().st_size if text_path.exists() else 0,
            "html_sha256": sha256(html_path) if html_path.exists() else "",
            "text_sha256": sha256(text_path) if text_path.exists() else "",
        }
        manifest["sources"].append(record)

    manifest_path = MANIFEST_DIR / "official_sources_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = sum(1 for item in manifest["sources"] if item["status"] == "ok")
    print(f"Wrote {ok}/{len(SOURCES)} text extracts")
    print(manifest_path)


if __name__ == "__main__":
    main()
