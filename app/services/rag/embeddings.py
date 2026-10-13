"""Hybrid embedding payloads: lexical sparse + dense vectors."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import numpy as np

from app.core.config import Settings, get_settings

EMBEDDING_METHOD = "hybrid-v1"
DENSE_HASH_MODEL = "dense-hash-v1"

_TOKEN = re.compile(r"[a-z0-9_]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in _TOKEN.findall(text.lower())
        if len(token) >= 2 and token not in _STOPWORDS
    ]


def sparse_embed(text: str) -> dict[str, float]:
    counts: dict[str, int] = {}
    for token in tokenize(text):
        counts[token] = counts.get(token, 0) + 1
    if not counts:
        return {}
    return {token: 1.0 + math.log(count) for token, count in counts.items()}


def sparse_cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[token] * right[token] for token in left.keys() & right.keys())
    if dot == 0.0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def dense_hash_embed(text: str, dim: int = 256) -> list[float]:
    """Offline dense channel via signed feature hashing (no model download)."""
    vec = np.zeros(dim, dtype=np.float64)
    tokens = tokenize(text)
    if not tokens:
        return vec.tolist()
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[index] += sign
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


def dense_cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def openai_dense_embed(text: str, settings: Settings) -> list[float]:
    import httpx

    from app.core.exceptions import RetrievalError

    if not settings.openai_api_key.strip():
        raise RetrievalError("OPENAI_API_KEY is required for OpenAI embeddings.")
    model = (
        "text-embedding-3-small"
        if settings.embedding_model.startswith("openai")
        else settings.embedding_model
    )
    try:
        response = httpx.post(
            f"{settings.openai_base_url.rstrip('/')}/embeddings",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "input": text},
            timeout=settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        vector = response.json()["data"][0]["embedding"]
        return [float(v) for v in vector]
    except Exception as exc:
        raise RetrievalError(f"OpenAI embedding failed: {exc}") from exc


def dense_embed(text: str, settings: Settings | None = None) -> list[float]:
    cfg = settings or get_settings()
    if cfg.use_openai_embeddings():
        if cfg.external_llm_phi_blocked():
            from app.core.exceptions import RetrievalError

            raise RetrievalError(
                "OpenAI embeddings blocked while ALLOW_PHI is on without "
                "LLM_BAA_ATTESTED and LLM_PHI_EGRESS_ALLOWED."
            )
        return openai_dense_embed(text, cfg)
    return dense_hash_embed(text, dim=cfg.embedding_dim)


def embed(text: str, settings: Settings | None = None) -> dict[str, Any]:
    """Hybrid payload stored on DocumentChunk.embedding."""
    cfg = settings or get_settings()
    return {
        "sparse": sparse_embed(text),
        "dense": dense_embed(text, cfg),
        "model": cfg.embedding_model or DENSE_HASH_MODEL,
        "method": EMBEDDING_METHOD,
    }


def parse_embedding(value: object) -> tuple[dict[str, float], list[float]]:
    """Parse a stored embedding payload into sparse and dense channels."""
    if not isinstance(value, dict):
        return {}, []
    if "sparse" in value or "dense" in value:
        sparse_raw = value.get("sparse") or {}
        dense_raw = value.get("dense") or []
        sparse = {
            str(k): float(v)
            for k, v in sparse_raw.items()
            if isinstance(k, str) and isinstance(v, int | float)
        }
        dense = [float(v) for v in dense_raw if isinstance(v, int | float)]
        return sparse, dense
    sparse = {
        str(k): float(v)
        for k, v in value.items()
        if isinstance(k, str) and isinstance(v, int | float)
    }
    return sparse, []


def cosine(left: object, right: object) -> float:
    """Cosine similarity over sparse channels."""
    left_sparse, _ = parse_embedding(left) if isinstance(left, dict) else ({}, [])
    right_sparse, _ = parse_embedding(right) if isinstance(right, dict) else ({}, [])
    return sparse_cosine(left_sparse, right_sparse)
