#!/usr/bin/env python3
"""Ingest the RAG rulebook into PostgreSQL with KURE embeddings.

The script is intentionally idempotent: rerunning it upserts by doc_id and
records each run in rag_ingest_runs. Database credentials are read from the
repository `.env` (or the process environment) without printing secrets.

This is the only way to rebuild the deployed index, so it lives beside the data
it ingests. It used to sit in the Spring repository and read that project's
application-secret.properties, which put the Java service in charge of a Python
data pipeline it never ran.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAG_ROOT = REPO_ROOT / "rag_rulebook"
# The loader skips comments and blank lines and splits on the first '=', which is
# exactly .env format. Credentials therefore come from the same file the service
# uses, instead of reaching into the Spring repository as this script used to.
# Anything absent from the file falls back to the process environment.
DEFAULT_SECRET_FILE = REPO_ROOT / ".env"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build/rag-ingest"
DEFAULT_KURE_MODEL = "nlpai-lab/KURE-v1"
DEFAULT_EMBEDDING_PROVIDER = "kure"
EXPECTED_EMBEDDING_DIMENSIONS = 1024


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    database: str
    username: str
    password: str
    sslmode: str | None


@dataclass
class RagRecord:
    doc_id: str
    index_version: str
    dataset_type: str | None
    retrieval_use: str | None
    department: str | None
    procedure: str | None
    phase: str | None
    intent: str | None
    risk_level: str | None
    title: str
    content: str
    answer_template: str | None
    source: str | None
    source_refs: list[Any]
    keywords: list[Any]
    metadata: dict[str, Any]
    embedding_input: str
    content_hash: str
    embedding: list[float] | None = None


def is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


def load_properties(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    properties: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        properties[key.strip()] = value.strip()
    return properties


def config_value(properties: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = properties.get(key)
        if value and not (value.startswith("${") and value.endswith("}")):
            return value

    for key in keys:
        env_key = key.replace(".", "_").replace("-", "_").upper()
        value = os.environ.get(env_key)
        if value:
            return value

    return None


def load_manifest(rag_root: Path) -> dict[str, Any]:
    manifest_path = rag_root / "derived/retriever_index_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"Missing manifest: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def make_embedding_input(raw: dict[str, Any], title: str, content: str) -> str:
    parts = [title, content, raw.get("answer_template")]
    return "\n\n".join(str(part).strip() for part in parts if part and str(part).strip())


def normalize_record(
    raw: dict[str, Any],
    manifest_entry: dict[str, Any],
    relative_path: str,
    line_number: int,
    index_version: str,
    embedding_provider: str,
    embedding_model: str,
) -> RagRecord:
    title = str(raw.get("title") or raw.get("metadata", {}).get("title") or raw["doc_id"]).strip()
    content = str(raw.get("content") or "").strip()
    if not content:
        raise RuntimeError(f"Blank content in {relative_path}:{line_number}")

    embedding_input = make_embedding_input(raw, title, content)
    content_hash = hashlib.sha256(embedding_input.encode("utf-8")).hexdigest()
    metadata = raw["metadata"].copy() if isinstance(raw.get("metadata"), dict) else {}
    metadata.update(
        {
            "trust_level": manifest_entry["trust_level"],
            "manifest_use": manifest_entry["use"],
            "manifest_path": relative_path,
            "source_line": line_number,
            "embedding_input_sha256": content_hash,
            "embedding_provider": embedding_provider,
            "embedding_model": embedding_model,
        }
    )

    return RagRecord(
        doc_id=str(raw.get("doc_id") or f"RAG-{content_hash[:16]}"),
        index_version=index_version,
        dataset_type=raw.get("dataset_type"),
        retrieval_use=raw.get("retrieval_use") or manifest_entry["trust_level"],
        department=raw.get("department"),
        procedure=raw.get("procedure"),
        phase=raw.get("phase"),
        intent=raw.get("intent"),
        risk_level=raw.get("risk_level"),
        title=title,
        content=content,
        answer_template=raw.get("answer_template"),
        source=raw.get("source"),
        source_refs=raw["source_refs"] if isinstance(raw.get("source_refs"), list) else [],
        keywords=raw["keywords"] if isinstance(raw.get("keywords"), list) else [],
        metadata=metadata,
        embedding_input=embedding_input,
        content_hash=content_hash,
    )


def load_records(
    rag_root: Path,
    index_version_override: str | None,
    embedding_provider: str,
    embedding_model: str,
) -> tuple[str, list[RagRecord], dict[str, int]]:
    manifest = load_manifest(rag_root)
    index_version = index_version_override or manifest["version"]
    records: list[RagRecord] = []
    counts_by_path: dict[str, int] = {}

    for entry in manifest["default_patient_answer_index"]:
        relative_path = entry["path"]
        path = rag_root / relative_path
        if not path.exists():
            raise RuntimeError(f"Missing dataset file: {path}")

        file_count = 0
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            raw = json.loads(line)
            records.append(
                normalize_record(
                    raw=raw,
                    manifest_entry=entry,
                    relative_path=relative_path,
                    line_number=line_number,
                    index_version=index_version,
                    embedding_provider=embedding_provider,
                    embedding_model=embedding_model,
                )
            )
            file_count += 1

        expected_count = entry.get("count")
        if expected_count and file_count != expected_count:
            raise RuntimeError(f"Count mismatch for {relative_path}: expected {expected_count}, found {file_count}")
        counts_by_path[relative_path] = file_count

    seen: set[str] = set()
    for record in records:
        if record.doc_id in seen:
            raise RuntimeError(f"Duplicate doc_id detected: {record.doc_id}")
        seen.add(record.doc_id)

    return index_version, records, counts_by_path


def parse_database_config(properties: dict[str, str]) -> DbConfig:
    raw_url = config_value(properties, "DATABASE_URL", "spring.datasource.url")
    username = config_value(properties, "DATABASE_USERNAME", "spring.datasource.username")
    password = config_value(properties, "DATABASE_PASSWORD", "spring.datasource.password")
    if is_blank(raw_url):
        raise RuntimeError("DATABASE_URL is missing")

    normalized_url = raw_url.removeprefix("jdbc:")
    parsed = urlparse(normalized_url)
    query = parse_qs(parsed.query)
    return DbConfig(
        host=parsed.hostname or "",
        port=parsed.port or 5432,
        database=parsed.path.removeprefix("/"),
        username=username or unquote(parsed.username or ""),
        password=password or unquote(parsed.password or ""),
        sslmode=query.get("sslmode", [None])[0],
    )


def psql_binary() -> str:
    configured = os.environ.get("PSQL_BIN")
    if configured:
        return configured

    for candidate in ["/opt/homebrew/bin/psql", "/usr/local/bin/psql", "psql"]:
        if candidate == "psql" or Path(candidate).exists():
            return candidate

    raise RuntimeError("psql not found")


def psql_env(config: DbConfig) -> dict[str, str]:
    env = os.environ.copy()
    if config.password:
        env["PGPASSWORD"] = config.password
    if config.sslmode:
        env["PGSSLMODE"] = config.sslmode
    return env


def psql_args(config: DbConfig) -> list[str]:
    return [
        psql_binary(),
        "-h",
        config.host,
        "-p",
        str(config.port),
        "-d",
        config.database,
        "-U",
        config.username,
        "-v",
        "ON_ERROR_STOP=1",
        "-X",
    ]


def run_psql_file(config: DbConfig, sql_path: Path) -> str:
    completed = subprocess.run(
        [*psql_args(config), "-f", str(sql_path)],
        env=psql_env(config),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"psql failed: {message}")
    return completed.stdout


def run_psql_query(config: DbConfig, sql: str) -> str:
    completed = subprocess.run(
        [*psql_args(config), "-A", "-F", "\t", "-c", sql],
        env=psql_env(config),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"psql query failed: {message}")
    return completed.stdout


def detect_existing_storage(config: DbConfig) -> str | None:
    output = run_psql_query(
        config,
        """
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'rag_documents'
  AND column_name IN ('embedding', 'embedding_values')
