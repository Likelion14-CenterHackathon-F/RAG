# Retrieval Schema

`mvp_care_knowledge.jsonl`의 각 줄은 하나의 검색 문서입니다. 벡터DB에는 `title + content + answer_template`를 임베딩하고, 나머지는 메타데이터 필터로 넣는 것을 권장합니다.

## 필드

- `doc_id`: 문서 고유 ID입니다.
- `dataset_type`: 문서 출처와 사용 범위입니다. 현재 값은 `post_care_guide`, `symptom_response`, `video_consult_trigger`, `safety_boundary`, `official_post_care_reference`, `trusted_post_care_reference`, `medical_qa_reference`, `problem_skin_makeup_reference`, `skin_care_ingredient_reference`입니다.
- `department`: `dermatology`, `rhinoplasty`, `common` 중 하나입니다.
- `procedure`: 시술명입니다. 공통이면 `common`을 사용합니다.
- `phase`: 경과일 범위입니다. 예: `D+0-D+2`, `D+8-D+21`.
- `intent`: 검색 의도입니다. 예: `washing`, `redness`, `asymmetry`, `anxiety`.
- `risk_level`: `normal`, `watch`, `urgent`, `emergency`.
- `video_consult`: 화상상담 유도 여부입니다.
- `keywords`: 사용자 입력과 매칭할 핵심 표현입니다.
- `title`: 관리자와 LLM이 읽기 쉬운 문서 제목입니다.
- `content`: RAG가 가져올 원문 지식입니다.
- `answer_template`: LLM이 답변할 때 따라야 할 문장 구조입니다.
- `source`: 데이터 출처 유형입니다.
- `source_refs`: 참고 출처 URL 또는 내부 데이터 출처입니다.

## 검색 필터 우선순위

1. `retrieval_use`
2. `department`
3. `procedure`
4. `phase`
5. `intent`
6. `risk_level`

## 색인 세트

- 기본 환자 답변 색인: `rag/mvp_care_knowledge.jsonl`, `derived/official_rag_candidate_chunks.jsonl`, `derived/trusted_rag_candidate_chunks.jsonl`
- 확장 참고 색인: `derived/skin_care_ingredient_rag.jsonl`, `derived/problem_skin_makeup_rag.jsonl`, `derived/source_medical_qa_rag.jsonl`
- 평가 holdout: `derived/skin_care_ingredient_eval.jsonl`, `derived/problem_skin_makeup_eval.jsonl`, `derived/source_medical_qa_eval.jsonl`

추가 신뢰 출처는 식약처/FDA/AAD/ASPS처럼 공신력 있는 기관 또는 전문가 단체의 환자용 자료입니다. 다만 `embedding_policy=allow_with_safety_filters` 문서는 정상 사후관리 답변에 사용할 때도 중대 위험 신호를 감지하면 즉시 hard-stop 룰이 우선해야 합니다.

확장 참고 색인은 답변 재료로 사용할 수 있지만, 공식 문서나 curated 문서를 이기면 안 됩니다. 특히 `medical_qa_reference`, `problem_skin_makeup_reference`, `skin_care_ingredient_reference`는 응급 판단이나 진단 확정 근거로 사용하지 않습니다.

## 추천 Top-K

- 정상 사후관리 문의: `top_k=3`
- 증상 문의: `top_k=5`
- 화상상담 후보: `top_k=5`, `video_consult=true` 문서에 가중치
- 응급 룰 매칭: RAG 검색하지 않음

## LLM 응답 제한

- 금지: "확실히 괜찮습니다", "감염이 아닙니다", "재수술이 필요 없습니다"처럼 진단을 확정하는 표현
- 권장: "정상 회복 과정에서 보일 수 있습니다", "정확한 확인을 위해 상담을 권장합니다"
- 응급: hard-coded 메시지만 출력하고 추가 관리법을 생성하지 않음
