"""Frozen prospective task validation and CPU-only interface availability checks.

Does not retrieve rankings, import neural libraries, load models or call agents.
Annotation hashes establish reproducibility, not independent literary truth.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import struct
import sys

from .fusion_replay import CHATBOT_SRC, SOURCE
from .replay import DATA, GOLDENS, PIPELINE, ROOT, RUNTIME

CONTRACT = ROOT / "docs/research/retrieval/prospective_tasks_v1.json"
LOCK = CONTRACT.with_suffix(".lock.json")
MODEL = Path("D:/models/Qwen/Qwen3-Reranker-0.6B")
INSTRUCTION = "Judge whether this novel passage provides evidence for the reader question within the confirmed reading scope."


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: dict) -> str:
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def source_rows() -> dict[str, dict]:
    return {row["unit_id"]: row for row in
            (json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines())}


def validate(payload: dict, lock: dict, rows: dict[str, dict], source_hash: str, dev_hash: str) -> dict:
    if (canonical(payload) != lock["contract_canonical_sha256"] or payload["version"] != lock["version"]
            or payload["source_sha256"] != source_hash or lock["source_sha256"] != source_hash
            or payload["development_goldens_sha256"] != dev_hash
            or lock["development_goldens_sha256"] != dev_hash):
        raise ValueError("Frozen contract/source/development snapshot changed; use an explicit new version")
    tasks, seen_ids, seen_variants, unit_groups = payload["tasks"], set(), set(), {}
    counts = Counter()
    for task in tasks:
        task_id, group = task["task_id"], task["split_group"]
        if task_id in seen_ids or lock["task_groups"].get(task_id) != group:
            raise ValueError("Duplicate task or changed split group")
        seen_ids.add(task_id)
        if task["split"] != "prospective_holdout_candidate" or len(task["variants"]) != 2:
            raise ValueError("Two variants must remain in the same prospective group")
        for variant in task["variants"]:
            vid = variant["variant_id"]
            if (vid in seen_variants or variant["split_group"] != group
                    or sha(variant["text"].encode()) != lock["variant_sha256"].get(vid)):
                raise ValueError("Variant changed or leaked across split groups")
            seen_variants.add(vid)
        if task["work_id"] != "wandering_earth" or type(task["max_order"]) is not int or not 0 < task["max_order"] <= 108:
            raise ValueError("Invalid reading scope")
        required = task["necessary_unit_candidates"]
        checked = [item["unit_id"] for item in task["evidence_checks"]]
        if set(required) != set(checked) or len(required) != len(set(required)):
            raise ValueError("Necessary candidates lack original-text checks")
        for uid in required + task["optional_units"]:
            if uid not in rows or not 0 < rows[uid]["order"] <= task["max_order"]:
                raise ValueError("Evidence exceeds reading boundary")
            if uid in unit_groups and unit_groups[uid] != group:
                raise ValueError("Shared original evidence crosses event-family groups")
            unit_groups[uid] = group
        for item in task["evidence_checks"]:
            row, start, end = rows[item["unit_id"]], item["char_start"], item["char_end"]
            text = row["text"]
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                    or sha(text.encode()) != item["raw_text_sha256"]
                    or sha(text[start:end].encode()) != item["span_sha256"]
                    or item["order"] != row["order"]
                    or item["source_line_range"] != [row["start_line"], row["end_line"]]
                    or not any(char.isalnum() for char in text[start:end])):
                raise ValueError("Original evidence hash/span invalid or separator-only")
        memory = task["reader_memory_fixture"]
        if any(record["anchor_order"] > task["max_order"] for record in memory["records"]):
            raise ValueError("Reader memory fixture exceeds reading boundary")
        if task["annotation_status"] == "missing_reader_memory":
            if required or memory["available"] or memory["records"] or task["expected_sources"] != ["reader_memory"]:
                raise ValueError("Missing reader memory must not be replaced by story gold")
        elif task["annotation_status"] != "source_checked_pending_independent_review" or not required:
            raise ValueError("Unreviewed literary labels cannot become formal gold")
        if not task["counter_or_unknown"] or len(task["navigation_requests"]) > 2:
            raise ValueError("Task lacks limits or exceeds navigation lookup contract")
        counts[task["annotation_status"]] += 1
    if seen_ids != lock["task_groups"].keys() or seen_variants != lock["variant_sha256"].keys():
        raise ValueError("Frozen task/variant set differs")
    return {"tasks": len(tasks), "questions": len(seen_variants),
            "event_groups": len({task["split_group"] for task in tasks}),
            "statuses": dict(counts), "original_span_checks": sum(len(task["evidence_checks"]) for task in tasks),
            "formal_independently_reviewed_gold": 0}


def question_input(task: dict, variant: dict) -> dict:
    """Only pre-existing reader context is visible; no evidence or answer labels."""
    if variant not in task["variants"]:
        raise ValueError("Variant does not belong to task")
    memory = task["reader_memory_fixture"]
    visible_memory = {"origin": memory["origin"], "available": memory["available"],
                      "records": [{key: record[key] for key in
                                   ("fixture_id", "anchor_order", "content", "status") if key in record}
                                  for record in memory["records"]]}
    return {"question": variant["text"], "visible_context": task["visible_context"],
            "reader_memory_fixture": visible_memory,
            "work_id": task["work_id"], "max_order": task["max_order"]}


def reranker_pair(query: str, evidence: dict, *, max_order: int) -> str:
    if (not query.strip() or evidence.get("work_id") != "wandering_earth"
            or type(evidence.get("order")) is not int or not 0 < evidence["order"] <= max_order
            or not isinstance(evidence.get("raw_text"), str) or not evidence["raw_text"].strip()):
        raise ValueError("Unsafe reranker pair")
    return f"<Instruct>: {INSTRUCTION}\n<Query>: {query}\n<Document>: {evidence['raw_text']}"


def rerank_scored(ids: list[str], scores: dict[str, float]) -> list[str]:
    """Contract only: accepts externally produced scores, never fabricates them."""
    if (len(ids) > 10 or len(ids) != len(set(ids)) or set(ids) != scores.keys()
            or any(type(score) not in (float, int) or not math.isfinite(score) for score in scores.values())):
        raise ValueError("Scores must cover the same distinct Top10 candidate pool")
    return sorted(ids, key=lambda uid: (-scores[uid], ids.index(uid)))


def model_files(path: Path = MODEL) -> dict:
    needed = ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "README.md")
    files = {name: {"exists": (path / name).is_file(),
                    "bytes": (path / name).stat().st_size if (path / name).is_file() else None} for name in needed}
    config = json.loads((path / "config.json").read_text(encoding="utf-8")) if files["config.json"]["exists"] else {}
    header_ok, tensor_count = False, None
    if files["model.safetensors"]["exists"]:
        with (path / "model.safetensors").open("rb") as stream:
            length = struct.unpack("<Q", stream.read(8))[0]
            if not 0 < length < 2_000_000:
                raise ValueError("Unexpected safetensors header size")
            header = json.loads(stream.read(length))
        tensors = [value for name, value in header.items() if name != "__metadata__"]
        payload_bytes = files["model.safetensors"]["bytes"] - 8 - length
        header_ok = all(0 <= value["data_offsets"][0] <= value["data_offsets"][1] <= payload_bytes for value in tensors)
        tensor_count = len(tensors)
    versions = {}
    for package in ("transformers", "torch", "sentence-transformers", "safetensors"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return {"model": "Qwen/Qwen3-Reranker-0.6B", "local_path": str(path), "files": files,
            "architectures": config.get("architectures"), "configured_dtype": config.get("torch_dtype"),
            "safetensors_header_offsets_valid": header_ok, "tensor_count": tensor_count,
            "installed_package_metadata": versions, "loaded": False, "inference_pairs": 0,
            "note": "File/header/dependency metadata only; no complete weight checksum, compatibility or CPU runtime verified."}


def structure_probe(tasks: list[dict], rows: dict[str, dict]) -> list[dict]:
    sys.path.insert(0, str(CHATBOT_SRC))
    sys.path.insert(0, str(PIPELINE))
    from storypal_chatbot.story_memory import PipelineStoryMemoryBackend, StoryMemoryService
    service = StoryMemoryService(PipelineStoryMemoryBackend(data_root=DATA, pipeline_code_path=PIPELINE, retrieval="fts"))
    results = []
    for task in tasks:
        ids, lookups = set(), []
        for request in task["navigation_requests"]:
            history = service.structured_context(kind=request["kind"], query=request["query"],
                                                work_id=task["work_id"], max_seen_order=task["max_order"])
            entries = history.get("history", [])
            for entry in entries:
                if (entry["unit_id"] not in rows or rows[entry["unit_id"]]["order"] != entry["order"]
                        or not 0 < entry["order"] <= task["max_order"]):
                    raise ValueError("Structured history unit provenance crosses scope")
            found = sorted({entry["unit_id"] for entry in entries})
            ids.update(found)
            lookups.append({"kind": request["kind"], "query": request["query"],
                            "records": len(entries), "unit_ids": found,
                            "origin": request["origin"]})
        needed = set(task["necessary_unit_candidates"])
        checked = []
        # Gold-directed availability check, never a claimed Agent route/Recall result.
        for uid in sorted(needed & ids):
            raw = service.get_evidence(work_id=task["work_id"], unit_id=uid, max_seen_order=task["max_order"])
            if sha(raw["raw_text"].encode()) != sha(rows[uid]["text"].encode()):
                raise ValueError("History-to-original lookup differs from source")
            checked.append(uid)
        results.append({"task_id": task["task_id"], "max_order": task["max_order"],
                        "lookups": lookups, "available_required_ids": sorted(needed & ids),
                        "required_not_named_by_history": sorted(needed - ids),
                        "raw_lookup_checked_ids": checked,
                        "note": "Manual exact names plus gold-directed reachability; not retrieval quality, budgeted selection or a real Agent trace."})
    return results


def cache_check(tasks: list[dict]) -> dict:
    files = [RUNTIME / "29-raw-vector.json", RUNTIME / "29-gold-vector.json",
             RUNTIME / "isolated/sol-luna-20261003-01/batch-audit.json"]
    cached = set()
    for file in files:
        report = json.loads(file.read_text(encoding="utf-8"))
        for row in report["cases"]:
            if row.get("query_sha256"):
                cached.add((row["query_sha256"], row["max_order"]))
    story = [(task, variant) for task in tasks if task["necessary_unit_candidates"] for variant in task["variants"]]
    matches = [variant["variant_id"] for task, variant in story if (sha(variant["text"].encode()), task["max_order"]) in cached]
    return {"story_questions": len(story), "exact_existing_dense_cache_matches": matches,
            "new_dense_queries_executed": 0, "new_sparse_queries_executed": 0,
            "ranking_results": "not_available_for_new_questions"}


def preflight() -> dict:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    rows = source_rows()
    result = {"schema": "prospective-understanding-preflight@1", "device": "cpu",
              "contract_canonical_sha256": canonical(payload),
              "contract_counts": validate(payload, lock, rows, sha(SOURCE.read_bytes()), sha(GOLDENS.read_bytes())),
              "cache_availability": cache_check(payload["tasks"]),
              "reranker_availability": model_files(),
              "structure_interface_checks": structure_probe(payload["tasks"], rows),
              "new_model_requests": 0, "embedding_loads": 0, "neural_reranker_loads": 0}
    if any(name in sys.modules for name in ("torch", "sentence_transformers", "transformers", "openai")):
        raise RuntimeError("Preflight unexpectedly imported neural/provider libraries")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path = args.output.resolve()
    if not path.is_relative_to(RUNTIME.resolve()) or path.exists():
        parser.error("Use a new output file in the isolated experiment runtime")
    ledger = RUNTIME / "isolated/sol-luna-20261003-01/requests.jsonl"
    before = sha(ledger.read_bytes())
    result = preflight()
    if sha(ledger.read_bytes()) != before:
        raise RuntimeError("Previous model request ledger changed")
    result["unchanged_previous_request_ledger_sha256"] = before
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"counts": result["contract_counts"], "cache": result["cache_availability"],
                      "model_files_present": all(value["exists"] for value in result["reranker_availability"]["files"].values()),
                      "history_missing": {row["task_id"]: row["required_not_named_by_history"]
                                          for row in result["structure_interface_checks"] if row["required_not_named_by_history"]}},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
