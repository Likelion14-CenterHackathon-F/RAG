# RAG Dataset README

이 문서는 성형/피부미용 사후관리 챗봇 RAG에 사용할 현재 데이터셋의 구성, 용도, 저장 형식, 활용 방식을 설명합니다.

## 현재 상태

현재 데이터셋은 **MVP 리트리버 개발을 시작할 수 있는 전처리 완료 상태**입니다. 다만 실제 서비스 투입 전에는 검색 품질 평가, 의료진 검수, 병원 내부 사후관리 지침 반영이 필요합니다.

## 서비스 범위

이 코퍼스는 다음 목적에 맞춰 정리되어 있습니다.

- 피부과/피부미용 시술 후 정상 회복 안내
- 코성형 사후관리와 붓기/비대칭 불안 대응
- 필러, 보툴리눔 톡신, 피부 레이저, 흉터/여드름 흉터 치료 후 관리
- 응급 또는 즉시 진료가 필요한 위험 신호 감지
- 응급이 아닌 경우의 현재 대처, 사후관리, 병원/화상상담 연결 기준 제시

현재 범위 밖으로 보는 자료는 기본 환자 답변 RAG에 넣지 않습니다.

- 심근경색, 뇌졸중, 열사병, 목 이물질 같은 일반 의학 상세 질환 자료
- CPR, 일반 응급처치 전문 내용
- API 문서 자체

이런 자료는 필요할 때 근거 확인용으로 보관하되, 환자 답변 생성용 벡터DB에서는 제외합니다.

## 데이터 계층

### 1. Safety Rules

RAG보다 먼저 실행되는 hard-stop 안전 룰입니다.

| 파일 | 형식 | 용도 | 답변 결과물 |
|---|---|---|---|
| `rules/emergency_rules.json` | JSON | 응급/즉시 진료 키워드 감지 | LLM 자유생성 차단, 병원/응급실 안내, 의료요약리포트 CTA |
| `rules/triage_policy.json` | JSON | hard-stop, RAG 답변, 화상상담, 추가질문 라우팅 정책 | 어떤 응답 경로를 탈지 결정 |
| `test_cases/integration_scenarios.json` | JSON | 대표 환자 입력으로 라우팅 검증 | 안전 룰/화상상담/RAG 경로 테스트 |

주의: `emergency_rules.json`은 벡터DB에 넣는 데이터가 아니라 애플리케이션 로직에서 먼저 실행해야 하는 규칙입니다.

### 2. Default Patient Answer Index

환자에게 직접 보여줄 답변 생성에 우선 사용하는 기본 RAG 색인입니다. 현재 총 **90개 문서/chunk**입니다.

| 파일 | 개수 | 형식 | 신뢰도 | 주 사용 답변 |
|---|---:|---|---|---|
| `rag/mvp_care_knowledge.jsonl` | 17 | JSONL | curated | 피부과 시술/코성형 사후관리, 증상별 기본 답변, 화상상담 유도 |
| `derived/official_rag_candidate_chunks.jsonl` | 15 | JSONL | official | 질병관리청 상처/흉터/두드러기 등 국내 공식 근거 기반 보강 |
| `derived/trusted_rag_candidate_chunks.jsonl` | 58 | JSONL | official/professional | 식약처/FDA/AAD/ASPS 기반 필러, 레이저, 보툴리눔 톡신, 코성형, 흉터 치료 사후관리 |

활용 원칙:

1. `emergency_rules.json`이 먼저 실행됩니다.
2. hard-stop이 없을 때만 이 기본 색인을 검색합니다.
3. 답변 생성 시 curated 문서와 공식/전문 출처를 우선합니다.
4. `embedding_policy=allow_with_safety_filters` 문서는 정상 관리 답변에 사용할 수 있지만, 위험 신호가 보이면 즉시 safety rule이 우선합니다.

### 3. Expanded Reference Index

답변 보조에는 쓸 수 있지만, 공식/curated 문서를 이기면 안 되는 참고 데이터입니다. 현재 총 **19,661개 문서**입니다.

| 파일 | 개수 | 형식 | 용도 | 제한 |
|---|---:|---|---|---|
| `derived/skin_care_ingredient_rag.jsonl` | 8,000 | JSONL | 피부 고민별 성분/효능 참고 | 진단/응급판단 근거로 사용 금지 |
| `derived/problem_skin_makeup_rag.jsonl` | 8,031 | JSONL | 문제성 피부 메이크업, 피해야 할 성분, 피부 상태 보조 설명 | 의료 처치 지시 근거로 사용 금지 |
| `derived/source_medical_qa_rag.jsonl` | 3,630 | JSONL | 피부과/외과 전문 QA 참고 | post-op 지침보다 우선 금지 |

이 계층은 “많은 정보”를 담기 위한 확장 코퍼스입니다. 다만 출처의 성격상 환자 답변에서 단독 근거로 쓰기보다는, 기본 환자 답변 색인이 부족할 때 보조 신호로 사용합니다.

### 4. Evaluation Holdout

검색 품질 평가에 쓰기 위해 Validation 데이터를 분리해 둔 파일입니다. 현재 총 **2,436개 문서**입니다.