ORDER BY column_name;
""",
    )
    columns = {line.strip() for line in output.splitlines() if line.strip() and line.strip() != "column_name"}
    if "embedding" in columns:
        return "pgvector"
    if "embedding_values" in columns:
        return "jsonb"
    return None


def resolve_storage(config: DbConfig, requested_storage: str) -> str:
    existing_storage = detect_existing_storage(config)

    if existing_storage == "pgvector":
        if requested_storage == "jsonb":
            raise RuntimeError("rag_documents already uses pgvector storage, but --storage jsonb was requested")
        return "pgvector"

    if requested_storage == "jsonb":
        return "jsonb"

    try:
        run_psql_query(config, "CREATE EXTENSION IF NOT EXISTS vector;")
        return "pgvector"
    except RuntimeError as error:
        if requested_storage == "pgvector":
            raise
        print(f"pgvector unavailable; falling back to jsonb storage ({error})")
        if existing_storage == "jsonb":
            return "jsonb"
        return "jsonb"


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def jsonb_literal(value: Any) -> str:
    return f"{sql_literal(json.dumps(value, ensure_ascii=False, separators=(',', ':')))}::jsonb"


def vector_literal(vector: list[float]) -> str:
    return f"{sql_literal('[' + ','.join(repr(float(item)) for item in vector) + ']')}::vector"


def embed_records_with_kure(records: list[RagRecord], model_name: str, batch_size: int) -> None:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed. "
            "Create an environment such as: uv venv /private/tmp/rag-embed-eval-venv "
            "--python /opt/homebrew/bin/python3.11 && "
            "uv pip install --python /private/tmp/rag-embed-eval-venv/bin/python sentence-transformers"
        ) from exc

    model = SentenceTransformer(model_name)
    embeddings = model.encode(
        [record.embedding_input for record in records],
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    for record, embedding in zip(records, embeddings, strict=True):
        vector = [float(value) for value in embedding]
        if len(vector) != EXPECTED_EMBEDDING_DIMENSIONS:
            raise RuntimeError(
                f"Embedding dimensions mismatch for {record.doc_id}: "
                f"expected {EXPECTED_EMBEDDING_DIMENSIONS}, got {len(vector)}"
            )
        record.embedding = vector


def schema_sql(storage: str) -> str:
    extension_sql = "CREATE EXTENSION IF NOT EXISTS vector;" if storage == "pgvector" else ""
    pre_schema_migration_sql = (
        """
