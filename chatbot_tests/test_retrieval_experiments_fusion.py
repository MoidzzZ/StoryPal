import pytest

from retrieval_experiments.fusion_replay import CONFIGS, rank_candidates, validate_inputs


def source_report(strategy):
    return {
        "schema": "retrieval-replay@2", "case_set": "goldens29",
        "strategy": strategy, "query_source": "raw_user",
        "source_sha256": "fixed-source", "candidate_k": 10, "top_k": 5,
        "cases": [
            {"case_id": f"R{i:02d}", "max_order": 1, "query_sha256": "same-query",
             "required_units": ["u"], "status": "searched", "boundary_ok": True,
             "candidate_units": ["u"]}
            for i in range(1, 30)
        ],
    }


def test_fixed_fusion_uses_only_four_predeclared_configurations():
    assert CONFIGS == ("jieba_or", "dense", "rrf_equal", "rrf_dense2_sparse1")


def test_equal_and_dense_weighted_rrf_rank_differently_without_tuning():
    dense = ["z", "x", "a"]
    sparse = ["a", "x", "z"]
    equal = rank_candidates(dense, sparse, "rrf_equal")
    weighted = rank_candidates(dense, sparse, "rrf_dense2_sparse1")
    assert equal[0]["unit_id"] == "a"
    assert weighted[0]["unit_id"] == "z"
    assert equal[0]["source_ranks"] == {"dense": 3, "jieba_or": 1}
    assert weighted[0]["source_ranks"] == {"dense": 1, "jieba_or": 3}


def test_fusion_keeps_at_most_ten_ranked_candidates():
    dense = [f"d{i}" for i in range(10)]
    sparse = [f"s{i}" for i in range(10)]
    assert len(rank_candidates(dense, sparse, "rrf_equal")) == 10


def test_fusion_rejects_scan_input_and_mismatched_query_or_boundary():
    dense, sparse = source_report("vector"), source_report("jieba_or")
    units = {"u": ("wandering_earth", 1)}
    validate_inputs(dense, sparse, source="raw_user", digest="fixed-source", units=units)
    sparse["strategy"] = "fts"
    with pytest.raises(ValueError, match="fixed jieba_or"):
        validate_inputs(dense, sparse, source="raw_user", digest="fixed-source", units=units)
    sparse["strategy"] = "jieba_or"
    sparse["cases"][0]["query_sha256"] = "different"
    with pytest.raises(ValueError, match="query"):
        validate_inputs(dense, sparse, source="raw_user", digest="fixed-source", units=units)
    sparse["cases"][0]["query_sha256"] = "same-query"
    sparse["cases"][0]["max_order"] = 2
    with pytest.raises(ValueError, match="boundary"):
        validate_inputs(dense, sparse, source="raw_user", digest="fixed-source", units=units)
    sparse["cases"][0]["max_order"] = 1
    with pytest.raises(ValueError, match="Candidate crosses"):
        validate_inputs(dense, sparse, source="raw_user", digest="fixed-source",
                        units={"u": ("wandering_earth", 2)})
