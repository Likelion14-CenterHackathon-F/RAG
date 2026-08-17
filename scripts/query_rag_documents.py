#!/usr/bin/env python3
"""Query the pgvector-backed RAG documents table with KURE embeddings."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAG_ROOT = REPO_ROOT / "rag_rulebook"
DEFAULT_SECRET_FILE = REPO_ROOT / ".env"
DEFAULT_KURE_MODEL = "nlpai-lab/KURE-v1"

SAMPLE_QUERIES = [
    "피코 프락셀 오늘 받았는데 세안이랑 화장은 언제부터 해도 돼요?",
    "레이저 후 물집이 생기고 진물이 나요. 병원에 가야 할까요?",
    "코성형하고 부목 붙어 있는데 물 닿아도 괜찮아요?",
    "필러 맞고 붓기랑 멍이 있는데 회복 기간 동안 뭘 조심해야 해요?",
    "보톡스 맞고 나서 얼굴 문지르거나 마사지해도 괜찮나요?",
]


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


def load_index_version(rag_root: Path) -> str:
    manifest = json.loads((rag_root / "derived/retriever_index_manifest.json").read_text(encoding="utf-8"))
    return manifest["version"]


def parse_database_config(properties: dict[str, str]) -> dict[str, str | int | None]:
    raw_url = config_value(properties, "DATABASE_URL", "spring.datasource.url")
    username = config_value(properties, "DATABASE_USERNAME", "spring.datasource.username")
    password = config_value(properties, "DATABASE_PASSWORD", "spring.datasource.password")
    if is_blank(raw_url):
        raise RuntimeError("DATABASE_URL is missing")

    parsed = urlparse(raw_url.removeprefix("jdbc:"))
    query = parse_qs(parsed.query)
    return {
        "host": parsed.hostname or "",
        "port": parsed.port or 5432,
        "database": parsed.path.removeprefix("/"),
        "username": username or unquote(parsed.username or ""),
        "password": password or unquote(parsed.password or ""),
        "sslmode": query.get("sslmode", [None])[0],
    }


def psql_binary() -> str:
    configured = os.environ.get("PSQL_BIN")
    if configured:
        return configured

    for candidate in ["/opt/homebrew/bin/psql", "/usr/local/bin/psql", "psql"]:
        if candidate == "psql" or Path(candidate).exists():
            return candidate

    raise RuntimeError("psql not found")


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def vector_literal(vector: list[float]) -> str:
    return sql_literal("[" + ",".join(repr(float(item)) for item in vector) + "]")


def embed_queries(queries: list[str], model_name: str, batch_size: int) -> list[list[float]]:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("sentence-transformers is required to query KURE embeddings") from exc

    model = SentenceTransformer(model_name)
    embeddings = model.encode(
        queries,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [[float(value) for value in embedding] for embedding in embeddings]


def run_query(
    database: dict[str, str | int | None],
    query_embedding: list[float],
    index_version: str,
    top_k: int,
) -> str:
    sql = f"""
WITH query_embedding AS (
  SELECT {vector_literal(query_embedding)}::vector AS embedding
)
SELECT
  d.doc_id,
  d.title,
  d.dataset_type,
  COALESCE(d.retrieval_use, '') AS retrieval_use,
  COALESCE(d.source, '') AS source,
  ROUND((d.embedding <=> query_embedding.embedding)::numeric, 6) AS cosine_distance,
  LEFT(REPLACE(d.content, E'\\n', ' '), 180) AS content_preview
FROM rag_documents d, query_embedding
WHERE d.index_version = {sql_literal(index_version)}
  AND d.embedding_storage = 'pgvector'
ORDER BY d.embedding <=> query_embedding.embedding
LIMIT {top_k};
"""
    env = os.environ.copy()
    if database["password"]:
        env["PGPASSWORD"] = str(database["password"])
    if database["sslmode"]:
        env["PGSSLMODE"] = str(database["sslmode"])

    completed = subprocess.run(
        [
            psql_binary(),
            "-h",
            str(database["host"]),
            "-p",
            str(database["port"]),
            "-d",
            str(database["database"]),
            "-U",
            str(database["username"]),
            "-v",
            "ON_ERROR_STOP=1",
            "-X",
            "-A",
            "-F",
            "\t",
            "-c",
            sql,
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"psql query failed: {message}")
    return completed.stdout


def parse_psql_table(output: str) -> list[dict[str, str]]:
    lines = [
        line
        for line in output.splitlines()
        if line.strip() and not line.startswith("(")
    ]
    if len(lines) < 2:
        return []

    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        values = line.split("\t")
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def print_results(query: str, rows: list[dict[str, str]]) -> None:
    print(f"\n## Query: {query}")
    for index, row in enumerate(rows, 1):
        print(
            f"{index}. {row['doc_id']} | distance={row['cosine_distance']} | "
            f"{row['title']} | {row['source']}"
        )
        print(f"   {row['content_preview']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", help="Question to retrieve RAG documents for.")
    parser.add_argument("--samples", action="store_true", help="Run representative sample queries.")
    parser.add_argument("--rag-root", type=Path, default=DEFAULT_RAG_ROOT)
    parser.add_argument("--secret-file", type=Path, default=DEFAULT_SECRET_FILE)
    parser.add_argument("--index-version")
    parser.add_argument("--embedding-model", default=os.environ.get("KURE_MODEL", DEFAULT_KURE_MODEL))
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("KURE_BATCH_SIZE", "8")))
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    queries = SAMPLE_QUERIES if args.samples else [args.query]
    queries = [query for query in queries if query and query.strip()]
    if not queries:
        raise RuntimeError("Pass a query or --samples")

    index_version = args.index_version or load_index_version(args.rag_root)
    properties = load_properties(args.secret_file)
    database = parse_database_config(properties)
    embeddings = embed_queries(queries, args.embedding_model, args.batch_size)

    print(f"Index version: {index_version}")
    print(f"Embedding model: {args.embedding_model}")
    print(f"Top-k: {args.top_k}")
    for query, embedding in zip(queries, embeddings, strict=True):
        rows = parse_psql_table(run_query(database, embedding, index_version, args.top_k))
        print_results(query, rows)


if __name__ == "__main__":
    main()