ALTER TABLE IF EXISTS rag_documents
  ADD COLUMN IF NOT EXISTS embedding vector(1024);

DO $$
BEGIN
  IF to_regclass('public.rag_documents') IS NOT NULL THEN
    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'rag_documents'
        AND column_name = 'embedding_values'
    ) THEN
      EXECUTE 'ALTER TABLE public.rag_documents ALTER COLUMN embedding_values DROP NOT NULL';
      EXECUTE $sql$
        UPDATE public.rag_documents d
        SET embedding = (
          SELECT ('[' || string_agg(item.value, ',' ORDER BY item.ordinality) || ']')::vector
          FROM jsonb_array_elements_text(d.embedding_values) WITH ORDINALITY AS item(value, ordinality)
        )
        WHERE d.embedding IS NULL
          AND d.embedding_values IS NOT NULL
          AND jsonb_typeof(d.embedding_values) = 'array'
          AND jsonb_array_length(d.embedding_values) = 1024
      $sql$;
    END IF;

    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'rag_documents'
        AND column_name = 'embedding_storage'
    ) THEN
      UPDATE public.rag_documents
      SET embedding_storage = 'pgvector'
      WHERE embedding IS NOT NULL;
    END IF;
  END IF;
END $$;
"""
        if storage == "pgvector"
        else ""
    )
    embedding_column_sql = (
        "  embedding vector(1024) NOT NULL,"
        if storage == "pgvector"
        else "  embedding_values jsonb NOT NULL,"
    )
    embedding_index_sql = (
        """
CREATE INDEX IF NOT EXISTS idx_rag_documents_embedding_hnsw
  ON rag_documents USING hnsw (embedding vector_cosine_ops);
"""
        if storage == "pgvector"
        else ""
    )

    return f"""
{extension_sql}
{pre_schema_migration_sql}

