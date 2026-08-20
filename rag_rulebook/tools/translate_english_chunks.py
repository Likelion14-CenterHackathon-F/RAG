#!/usr/bin/env python3
"""영어로 된 색인 청크를 한국어로 번역한다.

왜 필요한가. 임베딩 모델이 `nlpai-lab/KURE-v1` 로 한국어 특화이고 환자 질문은
한국어다. 색인 90건 중 24건이 순수 영어(ASPS/AAD/FDA)이며, 재측정 데이터에서
한국어 질문에 대한 유사도가 한국어 문서 평균 0.5305 대 영어 문서 평균 0.4918 로
갈렸다. 관련 프로브 12건의 1순위는 전부 한국어 문서였다.

무엇을 번역하는가. `title` 과 `content` 둘 다다. 적재 시 임베딩 입력은
title + content + answer_template 이므로 제목이 영어로 남으면 절반만 고치는 것이 된다.

원문은 버리지 않는다. `metadata.original_title`, `metadata.original_content` 에
보존한다. 오역이 발견되면 대조해야 하고, provenance 검증이 `metadata.url` 과
`source_path` 를 확인한다.

부수 작업 두 가지를 함께 처리한다.
- `=== HTML PAGE TEXT ===` 같은 추출 마커 제거. 번역 대상에서 빼고 임베딩도 오염시키지 않는다.
- `keywords` 재생성. 현재 영어 불용어("to", "you", "the")로 채워져 있어 의미가 없다.

번역 후에는 재적재와 재측정이 필수다. content 가 바뀌면 저장된 벡터가 무효이고
`RAG_MIN_SIMILARITY` 의 근거도 다시 세워야 한다.

    python rag_rulebook/tools/translate_english_chunks.py            # dry-run
    python rag_rulebook/tools/translate_english_chunks.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "derived" / "trusted_rag_candidate_chunks.jsonl",
    ROOT / "derived" / "official_rag_candidate_chunks.jsonl",
]

DEEPL_FREE = "https://api-free.deepl.com/v2/translate"
DEEPL_PRO = "https://api.deepl.com/v2/translate"

# 추출 단계에서 붙은 마커. 본문 내용이 아니므로 번역 전에 제거한다.
BOILERPLATE = re.compile(r"^=== [A-Z][A-Z ]+ ===\s*\n+|\[PDF page \d+\]\s*\n*", re.M)

# 한국어 불용어. keywords 재생성에서 제외한다.
STOPWORDS = {
    "그리고", "그러나", "또는", "또한", "하지만", "때문에", "위해", "통해", "대해",
    "있습니다", "있는", "있을", "합니다", "하는", "해야", "됩니다", "되는", "이런",
    "그런", "저런", "것을", "것이", "수도", "경우", "다음", "이후", "이상", "이하",
}


def is_english(text: str) -> bool:
    """한글이 한 자도 없으면 영어 청크로 본다."""
    return not re.search(r"[가-힣]", text or "")


def strip_boilerplate(text: str) -> str:
    return BOILERPLATE.sub("", text or "").strip()


def read_secret(key: str) -> str | None:
    """환경변수를 먼저 보고, 없으면 저장소 .env 를 읽는다."""
    value = os.environ.get(key)
    if value:
        return value
    env_path = ROOT.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip() or None
    return None


class DeepLTranslator:
    """DeepL 무료/유료 엔드포인트를 자동으로 고른다."""

    name = "deepl"

    def __init__(self, auth_key: str) -> None:
        self.auth_key = auth_key
        self.endpoint = DEEPL_FREE if auth_key.endswith(":fx") else DEEPL_PRO

    def translate(self, text: str) -> str:
        data = urllib.parse.urlencode(
            {
                "text": text,
                "target_lang": "KO",
                "source_lang": "EN",
                # 의학 안내문은 원문 서식이 의미를 가지므로 줄바꿈을 보존한다.
                "split_sentences": "nonewlines",
                "preserve_formatting": "1",
            }
        ).encode()
        request = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={"Authorization": f"DeepL-Auth-Key {self.auth_key}"},
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read())
                return payload["translations"][0]["text"]
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 456, 500, 503) and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("DeepL 재시도 실패")


def korean_keywords(text: str, limit: int = 20) -> list[str]:
    """번역문에서 keywords 를 다시 만든다. 2자 이상 한글 토큰만 센다."""
    tokens = re.findall(r"[가-힣]{2,}", text)
    counts = Counter(t for t in tokens if t not in STOPWORDS)
    return [token for token, _ in counts.most_common(limit)]


def translate_document(doc: dict[str, Any], translator: Any) -> dict[str, Any]:
    original_title = doc["title"]
    original_content = doc["content"]
    cleaned = strip_boilerplate(original_content)

    title_ko = translator.translate(original_title)
    content_ko = translator.translate(cleaned)

    doc = dict(doc)
    doc["title"] = title_ko
    doc["content"] = content_ko
    doc["keywords"] = korean_keywords(f"{title_ko}\n{content_ko}")

    metadata = dict(doc.get("metadata") or {})
    metadata["original_title"] = original_title
    metadata["original_content"] = original_content
    metadata["language"] = "ko"
    metadata["translated_from"] = "en"
    metadata["translator"] = translator.name
    doc["metadata"] = metadata
    return doc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="파일에 기록한다.")
    parser.add_argument("--limit", type=int, default=0, help="앞 N건만 처리 (검증용)")
    args = parser.parse_args()

    auth_key = read_secret("DEEPL_AUTH_KEY")
    if not auth_key:
        print("DEEPL_AUTH_KEY 가 없습니다. 환경변수나 .env 에 넣어 주세요.", file=sys.stderr)
        return 1
    translator = DeepLTranslator(auth_key)

    total = translated = 0
    for path in TARGETS:
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        out: list[str] = []
        changed = 0
        for line in lines:
            doc = json.loads(line)
            total += 1
            if not is_english(doc.get("content", "")):
                out.append(json.dumps(doc, ensure_ascii=False))
                continue
            if args.limit and translated >= args.limit:
                out.append(json.dumps(doc, ensure_ascii=False))
                continue

            new_doc = translate_document(doc, translator)
            translated += 1
            changed += 1
            print(f"  {new_doc['doc_id']}")
            print(f"    제목: {new_doc['title']}")
            print(f"    본문: {new_doc['content'][:90].replace(chr(10), ' ')}...")
            out.append(json.dumps(new_doc, ensure_ascii=False))

        if args.apply and changed:
            path.write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"{path.name}: {changed}건 번역 / 전체 {len(lines)}건")

    print(f"\n전체 {total}건 중 영어 {translated}건 번역")
    if not args.apply:
        print("dry-run 입니다. 파일에 기록하려면 --apply 를 붙이세요.")
    else:
        print("재적재와 재측정이 필요합니다:")
        print("  python scripts/ingest_rag_documents.py --apply")
        print("  python verification/probe_retrieval.py --out verification/retrieval_result_v3.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
