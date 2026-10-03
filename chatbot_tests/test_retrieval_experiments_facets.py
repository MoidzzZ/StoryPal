import pytest

from retrieval_experiments.facet_replay import _safe, rank_clauses, split_query


def test_split_preserves_nonquestion_context_and_does_not_invent_subjects():
    assert split_query("先看这一节，甲为什么变冷？乙怎么变热？我没看懂。") == [
        "先看这一节，甲为什么变冷", "乙怎么变热，我没看懂"]
    assert split_query("甲为什么斜着，后来又为什么变直？") == ["甲为什么斜着", "后来又为什么变直"]
    for text in ("甲怎么了？", "甲为什么？乙为何？丙为什么？", "先休息，陪我缓缓。"):
        assert split_query(text) == [text]


def test_head_reservation_retains_distinct_routes_without_gold_input():
    routes = [["a", "shared", "x"], ["b", "shared", "y"]]
    assert rank_clauses(routes, reserve_heads=False)[0] == "shared"
    assert rank_clauses(routes, reserve_heads=True)[:2] == ["a", "b"]
    assert set(rank_clauses(routes, reserve_heads=True)) == {"a", "b", "shared", "x", "y"}
    assert rank_clauses([["a", "b"], ["a", "c"]], reserve_heads=True).count("a") == 1


def test_unsplit_path_is_identical_and_result_slot_budget_is_enforced():
    route = [str(i) for i in range(10)]
    assert rank_clauses([route], reserve_heads=True) == route
    with pytest.raises(ValueError, match="ten"):
        rank_clauses([route, route], reserve_heads=False)
    with pytest.raises(ValueError, match="duplicates"):
        rank_clauses([["a", "a"]], reserve_heads=True)


def test_scope_check_rejects_future_wrong_work_and_noninteger_order():
    _safe([{"work_id": "wandering_earth", "order": 5}], 5)
    for row in ({"work_id": "wandering_earth", "order": 6},
                {"work_id": "other", "order": 5}, {"work_id": "wandering_earth", "order": "5"}):
        with pytest.raises(ValueError, match="boundary"):
            _safe([row], 5)