CREATE TABLE IF NOT EXISTS rag_documents (
  doc_id text PRIMARY KEY,
  index_version text NOT NULL,
  dataset_type text,
  retrieval_use text,
  department text,
  "procedure" text,
  phase text,
  intent text,
  risk_level text,
  title text NOT NULL,
  content text NOT NULL,
  answer_template text,
  source text,
  source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  keywords jsonb NOT NULL DEFAULT '[]'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
  embedding_provider text NOT NULL,
  embedding_model text NOT NULL,
  embedding_dimensions integer NOT NULL,
  embedding_storage text NOT NULL,
{embedding_column_sql}
  content_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_ingest_runs (
  id bigserial PRIMARY KEY,
  index_version text NOT NULL,
  embedding_provider text NOT NULL,
  embedding_model text NOT NULL,
  embedding_dimensions integer NOT NULL,
  embedding_storage text NOT NULL,
  document_count integer NOT NULL,
  corpus_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_documents_index_version
  ON rag_documents (index_version);
CREATE INDEX IF NOT EXISTS idx_rag_documents_retrieval_use
  ON rag_documents (retrieval_use);
CREATE INDEX IF NOT EXISTS idx_rag_documents_dataset_type
  ON rag_documents (dataset_type);
CREATE INDEX IF NOT EXISTS idx_rag_documents_department
  ON rag_documents (department);
CREATE INDEX IF NOT EXISTS idx_rag_documents_procedure
  ON rag_documents ("procedure");
CREATE INDEX IF NOT EXISTS idx_rag_documents_risk_level
  ON rag_documents (risk_level);
{embedding_index_sql}
"""


def upsert_sql(
    records: list[RagRecord],
    embedding_provider: str,
    embedding_model: str,
    embedding_storage: str,
) -> str:
    embedding_column = "embedding" if embedding_storage == "pgvector" else "embedding_values"
    columns = [
        "doc_id",
        "index_version",
        "dataset_type",
        "retrieval_use",
        "department",
        '"procedure"',
        "phase",
        "intent",
        "risk_level",
        "title",
        "content",
        "answer_template",
        "source",
        "source_refs",
        "keywords",
        "metadata",
        "embedding_provider",
        "embedding_model",
        "embedding_dimensions",
        "embedding_storage",
        embedding_column,
        "content_hash",
    ]
    updates = [f"{column} = EXCLUDED.{column}" for column in columns if column != "doc_id"]
    updates.append("updated_at = now()")

    statements: list[str] = []
    for record in records:
        if record.embedding is None:
            raise RuntimeError(f"Missing embedding for {record.doc_id}")
        values = [
            sql_literal(record.doc_id),
            sql_literal(record.index_version),
            sql_literal(record.dataset_type),
            sql_literal(record.retrieval_use),
            sql_literal(record.department),
            sql_literal(record.procedure),
            sql_literal(record.phase),
            sql_literal(record.intent),
            sql_literal(record.risk_level),
            sql_literal(record.title),
            sql_literal(record.content),
            sql_literal(record.answer_template),
            sql_literal(record.source),
            jsonb_literal(record.source_refs),
            jsonb_literal(record.keywords),
            jsonb_literal(record.metadata),
            sql_literal(embedding_provider),
            sql_literal(embedding_model),
            str(EXPECTED_EMBEDDING_DIMENSIONS),
            sql_literal(embedding_storage),
            vector_literal(record.embedding) if embedding_storage == "pgvector" else jsonb_literal(record.embedding),
            sql_literal(record.content_hash),
        ]
        statements.append(
            f"""
INSERT INTO rag_documents ({", ".join(columns)})
VALUES ({", ".join(values)})
ON CONFLICT (doc_id) DO UPDATE SET
  {", ".join(updates)};
"""
        )

    return "\n".join(statements)


def corpus_hash(records: list[RagRecord]) -> str:
    joined = "\n".join(sorted(f"{record.doc_id}:{record.content_hash}" for record in records))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def ingest_run_sql(
    records: list[RagRecord],
    index_version: str,
    embedding_provider: str,
    embedding_model: str,
    embedding_storage: str,
) -> str:
    return f"""
INSERT INTO rag_ingest_runs (
  index_version,
  embedding_provider,
  embedding_model,
  embedding_dimensions,
  embedding_storage,
  document_count,
  corpus_hash
)
VALUES (
  {sql_literal(index_version)},
  {sql_literal(embedding_provider)},
  {sql_literal(embedding_model)},
  {EXPECTED_EMBEDDING_DIMENSIONS},
  {sql_literal(embedding_storage)},
  {len(records)},
  {sql_literal(corpus_hash(records))}
);
"""


def build_sql(
    records: list[RagRecord],
    index_version: str,
    embedding_provider: str,
    embedding_model: str,
    embedding_storage: str,
) -> str:
    return f"""
BEGIN;
{schema_sql(embedding_storage)}
{upsert_sql(records, embedding_provider, embedding_model, embedding_storage)}
{ingest_run_sql(records, index_version, embedding_provider, embedding_model, embedding_storage)}
COMMIT;
"""


def write_summary(
    output_dir: Path,
    index_version: str,
    records: list[RagRecord],
    counts_by_path: dict[str, int],
    embedding_provider: str,
    embedding_model: str,
    embedding_storage: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "index_version": index_version,
        "document_count": len(records),
        "counts_by_path": counts_by_path,
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "embedding_dimensions": EXPECTED_EMBEDDING_DIMENSIONS,
        "embedding_storage": embedding_storage,
        "corpus_hash": corpus_hash(records),
        "sample_doc_ids": [record.doc_id for record in records[:5]],
    }
    path = output_dir / "rag_ingest_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def print_plan(
    index_version: str,
    records: list[RagRecord],
    counts_by_path: dict[str, int],
    args: argparse.Namespace,
) -> None:
    print("RAG ingest plan")
    print(f"Index version: {index_version}")
    print(f"RAG root: {args.rag_root}")
    print(f"Embedding provider: {DEFAULT_EMBEDDING_PROVIDER}")
    print(f"Embedding model: {args.embedding_model}")
    print(f"Embedding dimensions: {EXPECTED_EMBEDDING_DIMENSIONS}")
    print(f"Storage mode: {args.storage}")
    print(f"Target documents: {len(records)}")
    for path, count in counts_by_path.items():
        print(f"- {path}: {count}")
    print("Sample doc_ids:", ", ".join(record.doc_id for record in records[:5]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write to the configured database.")
    parser.add_argument("--rag-root", type=Path, default=DEFAULT_RAG_ROOT)
    parser.add_argument("--secret-file", type=Path, default=DEFAULT_SECRET_FILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--index-version")
    parser.add_argument("--embedding-model", default=os.environ.get("KURE_MODEL", DEFAULT_KURE_MODEL))
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("KURE_BATCH_SIZE", "8")))
    parser.add_argument("--storage", choices=["auto", "pgvector", "jsonb"], default="auto")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    index_version, records, counts_by_path = load_records(
        rag_root=args.rag_root,
        index_version_override=args.index_version,
        embedding_provider=DEFAULT_EMBEDDING_PROVIDER,
        embedding_model=args.embedding_model,
    )
    print_plan(index_version, records, counts_by_path, args)

    summary_path = write_summary(
        output_dir=args.output_dir,
        index_version=index_version,
        records=records,
        counts_by_path=counts_by_path,
        embedding_provider=DEFAULT_EMBEDDING_PROVIDER,
        embedding_model=args.embedding_model,
        embedding_storage=args.storage,
    )
    print(f"Summary: {summary_path}")

    if not args.apply:
        print("No database writes were made. Pass --apply to ingest.")
        return

    properties = load_properties(args.secret_file)
    database = parse_database_config(properties)
    embedding_storage = resolve_storage(database, args.storage)
    for record in records:
        record.metadata["embedding_storage"] = embedding_storage
    print(f"Resolved storage: {embedding_storage}")

    summary_path = write_summary(
        output_dir=args.output_dir,
        index_version=index_version,
        records=records,
        counts_by_path=counts_by_path,
        embedding_provider=DEFAULT_EMBEDDING_PROVIDER,
        embedding_model=args.embedding_model,
        embedding_storage=embedding_storage,
    )
    print(f"Summary: {summary_path}")

    print("Embedding documents with KURE...")
    embed_records_with_kure(records, args.embedding_model, args.batch_size)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".sql", delete=False) as file:
        sql_path = Path(file.name)
        file.write(build_sql(records, index_version, DEFAULT_EMBEDDING_PROVIDER, args.embedding_model, embedding_storage))

    try:
        run_psql_file(database, sql_path)
    finally:
        sql_path.unlink(missing_ok=True)

    verification = run_psql_query(
        database,
        f"""
SELECT dataset_type, COUNT(*) AS count
FROM rag_documents
WHERE index_version = {sql_literal(index_version)}
GROUP BY dataset_type
ORDER BY dataset_type;
""",
    )
    latest_run = run_psql_query(
        database,
        """
SELECT id, index_version, embedding_provider, embedding_model, embedding_dimensions, embedding_storage, document_count
FROM rag_ingest_runs
ORDER BY id DESC
LIMIT 1;
""",
    )

    print("RAG ingest complete")
    print("Verification:")
    print(verification)
    print("Latest ingest run:")
    print(latest_run)


if __name__ == "__main__":
    main()
