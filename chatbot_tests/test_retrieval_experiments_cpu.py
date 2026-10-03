"""Risk tests for offline route separation, boundaries and source decisions."""
import copy
import json
from types import SimpleNamespace

import pytest

from retrieval_experiments import cpu_routes as cpu


def test_revision_preserves_frozen_groups_candidates_and_records_premise_correction():
    old = json.loads((cpu.CONTRACT.parent / "prospective_tasks_v1.json").read_text(encoding="utf-8"))
    revised = json.loads(cpu.CONTRACT.read_text(encoding="utf-8"))
    assert revised["revisions"][0]["task_id"] == "H04"
    for before, after in zip(old["tasks"], revised["tasks"]):
        assert before["split_group"] == after["split_group"]
        assert before["max_order"] == after["max_order"]
        assert before["necessary_unit_candidates"] == after["necessary_unit_candidates"]
        assert before["evidence_checks"] == after["evidence_checks"]
        if before["task_id"] != "H04":
            assert before == after
    assert "之前" in revised["tasks"][3]["variants"][0]["text"]


def test_route_selector_uses_only_current_names_not_future_or_gold():
    rows = {
        "a": {"order": 1, "entity_updates": [{"name": "爸爸"}, {"name": "地球发动机"}], "plotline_updates": []},
        "b": {"order": 9, "entity_updates": [{"name": "加代子"}], "plotline_updates": []}}
    tokens = lambda text: text.split()
    assert cpu.choose_navigation("地球发动机和爸爸、加代子", 1, rows, tokens) == [
        {"kind": "entity", "query": "地球发动机"}, {"kind": "entity", "query": "爸爸"}]
    changed = copy.deepcopy(rows)
    changed["a"]["required_units"] = ["never"]
    assert cpu.choose_navigation("地球发动机和爸爸、加代子", 1, changed, tokens) == cpu.choose_navigation(
        "地球发动机和爸爸、加代子", 1, rows, tokens)
    assert cpu.choose_navigation("加代子", 1, rows, tokens) == []


def test_structure_budget_recency_drops_early_evidence_without_gold_rescue():
    rows = {str(i): {"order": i, "work_id": "wandering_earth", "text": "合成正文",
                    "entity_updates": [{"name": "人物"}], "plotline_updates": []} for i in range(1, 26)}
    class Service:
        def structured_context(self, **kwargs):
            return {"history": [{"unit_id": str(i), "order": i, "update": {}} for i in range(1, 26)]}
        def get_evidence(self, **kwargs):
            return {"raw_text": "合成正文"}
    ids, info = cpu.structure("人物", 25, rows, lambda q: [q], Service())
    assert ids == [str(i) for i in range(25, 15, -1)]
    assert info["history_records_kept"] == 20
    assert info["history_dropped"] == 5
    assert "1" not in ids


def test_structure_rejects_future_history_instead_of_silently_counting_it():
    rows = {"a": {"order": 1, "entity_updates": [{"name": "人物"}], "plotline_updates": []}}
    class Service:
        def structured_context(self, **kwargs):
            return {"history": [{"unit_id": "future", "order": 10, "update": {}}]}
    with pytest.raises(ValueError, match="provenance"):
        cpu.structure("人物", 1, rows, lambda q: [q], Service())


def test_incomplete_stage_is_not_scored_as_full_evidence_failure():
    rows = {"a": {"work_id": "wandering_earth", "order": 1, "text": "正文"},
            "b": {"work_id": "wandering_earth", "order": 2, "text": "后续正文"}}
    c = {"case_id": "stage", "task_id": "t", "set": "stage", "group": "g", "max_order": 1,
         "query": "合成问题", "required_units": ["a", "b"], "provisional": True, "decision": "search"}
    memory = SimpleNamespace(get_unit=lambda *args: {"unit_id": "a"})
    packer = SimpleNamespace(pack=lambda *args, **kwargs: SimpleNamespace(
        anchors=[{"unit_id": "a"}], adjacent_context=[], dropped=[], token_estimate=1))
    result = cpu.evaluate(c, ["a"], rows, memory, packer)
    assert result["joint_at_10"] is None and result["packed_joint"] is None
    assert result["visible_packed_joint"] is True and result["unread_required_units"] == ["b"]
    assert result["failure_type"] == "incomplete_scope"
    assert cpu.summarize([result])["stage"]["diagnostic_denominator"] == 0


def test_memory_absence_and_pause_are_not_forced_into_story_retrieval():
    cases = cpu.cases()
    skipped = [c for c in cases if c["decision"] != "search"]
    assert {c["case_id"] for c in skipped} == {"H15-a", "H15-b", "N01"}
    assert all(not c["required_units"] for c in skipped)
    assert len([c for c in cases if c["set"] == "stage"]) == 26
    assert len({c["query"] for c in cases if c["decision"] == "search"}) == 57


def test_candidate_guard_rejects_duplicate_overbudget_wrong_work_or_future():
    rows = {"a": {"order": 2, "work_id": "wandering_earth"},
            "b": {"order": 1, "work_id": "other"}}
    for ids, scope in [(["a", "a"], 2), (["a"], 1), (["b"], 2), (["missing"], 2)]:
        with pytest.raises(ValueError):
            cpu.safe_ids(ids, scope, rows)
