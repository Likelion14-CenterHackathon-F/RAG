#!/usr/bin/env python3
"""Build JSONL retrieval datasets from local source folders and zip archives.

The script keeps source-derived data separate from the curated MVP post-care
rulebook. In patient-facing answers, the chatbot should prioritize
rules/emergency_rules.json, rag/mvp_care_knowledge.jsonl, and vetted official
chunks before lower-trust reference datasets.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "derived"
HOME = Path.home()


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def safe_member_name(name: str) -> str:
    return name.lstrip("/")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        print(f"[skip] {path}: {exc}")
        return None


def load_json_bytes(raw: bytes, source: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
        return data if isinstance(data, dict) else None
    except Exception as exc:
        print(f"[skip] {source}: {exc}")
        return None


def load_jsonl_bytes(raw: bytes, source: str) -> Iterator[dict[str, Any]]:
    text = raw.decode("utf-8-sig", errors="replace")
    for line_number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                yield data
        except Exception as exc:
            print(f"[skip] {source}:{line_number}: {exc}")


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            f.write("\n")
            count += 1
    return count


def find_download_dataset_dir(expected_name: str) -> Path | None:
    downloads = HOME / "Downloads"
    if not downloads.exists():
        return None
    for child in downloads.iterdir():
        if child.is_dir() and nfc(child.name) == expected_name:
            return child
    return None


def find_desktop_source_dirs() -> dict[str, Path]:
    desktop = HOME / "Desktop"
    wanted = {
        "surgery": "TL_외과",
        "dermatology": "TL_피부과",
    }
    found: dict[str, Path] = {}
    if not desktop.exists():
        return found
    for child in desktop.iterdir():
        if not child.is_dir():
            continue
        child_name = nfc(child.name)
        for key, expected in wanted.items():
            if child_name == expected:
                found[key] = child
    return found


def keywords_from(text: str, limit: int = 24) -> list[str]:
    tokens = re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
    stopwords = {"환자", "무엇", "있는", "한다", "가장", "대한", "경우", "사용", "피부", "시술"}
    counts = Counter(t for t in tokens if t not in stopwords)
    return [token for token, _ in counts.most_common(limit)]


def first_nonempty_source_info(data: dict[str, Any]) -> dict[str, Any]:
    for i in range(1, 6):
        source = data.get(f"Source_info{i}") or {}
        if clean_text(source.get(f"Knowledge Data{i}")):
            return {
                "status": clean_text(source.get(f"Status{i}")),
                "knowledge": clean_text(source.get(f"Knowledge Data{i}")),
                "title": clean_text(source.get(f"Title{i}")),
                "author": clean_text(source.get(f"Author Name{i}")),
                "publisher": clean_text(source.get(f"Publisher Name (Institution Name){i}")),
                "year": source.get(f"Year of Publication{i}"),
            }
    return {}


def medical_qa_zips(split: str) -> dict[str, Path]:
    base = find_download_dataset_dir("08.전문 의학지식 데이터")
    if not base:
        return {}
    prefix = "TL" if split == "Training" else "VL"
    label_root = base / "3.개방데이터" / "1.데이터" / split / "02.라벨링데이터"
    candidates = {
        "surgery": label_root / f"{prefix}_외과.zip",
        "dermatology": label_root / f"{prefix}_피부과.zip",
    }
    return {key: path for key, path in candidates.items() if path.exists()}


def medical_qa_records_from_zips(split: str) -> Iterable[dict[str, Any]]:
    department_label = {
        "surgery": "외과",
        "dermatology": "피부과",
    }
    for department, zip_path in medical_qa_zips(split).items():
        with ZipFile(zip_path) as zf:
            members = sorted(n for n in zf.namelist() if n.endswith(".json"))
            for member in members:
                data = load_json_bytes(zf.read(member), f"{zip_path}!{member}")
                if not data:
                    continue
                qa_id = clean_text(data.get("qa_id") or Path(safe_member_name(member)).stem)
                question = clean_text(data.get("question"))
                answer = clean_text(data.get("answer"))
                if not question or not answer:
                    continue
                text = f"질문: {question}\n정답: {answer}"
                yield {
                    "doc_id": f"MEDQA-{department.upper()}-{qa_id}",
                    "dataset_type": "medical_qa_reference",
                    "department": department,
                    "department_label": department_label[department],
                    "retrieval_use": "reference_only_not_postop_instruction",
                    "title": f"{department_label[department]} 전문 QA {qa_id}",
                    "content": text,
                    "keywords": keywords_from(text),
                    "metadata": {
                        "qa_id": qa_id,
                        "domain": data.get("domain"),
                        "q_type": data.get("q_type"),
                        "split": split,
                        "source_zip": str(zip_path),
                        "source_member": safe_member_name(member),
                    },
                }


def medical_qa_records_from_desktop(source_dirs: dict[str, Path]) -> Iterable[dict[str, Any]]:
    department_label = {
        "surgery": "외과",
        "dermatology": "피부과",
    }
    for department, source_dir in source_dirs.items():
        for path in sorted(source_dir.glob("*.json")):
            data = load_json(path)
            if not data:
                continue
            qa_id = clean_text(data.get("qa_id") or path.stem)
            question = clean_text(data.get("question"))
            answer = clean_text(data.get("answer"))
            if not question or not answer:
                continue
            text = f"질문: {question}\n정답: {answer}"
            yield {
                "doc_id": f"MEDQA-{department.upper()}-{qa_id}",
                "dataset_type": "medical_qa_reference",
                "department": department,
                "department_label": department_label[department],
                "retrieval_use": "reference_only_not_postop_instruction",
                "title": f"{department_label[department]} 전문 QA {qa_id}",
                "content": text,
                "keywords": keywords_from(text),
                "metadata": {
                    "qa_id": qa_id,
                    "domain": data.get("domain"),
                    "q_type": data.get("q_type"),
                    "split": "Training",
                    "source_path": str(path),
                },
            }


def medical_qa_records(split: str) -> Iterable[dict[str, Any]]:
    zip_sources = medical_qa_zips(split)
    if zip_sources:
        yield from medical_qa_records_from_zips(split)
        return
    if split == "Training":
        yield from medical_qa_records_from_desktop(find_desktop_source_dirs())


def problem_skin_label_zips(split: str) -> list[Path]:
    base = find_download_dataset_dir("02.문제성 피부 메이크업 추천 데이터")
    if not base:
        return []
    label_root = base / "3.개방데이터" / "1.데이터" / split / "2.라벨링데이터"
    return sorted(label_root.glob("*.zip"), key=lambda p: nfc(p.name)) if label_root.exists() else []


def problem_skin_records(split: str) -> Iterable[dict[str, Any]]:
    for zip_path in problem_skin_label_zips(split):
        folder_label = nfc(zip_path.stem)
        with ZipFile(zip_path) as zf:
            members = sorted(n for n in zf.namelist() if n.endswith(".json"))
            for member in members:
                data = load_json_bytes(zf.read(member), f"{zip_path}!{member}")
                if not data:
                    continue

                data_info = data.get("Data_info") or {}
                human = data.get("Human_info") or {}
                skin = data.get("Skin_info") or {}
                annotation = data.get("Annotation_info") or {}
                source = first_nonempty_source_info(data)

                seq = clean_text(data_info.get("SEQ") or Path(member).stem)
                user_question = clean_text(annotation.get("User Question"))
                response = clean_text(annotation.get("Makeup Response"))
                if not user_question or not response:
                    continue

                skin_problem = clean_text(human.get("Skin Problem Type"))
                recommended = clean_text(annotation.get("Recommended Ingredients"))
                avoid = clean_text(annotation.get("Ingredients to Avoid"))
                knowledge = clean_text(source.get("knowledge", ""))
                content_parts = [
                    f"피부 문제 유형: {skin_problem}",
                    f"피부 상태: {clean_text(skin.get('Skin condition category'))}",
                    f"사용자 질문: {user_question}",
                    f"권장 응답: {response}",
                ]
                if recommended:
                    content_parts.append(f"추천 성분: {recommended}")
                if avoid:
                    content_parts.append(f"피해야 할 성분: {avoid}")
                if knowledge:
                    content_parts.append(f"근거 지식: {knowledge}")
                text = "\n".join(part for part in content_parts if part)

                yield {
                    "doc_id": f"PROBLEM-SKIN-{seq}",
                    "dataset_type": "problem_skin_makeup_reference",
                    "department": "dermatology",
                    "retrieval_use": "makeup_and_skin_reference_only",
                    "title": f"{skin_problem or folder_label} QA {seq}",
                    "content": text,
                    "keywords": keywords_from(text),
                    "metadata": {
                        "seq": seq,
                        "split": split,
                        "source_folder": folder_label,
                        "source_zip": str(zip_path),
                        "source_member": safe_member_name(member),
                        "gender": clean_text(human.get("Gender")),
                        "age": clean_text(human.get("Age")),
                        "skin_problem_type": skin_problem,
                        "makeup_focus_areas": clean_text(human.get("Makeup focus areas")),
                        "recommended_ingredients": recommended,
                        "ingredients_to_avoid": avoid,
                        "source_title": source.get("title", ""),
                        "source_year": source.get("year", 0),
                    },
                }


def skin_care_label_zips(split: str) -> list[Path]:
    base = find_download_dataset_dir("03.스킨케어 성분-효능 추천 데이터")
    if not base:
        return []
    label_root = base / "3.개방데이터" / "2.데이터(NIA)" / split / "02.라벨링데이터"
    return sorted(label_root.glob("*.zip"), key=lambda p: nfc(p.name)) if label_root.exists() else []


def skin_care_records(split: str) -> Iterable[dict[str, Any]]:
    for zip_path in skin_care_label_zips(split):
        concern_from_zip = nfc(zip_path.stem).replace("TL_", "").replace("VL_", "")
        with ZipFile(zip_path) as zf:
            members = sorted(n for n in zf.namelist() if n.endswith(".jsonl"))
            for member in members:
                for data in load_jsonl_bytes(zf.read(member), f"{zip_path}!{member}"):
                    info = data.get("info") or {}
                    meta = data.get("meta") or {}
                    external = data.get("external") or []

                    record_id = clean_text(info.get("id") or Path(member).stem)
                    question = clean_text(info.get("question"))
                    answer = clean_text(info.get("answer"))
                    if not question or not answer:
                        continue

                    target_concern = clean_text(info.get("target_concern") or concern_from_zip)
                    skin_type = clean_text(meta.get("skin_type"))
                    evidence_sources = info.get("evidence_sources") or []
                    external_factors = [
                        f"{clean_text(item.get('factor'))}: {clean_text(item.get('details'))}"
                        for item in external
                        if isinstance(item, dict) and clean_text(item.get("factor"))
                    ]

                    content_parts = [
                        f"피부 고민: {target_concern}",
                        f"피부 타입: {skin_type}",
                        f"사용자 질문: {question}",
                        f"권장 응답: {answer}",
                    ]
                    if evidence_sources:
                        content_parts.append("참고 식별자: " + ", ".join(map(str, evidence_sources)))
                    if external_factors:
                        content_parts.append("외부 요인: " + "; ".join(external_factors))
                    text = "\n".join(part for part in content_parts if part)

                    yield {
                        "doc_id": f"SKINCARE-{record_id}",
                        "dataset_type": "skin_care_ingredient_reference",
                        "department": "dermatology",
                        "retrieval_use": "ingredient_and_skin_care_reference_only",
                        "title": f"{target_concern} 성분 추천 {record_id}",
                        "content": text,
                        "keywords": keywords_from(text),
                        "metadata": {
                            "record_id": record_id,
                            "split": split,
                            "target_concern": target_concern,
                            "source_survey_id": clean_text(info.get("source_survey_id")),
                            "gender": clean_text(meta.get("gender")),
                            "age": meta.get("age"),
                            "initial_skin_condition": clean_text(meta.get("initial_skin_condition")),
                            "skin_type": skin_type,
                            "skin_concerns": meta.get("skin_concerns") or [],
                            "image_filename": clean_text(meta.get("image_filename")),
                            "evidence_sources": evidence_sources,
                            "external_factors": external_factors,
                            "source_zip": str(zip_path),
                            "source_member": safe_member_name(member),
                        },
                    }


def chunk_text(text: str, max_chars: int = 1200, overlap_chars: int = 160) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for start in range(0, len(paragraph), max_chars - overlap_chars):
                chunk = paragraph[start : start + max_chars].strip()
                if chunk:
                    chunks.append(chunk)
            continue

        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current.strip())
            tail = current[-overlap_chars:].strip()
            current = f"{tail}\n\n{paragraph}" if tail else paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph

    if current.strip():
        chunks.append(current.strip())
    return chunks


def clean_official_text(text: str) -> str:
    lines = [clean_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    start_index = 0
    for index, line in enumerate(lines):
        if line.startswith("등록일자"):
            start_index = index
            break

    end_index = len(lines)
    footer_markers = (
        "본 공공저작물은",
        "목록",
        "개인정보처리방침",
        "COPYRIGHT",
        "↑ TOP",
    )
    for index in range(start_index, len(lines)):
        if any(lines[index].startswith(marker) for marker in footer_markers):
            end_index = index
            break

    cleaned: list[str] = []
    seen_recent: list[str] = []
    for line in lines[start_index:end_index]:
        if line in {"요약문"} and seen_recent.count(line) >= 1:
            continue
        if cleaned and cleaned[-1] == line:
            continue
        cleaned.append(line)
        seen_recent = (seen_recent + [line])[-6:]

    return "\n\n".join(cleaned)


def official_rag_candidate_records() -> Iterable[dict[str, Any]]:
    manifest_path = PROJECT_ROOT / "sources" / "official_by_use" / "manifests" / "official_sources_by_use.json"
    if not manifest_path.exists():
        return
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)
    for source in manifest.get("sources", []):
        if source.get("bucket") != "rag_candidate":
            continue
        text_path = PROJECT_ROOT / source["partitioned_text_path"]
        if not text_path.exists():
            print(f"[skip] missing official text: {text_path}")
            continue
        text = clean_official_text(text_path.read_text(encoding="utf-8"))
        for index, chunk in enumerate(chunk_text(text), 1):
            slug = clean_text(source.get("slug"))
            yield {
                "doc_id": f"OFFICIAL-{slug.upper()}-{index:04d}",
                "dataset_type": "official_post_care_reference",
                "department": "dermatology",
                "retrieval_use": "official_rag_candidate",
                "title": f"{source.get('title')} #{index}",
                "content": chunk,
                "keywords": keywords_from(chunk),
                "source": source.get("institution"),
                "source_refs": [source.get("url")],
                "metadata": {
                    "slug": slug,
                    "chunk_index": index,
                    "title": source.get("title"),
                    "institution": source.get("institution"),
                    "url": source.get("url"),
                    "bucket": source.get("bucket"),
                    "embedding_policy": source.get("embedding_policy"),
                    "text_sha256": source.get("text_sha256"),
                    "source_path": str(text_path),
                },
            }


def clean_trusted_text(text: str) -> str:
    lines = [clean_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    cleaned: list[str] = []
    for line in lines:
        if line in {"=== HTML PAGE TEXT ===", "=== ATTACHED PDF TEXT ==="}:
            cleaned.append(line)
            continue
        if line.startswith("[PDF page"):
            cleaned.append(line)
            continue
        if cleaned and cleaned[-1] == line:
            continue
        cleaned.append(line)

    return "\n\n".join(cleaned)


def trusted_rag_candidate_records() -> Iterable[dict[str, Any]]:
    manifest_path = PROJECT_ROOT / "sources" / "trusted_by_use" / "manifests" / "trusted_sources_by_use.json"
    if not manifest_path.exists():
        return
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)
    for source in manifest.get("sources", []):
        if source.get("bucket") != "rag_candidate":
            continue
        text_path = PROJECT_ROOT / source["partitioned_text_path"]
        if not text_path.exists():
            print(f"[skip] missing trusted text: {text_path}")
            continue
        text = clean_trusted_text(text_path.read_text(encoding="utf-8"))
        for index, chunk in enumerate(chunk_text(text), 1):
            slug = clean_text(source.get("slug"))
            yield {
                "doc_id": f"TRUSTED-{slug.upper()}-{index:04d}",
                "dataset_type": "trusted_post_care_reference",
                "department": source.get("department", "dermatology"),
                "procedure": source.get("procedure", "common"),
                "retrieval_use": "trusted_rag_candidate",
                "title": f"{source.get('title')} #{index}",
                "content": chunk,
                "keywords": keywords_from(chunk),
                "source": source.get("institution"),
                "source_refs": [source.get("url")],
                "metadata": {
                    "slug": slug,
                    "chunk_index": index,
                    "title": source.get("title"),
                    "institution": source.get("institution"),
                    "source_type": source.get("source_type"),
                    "url": source.get("url"),
                    "bucket": source.get("bucket"),
                    "embedding_policy": source.get("embedding_policy"),
                    "recommended_use": source.get("recommended_use"),
                    "text_sha256": source.get("text_sha256"),
                    "source_path": str(text_path),
                },
            }


def write_retriever_index_manifest(counts: dict[str, int]) -> None:
    manifest = {
        "version": "2026-08-15-expanded-corpus",
        "principle": "Index broad data only with explicit trust, scope, and routing metadata. Emergency and out-of-scope official documents remain excluded from patient-answer retrieval.",
        "default_patient_answer_index": [
            {
                "path": "rag/mvp_care_knowledge.jsonl",
                "trust_level": "curated",
                "use": "Primary post-care answer guidance",
                "count": line_count(PROJECT_ROOT / "rag" / "mvp_care_knowledge.jsonl"),
            },
            {
                "path": "derived/official_rag_candidate_chunks.jsonl",
                "trust_level": "official",
                "use": "Official wound/scar/urticaria reference chunks",
                "count": counts.get("official_rag_candidate_chunks", 0),
            },
            {
                "path": "derived/trusted_rag_candidate_chunks.jsonl",
                "trust_level": "official_or_professional",
                "use": "MFDS/FDA/AAD/ASPS skin-aesthetic aftercare and recovery chunks",
                "count": counts.get("trusted_rag_candidate_chunks", 0),
            },
        ],
        "expanded_reference_index": [
            {
                "path": "derived/skin_care_ingredient_rag.jsonl",
                "trust_level": "dataset_reference",
                "use": "Ingredient and skincare guidance only; not diagnosis or emergency triage",
                "count": counts.get("skin_care_ingredient_rag", 0),
            },
            {
                "path": "derived/problem_skin_makeup_rag.jsonl",
                "trust_level": "dataset_reference",
                "use": "Problem-skin makeup and ingredient caution reference only",
                "count": counts.get("problem_skin_makeup_rag", 0),
            },
            {
                "path": "derived/source_medical_qa_rag.jsonl",
                "trust_level": "medical_qa_reference",
                "use": "Specialist QA reference only; must not override emergency rules or official sources",
                "count": counts.get("source_medical_qa_rag", 0),
            },
        ],
        "evaluation_holdout": [
            {
                "path": "derived/skin_care_ingredient_eval.jsonl",
                "count": counts.get("skin_care_ingredient_eval", 0),
            },
            {
                "path": "derived/problem_skin_makeup_eval.jsonl",
                "count": counts.get("problem_skin_makeup_eval", 0),
            },
            {
                "path": "derived/source_medical_qa_eval.jsonl",
                "count": counts.get("source_medical_qa_eval", 0),
            },
        ],
        "excluded_from_embedding": [
            "sources/official_by_use/safety_only/",
            "sources/official_by_use/out_of_scope/",
            "sources/official_by_use/api_reference/",
            "sources/trusted_by_use/safety_only/",
            "sources/trusted_by_use/out_of_scope/",
            "sources/trusted_by_use/api_reference/",
        ],
    }
    with (OUTPUT_DIR / "retriever_index_manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    counts["source_medical_qa_rag"] = write_jsonl(
        OUTPUT_DIR / "source_medical_qa_rag.jsonl",
        medical_qa_records("Training"),
    )
    counts["source_medical_qa_eval"] = write_jsonl(
        OUTPUT_DIR / "source_medical_qa_eval.jsonl",
        medical_qa_records("Validation"),
    )
    counts["problem_skin_makeup_rag"] = write_jsonl(
        OUTPUT_DIR / "problem_skin_makeup_rag.jsonl",
        problem_skin_records("Training"),
    )
    counts["problem_skin_makeup_eval"] = write_jsonl(
        OUTPUT_DIR / "problem_skin_makeup_eval.jsonl",
        problem_skin_records("Validation"),
    )
    counts["skin_care_ingredient_rag"] = write_jsonl(
        OUTPUT_DIR / "skin_care_ingredient_rag.jsonl",
        skin_care_records("Training"),
    )
    counts["skin_care_ingredient_eval"] = write_jsonl(
        OUTPUT_DIR / "skin_care_ingredient_eval.jsonl",
        skin_care_records("Validation"),
    )
    counts["official_rag_candidate_chunks"] = write_jsonl(
        OUTPUT_DIR / "official_rag_candidate_chunks.jsonl",
        official_rag_candidate_records(),
    )
    counts["trusted_rag_candidate_chunks"] = write_jsonl(
        OUTPUT_DIR / "trusted_rag_candidate_chunks.jsonl",
        trusted_rag_candidate_records(),
    )

    manifest = {
        "version": "2026-08-15-expanded-corpus",
        "outputs": counts,
        "source_dirs": {
            "medical_qa_training_zips": {key: str(path) for key, path in medical_qa_zips("Training").items()},
            "medical_qa_validation_zips": {key: str(path) for key, path in medical_qa_zips("Validation").items()},
            "problem_skin_training_zips": [str(path) for path in problem_skin_label_zips("Training")],
            "problem_skin_validation_zips": [str(path) for path in problem_skin_label_zips("Validation")],
            "skin_care_training_zips": [str(path) for path in skin_care_label_zips("Training")],
            "skin_care_validation_zips": [str(path) for path in skin_care_label_zips("Validation")],
            "official_rag_candidate_dir": str(PROJECT_ROOT / "sources" / "official_by_use" / "rag_candidate"),
            "trusted_rag_candidate_dir": str(PROJECT_ROOT / "sources" / "trusted_by_use" / "rag_candidate"),
        },
        "notes": [
            "Training files are converted as retrieval candidates; Validation files are kept as evaluation holdout.",
            "Curated post-care answers should use rag/mvp_care_knowledge.jsonl first.",
            "Official rag_candidate chunks are safe for patient-answer retrieval, but emergency/safety-only official docs remain excluded.",
            "Trusted MFDS/FDA/AAD/ASPS rag_candidate chunks are patient-answer candidates only when emergency rules do not match.",
            "Source-derived QA, makeup, and ingredient files are reference-only and should not override emergency rules or official sources.",
            "chain_of_thought from the skincare ingredient dataset is intentionally excluded from all outputs.",
        ],
    }
    with (OUTPUT_DIR / "dataset_manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    write_retriever_index_manifest(counts)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
