"""Runtime configuration. Standard library only so it stays testable."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAG_ROOT = REPO_ROOT / "rag_rulebook"
DEFAULT_INDEX_VERSION = "2026-08-20-translated-corpus"
DEFAULT_KURE_MODEL = "nlpai-lab/KURE-v1"

# Measured on the real evidence payload for the two demo questions, 3 runs each:
# gpt-5.6-terra p50 5.4s / 25.0s with a 25.5s worst case, gpt-5.6-sol up to 30.1s,
# gpt-5.6-luna 4.2-6.9s throughout. The tail, not the median, is what breaks the
# 10s budget, so the default is luna. Re-measure before changing this.
DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"

# Only the default patient-answer index may ground an answer. The expanded
# reference corpus and the evaluation holdout must never be retrieved here.
#
# These are the values ingestion actually assigned, confirmed against the
# deployed table: curated 17, official_rag_candidate 15, trusted_rag_candidate 58
# — 90 rows total. `curated` is the tier that carries the reviewed
# `answer_template`, so it must be listed first in intent and never omitted.
#
# An earlier version of this list left `curated` out. mvp_care_knowledge.jsonl has
# no `retrieval_use` field, so the assumption was that those documents would land
# as NULL and be covered by `allow_null_retrieval_use`. Ingestion assigned the
# literal 'curated' instead, so the filter silently narrowed retrieval to 73 rows
# and made every curated document unreachable. Measurement showed all 14 expected
# documents missing from the top 20 as a result. Do not remove a tier from this
# list without re-running verification/probe_retrieval.py.
DEFAULT_ALLOWED_RETRIEVAL_USE = (
    "curated",
    "official_rag_candidate",
    "trusted_rag_candidate",
)


@dataclass(frozen=True)
class Settings:
    database_url: str
    database_username: str | None
    database_password: str | None
    rag_root: Path
    rag_index_version: str
    rag_top_k: int
    rag_min_similarity: float
    rag_allowed_retrieval_use: tuple[str, ...]
    rag_allow_null_retrieval_use: bool
    kure_model: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    openai_max_output_tokens: int

    @property
    def rules_path(self) -> Path:
        return self.rag_root / "rules" / "emergency_rules.json"


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    return values or default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_openai_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    if normalized == "https://api.openai.com":
        return f"{normalized}/v1"
    return normalized


def build_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", ""),
        database_username=os.getenv("DATABASE_USERNAME"),
        database_password=os.getenv("DATABASE_PASSWORD"),
        rag_root=Path(os.getenv("RAG_RULEBOOK_ROOT", str(DEFAULT_RAG_ROOT))),
        rag_index_version=os.getenv("RAG_INDEX_VERSION", DEFAULT_INDEX_VERSION),
        rag_top_k=int(os.getenv("RAG_TOP_K", "5")),
        rag_min_similarity=float(os.getenv("RAG_MIN_SIMILARITY", "0.50")),
        rag_allowed_retrieval_use=_csv_env(
            "RAG_ALLOWED_RETRIEVAL_USE", DEFAULT_ALLOWED_RETRIEVAL_USE
        ),
        # No row in the deployed index has a NULL retrieval_use, so allowing NULL
        # buys nothing and would silently admit anything ingested without a tier.
        rag_allow_null_retrieval_use=_bool_env("RAG_ALLOW_NULL_RETRIEVAL_USE", False),
        kure_model=os.getenv("KURE_MODEL", DEFAULT_KURE_MODEL),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_base_url=normalize_openai_base_url(
            os.getenv("OPENAI_BASE_URL", "https://api.openai.com")
        ),
        openai_model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        openai_max_output_tokens=int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "900")),
    )


@lru_cache
def get_settings() -> Settings:
    return build_settings()


def database_kwargs(settings: Settings) -> dict[str, Any]:
    parsed = urlparse(settings.database_url.removeprefix("jdbc:"))
    query = parse_qs(parsed.query)

    kwargs: dict[str, Any] = {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": parsed.path.removeprefix("/"),
        "user": settings.database_username or unquote(parsed.username or ""),
        "password": settings.database_password or unquote(parsed.password or ""),
    }
    sslmode = query.get("sslmode", [None])[0]
    if sslmode:
        kwargs["sslmode"] = sslmode
    return kwargs
