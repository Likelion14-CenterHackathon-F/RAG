-- DB와 색인 실태 확인. VERIFICATION_REQUEST.md 의 Q1 부터 Q8 에 대응합니다.
-- 각 쿼리 결과를 그대로 VERIFICATION_RESULT.md 에 붙여 주세요.
-- 조회만 수행하며 데이터를 변경하지 않습니다.

-- ============================================================
-- Q1. 테이블 구조
-- ============================================================
SELECT column_name, data_type, is_nullable, character_maximum_length
FROM information_schema.columns
WHERE table_name = 'rag_documents'
ORDER BY ordinal_position;

-- ============================================================
-- Q2. department / procedure / phase 컬럼 존재 여부와 채워진 정도
--     없으면 오류가 납니다. 오류 메시지 자체가 답입니다.
-- ============================================================
SELECT
  count(*)                                        AS total,
  count(department)                               AS department_not_null,
  count(procedure)                                AS procedure_not_null,
  count(phase)                                    AS phase_not_null
FROM rag_documents;

-- 채워져 있다면 어떤 값들인지
SELECT department, procedure, phase, count(*) AS rows
FROM rag_documents
GROUP BY department, procedure, phase
ORDER BY rows DESC
LIMIT 40;

-- ============================================================
-- Q3. index_version 별 행 수
--     기본 90 / 확장 19,661 / 홀드아웃 2,436 이 같은 버전을 쓰는지가 핵심
-- ============================================================
SELECT index_version, count(*) AS rows
FROM rag_documents
GROUP BY index_version
ORDER BY rows DESC;

-- ============================================================
-- Q4. retrieval_use 별 행 수. NULL 도 별도로 확인
-- ============================================================
SELECT
  coalesce(retrieval_use, '<NULL>') AS retrieval_use,
  count(*)                          AS rows
FROM rag_documents
GROUP BY retrieval_use
ORDER BY rows DESC;

-- 서비스가 사용하는 필터를 그대로 적용했을 때 몇 건이 남는지.
-- 90 이 나와야 정상입니다.
SELECT count(*) AS default_index_rows
FROM rag_documents
WHERE index_version = '2026-08-15-expanded-corpus'
  AND embedding_storage = 'pgvector'
  AND embedding IS NOT NULL
  AND (retrieval_use IS NULL
       OR retrieval_use = ANY (ARRAY['official_rag_candidate', 'trusted_rag_candidate']));

-- NULL 로 들어온 문서가 실제로 큐레이션 17개인지 확인
SELECT doc_id, dataset_type, risk_level
FROM rag_documents
WHERE retrieval_use IS NULL
ORDER BY doc_id;

-- ============================================================
-- Q5. 평가 홀드아웃 적재 여부
--     확장 색인과 retrieval_use 값이 같아 구분할 컬럼이 필요합니다
-- ============================================================
SELECT dataset_type, retrieval_use, count(*) AS rows
FROM rag_documents
GROUP BY dataset_type, retrieval_use
ORDER BY rows DESC;

-- 홀드아웃을 구분할 수 있는 컬럼이 있는지 (없으면 오류)
-- SELECT split, count(*) FROM rag_documents GROUP BY split;

-- ============================================================
-- Q6. 임베딩 차원과 정규화 여부
-- ============================================================
SELECT vector_dims(embedding) AS dimension, count(*) AS rows
FROM rag_documents
WHERE embedding IS NOT NULL
GROUP BY vector_dims(embedding);

-- L2 norm. 정규화되어 있으면 1.0 에 가깝습니다.
-- similarity = 1 - distance 계산이 이 전제에 의존합니다.
SELECT doc_id, round(sqrt(embedding <#> embedding * -1)::numeric, 6) AS approx_norm
FROM rag_documents
WHERE embedding IS NOT NULL
LIMIT 5;

-- 위 식이 실패하면 이쪽을 사용하세요.
-- SELECT doc_id, l2_norm(embedding) AS norm
-- FROM rag_documents WHERE embedding IS NOT NULL LIMIT 5;

-- ============================================================
-- Q7. embedding_storage 값 분포
-- ============================================================
SELECT coalesce(embedding_storage, '<NULL>') AS embedding_storage, count(*) AS rows
FROM rag_documents
GROUP BY embedding_storage;

-- ============================================================
-- Q8. 인덱스 종류와 연산자 클래스
-- ============================================================
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'rag_documents';

-- 실제로 인덱스를 타는지. 벡터 리터럴은 실제 값으로 바꿔 주세요.
-- EXPLAIN ANALYZE
-- SELECT doc_id, embedding <=> '[...]'::vector AS distance
-- FROM rag_documents
-- WHERE index_version = '2026-08-15-expanded-corpus'
-- ORDER BY embedding <=> '[...]'::vector
-- LIMIT 5;

-- ============================================================
-- 참고. 보일러플레이트가 적재된 content 에 남아 있는지
--       Q11 판단 근거가 됩니다
-- ============================================================
SELECT count(*) AS rows_with_boilerplate
FROM rag_documents
WHERE content LIKE '%등록일자%'
   OR content LIKE '%법적책임은 없음%'
   OR content LIKE '%HTML PAGE TEXT%'
   OR content LIKE '%PDF page%';

-- 길이 분포. 큐레이션과 official/trusted 가 8배 차이 납니다.
SELECT
  coalesce(retrieval_use, '<NULL>') AS retrieval_use,
  count(*)                          AS rows,
  min(length(content))              AS min_len,
  round(avg(length(content)))       AS avg_len,
  max(length(content))              AS max_len
FROM rag_documents
GROUP BY retrieval_use
ORDER BY rows DESC;
