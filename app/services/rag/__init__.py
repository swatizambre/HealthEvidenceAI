"""Hybrid retrieval package."""

from typing import Any

from app.services.rag.embeddings import EMBEDDING_METHOD, cosine, embed, tokenize
from app.services.rag.types import RetrievalHit

__all__ = [
    "EMBEDDING_METHOD",
    "RetrievalHit",
    "cosine",
    "embed",
    "hybrid_search",
    "search_chunks",
    "tokenize",
]


def __getattr__(name: str) -> Any:
    if name in {"hybrid_search", "search_chunks"}:
        from app.services.rag.pipeline import hybrid_search, search_chunks

        return hybrid_search if name == "hybrid_search" else search_chunks
    raise AttributeError(name)
