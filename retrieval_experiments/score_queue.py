"""Strict score identities and resumable CPU pilot; prepare never imports models."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import time

from . import cpu_routes as cpu
from .holdout_contract import INSTRUCTION, canonical, reranker_pair, rerank_scored
from .cache_audit import CACHE

PREFIX = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
SETTINGS = {"device": "cpu", "dtype": "float32", "attention": "eager", "batch_size": 1,
            "threads": 2, "max_length": 4096, "use_cache": False, "logits_to_keep": 1,
            "score": "softmax(no,yes)[yes]"}
BUDGET = {"attempts": 600, "seconds": 1200, "single_seconds": 20, "rss_bytes": 12 * 1024 ** 3}
GLOBAL_JOURNAL = cpu.RUNTIME / "qwen-expanded-20261004.events.jsonl"


def stream_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def model_identity():
    names = ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
             "vocab.json", "merges.txt", "chat_template.jinja")
    missing = [n for n in names if not (cpu.QWEN / n).is_file()]
    if missing:
        raise FileNotFoundError("No download permitted, missing local files: " + ",".join(missing))
    versions = {name: importlib.metadata.version(name) for name in ("torch", "transformers")}
    return {"model": "Qwen/Qwen3-Reranker-0.6B", "files": {n: stream_sha(cpu.QWEN / n) for n in names},
            "installed_versions": versions}


def identity(query, evidence, scope, model_sha):
    cpu.safe_ids([evidence["unit_id"]], scope, {evidence["unit_id"]: evidence})
    return {"query_sha256": hashlib.sha256(query.encode()).hexdigest(),
            "document_sha256": hashlib.sha256(evidence["raw_text"].encode()).hexdigest(),
            "work_id": evidence["work_id"], "unit_id": evidence["unit_id"], "max_order": scope,
            "model_sha256": model_sha,
            "prompt_sha256": canonical({"prefix": PREFIX, "instruction": INSTRUCTION, "suffix": SUFFIX, "settings": SETTINGS})}


def verify_cached(record, expected):
    if record.get("identity") != expected or record.get("key") != canonical(expected):
        raise ValueError("Score query/document/model/prompt identity differs or legacy proof missing")
    if type(record.get("score")) not in (float, int) or not math.isfinite(record["score"]) or not 0 <= record["score"] <= 1:
        raise ValueError("Score is not a finite yes probability")
    return record["score"]


class Journal:
    def __init__(self, path, queue_sha):
        self.path, self.queue_sha = Path(path), queue_sha
        if not self.path.exists():
            self.append({"event": "header", "queue_sha256": queue_sha, "budget": BUDGET})
        if self.read()[0] != {"event": "header", "queue_sha256": queue_sha, "budget": BUDGET}:
            raise ValueError("Budget journal bound to another queue or changed limits")

    def read(self):
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def append(self, event):
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def state(self):
        events = self.read()
        begun = {e["attempt"]: e for e in events if e["event"] == "begin"}
        ended = {e["attempt"]: e for e in events if e["event"] == "end"}
        pending = set(begun) - set(ended)
        # Unknown interrupted inference duration spends the entire time ceiling.
        seconds = BUDGET["seconds"] if pending else sum(e["seconds"] for e in ended.values())
        return {"attempts": len(begun), "seconds": seconds, "pending_attempts": sorted(pending),
                "stop_seen": any(e["event"] == "stop" for e in events)}

    def begin(self, key):
        state = self.state()
        if state["pending_attempts"] or state["stop_seen"] or state["attempts"] >= BUDGET["attempts"] or state["seconds"] + BUDGET["single_seconds"] > BUDGET["seconds"]:
            raise RuntimeError("Persistent score budget exhausted/interrupted; cannot reset")
        attempt = state["attempts"] + 1
        self.append({"event": "begin", "attempt": attempt, "key": key, "started_at": time.time()})
        return attempt

    def end(self, attempt, seconds, rss, *, error=None):
        state = self.state()
        if state["pending_attempts"] != [attempt] or seconds < 0 or not math.isfinite(seconds):
            raise ValueError("Unexpected attempt completion")
        self.append({"event": "end", "attempt": attempt, "seconds": seconds, "rss_bytes": rss, "error": error})
        state = self.state()
        if seconds > BUDGET["single_seconds"] or state["seconds"] >= BUDGET["seconds"] or rss > BUDGET["rss_bytes"] or error:
            self.append({"event": "stop", "attempt": attempt, "reason": "time_memory_or_error"})
        return self.state()


def prepare():
    from .cached_context_pack import source_evidence
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    if cache["source_sha256"] != cpu.digest(cpu.SOURCE):
        raise ValueError("Cache source differs")
    model = model_identity()
    model_sha = canonical(model)
    evidence = source_evidence()
    source_cases = {c["case_id"]: c for c in cpu.cases()}
    pairs = []
    case_plan = []
    for r in cache["configurations"]["dense"]["cases"]:
        if r["set"] not in ("prospective", "development") or r["decision"] != "search":
            continue
        c = source_cases[r["case_id"]]
        if hashlib.sha256(c["query"].encode()).hexdigest() != r["query_sha256"] or c["max_order"] != r["max_order"]:
            raise ValueError("Queue query/scope changed")
        case_plan.append({"case_id": c["case_id"], "set": c["set"], "candidate_units": r["candidate_units"]})
        for uid in r["candidate_units"]:
            ident = identity(c["query"], evidence[uid], c["max_order"], model_sha)
            pairs.append({"case_id": c["case_id"], "unit_id": uid, "identity": ident, "key": canonical(ident)})
    if len(pairs) > BUDGET["attempts"]:
        raise ValueError("Queue exceeds package ceiling")
    return {"schema": "qwen-cpu-expanded-queue@1", "source_sha256": cpu.digest(cpu.SOURCE),
            "ranking_cache_sha256": cpu.digest(CACHE), "model_identity": model, "model_sha256": model_sha,
            "settings": SETTINGS, "budget": BUDGET, "pairs": pairs, "cases": case_plan, "batch_pairs": 100,
            "legacy_pilot_disposition": "100 scores lack full model hash; not reused in this strict queue",
            "model_loaded": False, "new_provider_requests": 0}


def run(queue_path, output, batch_index, resource_window_clear):
    if not resource_window_clear:
        raise RuntimeError("WebUI acceptance window not released; keep model-free work only")
    from .cached_context_pack import source_evidence
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    if (queue["source_sha256"] != cpu.digest(cpu.SOURCE) or queue["ranking_cache_sha256"] != cpu.digest(CACHE)
            or queue["settings"] != SETTINGS or queue["budget"] != BUDGET
            or canonical(model_identity()) != queue["model_sha256"]):
        raise ValueError("Queue/config/checkpoint changed")
    evidence = source_evidence()
    cases = {c["case_id"]: c for c in cpu.cases()}
    for pair in queue["pairs"]:
        expected = identity(cases[pair["case_id"]]["query"], evidence[pair["unit_id"]],
                            cases[pair["case_id"]]["max_order"], queue["model_sha256"])
        if pair["identity"] != expected or pair["key"] != canonical(expected):
            raise ValueError("Queued pair provenance changed")
    journal = Journal(GLOBAL_JOURNAL, stream_sha(queue_path))
    if journal.state()["pending_attempts"] or journal.state()["stop_seen"]:
        raise RuntimeError("Interrupted/stopped package cannot restart scoring")
    score_path = queue_path.with_suffix(".scores.jsonl")
    score_records = {}
    if score_path.exists():
        for line in score_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            score_records[record["key"]] = record
    start_index = batch_index * 100
    batch = queue["pairs"][start_index:start_index + 100]
    if not batch:
        raise ValueError("No pairs for batch")
    cpu.cpu_environment()
    os.environ.update(OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    torch.set_num_threads(2)
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(str(cpu.QWEN), local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(str(cpu.QWEN), local_files_only=True,
                                               torch_dtype=torch.float32, attn_implementation="eager").to("cpu").eval()
    if any(p.device.type != "cpu" for p in model.parameters()) or cpu.memory_stats()["rss_bytes"] > BUDGET["rss_bytes"]:
        raise RuntimeError("Load violates CPU or memory ceiling")
    prefix_ids, suffix_ids = [tokenizer.encode(text, add_special_tokens=False) for text in (PREFIX, SUFFIX)]
    no, yes = tokenizer.encode("no", add_special_tokens=False), tokenizer.encode("yes", add_special_tokens=False)
    if len(no) != 1 or len(yes) != 1:
        raise ValueError("yes/no not single tokens")
    report = {"batch_index": batch_index, "load_ms": (time.perf_counter() - started) * 1000,
              "load_memory": cpu.memory_stats(), "completed": [], "skipped": [], "reuse": 0}
    for pair in batch:
        key, uid, case = pair["key"], pair["unit_id"], cases[pair["case_id"]]
        if key in score_records:
            verify_cached(score_records[key], pair["identity"])
            report["reuse"] += 1
            continue
        encoded = prefix_ids + tokenizer.encode(reranker_pair(case["query"], evidence[uid], max_order=case["max_order"]),
                                                add_special_tokens=False) + suffix_ids
        if len(encoded) > SETTINGS["max_length"]:
            report["skipped"].append({"key": key, "reason": "too_long_no_truncation", "tokens": len(encoded)})
            continue
        attempt = journal.begin(key)
        begin = time.perf_counter()
        error = None
        try:
            tokens = torch.tensor([encoded], device="cpu")
            with torch.inference_mode():
                logits = model(input_ids=tokens, attention_mask=torch.ones_like(tokens),
                               use_cache=False, logits_to_keep=1).logits[0, -1, :]
                score = torch.softmax(torch.stack([logits[no[0]], logits[yes[0]]]).float(), dim=0)[1].item()
            record = {"key": key, "identity": pair["identity"], "score": score, "tokens": len(encoded),
                      "inference_ms": (time.perf_counter() - begin) * 1000}
            verify_cached(record, pair["identity"])
            with score_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record) + "\n"); stream.flush(); os.fsync(stream.fileno())
            score_records[key] = record
            report["completed"].append(record)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        state = journal.end(attempt, time.perf_counter() - begin, cpu.memory_stats()["rss_bytes"], error=error)
        print(f"CPU pair {attempt}, {pair['case_id']} {uid}", flush=True)
        if state["stop_seen"]:
            break
    report["budget_state"] = journal.state()
    report["memory"] = cpu.memory_stats()
    report["cuda_initialized"] = torch.cuda.is_initialized()
    if report["cuda_initialized"]:
        raise RuntimeError("CUDA initialized")
    # Model process exits after this batch; no persistent worker.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)


def analyze(queue_path):
    from .cached_context_pack import source_evidence, terms
    from .cache_audit import MODES, select, packing_metrics
    from .sparse import _jieba
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    if (queue["source_sha256"] != cpu.digest(cpu.SOURCE) or queue["ranking_cache_sha256"] != cpu.digest(CACHE)
            or queue["settings"] != SETTINGS or queue["budget"] != BUDGET
            or canonical(model_identity()) != queue["model_sha256"]):
        raise ValueError("Analysis queue/source/checkpoint changed")
    score_path = queue_path.with_suffix(".scores.jsonl")
    records = {r["key"]: r for r in map(json.loads, score_path.read_text(encoding="utf-8").splitlines())} if score_path.exists() else {}
    expected_pairs = {(p["case_id"], p["unit_id"]): p for p in queue["pairs"]}
    cases = {c["case_id"]: c for c in cpu.cases()}
    evidence = source_evidence()
    import sys
    sys.path.insert(0, str(cpu.CHATBOT_SRC))
    from storypal_chatbot.context_packer import ContextPacker
    packer = ContextPacker()
    tokenizer = _jieba()
    reports = {}
    for pool_k in (5, 10):
        for mode in MODES:
            rows, incomplete = [], []
            for planned in queue["cases"]:
                c = cases[planned["case_id"]]
                pool, scores = planned["candidate_units"][:pool_k], {}
                for uid in pool:
                    p = expected_pairs[(c["case_id"], uid)]
                    expected = identity(c["query"], evidence[uid], c["max_order"], queue["model_sha256"])
                    if p["identity"] != expected or p["key"] != canonical(expected):
                        raise ValueError("Queued analysis identity differs")
                    if p["key"] in records:
                        scores[uid] = verify_cached(records[p["key"]], expected)
                if set(scores) != set(pool) or not pool:
                    incomplete.append(c["case_id"])
                    continue
                ranked = rerank_scored(pool, scores)
                selected, tokens, drops = select(ranked, evidence, c["query"], mode, packer,
                                                 lambda text: terms(text, tokenizer))
                required = set(c["required_units"])
                rows.append({"case_id": c["case_id"], "task_id": c["task_id"], "set": c["set"],
                             "group": c["group"], "eligible": bool(required),
                             "packed_joint": required.issubset(selected) if required else None,
                             "packed_units": selected, "candidate_units": ranked, "tokens": tokens,
                             "drops": drops, "separator_only": [u for u in selected if not any(x.isalnum() for x in evidence[u]["raw_text"])],
                             "raw_duplicates_selected": False})
            reports[f"top{pool_k}/{mode}"] = {"summary": packing_metrics(rows), "cases": rows,
                                             "incomplete_cases": incomplete}
    if any(n in sys.modules for n in ("torch", "transformers", "sentence_transformers")):
        raise RuntimeError("Score cache analysis unexpectedly loaded neural libraries")
    return {"schema": "expanded-qwen-cache-analysis@1", "strict_scores_available": len(records),
            "planned_pairs": len(queue["pairs"]), "new_neural_pairs_in_analysis": 0,
            "configurations": reports, "note": "Incomplete pools are not scored as failures or successes."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=("prepare", "run", "analyze"))
    p.add_argument("--queue", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--batch-index", type=int, default=0)
    p.add_argument("--resource-window-clear", action="store_true")
    a = p.parse_args()
    output = a.output.resolve()
    if not output.is_relative_to(cpu.RUNTIME.resolve()) or output.exists():
        p.error("Use a new isolated output file")
    if a.phase == "prepare":
        before = cpu.digest(cpu.LEDGER)
        result = prepare()
        if before != cpu.digest(cpu.LEDGER):
            raise RuntimeError("Previous provider ledger changed")
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(json.dumps({"cases": len(result["cases"]), "pairs": len(result["pairs"]), "loaded": False}))
    elif a.phase == "analyze":
        if not a.queue or not a.queue.resolve().is_relative_to(cpu.RUNTIME.resolve()):
            p.error("Analysis requires isolated queue")
        result = analyze(a.queue)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(json.dumps({"scores_available": result["strict_scores_available"], "planned": result["planned_pairs"]}))
    else:
        if not a.queue or not a.queue.resolve().is_relative_to(cpu.RUNTIME.resolve()) or a.batch_index < 0:
            p.error("Run needs isolated queue and nonnegative batch")
        run_lock = GLOBAL_JOURNAL.with_suffix(".lock")
        try:
            fd = os.open(run_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError("Another score run/unchecked interrupted lock exists; do not clear automatically")
        os.close(fd)
        try:
            run(a.queue, output, a.batch_index, a.resource_window_clear)
        except Exception as exc:
            if not output.exists():
                with output.open("x", encoding="utf-8") as stream:
                    json.dump({"schema": "expanded-score-failure@1", "error_type": type(exc).__name__,
                               "error": str(exc), "queue_sha256": stream_sha(a.queue)}, stream, ensure_ascii=False, indent=2)
            raise
        finally:
            run_lock.unlink()


if __name__ == "__main__":
    main()