| 파일 | 개수 | 형식 | 용도 |
|---|---:|---|---|
| `derived/skin_care_ingredient_eval.jsonl` | 1,000 | JSONL | 스킨케어 성분 검색 품질 평가 |
| `derived/problem_skin_makeup_eval.jsonl` | 1,000 | JSONL | 문제성 피부/메이크업 검색 품질 평가 |
| `derived/source_medical_qa_eval.jsonl` | 436 | JSONL | 피부과/외과 QA 검색 품질 평가 |

주의: 평가용 holdout은 기본 벡터DB 적재 대상이 아닙니다.

## 원본 출처 폴더

| 폴더 | 내용 | 용도 |
|---|---|---|
| `sources/raw_official/` | 국내 공식 HTML 원본, 추출 텍스트, manifest | provenance 보존 |
| `sources/official_by_use/` | 국내 공식 자료를 `rag_candidate`, `safety_only`, `out_of_scope`, `api_reference`로 분류 | 국내 공식 자료 사용 범위 관리 |
| `sources/raw_trusted/` | 식약처/FDA/AAD/ASPS HTML/PDF 원본, 추출 텍스트, manifest | provenance 보존 |
| `sources/trusted_by_use/` | 추가 신뢰 출처를 `rag_candidate`, `safety_only`로 분류 | 환자 답변/안전 룰 근거 분리 |

원본은 삭제하지 않고 보관합니다. 나중에 출처 갱신, 법적 근거 확인, 의료진 리뷰가 필요할 때 원문으로 돌아갈 수 있어야 하기 때문입니다.

## JSONL 저장 형식

RAG용 문서는 대부분 JSONL입니다. 한 줄이 하나의 검색 문서입니다.

대표 필드:

| 필드 | 설명 |
|---|---|
| `doc_id` | 검색 문서 고유 ID |
| `dataset_type` | 문서 출처와 사용 범위 |
| `department` | `dermatology`, `rhinoplasty`, `common` 등 |
| `procedure` | 시술명 또는 시술 범주 |
| `phase` | 경과일 범위. 예: `D+0-D+2` |
| `intent` | 세안, 붉음, 건조, 비대칭, 불안 등 검색 의도 |
| `risk_level` | `normal`, `watch`, `urgent`, `emergency` |
| `retrieval_use` | 기본 답변, 참고용, 안전용 등 사용 목적 |
| `title` | 관리자/LLM이 읽기 쉬운 제목 |
| `content` | 검색과 답변 생성에 사용할 본문 |
| `answer_template` | curated 문서에 있는 권장 답변 구조 |
| `keywords` | 검색 보조 키워드 |
| `source_refs` | 출처 URL 또는 원본 경로 |
| `metadata` | 원본 zip, split, chunk index, 정책 등 부가정보 |

임베딩 권장값:

- curated 문서: `title + content + answer_template`
- 공식/신뢰 chunk: `title + content`
- 필터 메타데이터: `retrieval_use`, `department`, `procedure`, `phase`, `risk_level`, `dataset_type`

## 추천 검색 흐름

1. 사용자 입력을 정규화합니다.
2. `rules/emergency_rules.json`을 먼저 매칭합니다.
3. 매칭되면 RAG 검색 없이 hard-coded 안전 메시지를 반환합니다.
4. 매칭되지 않으면 시술명, 경과일, 증상, 부위, 사진 유무, 불안도를 추출합니다.
5. 기본 환자 답변 색인 3개를 먼저 검색합니다.
6. 부족하면 확장 참고 색인을 보조 검색합니다.
7. 답변에는 진단 확정 표현을 금지하고, 병원 지침이 있으면 병원 지침 우선을 안내합니다.
8. 사진 신뢰도가 낮거나 불안도가 높으면 화상상담 CTA를 노출합니다.

## 재생성 명령

원본 zip은 풀지 않아도 됩니다. 변환 스크립트가 zip 내부 JSON/JSONL을 직접 읽습니다.

```bash
python3 rag_rulebook/tools/extract_official_source_text.py
python3 rag_rulebook/tools/partition_official_sources.py
python3 rag_rulebook/tools/extract_trusted_source_text.py
python3 rag_rulebook/tools/partition_trusted_sources.py
python3 rag_rulebook/tools/build_rag_datasets.py
python3 rag_rulebook/tools/validate_triage.py
```

현재 검증 결과:

- JSONL 전체 파싱 성공
- `validate_triage.py`: 8개 시나리오 통과

## 현재 남은 보강 후보

- 실제 병원 내부 사후관리 안내문
- 필러/보툴리눔 톡신 제품별 환자 안내문
- 한국어 환자 표현 동의어 데이터
- 실제 상담 로그 기반 검색 평가셋
- 의료진/도메인 전문가 검수 결과

## 사용하면 안 되는 방식

- `safety_only/` 자료를 환자 답변용 벡터DB에 그대로 넣기
- 응급 키워드가 있는데 RAG 답변으로 “관리법”을 생성하기
- 확장 참고 코퍼스만 보고 진단, 약물, 처치 지시를 생성하기
- Validation holdout을 학습/색인 데이터로 섞기
- 출처 URL과 원본 파일 경로를 제거한 채 chunk만 보관하기
