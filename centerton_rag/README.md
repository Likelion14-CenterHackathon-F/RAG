# centerton_rag

시술 후 사후관리 RAG 서비스입니다. 지식베이스인 `rag_rulebook/`과 같은 저장소에 있습니다. 분리하지 않는 이유는 ADR-0022에 있습니다.

## 흐름

```
질문
  -> 응급 룰 검사 (rag_rulebook.tools.emergency_matcher)
     -> 매칭: 고정 안내 반환. 임베딩·검색·생성 없음
     -> 미매칭: 항상 검색
  -> pgvector 기본 색인 90개 검색, RAG_MIN_SIMILARITY 컷오프
     -> 0건: insufficient_evidence. OpenAI 호출 없음
     -> 있으면: 근거 기반 생성 + 근거에서 도출한 상담 CTA
```

검색 앞단에 LLM 분류기가 없습니다. 검색은 판단이 아니라 근거 수집이므로 위험해 보이는 질문이라고 건너뛰지 않습니다. 자세한 이유는 ADR-0023에 있습니다.

## 모듈

| 파일 | 역할 | 의존성 |
| --- | --- | --- |
| `main.py` | FastAPI 라우트와 배선 | fastapi |
| `models.py` | 요청·응답 스키마 | pydantic |
| `config.py` | 환경변수와 DB 접속 정보 | 표준 라이브러리 |
| `emergency.py` | 응급 하드스톱 판정 | 표준 라이브러리 |
| `retrieval.py` | pgvector 검색과 컷오프 | 표준 라이브러리 (psycopg는 지연 import) |
| `consultation.py` | 상담 CTA와 위험도 도출 | 표준 라이브러리 |
| `answer.py` | 생성 게이트와 가드레일 | 표준 라이브러리 (openai는 지연 import) |

계약에 관여하는 로직은 표준 라이브러리만 사용합니다. 웹 프레임워크나 DB, 모델 없이 검증할 수 있어야 하기 때문입니다.

## 응급 룰을 여기서 구현하지 않습니다

`emergency.py`에는 매칭 로직이 없습니다. 정규화, 키워드 매칭, 패턴 매칭, 부정 억제는 모두 `rag_rulebook.tools.emergency_matcher`에 있습니다.

이전에는 서비스가 자체 `EmergencyRuleEngine`을 갖고 있었고, 룰북 JSON만 볼륨으로 공유했습니다. 그 결과 구현이 계약과 갈라져 회귀 66건 중 18건이 실패했습니다. 정상 문의가 응급실 안내로 종결되고 RAG 검색이 실행되지 않았습니다.

## 실행

```bash
pip install -e .
cp .env.example .env    # 값 채우기
uvicorn centerton_rag.main:app --host 0.0.0.0 --port 8001
```

## 테스트

서비스 의존성 없이 실행됩니다.

```bash
python -m unittest discover -s tests -t .
# 또는
pytest
```

| 파일 | 검증 대상 |
| --- | --- |
| `test_emergency_contract.py` | 회귀 66건을 서비스가 호출하는 코드에 대해 실행 |
| `test_retrieval_contract.py` | 유사도 경계값, top-k, 데이터 계층 필터 |
| `test_generation_gate.py` | 근거 0건일 때 생성 함수가 호출되지 않음 |
| `test_consultation.py` | CTA 도출과 큐레이션 메타데이터 정합성 |

## 배포

FastAPI 포트는 외부에 공개하지 않습니다. Spring이 도커 네트워크로 `http://centerton-rag:8001`을 호출합니다.

Spring은 응급 룰을 구현하지 않습니다. 이 서비스에 도달할 수 없으면 보수 안내로 종결합니다.

## 남은 작업

- `retrieval_use` 백필: 큐레이션 17개 문서에 값이 없어 현재는 NULL 허용으로 계층 경계를 유지하고 있습니다. 백필 후 재적재하면 `RAG_ALLOW_NULL_RETRIEVAL_USE=false`로 바꿀 수 있습니다.
- 이미지 신뢰도 기반 상담 유도: `COMMON-LOW-CONFIDENCE-PHOTO` 문서가 이 역할을 하도록 작성돼 있으나 요청 스키마에 신뢰도 점수가 없습니다.
- 다국어 입력 처리: ADR-0020의 번역 정규화가 미구현입니다.
- 응급 룰 검사 범위: 현재 턴의 질문만 검사합니다. 이전 대화는 보지 않습니다.
