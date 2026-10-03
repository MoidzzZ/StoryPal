import json

import pytest

from retrieval_experiments import generated_replay
from retrieval_experiments.model_batch import MODELS, digest


def prepare(tmp_path, monkeypatch):
    cases = [dict(case_id="R25", max_order=26, retrieval_decision="search", required_units=["a", "b"]),
             dict(case_id="P01", max_order=22, retrieval_decision="search", required_units=["c"]),
             dict(case_id="N01", max_order=22, retrieval_decision="skip", required_units=[])]
    monkeypatch.setattr(generated_replay, "run_path", lambda path: path)
    monkeypatch.setattr(generated_replay, "selected_cases", lambda: cases)
    (tmp_path / "generated").mkdir()
    acceptance = {}
    for case in cases:
        row = dict(case_id=case["case_id"], max_order=case["max_order"], model=MODELS["user"],
                   question="固定的模拟问题", question_sha256=digest("固定的模拟问题"))
        (tmp_path / "generated" / (case["case_id"] + ".json")).write_text(json.dumps(row), encoding="utf-8")
        acceptance[case["case_id"]] = dict(accepted=True, question_sha256=row["question_sha256"])
    (tmp_path / "acceptance.json").write_text(json.dumps(acceptance), encoding="utf-8")


def test_provisional_label_is_explicit_and_pause_case_is_not_forced_into_retrieval(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    cases = generated_replay.inputs(tmp_path)
    assert [case["case_id"] for case in cases] == ["R25", "P01"]
    assert cases[0]["gold_status"] == "existing_gold" and cases[1]["gold_status"] == "provisional"


def test_modified_question_or_wrong_case_cannot_reuse_review(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    path = tmp_path / "generated" / "R25.json"
    row = json.loads(path.read_text(encoding="utf-8"))
    original = row.copy()
    for fault in ("question", "case_id", "model", "max_order"):
        row = original.copy()
        row[fault] = "changed"
        path.write_text(json.dumps(row), encoding="utf-8")
        with pytest.raises(ValueError, match="review"):
            generated_replay.inputs(tmp_path)
