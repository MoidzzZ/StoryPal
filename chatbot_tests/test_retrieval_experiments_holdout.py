import copy
import json

import pytest

from retrieval_experiments.holdout_contract import (
    CONTRACT, LOCK, canonical, question_input, reranker_pair, rerank_scored,
    sha, source_rows, validate,
)
from retrieval_experiments.replay import GOLDENS
from retrieval_experiments.fusion_replay import SOURCE


@pytest.fixture
def frozen():
    return (json.loads(CONTRACT.read_text(encoding="utf-8")),
            json.loads(LOCK.read_text(encoding="utf-8")), source_rows(),
            sha(SOURCE.read_bytes()), sha(GOLDENS.read_bytes()))


def restamp_for_validation(payload, lock):
    lock["contract_canonical_sha256"] = canonical(payload)


def test_post_freeze_question_or_label_edit_requires_new_contract_version(frozen):
    payload, lock, rows, source_hash, dev_hash = frozen
    for mutation in ("text", "necessary_unit_candidates"):
        changed = copy.deepcopy(payload)
        if mutation == "text":
            changed["tasks"][0]["variants"][0]["text"] += "改了问题"
        else:
            changed["tasks"][0][mutation] = []
        with pytest.raises(ValueError, match="Frozen"):
            validate(changed, lock, rows, source_hash, dev_hash)


def test_variants_and_shared_evidence_cannot_be_split_independently(frozen):
    payload, lock, rows, source_hash, dev_hash = frozen
    changed, stamp = copy.deepcopy(payload), copy.deepcopy(lock)
    changed["tasks"][0]["variants"][1]["split_group"] = "different"
    restamp_for_validation(changed, stamp)
    with pytest.raises(ValueError, match="Variant"):
        validate(changed, stamp, rows, source_hash, dev_hash)
    changed, stamp = copy.deepcopy(payload), copy.deepcopy(lock)
    case = next(task for task in changed["tasks"] if task["task_id"] == "H12")
    case["split_group"] = "separate_rebellion"
    for variant in case["variants"]:
        variant["split_group"] = case["split_group"]
    stamp["task_groups"]["H12"] = case["split_group"]
    restamp_for_validation(changed, stamp)
    with pytest.raises(ValueError, match="Shared original"):
        validate(changed, stamp, rows, source_hash, dev_hash)


def test_original_span_or_boundary_error_cannot_be_validated_as_story_evidence(frozen):
    payload, lock, rows, source_hash, dev_hash = frozen
    changed, stamp = copy.deepcopy(payload), copy.deepcopy(lock)
    changed["tasks"][0]["evidence_checks"][0]["span_sha256"] = "wrong"
    restamp_for_validation(changed, stamp)
    with pytest.raises(ValueError, match="hash/span"):
        validate(changed, stamp, rows, source_hash, dev_hash)
    changed, stamp = copy.deepcopy(payload), copy.deepcopy(lock)
    changed["tasks"][0]["max_order"] = 13
    restamp_for_validation(changed, stamp)
    with pytest.raises(ValueError, match="boundary"):
        validate(changed, stamp, rows, source_hash, dev_hash)


def test_missing_reader_memory_is_not_upgraded_to_an_available_record(frozen):
    payload, lock, rows, source_hash, dev_hash = frozen
    changed, stamp = copy.deepcopy(payload), copy.deepcopy(lock)
    changed["tasks"][-1]["reader_memory_fixture"]["available"] = True
    restamp_for_validation(changed, stamp)
    with pytest.raises(ValueError, match="Missing reader memory"):
        validate(changed, stamp, rows, source_hash, dev_hash)
    counts = validate(payload, lock, rows, source_hash, dev_hash)
    assert counts["formal_independently_reviewed_gold"] == 0
    assert counts["statuses"]["missing_reader_memory"] == 1


def test_question_input_keeps_old_prediction_but_excludes_review_answer_and_gold(frozen):
    payload, *_ = frozen
    task = next(case for case in payload["tasks"] if case["task_id"] == "H06")
    visible = question_input(task, task["variants"][0])
    assert visible["reader_memory_fixture"]["records"][0]["content"]
    serialized = json.dumps(visible, ensure_ascii=False)
    for field in ("necessary_unit_candidates", "evidence_checks", "counter_or_unknown", "expected_review", "weakened_not_fully_falsified"):
        assert field not in serialized
    assert "source_checked_pending_independent_review" not in serialized


def test_reranker_contract_checks_scope_and_requires_real_complete_pool_scores():
    evidence = {"work_id": "wandering_earth", "order": 3, "raw_text": "合成段落，只验接口。"}
    assert "<Query>: 当前问题" in reranker_pair("当前问题", evidence, max_order=3)
    with pytest.raises(ValueError, match="Unsafe"):
        reranker_pair("当前问题", evidence, max_order=2)
    assert rerank_scored(["a", "b"], {"a": .1, "b": .9}) == ["b", "a"]
    assert rerank_scored(["a", "b"], {"a": .5, "b": .5}) == ["a", "b"]
    for scores in ({"a": .1}, {"a": .1, "b": float("nan")}, {"a": .1, "b": .9, "extra": 1}):
        with pytest.raises(ValueError, match="same distinct"):
            rerank_scored(["a", "b"], scores)
