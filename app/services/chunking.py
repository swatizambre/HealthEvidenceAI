"""Deterministic character chunking for clinical and policy text."""

from __future__ import annotations


def chunk_text(text: str, size: int = 4000, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks. Default size keeps short records in one chunk."""
    normalized = text.strip()
    if not normalized:
        return []
    if size <= 0:
        raise ValueError("size must be positive")
    if len(normalized) <= size:
        return [normalized]
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be smaller than size")
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + size)
        chunks.append(normalized[start:end])
        if end >= len(normalized):
            break
        next_start = end - overlap
        if next_start <= start:
            break
        start = next_start
    return chunks
