# scripts

색인을 만들고 진단하는 운영 스크립트입니다. 서비스 런타임(`centerton_rag/`)이나 룰북
검증(`rag_rulebook/tools/`)과 달리, 여기 있는 것들은 사람이 직접 실행합니다.

원래 Spring 저장소(`Backend/scripts/`)에 있었습니다. ADR-0022 는 서비스 코드를 Rag-Lab 으로
모았는데 데이터 파이프라인은 남아 있었고, 그래서 Java 저장소가 자기가 실행하지도 않는 Python
적재 스크립트를 들고 있으면서 Rag-Lab 경로를 절대경로로 하드코딩해 참조하는 상태였습니다.

`rag_rulebook/tools/` 가 아니라 별도 디렉터리인 이유는, `rag_rulebook.tools` 는 패키징 대상이고
표준 라이브러리만 쓴다는 전제가 있어서입니다(`pyproject.toml` 참고). 여기 스크립트는 numpy,
psycopg, sentence-transformers, `psql` 바이너리를 씁니다. Docker 이미지에도 포함되지 않습니다.

## 자격 증명

`--secret-file` 기본값이 저장소 루트의 `.env` 입니다. 파일이 없으면 프로세스 환경변수로
넘어갑니다. 읽는 키는 `DATABASE_URL`, `DATABASE_USERNAME`, `DATABASE_PASSWORD` 이고 값은
출력하지 않습니다.

## ingest_rag_documents.py

배포 색인을 만드는 **유일한** 스크립트입니다. 이것 없이는 `rag_documents` 90건을 재현할 수 없습니다.

doc_id 기준 upsert 이고 실행 이력을 `rag_ingest_runs` 에 남기므로 여러 번 실행해도 안전합니다.

```bash
# dry-run. DB에 쓰지 않고 계획만 출력한다
python scripts/ingest_rag_documents.py

# 실제 적재
python scripts/ingest_rag_documents.py --apply
```

`--apply` 는 배포 DB 를 덮어씁니다. 실행 전에 현재 색인을 백업하고, 실행 후에는
`verification/probe_retrieval.py` 로 검색 품질을 재측정해 기존 기준과 비교하세요. 임베딩이 바뀌면
`RAG_MIN_SIMILARITY` 근거가 무효가 됩니다.

## query_rag_documents.py

임의 질문으로 실제 색인을 조회합니다. 서비스를 띄우지 않고 검색만 확인할 때 씁니다.

```bash
python scripts/query_rag_documents.py "코 수술 2주차인데 코끝이 휜 것 같아요"
python scripts/query_rag_documents.py --samples
```

## evaluate_embedding_retrieval.py

임베딩 제공자(OpenAI / KURE)별 검색 품질을 비교합니다. 임베딩 모델 교체를 검토할 때만 씁니다.
모델을 바꾸면 저장된 벡터가 전부 무효이므로 재적재가 따라옵니다.

## serve_kure_embeddings.py

KURE 임베딩을 HTTP 로 제공하는 개발용 서버입니다. 현재 서비스는 KURE 를 프로세스 안에서
직접 로드하므로 운영 경로에는 필요하지 않습니다.

```bash
python scripts/serve_kure_embeddings.py --port 8002
```
