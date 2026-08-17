# Post-Care Chatbot RAG Rulebook

이 폴더는 피부과 시술 및 코성형 사후관리 챗봇 MVP를 위한 Retrieval 데이터셋과 안전 룰북입니다.

## 핵심 구조

- `rules/emergency_rules.json`: RAG와 LLM보다 먼저 실행되는 hard-stop 응급 룰셋입니다.
- `rules/triage_policy.json`: 위험도 판정, RAG 검색, 화상상담 유도 우선순위를 정의합니다.
- `DATASET_README.md`: 현재 데이터셋의 출처, 용도, 저장 형식, 활용 방식을 설명하는 인벤토리 문서입니다.
- `rag/mvp_care_knowledge.jsonl`: 바로 벡터DB에 적재할 수 있는 curated 사후관리 지식 문서입니다.
- `rag/retrieval_schema.md`: RAG 문서 필드와 검색 필터 설계입니다.
- `test_cases/integration_scenarios.json`: MVP 통합 테스트 시나리오와 기대 라우팅입니다.
- `tools/build_rag_datasets.py`: 다운로드 원본 zip과 첨부 JSON 폴더를 RAG용 JSONL로 변환합니다. 압축을 풀지 않고 zip 내부 JSON/JSONL을 직접 읽습니다.
- `tools/extract_official_source_text.py`: 공식 HTML 원본에서 텍스트와 manifest를 생성합니다.
- `tools/partition_official_sources.py`: 공식 텍스트를 제품 범위에 맞춰 RAG 후보, safety 전용, 범위 밖으로 분류합니다.
- `tools/extract_trusted_source_text.py`: 식약처/FDA/AAD/ASPS HTML/PDF 원본에서 텍스트와 manifest를 생성합니다.
- `tools/partition_trusted_sources.py`: 추가 신뢰 출처를 RAG 후보와 safety 전용으로 분류합니다.
- `tools/validate_triage.py`: 룰셋과 테스트 케이스의 라우팅을 간단히 검증합니다.
- `sources/raw_official/`: 공식 자료 원본 HTML, 추출 텍스트, 원본 manifest입니다.
- `sources/official_by_use/`: 성형/피부미용 사후관리 범위에 맞춘 공식 자료 분류본입니다.
- `sources/raw_trusted/`: 식약처/FDA/AAD/ASPS 원본 HTML/PDF, 추출 텍스트, 원본 manifest입니다.
- `sources/trusted_by_use/`: 추가 신뢰 출처의 용도별 분류본입니다.

## 권장 처리 순서

1. 사용자 입력 텍스트와 이미지 메타데이터를 정규화합니다.
2. `emergency_rules.json`을 먼저 적용합니다.
3. hard-stop이 아니면 시술명, 경과일, 증상 키워드, 불안 표현을 추출합니다.
4. `mvp_care_knowledge.jsonl`에서 `department`, `procedure`, `phase`, `keywords`, `risk_level`을 필터로 검색합니다.
5. 검색 결과를 바탕으로 LLM이 답변하되, 진단 확정 표현은 금지합니다.
6. 불안도가 높거나 이미지 판단 신뢰도가 낮으면 화상상담 CTA를 노출합니다.

## 안전 원칙

응급 키워드가 감지되면 LLM 자유 응답을 중단하고 hard-coded 메시지를 반환합니다. RAG 검색 결과는 환자 상태 설명과 관리 가이드를 돕기 위한 근거이며, 응급 판단을 대체하지 않습니다.

## 공식 자료 분류 원칙

성형/피부미용 사후관리와 직접 연결되는 공식 자료만 `sources/official_by_use/rag_candidate/`에 둡니다. 일반 응급처치, CPR, 응급의료법 기준은 벡터DB에 넣지 않고 `safety_only/`에 두어 hard-stop 룰과 CTA 근거로만 사용합니다. 심근경색, 뇌졸중, 열사병, 목 이물질처럼 현재 도메인 밖의 일반 의학 자료는 `out_of_scope/`에 보관합니다.

## 추가 신뢰 출처 분류 원칙

식약처, FDA, AAD, ASPS처럼 공신력 있는 기관/전문가 단체 자료 중 성형·피부미용 사후관리와 직접 연결되는 문서만 `sources/trusted_by_use/rag_candidate/`에 둡니다. 필러 혈류 차단, 시야 이상, 보툴리눔 톡신 후 호흡·삼킴 이상처럼 중대 위험 신호 중심 문서는 `safety_only/`에 두고 hard-stop 룰 근거로만 사용합니다.

## 첨부 데이터 활용 방식

다운로드의 `08.전문 의학지식 데이터` 중 `TL_외과`, `TL_피부과`는 전문의학 QA 참고 문서로 변환합니다. 다운로드의 `02.문제성 피부 메이크업 추천 데이터`는 피부 문제 유형, 사용자 질문, 메이크업/성분 응답을 보조 RAG 문서로 변환합니다. 다운로드의 `03.스킨케어 성분-효능 추천 데이터`는 성분/효능/피부고민 참고 문서로 변환하되, `chain_of_thought`는 산출물에 포함하지 않습니다.

Training 데이터는 RAG 후보로 변환하고, Validation 데이터는 검색 품질 평가용 holdout으로 분리합니다. 시술 후 사후관리 MVP 답변은 안전성을 위해 `rag/mvp_care_knowledge.jsonl`과 `derived/official_rag_candidate_chunks.jsonl`을 우선 사용합니다. 추가 신뢰 출처는 `derived/trusted_rag_candidate_chunks.jsonl`로 별도 변환하며, 응급 룰이 매칭되지 않은 경우에만 기본 환자 답변 색인에 포함합니다.

## 현재 산출물

- `rag/mvp_care_knowledge.jsonl`: curated 사후관리 문서 17개
- `derived/official_rag_candidate_chunks.jsonl`: 국내 공식 RAG 후보 문서 chunk
- `derived/trusted_rag_candidate_chunks.jsonl`: 식약처/FDA/AAD/ASPS RAG 후보 문서 chunk
- `derived/skin_care_ingredient_rag.jsonl`: 스킨케어 성분/효능 Training 문서 8,000개
- `derived/problem_skin_makeup_rag.jsonl`: 문제성 피부/메이크업 Training 문서 8,031개
- `derived/source_medical_qa_rag.jsonl`: 피부과/외과 전문 QA Training 문서 3,630개
- `derived/skin_care_ingredient_eval.jsonl`: 스킨케어 성분/효능 Validation holdout 1,000개
- `derived/problem_skin_makeup_eval.jsonl`: 문제성 피부/메이크업 Validation holdout 1,000개
- `derived/source_medical_qa_eval.jsonl`: 피부과/외과 전문 QA Validation holdout 436개
- `derived/dataset_manifest.json`: 변환된 데이터셋과 원본 zip 경로
- `derived/retriever_index_manifest.json`: 기본 색인/확장 색인/평가 holdout 분리 기준
