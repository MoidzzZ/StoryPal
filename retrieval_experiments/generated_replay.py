"""Replay fixed Sol paraphrases locally; do not call Luna or count as agent_query."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .facet_replay import replay
from .model_batch import MODELS, digest, run_path, selected_cases, write_new


def inputs(root: Path) -> list[dict]:
    root = run_path(root)
    acceptance = json.loads((root / "acceptance.json").read_text(encoding="utf-8"))
    cases = []
    for case in selected_cases():
        generated = json.loads((root / "generated" / (case["case_id"] + ".json")).read_text(encoding="utf-8"))
        reviewed = acceptance.get(case["case_id"], {})
        if (generated.get("case_id") != case["case_id"] or generated.get("model") != MODELS["user"]
                or generated.get("max_order") != case["max_order"]
                or not isinstance(generated.get("question"), str)
                or generated.get("question_sha256") != digest(generated["question"].strip())
                or not reviewed.get("accepted")
                or reviewed.get("question_sha256") != generated["question_sha256"]):
            raise ValueError("Generated input lacks exact question review")
        if case["retrieval_decision"] == "skip":
            continue  # No fabricated actual decision: do not force local retrieval on N01.
        cases.append({**case, "raw_user": generated["question"].strip(),
                      "gold_status": "provisional" if case["case_id"] == "P01" else "existing_gold"})
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = run_path(args.run_root)
    output = root / "sol-local-replay.json"
    if output.exists():
        parser.error("Do not overwrite an existing replay")
    result = replay(inputs(root), query_source="sol_paraphrase", case_set="approved_six_scenes")
    result["decision_note"] = "N01 excluded: expected no retrieval, actual Luna decision is not yet assessed."
    result["gold_note"] = "Only three nonempty existing R gold sets scored; P01 reported provisionally, never pooled."
    write_new(output, result)
    print(json.dumps({name: value["metrics"] for name, value in result["configurations"].items()},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
