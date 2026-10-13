"""Sparse embeddings are deterministic and rank a unique marker first."""

import pytest
from app.services.embeddings import EMBEDDING_METHOD, cosine, embed


def test_embedding_method_is_named() -> None:
    assert EMBEDDING_METHOD == "hybrid-v1"


def test_identical_text_has_cosine_one() -> None:
    vector = embed("dynamic catalog evidence review criteria")
    assert cosine(vector, embed("dynamic catalog evidence review criteria")) == pytest.approx(1.0)


def test_empty_text_has_no_similarity() -> None:
    assert cosine(embed("   "), embed("catalog review")) == 0.0


def test_unique_marker_outranks_unrelated_text() -> None:
    query = embed("POLICY_MARKER_DYNAMIC_REVIEW Dynamic catalog evidence review")
    scores = {
        "policy": cosine(
            query,
            embed(
                "POLICY_MARKER_DYNAMIC_REVIEW Dynamic catalog evidence review "
                "criteria were derived from facts present in the loaded catalog"
            ),
        ),
        "other": cosine(query, embed("synthetic condition alpha recorded in a routine note")),
    }
    assert scores["policy"] > scores["other"]
    assert scores["policy"] > 0
