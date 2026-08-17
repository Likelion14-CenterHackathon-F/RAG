#!/usr/bin/env python3
"""Extract readable text and metadata from collected trusted source snapshots.

This source group is scoped to cosmetic surgery, dermatology, and
skin-aesthetic aftercare. Raw HTML/PDF files remain as provenance; this script
creates normalized text companions and a manifest for downstream partitioning.
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


try:
    import pdfplumber
except Exception:  # pragma: no cover - dependency availability is environment-specific.
    pdfplumber = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "sources" / "raw_trusted"
HTML_DIR = SOURCE_ROOT / "html"
PDF_DIR = SOURCE_ROOT / "pdf"
TEXT_DIR = SOURCE_ROOT / "text"
MANIFEST_DIR = SOURCE_ROOT / "manifests"


SOURCES: list[dict[str, Any]] = [
    {
        "slug": "mfds_filler_safety_guide",
        "title": "식품의약품안전처 성형용 필러 안전사용을 위한 안내서",
        "institution": "식품의약품안전처",
        "source_type": "official_medical_device_safety",
        "url": "https://www.mfds.go.kr/brd/m_465/view.do?seq=27164",
        "recommended_use": "필러 부작용, 시술 전후 주의사항, 병원 문의 기준",
        "department": "dermatology",
        "procedure": "dermal_filler",
        "html_file": "mfds_filler_safety_guide.html",
        "pdf_file": "mfds_filler_safety_guide.pdf",
        "start_markers": ["○ 성형용필러란 얼굴"],
        "end_markers": ["첨부파일", "목록"],
    },
    {
        "slug": "mfds_filler_device_info",
        "title": "식품의약품안전처 성형용필러",
        "institution": "식품의약품안전처",
        "source_type": "official_medical_device_info",
        "url": "https://www.mfds.go.kr/brd/m_464/view.do?seq=28280",
        "recommended_use": "성형용 필러 정의와 사용 전 주의사항",
        "department": "dermatology",
        "procedure": "dermal_filler",
        "html_file": "mfds_filler_device_info.html",
        "start_markers": ["○ 성형용필러란"],
        "end_markers": ["목록", "만족도"],
    },
    {
        "slug": "mfds_laser_safety_guide",
        "title": "식품의약품안전처 의료용레이저 안전사용 안내서",
        "institution": "식품의약품안전처",
        "source_type": "official_medical_device_safety",
        "url": "https://www.mfds.go.kr/brd/m_465/view.do?seq=27162",
        "recommended_use": "피부 레이저 시술 후 주의사항, 부작용 종류, 문의 기준",
        "department": "dermatology",
        "procedure": "laser_skin_treatment",
        "html_file": "mfds_laser_safety_guide.html",
        "pdf_file": "mfds_laser_safety_guide.pdf",
        "start_markers": ["○ 의료용레이저(피부치료용)란"],
        "end_markers": ["첨부파일", "목록"],
    },
    {
        "slug": "mfds_laser_device_info",
        "title": "식품의약품안전처 의료용 레이저(피부치료용)",
        "institution": "식품의약품안전처",
        "source_type": "official_medical_device_info",
        "url": "https://www.mfds.go.kr/brd/m_464/view.do?seq=28291",
        "recommended_use": "레이저 치료 후 열, 자극, 자외선, 추가 시술 회피",
        "department": "dermatology",
        "procedure": "laser_skin_treatment",
        "html_file": "mfds_laser_device_info.html",
        "start_markers": ["○ 의료용레이저(피부치료용)란"],
        "end_markers": ["목록", "만족도"],
    },
    {
        "slug": "aad_acne_scar_aftercare",
        "title": "American Academy of Dermatology acne scar treatment aftercare",
        "institution": "American Academy of Dermatology",
        "source_type": "professional_patient_guidance",
        "url": "https://www.aad.org/public/diseases/acne/derm-treat/scars/self-care",
        "recommended_use": "여드름 흉터 치료 후 세안, 메이크업, 자외선 차단, 감염 예방",
        "department": "dermatology",
        "procedure": "acne_scar_treatment",
        "html_file": "aad_acne_scar_aftercare.html",
        "start_markers": ["Proper aftercare plays an important role"],
        "end_markers": ["Image", "References"],
    },
    {
        "slug": "aad_laser_scar_treatment",
        "title": "American Academy of Dermatology laser treatment for scars",
        "institution": "American Academy of Dermatology",
        "source_type": "professional_patient_guidance",
        "url": "https://www.aad.org/public/cosmetic/scars-stretch-marks/laser-treatment-scar",
        "recommended_use": "흉터 레이저 전후 주의사항, 자외선, 레티노이드/글리콜릭산, 헤르페스 병력",
        "department": "dermatology",
        "procedure": "laser_scar_treatment",
        "html_file": "aad_laser_scar_treatment.html",
        "start_markers": ["A laser can seem like a magic wand"],
        "end_markers": ["Images", "References"],
    },
    {
        "slug": "asps_dermal_filler_safety",
        "title": "American Society of Plastic Surgeons dermal fillers risks and safety",
        "institution": "American Society of Plastic Surgeons",
        "source_type": "professional_patient_guidance",
        "url": "https://www.plasticsurgery.org/cosmetic-procedures/dermal-fillers/safety",
        "recommended_use": "필러 감염, 피부괴사, 혈류 차단, 시야 이상 등 위험 신호",
        "department": "dermatology",
        "procedure": "dermal_filler",
        "html_file": "asps_dermal_filler_safety.html",
        "start_markers": ["What are the risks of dermal fillers?"],
        "end_markers": ["Procedures", "Footer"],
    },
    {
        "slug": "asps_dermal_filler_recovery",
        "title": "American Society of Plastic Surgeons dermal fillers recovery",
        "institution": "American Society of Plastic Surgeons",
        "source_type": "professional_patient_guidance",
        "url": "https://www.plasticsurgery.org/cosmetic-procedures/dermal-fillers/recovery",
        "recommended_use": "필러 후 붓기, 멍, 활동 제한, 즉시 진료 신호",
        "department": "dermatology",
        "procedure": "dermal_filler",
        "html_file": "asps_dermal_filler_recovery.html",
        "start_markers": ["What should I expect during my dermal fillers recovery?"],
        "end_markers": ["Procedures", "Footer"],
    },
    {
        "slug": "asps_rhinoplasty_recovery",
        "title": "American Society of Plastic Surgeons rhinoplasty recovery",
        "institution": "American Society of Plastic Surgeons",
        "source_type": "professional_patient_guidance",
        "url": "https://www.plasticsurgery.org/cosmetic-procedures/rhinoplasty/recovery",
        "recommended_use": "코성형 회복 기간, 부목/패킹, 붓기 변화, follow-up",
        "department": "rhinoplasty",
        "procedure": "rhinoplasty",
        "html_file": "asps_rhinoplasty_recovery.html",
        "start_markers": ["What should I expect during my rhinoplasty recovery?"],
        "end_markers": ["Procedures", "Footer"],
    },
    {
        "slug": "fda_dermal_filler_dos_donts",
        "title": "FDA dermal filler do's and don'ts for wrinkles, lips, and more",
        "institution": "U.S. Food and Drug Administration",
        "source_type": "official_consumer_update",
        "url": "https://www.fda.gov/consumers/consumer-updates/dermal-filler-dos-and-donts-wrinkles-lips-and-more",
        "recommended_use": "필러 승인 용도, 일반 부작용, 금지 사용, 소비자 주의사항",
        "department": "dermatology",
        "procedure": "dermal_filler",
        "html_file": "fda_dermal_filler_dos_donts.html",
        "start_markers": ["People are seeking treatments"],
        "end_markers": ["BEGIN QUALTRICS", "Additional Information"],
    },
    {
        "slug": "fda_dermal_fillers_soft_tissue",
        "title": "FDA dermal fillers soft tissue fillers",
        "institution": "U.S. Food and Drug Administration",
        "source_type": "official_medical_device_safety",
        "url": "https://www.fda.gov/medical-devices/aesthetic-cosmetic-devices/dermal-fillers-soft-tissue-fillers",
        "recommended_use": "필러 혈관 주입 위험, 즉시 진료 기준, 환자/의료진 안전 정보",
        "department": "dermatology",
        "procedure": "dermal_filler",
        "html_file": "fda_dermal_fillers_soft_tissue.html",
        "start_markers": ["Approved Uses of Dermal Fillers"],
        "end_markers": ["Date Issued", "Subscribe to FDA"],
    },
    {
        "slug": "asps_botulinum_toxin_safety",
        "title": "American Society of Plastic Surgeons botulinum toxin risks and safety",
        "institution": "American Society of Plastic Surgeons",
        "source_type": "professional_patient_guidance",
        "url": "https://www.plasticsurgery.org/cosmetic-procedures/botulinum-toxin/safety",
        "recommended_use": "보툴리눔 톡신 후 호흡, 삼킴, 말 어눌함 등 위험 신호",
        "department": "dermatology",
        "procedure": "botulinum_toxin",
        "html_file": "asps_botulinum_toxin_safety.html",
        "start_markers": ["What are the risks of botulinum toxin injections?"],
        "end_markers": ["Procedures", "Footer"],
    },
    {
        "slug": "asps_botulinum_toxin_recovery",
        "title": "American Society of Plastic Surgeons botulinum toxin recovery",
        "institution": "American Society of Plastic Surgeons",
        "source_type": "professional_patient_guidance",
        "url": "https://www.plasticsurgery.org/cosmetic-procedures/botulinum-toxin/recovery",
        "recommended_use": "보툴리눔 톡신 후 회복, 문지르기/마사지 회피",
        "department": "dermatology",
        "procedure": "botulinum_toxin",
        "html_file": "asps_botulinum_toxin_recovery.html",
        "start_markers": ["What should I expect during my recovery after botulinum toxin injections?"],
        "end_markers": ["Procedures", "Footer"],
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
        return raw.strip()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_text(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = text.replace("\u200b", "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def crop_text(text: str, start_markers: list[str], end_markers: list[str]) -> str:
    text = normalize_text(text)
    start = 0
    for marker in start_markers:
        index = text.find(marker)
        if index >= 0:
            start = index
            break

    end = len(text)
    for marker in end_markers:
        index = text.find(marker, start + 1)
        if index >= 0:
            end = min(end, index)

    cropped = text[start:end].strip()
    return re.sub(r"\n{3,}", "\n\n", cropped)


def extract_html_text(html_path: Path, source: dict[str, Any]) -> str:
    parser = TextExtractor()
    parser.feed(html_path.read_text(encoding="utf-8", errors="replace"))
    return crop_text(parser.text(), source.get("start_markers", []), source.get("end_markers", []))


def extract_pdf_text(pdf_path: Path) -> str:
    if pdfplumber is None:
        return ""
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, 1):
            page_text = page.extract_text() or ""
            page_text = normalize_text(page_text)
            if page_text:
                pages.append(f"[PDF page {page_index}]\n{page_text}")
    return "\n\n".join(pages)


def combined_text(source: dict[str, Any]) -> tuple[str, str]:
    sections: list[str] = []
    status_parts: list[str] = []

    html_name = source.get("html_file")
    if html_name:
        html_path = HTML_DIR / html_name
        if html_path.exists():
            html_text = extract_html_text(html_path, source)
            if html_text:
                sections.append("=== HTML PAGE TEXT ===\n" + html_text)
                status_parts.append("html_ok")
        else:
            status_parts.append("missing_html")

    pdf_name = source.get("pdf_file")
    if pdf_name:
        pdf_path = PDF_DIR / pdf_name
        if pdf_path.exists():
            pdf_text = extract_pdf_text(pdf_path)
            if pdf_text:
                sections.append("=== ATTACHED PDF TEXT ===\n" + pdf_text)
                status_parts.append("pdf_ok")
            else:
                status_parts.append("pdf_text_empty")
        else:
            status_parts.append("missing_pdf")

    return "\n\n".join(sections).strip() + "\n", ",".join(status_parts) or "missing_source"


def source_record(source: dict[str, Any], status: str, text_path: Path) -> dict[str, Any]:
    html_name = source.get("html_file")
    pdf_name = source.get("pdf_file")
    html_path = HTML_DIR / html_name if html_name else None
    pdf_path = PDF_DIR / pdf_name if pdf_name else None
    return {
        **{key: value for key, value in source.items() if key not in {"start_markers", "end_markers"}},
        "status": status,
        "html_path": str(html_path.relative_to(PROJECT_ROOT)) if html_path else "",
        "pdf_path": str(pdf_path.relative_to(PROJECT_ROOT)) if pdf_path else "",
        "text_path": str(text_path.relative_to(PROJECT_ROOT)),
        "html_size_bytes": html_path.stat().st_size if html_path and html_path.exists() else 0,
        "pdf_size_bytes": pdf_path.stat().st_size if pdf_path and pdf_path.exists() else 0,
        "text_size_bytes": text_path.stat().st_size if text_path.exists() else 0,
        "html_sha256": sha256(html_path) if html_path and html_path.exists() else "",
        "pdf_sha256": sha256(pdf_path) if pdf_path and pdf_path.exists() else "",
        "text_sha256": sha256(text_path) if text_path.exists() else "",
    }


def main() -> None:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "collection_method": "static_html_snapshot_via_curl; mfds_pdf_attachments_via_static_down_link",
        "scope": "cosmetic surgery, dermatology, skin-aesthetic aftercare",
        "sources": [],
    }

    for source in SOURCES:
        slug = source["slug"]
        text_path = TEXT_DIR / f"{slug}.txt"
        text, status = combined_text(source)
        if text.strip():
            text_path.write_text(text, encoding="utf-8")
        manifest["sources"].append(source_record(source, status, text_path))

    manifest_path = MANIFEST_DIR / "trusted_sources_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = sum(1 for item in manifest["sources"] if "ok" in item["status"])
    print(f"Wrote {ok}/{len(SOURCES)} trusted text extracts")
    print(manifest_path)


if __name__ == "__main__":
    main()
