"""在固定故事语料上对 BM25 与向量检索进行中文金标对照。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "story_mem" / "data"
DEFAULT_PIPELINE = ROOT / "story_mem" / "code"
DEFAULT_CASES = Path(__file__).with_name("story_retrieval_goldens.json")


def load_adapter(data_root: Path, pipeline_code: Path, retrieval: str):
    if str(pipeline_code) not in sys.path:
        sys.path.insert(0, str(pipeline_code))
    from storymemory.adapter import StoryMemory

    return StoryMemory(data_root, retrieval=retrieval)


def evaluate(adapter, cases: list[dict]) -> tuple[list[dict], dict]:
    results: list[dict] = []
    hit_at = {1: 0, 3: 0, 5: 0}
    scored_cases = 0
    violations = 0
    for case in cases:
        started = time.perf_counter()
        hits = adapter.search(
            "wandering_earth", case.get("检索查询", case["用户原话"]),
            max_order=case["阅读边界"], top_k=5,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        ids = [item["unit_id"] for item in hits]
        expected = set(case["期望单元"])
        safe = all(int(item["order"]) <= case["阅读边界"] for item in hits)
        violations += 0 if safe else 1
        row = {
            "编号": case["编号"], "类别": case["类别"], "用户原话": case["用户原话"], "检索查询": case.get("检索查询", case["用户原话"]), "阅读边界": case["阅读边界"],
            "结果单元": ids, "耗时毫秒": elapsed_ms, "防剧透通过": safe,
        }
        if expected:
            scored_cases += 1
            for limit in hit_at:
                row[f"前{limit}命中"] = bool(expected.intersection(ids[:limit]))
                hit_at[limit] += int(row[f"前{limit}命中"])
        results.append(row)
    metrics = {
        "有金标用例数": scored_cases,
        "前1命中率": round(hit_at[1] / scored_cases, 3) if scored_cases else None,
        "前3命中率": round(hit_at[3] / scored_cases, 3) if scored_cases else None,
        "前5命中率": round(hit_at[5] / scored_cases, 3) if scored_cases else None,
        "防剧透违规用例数": violations,
    }
    return results, metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--pipeline-code", type=Path, default=DEFAULT_PIPELINE)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    report = {"用例版本": "story-retrieval@0.1", "结果": {}}
    for retrieval in ("fts", "vector"):
        rows, metrics = evaluate(load_adapter(args.data_root, args.pipeline_code, retrieval), cases)
        report["结果"][retrieval] = {"指标": metrics, "用例": rows}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: value["指标"] for name, value in report["结果"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()