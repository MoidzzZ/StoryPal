import copy
import json
from types import SimpleNamespace

import pytest

from retrieval_experiments import cache_audit as audit
from retrieval_experiments import score_queue as queue


def evidence(uid, order, raw, summary=""):
    return {"unit_id": uid, "order": order, "raw_text": raw, "summary": summary,
            "work_id": "wandering_earth", "metadata": {"chapter": "合成"}}


def packer():
    import sys
    from retrieval_experiments.cpu_routes import CHATBOT_SRC
    sys.path.insert(0, str(CHATBOT_SRC))
    from storypal_chatbot.context_packer import ContextPacker
    return ContextPacker()


def test_business_contract_preserves_old_groups_and_separates_denominators():
    counts = audit.validate_business()
    assert counts["tasks"] == 30 and counts["questions"] == 60
    assert counts["domains"] == {"story_retrieval": 23, "reader_memory": 4, "no_story_search": 3}
    assert counts["formal_independent_gold"] == 0


def test_business_model_input_has_owner_and_revision_but_no_verdict():
    p = json.loads(audit.CONTRACT.read_text(encoding="utf-8"))
    t = next(t for t in p["tasks"] if t["task_id"] == "H25")
    value = audit.business_question_input(t, t["variants"][0])
    assert value["owner"] == "reader-A"
    assert value["reader_memory_fixture"]["records"][1]["revision"] == 2
    text = json.dumps(value)
    for label in ("expected_fixture_ids", "acceptable_evidence_sets", "necessary_unit_candidates", "expected_story_decision"):
        assert label not in text


def test_raw_dedup_removes_original_duplicates_despite_different_summary():
    ev = {"a": evidence("a", 1, "same original", "one"),
          "b": evidence("b", 2, "same original", "two"), "c": evidence("c", 3, "other")}
    chosen, drops = audit.prepare(["a", "b", "c"], ev, "raw_dedup")
    assert chosen == ["a", "c"]
    assert drops == [{"unit_id": "b", "reason": "duplicate_original"}]
    assert audit.prepare(["a", "b", "c"], ev, "production")[0] == ["a", "b", "c"]


def test_separator_filter_is_explicit_separate_source_rule():
    ev = {"a": evidence("a", 1, "---", "misleading story summary"),
          "b": evidence("b", 2, "real original")}
    assert audit.prepare(["a", "b"], ev, "raw_dedup")[0] == ["a", "b"]
    chosen, drops = audit.prepare(["a", "b"], ev, "source_checked_dedup")
    assert chosen == ["b"] and drops[0]["reason"] == "separator_only_source"


def test_adjacency_prefers_input_chain_without_reading_gold_or_extra_neighbors():
    ev = {str(i): evidence(str(i), i, "合成正文") for i in (1, 2, 3, 8, 9)}
    ids = ["1", "8", "9", "3", "2"]
    got = audit.select(ids, ev, "irrelevant", "adjacency_first", packer(), lambda s: set(s.split()))[0]
    assert got == ["1", "2", "3", "8"]
    changed = copy.deepcopy(ev)
    changed["9"]["gold_required"] = True
    assert got == audit.select(ids, changed, "irrelevant", "adjacency_first", packer(), lambda s: set(s.split()))[0]


def test_custom_packing_enforces_original_token_budget_without_text_truncation():
    ev = {"a": evidence("a", 1, "a" * 2000), "b": evidence("b", 2, "b" * 2000),
          "c": evidence("c", 3, "small")}
    selected, tokens, drops = audit.select(["a", "b", "c"], ev, "b c", "complementary", packer(), lambda s: set(s.split()))
    assert tokens <= 2400 and len(selected) <= 4 and "b" not in selected
    assert len(ev["b"]["raw_text"]) == 2000


def test_memory_fts_source_table_names_do_not_conflict_with_body_column():
    from retrieval_experiments.sparse import _jieba
    ev = {"a": evidence("a", 1, "太阳", "其他")}
    rows = {"a": {"unit_id": "a", "work_id": "wandering_earth", "order": 1, "text": "太阳"}}
    case = {"case_id": "synthetic", "task_id": "H04", "set": "prospective", "group": "synthetic",
            "query": "太阳", "max_order": 1, "required_units": ["a"], "provisional": True, "decision": "search"}
    result = audit.source_alignment(ev, rows, {"synthetic": case}, {}, packer(), _jieba())
    assert set(result) == {"body", "summary", "structure"}
    assert all(r["query_count"] == 1 and r["source_units"] == 1 for r in result.values())


def test_strict_score_rejects_legacy_or_any_identity_field_change():
    expected = {"query_sha256": "q", "document_sha256": "d", "model_sha256": "m", "prompt_sha256": "p"}
    record = {"identity": expected, "key": queue.canonical(expected), "score": .5}
    assert queue.verify_cached(record, expected) == .5
    for key in expected:
        changed = dict(expected, **{key: "changed"})
        with pytest.raises(ValueError, match="identity"):
            queue.verify_cached(record, changed)
    with pytest.raises(ValueError):
        queue.verify_cached({"score": .5}, expected)


def test_persistent_budget_counts_interrupted_attempt_and_cannot_reset(tmp_path):
    path = tmp_path / "events.jsonl"
    j = queue.Journal(path, "queue")
    assert j.begin("pair") == 1
    assert queue.Journal(path, "queue").state()["seconds"] == 1200
    with pytest.raises(RuntimeError, match="Persistent"):
        queue.Journal(path, "queue").begin("again")
    with pytest.raises(ValueError):
        queue.Journal(path, "another-queue")


def test_budget_stops_on_single_time_or_error_and_reserves_last20_seconds(tmp_path, monkeypatch):
    j = queue.Journal(tmp_path / "one.jsonl", "q")
    j.end(j.begin("first"), 21, 100)
    with pytest.raises(RuntimeError):
        j.begin("second")
    monkeypatch.setitem(queue.BUDGET, "seconds", 60)
    j = queue.Journal(tmp_path / "two.jsonl", "q")
    for i in range(3):
        j.end(j.begin(str(i)), 19, 100)
    assert not j.state()["stop_seen"] and j.state()["seconds"] == 57
    with pytest.raises(RuntimeError):
        j.begin("fourth")


def test_resource_window_guard_precedes_model_or_file_loading(tmp_path):
    with pytest.raises(RuntimeError, match="WebUI"):
        queue.run(tmp_path / "absent", tmp_path / "output", 0, False)
