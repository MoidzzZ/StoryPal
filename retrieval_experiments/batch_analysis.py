"""Verify explicit six-scene receipts and audit real queries locally; no LLM calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

from .fusion_replay import CHATBOT_SRC, _source_units
from .model_batch import CASES, MODELS, TOTAL_LIMIT, run_path, selected_cases, write_new
from .replay import RUNTIME, _adapter, capture_trace


def evidence_rows(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [row for item in value for row in evidence_rows(item)]
    if not isinstance(value, dict):
        return []
    own = [value] if isinstance(value.get("raw_text"), str) and value["raw_text"].strip() and value.get("unit_id") else []
    return own + [row for item in value.values() if isinstance(item, (dict, list)) for row in evidence_rows(item)]


def audit(root: Path) -> dict:
    sys.path.insert(0, str(CHATBOT_SRC))
    from storypal_chatbot.context_packer import ContextPacker
    from storypal_chatbot.query_capture import export_query
    digest, units = _source_units()
    cases = selected_cases()
    events, rows = [], []
    for case in cases:
        case_id = case["case_id"]
        result = json.loads((root / case_id / "result.json").read_text(encoding="utf-8"))
        completion = result["completion"]
        if (result["failure"] or completion["stop_reason"] != "completed" or completion["has_error"]
                or completion["had_injections"] or result["model"] != MODELS["role"]):
            raise ValueError("Incomplete/unsafe role turn: " + case_id)
        receipt_path = root / case_id / "receipt.json"
        event = export_query(receipt_path)
        if event != result["query_export"]:
            raise ValueError("Receipt no longer matches saved result")
        events.append(event)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        transcript = (RUNTIME / receipt["transcript_ref"]).resolve()
        if not transcript.is_relative_to(root.resolve()):
            raise ValueError("Transcript outside selected batch")
        messages = [json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines() if line.strip()]
        messages = [message for message in messages if message.get("_type") is None]
        start, end = receipt["message_range"]
        selected = messages[start:end]
        returned = []
        tool_names = []
        for message in selected:
            if message.get("role") == "tool":
                tool_names.append(message.get("name"))
                returned.extend(evidence_rows(json.loads(message["content"])))
        returned_ids = list(dict.fromkeys(row["unit_id"] for row in returned))
        if any(row.get("work_id") != case["work_id"] or type(row.get("order")) is not int
               or not 0 < row["order"] <= case["max_order"]
               or units.get(row["unit_id"]) != (case["work_id"], row["order"]) for row in returned):
            raise ValueError("Original evidence crosses approved scope")
        gold = set(case["required_units"])
        rows.append({"case_id": case_id, "decision": event["decision"], "tool_names": tool_names,
                     "max_order": case["max_order"], "required_units": sorted(gold),
                     "gold_status": "provisional" if case_id == "P01" else "existing_gold",
                     "original_evidence_units": returned_ids,
                     "original_joint": gold.issubset(returned_ids) if gold else None,
                     "completed": True, "boundary_ok": True,
                     "final_reply_sha256": hashlib.sha256(result["final_content"].encode()).hexdigest()})
    captured = capture_trace(events, cases)
    path = root / "agent-queries.jsonl"
    with path.open("x", encoding="utf-8") as stream:
        for row in captured:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    adapter = _adapter("vector", 10)
    packer = ContextPacker()
    for row, event in zip(rows, events):
        if event["decision"] == "skip":
            continue
        started = time.perf_counter()
        hits = adapter.search("wandering_earth", event["arguments"]["query"],
                              max_order=row["max_order"], top_k=10)
        ms = round((time.perf_counter() - started) * 1000, 2)
        if adapter.last_search_diagnostics.get("used_retrieval") != "vector":
            raise ValueError("Local real-query replay fell back")
        if any(hit.get("work_id") != "wandering_earth" or type(hit.get("order")) is not int
               or not 0 < hit["order"] <= row["max_order"] for hit in hits):
            raise ValueError("Replay candidate crosses boundary")
        packed = packer.pack(hits[:5], work_id="wandering_earth", max_seen_order=row["max_order"])
        packed_ids = [item["unit_id"] for item in packed.anchors + packed.adjacent_context]
        if set(packed_ids) != set(row["original_evidence_units"]):
            raise ValueError("Actual tool evidence differs from matched local replay: " + row["case_id"])
        ids = [hit["unit_id"] for hit in hits]
        gold = set(row["required_units"])
        row.update({"query_sha256": hashlib.sha256(event["arguments"]["query"].encode()).hexdigest(),
                    "candidate_units": ids, "result_units": ids[:5],
                    "anchor_units": [item["unit_id"] for item in packed.anchors],
                    "adjacent_units": [item["unit_id"] for item in packed.adjacent_context],
                    "candidate_joint": gold.issubset(ids) if gold else None,
                    "joint_at_3": gold.issubset(ids[:3]) if gold else None,
                    "joint_at_5": gold.issubset(ids[:5]) if gold else None,
                    "packed_joint": gold.issubset(packed_ids) if gold else None,
                    "replay_retrieval_ms": ms, "estimated_pack_tokens": packed.token_estimate})
    ledger = [json.loads(line) for line in (root / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
    begins = {row["request_no"]: row for row in ledger if row["event"] == "begin"}
    ends = {row["request_no"]: row for row in ledger if row["event"] == "end"}
    if len(begins) > TOTAL_LIMIT or begins.keys() != ends.keys() or len(ledger) != 2 * len(begins):
        raise ValueError("Request ledger incomplete or exceeds approved budget")
    usage = {}
    for role in MODELS:
        selected = [ends[number] for number, begin in begins.items() if begin["role"] == role]
        if any(row.get("usage", {}).get("source") != "reported" for row in selected):
            raise ValueError("Do not silently estimate missing actual token usage")
        usage[role] = {"requests": len(selected),
                       **{field: sum(row["usage"][field] for row in selected) for field in
                          ("input_tokens", "output_tokens", "total_tokens", "cache_read_tokens")},
                       "request_wall_ms": round(sum(row["elapsed_ms"] for row in selected), 2)}
    scored = [row for row in rows if row["required_units"] and row["gold_status"] == "existing_gold"]
    return {"schema": "real-query-batch-audit@1", "source_sha256": digest,
            "cases": rows, "usage": usage, "metrics": {
                "scenes": len(rows), "completed": len(rows), "scored": len(scored),
                "search_decisions": sum(row["decision"] == "search" for row in rows),
                "skip_decisions": sum(row["decision"] == "skip" for row in rows),
                **{field: sum(row.get(field) is True for row in scored) for field in
                   ("candidate_joint", "joint_at_3", "joint_at_5", "packed_joint", "original_joint")},
                "boundary_violations": sum(not row["boundary_ok"] for row in rows),
                "actual_evidence_matches_local_replay": True},
            "latency_note": "Request times exclude local tool/model loading; replay times are a separate local process. "
                            "Neither is full end-to-end user latency.",
            "answer_note": "Original evidence coverage is not a claim-level answer correctness score; separate qualitative review required."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    root = run_path(args.run_root)
    if (root / "batch-audit.json").exists() or (root / "agent-queries.jsonl").exists():
        parser.error("Audit never overwrites previous artifacts")
    result = audit(root)
    write_new(root / "batch-audit.json", result)
    print(json.dumps({"metrics": result["metrics"], "usage": result["usage"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
