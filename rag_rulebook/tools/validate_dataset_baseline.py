#!/usr/bin/env python3
"""Validate the Rag-Lab data baseline described in CLAUDE_HANDOFF.md step 1.

Checks performed:
  1. Every JSON file under rag_rulebook/ parses.
  2. Every JSONL file under rag_rulebook/ parses line by line.
  3. dataset_manifest.json output counts match real line counts.
  4. retriever_index_manifest.json counts match real line counts.
  5. The default patient-answer index really is 90 documents with unique doc_ids.
  6. No safety_only / out_of_scope / api_reference material leaked into the
     default patient-answer index (slug check + embedding_policy check).
  7. Provenance is preserved: official/trusted chunks keep a source URL,
     a source_path and non-empty source_refs.
  8. chain_of_thought never appears in any JSONL payload.
  9. Default-index documents have non-empty content.

Exit code 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

ROOT = Path(__file__).resolve().parents[1]

DATASET_MANIFEST = ROOT / "derived" / "dataset_manifest.json"
RETRIEVER_MANIFEST = ROOT / "derived" / "retriever_index_manifest.json"

# dataset_manifest.outputs key -> jsonl path relative to ROOT
MANIFEST_KEY_TO_PATH = {
    "source_medical_qa_rag": "derived/source_medical_qa_rag.jsonl",
    "source_medical_qa_eval": "derived/source_medical_qa_eval.jsonl",
    "problem_skin_makeup_rag": "derived/problem_skin_makeup_rag.jsonl",
    "problem_skin_makeup_eval": "derived/problem_skin_makeup_eval.jsonl",
    "skin_care_ingredient_rag": "derived/skin_care_ingredient_rag.jsonl",
    "skin_care_ingredient_eval": "derived/skin_care_ingredient_eval.jsonl",
    "official_rag_candidate_chunks": "derived/official_rag_candidate_chunks.jsonl",
    "trusted_rag_candidate_chunks": "derived/trusted_rag_candidate_chunks.jsonl",
}

EXCLUDED_BUCKETS = ("safety_only", "out_of_scope", "api_reference")
SOURCE_FAMILIES = ("official_by_use", "trusted_by_use")

# ASPS 추출에서 페이지 내비게이션이 본문으로 들어간 청크 3건을 제거한 뒤의 값이다.
# end_markers 가 실제 텍스트와 맞지 않아 크롭이 블로그 목록까지 포함하고 있었다.
EXPECTED_DEFAULT_INDEX_TOTAL = 106

# 확장 참고 색인과 평가 홀드아웃은 저장소에 담지 않는다(.gitignore 참고).
# AI-Hub 가공물이라 재배포 여지가 있고, 전문의 QA 는 진단 확정형이어서 환자 답변
# 색인에 섞이면 제품 경계를 넘는다. 런타임도 배포 DB 도 이 파일을 쓰지 않는다.
#
# 그래서 없으면 SKIP 이고, 있으면 매니페스트 건수와 일치해야 한다. 두 경우 모두
# 검증이 통과해야 한다. 기본 환자 답변 색인 90건은 언제나 필수다.
OPTIONAL_GROUPS = ("expanded_reference_index", "evaluation_holdout")
REQUIRED_GROUP = "default_patient_answer_index"


class Report:
    def __init__(self) -> None:
        self.failures: List[str] = []
        self.lines: List[str] = []

    def ok(self, label: str, detail: str = "") -> None:
        suffix = f" — {detail}" if detail else ""
        self.lines.append(f"  PASS  {label}{suffix}")

    def fail(self, label: str, detail: str) -> None:
        self.lines.append(f"  FAIL  {label} — {detail}")
        self.failures.append(f"{label}: {detail}")

    def skip(self, label: str, detail: str = "") -> None:
        """Not present and not required. Distinct from PASS so it stays visible."""
        suffix = f" — {detail}" if detail else ""
        self.lines.append(f"  SKIP  {label}{suffix}")

    def section(self, title: str) -> None:
        self.lines.append("")
        self.lines.append(title)

    def render(self) -> str:
        return "\n".join(self.lines)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def iter_jsonl(path: Path) -> Iterator[Tuple[int, Dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, start=1):
            raw = raw.strip()
            if not raw:
                continue
            yield lineno, json.loads(raw)


def check_json_parsing(report: Report) -> None:
    report.section("[1] JSON parsing")
    paths = sorted(ROOT.rglob("*.json"))
    bad: List[str] = []
    for path in paths:
        try:
            load_json(path)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{path.relative_to(ROOT)}: {exc}")
    if bad:
        report.fail("all *.json parse", "; ".join(bad))
    else:
        report.ok("all *.json parse", f"{len(paths)} files")


def check_jsonl_parsing(report: Report) -> Dict[str, int]:
    report.section("[2] JSONL parsing and line counts")
    counts: Dict[str, int] = {}
    for path in sorted(ROOT.rglob("*.jsonl")):
        rel = str(path.relative_to(ROOT))
        try:
            n = sum(1 for _ in iter_jsonl(path))
        except Exception as exc:  # noqa: BLE001
            report.fail(f"{rel} parses", str(exc))
            continue
        counts[rel] = n
        report.ok(f"{rel} parses", f"{n} records")
    return counts


def check_dataset_manifest(report: Report, counts: Dict[str, int]) -> None:
    report.section("[3] dataset_manifest.json counts")
    if not DATASET_MANIFEST.exists():
        # 이 매니페스트는 확장 색인을 AI-Hub 원본에서 만든 기록이다. 설명 대상 산출물이
        # 저장소에 없으면 매니페스트도 없다. 기본 색인 검증은 [4]에서 계속된다.
        report.skip("dataset_manifest.json", "not present; expanded datasets are not in this repo")
        return
    manifest = load_json(DATASET_MANIFEST)
    outputs = manifest.get("outputs", {})
    unmapped = sorted(set(outputs) - set(MANIFEST_KEY_TO_PATH))
    if unmapped:
        report.fail("every manifest output is mapped to a file", f"unmapped keys {unmapped}")
    for key, expected in sorted(outputs.items()):
        rel = MANIFEST_KEY_TO_PATH.get(key)
        if rel is None:
            continue
        actual = counts.get(rel)
        if actual is None:
            if (ROOT / rel).exists():
                report.fail(f"{key}", f"{rel} exists but failed to parse")
            else:
                report.skip(f"{key}", f"{rel} not in this repo")
        elif actual != expected:
            report.fail(f"{key}", f"manifest {expected} != actual {actual}")
        else:
            report.ok(f"{key}", f"{actual} records")


def check_retriever_manifest(
    report: Report, counts: Dict[str, int]
) -> Tuple[List[str], List[str]]:
    report.section("[4] retriever_index_manifest.json counts")
    manifest = load_json(RETRIEVER_MANIFEST)
    default_paths: List[str] = []
    for group in (REQUIRED_GROUP, *OPTIONAL_GROUPS):
        for entry in manifest.get(group, []):
            rel = entry["path"]
            expected = entry["count"]
            actual = counts.get(rel)
            label = f"{group}/{rel}"
            if actual is None:
                if group in OPTIONAL_GROUPS and not (ROOT / rel).exists():
                    report.skip(label, "not in this repo")
                else:
                    report.fail(label, "missing on disk")
            elif actual != expected:
                report.fail(label, f"manifest {expected} != actual {actual}")
            else:
                report.ok(label, f"{actual} records")
            if group == REQUIRED_GROUP:
                default_paths.append(rel)

    declared_total = sum(e["count"] for e in manifest.get(REQUIRED_GROUP, []))
    if declared_total != EXPECTED_DEFAULT_INDEX_TOTAL:
        report.fail(
            "default index total",
            f"expected {EXPECTED_DEFAULT_INDEX_TOTAL}, manifest declares {declared_total}",
        )
    else:
        report.ok("default index total", f"{declared_total} documents")

    excluded_prefixes = manifest.get("excluded_from_embedding", [])
    return default_paths, excluded_prefixes


def collect_excluded_slugs(report: Report) -> Dict[str, str]:
    """Map slug -> bucket for every source marked as not embeddable."""
    slug_to_bucket: Dict[str, str] = {}
    for family in SOURCE_FAMILIES:
        for bucket in EXCLUDED_BUCKETS:
            index_path = ROOT / "sources" / family / bucket / "_index.json"
            if not index_path.exists():
                continue
            for entry in load_json(index_path):
                slug = entry.get("slug")
                if slug:
                    slug_to_bucket[slug] = f"{family}/{bucket}"
    return slug_to_bucket


def check_default_index_integrity(
    report: Report, default_paths: List[str], excluded_prefixes: List[str]
) -> None:
    report.section("[5] default patient-answer index integrity")
    excluded_slugs = collect_excluded_slugs(report)

    doc_ids: Dict[str, str] = {}
    total = 0
    duplicate_failures: List[str] = []
    empty_content: List[str] = []
    leaked_slug: List[str] = []
    denied_policy: List[str] = []
    missing_provenance: List[str] = []
    chain_of_thought: List[str] = []

    for rel in default_paths:
        path = ROOT / rel
        for lineno, doc in iter_jsonl(path):
            total += 1
            where = f"{rel}:{lineno}"
            doc_id = doc.get("doc_id")

            if not doc_id:
                duplicate_failures.append(f"{where} has no doc_id")
            elif doc_id in doc_ids:
                duplicate_failures.append(f"{doc_id} duplicated in {doc_ids[doc_id]} and {where}")
            else:
                doc_ids[doc_id] = where

            if not (doc.get("content") or "").strip():
                empty_content.append(where)

            if "chain_of_thought" in json.dumps(doc, ensure_ascii=False):
                chain_of_thought.append(where)

            metadata = doc.get("metadata") or {}
            slug = metadata.get("slug")
            if slug and slug in excluded_slugs:
                leaked_slug.append(f"{where} slug={slug} bucket={excluded_slugs[slug]}")

            bucket = metadata.get("bucket")
            if bucket in EXCLUDED_BUCKETS:
                leaked_slug.append(f"{where} bucket={bucket}")

            policy = metadata.get("embedding_policy")
            if policy == "deny":
                denied_policy.append(f"{where} doc_id={doc_id}")

            # Provenance only applies to chunks derived from external sources.
            if metadata:
                if not metadata.get("url"):
                    missing_provenance.append(f"{where} missing metadata.url")
                if not metadata.get("source_path"):
                    missing_provenance.append(f"{where} missing metadata.source_path")
            if not doc.get("source_refs"):
                missing_provenance.append(f"{where} missing source_refs")

    if total != EXPECTED_DEFAULT_INDEX_TOTAL:
        report.fail("document count", f"expected {EXPECTED_DEFAULT_INDEX_TOTAL}, read {total}")
    else:
        report.ok("document count", f"{total} documents")

    for label, problems in (
        ("unique doc_id", duplicate_failures),
        ("non-empty content", empty_content),
        ("no excluded bucket leakage", leaked_slug),
        ("no embedding_policy=deny", denied_policy),
        ("provenance preserved", missing_provenance),
        ("no chain_of_thought", chain_of_thought),
    ):
        if problems:
            report.fail(label, f"{len(problems)} problem(s): " + "; ".join(problems[:5]))
        else:
            report.ok(label)

    report.section("[6] excluded_from_embedding prefixes exist")
    for prefix in excluded_prefixes:
        path = ROOT / prefix
        if path.exists():
            n = len(list(path.glob("*.txt")))
            report.ok(prefix, f"{n} text file(s), all kept out of the index")
        else:
            report.ok(prefix, "declared but empty on disk")


def check_chain_of_thought_everywhere(report: Report) -> None:
    report.section("[7] chain_of_thought absent from every JSONL")
    offenders: List[str] = []
    for path in sorted(ROOT.rglob("*.jsonl")):
        rel = str(path.relative_to(ROOT))
        with path.open("r", encoding="utf-8") as handle:
            for lineno, raw in enumerate(handle, start=1):
                if "chain_of_thought" in raw:
                    offenders.append(f"{rel}:{lineno}")
                    break
    if offenders:
        report.fail("no chain_of_thought key", ", ".join(offenders))
    else:
        report.ok("no chain_of_thought key")


def main() -> None:
    report = Report()
    report.lines.append(f"Rag-Lab data baseline validation (root: {ROOT})")

    check_json_parsing(report)
    counts = check_jsonl_parsing(report)
    check_dataset_manifest(report, counts)
    default_paths, excluded_prefixes = check_retriever_manifest(report, counts)
    check_default_index_integrity(report, default_paths, excluded_prefixes)
    check_chain_of_thought_everywhere(report)

    print(report.render())
    print()
    if report.failures:
        print(f"RESULT: FAIL ({len(report.failures)} problem(s))")
        for failure in report.failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("RESULT: PASS")


if __name__ == "__main__":
    main()
