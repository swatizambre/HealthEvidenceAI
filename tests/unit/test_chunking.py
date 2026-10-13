"""Chunking covers the source text without dropping characters."""

from app.services.chunking import chunk_text


def test_blank_text_has_no_chunks() -> None:
    assert chunk_text("   ") == []


def test_short_text_is_one_chunk() -> None:
    assert chunk_text("synthetic note", size=100) == ["synthetic note"]


def test_overlap_reassembles_the_original_text() -> None:
    text = "abcdefghijklmnopqrstuvwxyz" * 20
    chunks = chunk_text(text, size=50, overlap=10)
    assert len(chunks) > 1
    rebuilt = chunks[0]
    for chunk in chunks[1:]:
        assert chunk[:10] == rebuilt[-10:]
        rebuilt += chunk[10:]
    assert rebuilt == text


def test_overlap_must_be_smaller_than_size() -> None:
    try:
        chunk_text("abcdef", size=4, overlap=4)
    except ValueError as exc:
        assert "overlap" in str(exc)
    else:
        raise AssertionError("expected overlap to be rejected")
