from pathlib import Path

import pytest

from retrieval_experiments import replay as experiment


def test_first_batch_contract_matches_read_only_goldens():
    cases = experiment.load_cases()
    assert len(cases) == 9
    assert {c["case_id"] for c in cases} == {
        "R12", "R14", "R20", "R25", "R26", "R21", "R29", "P01", "N01"
    }
    assert next(c for c in cases if c["case_id"] == "R25")["required_units"] == [
        "we-0004", "we-0026"
    ]


def test_full_case_set_reuses_all_existing_goldens_without_p01():
    cases = experiment.load_cases("goldens29")
    assert len(cases) == 29
    assert len({c["case_id"] for c in cases}) == 29
    assert all(c["work_id"] == "wandering_earth" for c in cases)
    assert "P01" not in {c["case_id"] for c in cases}
    assert sum(bool(c["required_units"]) for c in cases) == 27


def test_capture_requires_actual_tool_argument_and_boundary():
    cases = experiment.load_cases()
    base = {"case_id": "R14", "origin": "agent_trace", "trace_ref": "opaque-1",
            "work_id": "wandering_earth", "max_order": 26,
            "tool_name": "search_story", "arguments": {"query": "五步 逃亡"}}
    captured = experiment.capture_trace([base], cases)
    assert captured[0]["query_source"] == "agent_query"
    assert captured[0]["query"] == "五步 逃亡"
    with pytest.raises(ValueError, match="origin"):
        experiment.capture_trace([{**base, "origin": "gold_rewrite"}], cases)
    with pytest.raises(ValueError, match="boundary"):
        experiment.capture_trace([{**base, "max_order": 27}], cases)
    with pytest.raises(ValueError, match="query"):
        experiment.capture_trace([{**base, "arguments": {}}], cases)


def test_agent_replay_requires_trace():
    with pytest.raises(ValueError, match="explicit captured"):
        experiment._queries("agent_query", experiment.load_cases(), None)


def test_joint_coverage_differs_from_any_hit(monkeypatch):
    requested_k = []
    class Fake:
        last_search_diagnostics = {"used_retrieval": "fts"}

        def search(self, work_id, query, *, max_order, top_k):
            requested_k.append(top_k)
            return [{"work_id": work_id, "unit_id": "we-0004", "order": 4}]

    monkeypatch.setattr(experiment, "_adapter", lambda *_: Fake())
    report = experiment.replay(source="raw_user", strategy="fts", case_ids={"R25"})
    row = report["cases"][0]
    assert row["hit_at_3"] is True
    assert row["recall_at_3"] == 0.5
    assert row["joint_at_3"] is False
    assert row["candidate_joint"] is False
    assert requested_k == [10]
    assert row["boundary_ok"] is True


def test_candidate_boundary_is_checked_before_top_five(monkeypatch):
    class Fake:
        last_search_diagnostics = {"used_retrieval": "fts"}

        def search(self, work_id, query, *, max_order, top_k):
            return [{"work_id": work_id, "unit_id": f"we-{i:04d}", "order": i}
                    for i in range(1, 6)] + [
                        {"work_id": work_id, "unit_id": "we-0099", "order": 99}
                    ]

    monkeypatch.setattr(experiment, "_adapter", lambda *_: Fake())
    row = experiment.replay(source="raw_user", strategy="fts", case_ids={"R12"})["cases"][0]
    assert len(row["result_units"]) == 5
    assert len(row["candidate_units"]) == 6
    assert row["boundary_ok"] is False
