import copy
import re

import pytest

from retrieval_experiments.cached_context_pack import (
    frame, metrics, rank, select_coverage4, terms, validate_cache,
)


class Words:
    def cut(self, value, cut_all=False):
        return value.split()


def test_phase_negation_and_relation_tokens_are_not_removed_as_filler():
    selected = terms("我 为什么 开始 先 后 刚才 近日点 没有 不能 原因", Words())
    assert {"开始", "先", "后", "刚才", "近日点", "没有", "不能", "原因"} <= selected
    assert not {"我", "为什么"} & selected


def test_full_frame_preserves_omitted_subject_stage_and_filters_meta_question():
    tokenize = lambda value: set(re.findall(r"\w+", value))
    query = "甲 光柱 为什么 斜着？启航 时 又 为什么 变直？"
    representation = frame(query, "", "frame_terms", tokenize)
    assert representation["active"] and representation["clause_count"] == 2
    assert {"光柱", "启航"} <= representation["frame_terms"]
    assert "光柱" not in representation["clause_terms"][1]
    guarded = frame("我是不是记错了，光柱为什么斜着？", "", "guard_context_terms", tokenize)
    assert not guarded["active"] and guarded["clause_count"] == 1
    contextual = frame("刚才那个谜底为什么让我发冷？", "哲学课 死亡", "guard_context_terms", tokenize)
    assert contextual["active"] and contextual["context_used"]
    assert {"哲学课", "死亡"} <= contextual["frame_terms"]


def test_candidate_internal_ranking_cannot_add_gold_or_drop_candidate_ids():
    ids = ["dense-first", "subject", "phase", "unrelated"]
    docs = {"dense-first": {"甲"}, "subject": {"甲", "光柱"},
            "phase": {"启航", "变直"}, "unrelated": {"其他"}}
    representation = {"active": True, "clause_terms": [{"甲", "光柱"}, {"启航", "变直"}],
                      "frame_terms": {"甲", "光柱", "启航", "变直"}}
    ranked = rank(ids, docs, representation, "frame_terms")
    assert set(ranked) == set(ids) and len(ranked) == len(ids)
    assert ranked.index("subject") < ranked.index("unrelated")
    assert rank(ids, docs, {**representation, "active": False}, "cached_dense") == ids


def test_packing_can_choose_fifth_distinct_evidence_without_exceeding_unit_or_token_budget():
    ids = ["a", "b", "c", "d", "e"]
    evidence = {uid: {"cost": 600} for uid in ids}
    docs = {"a": {"topic"}, "b": {"topic"}, "c": {"topic"},
            "d": {"topic"}, "e": {"phase"}}
    selected = select_coverage4(ids, evidence, docs, {"topic", "phase"}, lambda item: item["cost"])
    assert selected[0] == "a" and "e" in selected and len(selected) == 4
    assert sum(evidence[uid]["cost"] for uid in selected) <= 2400
    evidence["e"]["cost"] = 2500
    assert "e" not in select_coverage4(ids, evidence, docs, {"topic", "phase"}, lambda item: item["cost"])
    with pytest.raises(ValueError, match="Top5"):
        select_coverage4(ids + ["a"], evidence, docs, {"topic"}, lambda item: item["cost"])


def test_cache_query_boundary_source_and_candidate_budget_are_verified():
    from retrieval_experiments.cached_context_pack import query_sha
    expected = [{"case_id": "test", "max_order": 5, "query": "原问", "required_units": ["a"]}]
    cache = {"source_sha256": "source", "cases": [{"case_id": "test", "max_order": 5,
             "query_sha256": query_sha("原问"), "required_units": ["a"], "candidate_units": ["a"]}]}
    evidence = {"a": {"work_id": "wandering_earth", "order": 5}}
    validate_cache(cache, expected, evidence, "source")
    for field, fault in (("query_sha256", "other"), ("max_order", 6), ("candidate_units", ["a", "a"])):
        changed = copy.deepcopy(cache)
        changed["cases"][0][field] = fault
        with pytest.raises(ValueError):
            validate_cache(changed, expected, evidence, "source")
    with pytest.raises(ValueError, match="boundary"):
        validate_cache(cache, expected, {"a": {"work_id": "wandering_earth", "order": 6}}, "source")
    with pytest.raises(ValueError, match="source"):
        validate_cache(cache, expected, evidence, "different")


def test_provisional_history_and_empty_gold_are_not_pooled_into_three_scene_score():
    base = dict(required_units=["a"], gold_status="existing_gold", candidate_joint=True,
                joint_at_3=True, joint_at_5=True, packed_joint=True, mrr=1,
                packed_units=["a"], estimated_tokens=100, boundary_ok=True,
                query_processing_active=False, local_ms=1)
    rows = [{**base, "case_id": str(n)} for n in range(3)]
    rows += [{**base, "case_id": "P01", "gold_status": "provisional", "packed_joint": False},
             {**base, "case_id": "R21", "required_units": [], "mrr": None}]
    result = metrics(rows)
    assert result["cases"] == 5 and result["scored"] == result["packed_joint"] == 3
    assert result["provisional_cases"] == ["P01"]
