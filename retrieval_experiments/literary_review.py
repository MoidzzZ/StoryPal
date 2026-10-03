"""One P01 Luna evidence-sufficiency review within its existing three-call cap."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

from .fusion_replay import SOURCE
from .model_batch import MODELS, RequestBudget, SCOPE, count_transport, digest, provider, run_path, write_new
from .replay import PIPELINE, ROOT


async def review(root: Path) -> None:
    scope_path = root / "luna-outbound-scope.json"
    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    approval = json.loads((root / "materials-authorization.json").read_text(encoding="utf-8"))
    if (approval.get("approved") is not True or approval.get("model") != MODELS["role"]
            or approval.get("scope_sha256") != hashlib.sha256(scope_path.read_bytes()).hexdigest()
            or scope.get("source_sha256") != hashlib.sha256(SOURCE.read_bytes()).hexdigest()):
        raise ValueError("P01 review materials lack exact-scope authorization")
    allowed = next(row for row in scope["scenes"] if row["case_id"] == "P01")
    if allowed["max_order"] != 22:
        raise ValueError("P01 scope differs")
    sys.path.insert(0, str(PIPELINE))
    from storymemory.adapter import StoryMemory
    memory = StoryMemory(ROOT / "story_mem" / "data", retrieval="fts")
    sources = [memory.get_unit("wandering_earth", f"we-{number:04d}") for number in range(18, 23)]
    if any(not row or row["unit_id"] not in allowed["allowed_unit_ids"] or not 18 <= row["order"] <= 22 for row in sources):
        raise ValueError("Review source exceeds approved scope")
    question = json.loads((root / "generated" / "P01.json").read_text(encoding="utf-8"))["question"]
    messages = [{"role": "system", "content": (
        "你核验阅读问题需要哪些原文证据，不扮演用户、不补全未给出的剧情。"
        "只依据给出的已读原文判断：为了完整解释争论如何逐步展开，哪些单元是不可缺少的，"
        "哪些仅补充背景？必要集合可有不同合理选择，说明你的依据和不确定处。"
        "只输出JSON对象，字段 necessary_units（编号数组）、supplemental_units（编号数组）、"
        "reason_by_unit（编号到简短理由）、limits（说明）。不要复述长原文。")},
        {"role": "user", "content": json.dumps({"question": question,
         "read_boundary": 22, "sources": [{"unit_id": row["unit_id"], "order": row["order"],
                                              "raw_text": row["raw_text"]} for row in sources]}, ensure_ascii=False)}]
    destination = root / "P01-literary-review.json"
    if destination.exists():
        raise ValueError("Never overwrite or rerun an existing review")
    budget = RequestBudget(root / "requests.jsonl")
    if budget.counts[("P01", "role")] != 2:
        raise ValueError("P01 has no exactly-one remaining review slot")
    role = provider("role")
    token = SCOPE.set(("P01", "role"))
    try:
        with count_transport(budget):
            response = await role.chat_with_retry(messages=messages, tools=[], model=MODELS["role"],
                                                  max_tokens=1800, temperature=.1, reasoning_effort="medium")
    finally:
        SCOPE.reset(token)
    parsed = None
    validation = "failed_response"
    if response.finish_reason == "stop":
        try:
            parsed = json.loads(response.content)
            necessary, extra = parsed["necessary_units"], parsed["supplemental_units"]
            ids = necessary + extra
            valid_ids = {row["unit_id"] for row in sources}
            if (not isinstance(necessary, list) or not isinstance(extra, list) or not necessary
                    or len(ids) != len(set(ids)) or not set(ids).issubset(valid_ids)):
                raise ValueError("Invalid evidence selection")
            validation = "valid_source_ids_not_human_gold"
        except (ValueError, TypeError, KeyError):
            parsed = None
            validation = "invalid_review_format"
    write_new(destination, {"schema": "p01-literary-review@1", "model": MODELS["role"],
                           "role": "separate evidence review, not the reading companion turn",
                           "prompt_sha256": digest(messages), "source_sha256": scope["source_sha256"],
                           "supplied_units": [row["unit_id"] for row in sources],
                           "finish_reason": response.finish_reason, "validation": validation,
                           "raw_response": response.content, "review": parsed,
                           "usage": response.usage.to_dict() if response.usage else None,
                           "total_requests_used": budget.total,
                           "note": "One model's literary judgment is provisional; existing goldens are unchanged."})
    print(json.dumps({"validation": validation, "total_requests_used": budget.total,
                      "review": parsed, "usage": response.usage.to_dict() if response.usage else None}, ensure_ascii=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--execute-authorized-batch", action="store_true", required=True)
    args = parser.parse_args()
    asyncio.run(review(run_path(args.run_root)))


if __name__ == "__main__":
    main()
