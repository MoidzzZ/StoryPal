from __future__ import annotations

from storypal_chatbot.context_packer import (
    ContextPacker,
    DROP_DUPLICATE,
    DROP_LOWER_RELEVANCE,
    DROP_NOT_ADJACENT,
    DROP_SPOILER,
    DROP_TOKEN_BUDGET,
)


def evidence(unit_id: str, order: int, chapter: str = "第一章", text: str = "正文") -> dict:
    return {
        "work_id": "demo",
        "unit_id": unit_id,
        "order": order,
        "raw_text": text,
        "summary": f"摘要-{unit_id}",
        "score": 1.0,
        "metadata": {"chapter": chapter, "start_line": order, "end_line": order},
    }


def test_context_packer_filters_deduplicates_and_records_reasons() -> None:
    first = evidence("a", 1)
    packed = ContextPacker(token_budget=200, primary_limit=2).pack(
        [
            evidence("future", 6),
            first,
            dict(first),
            evidence("c", 3, "第二章"),
            evidence("b", 2),
            evidence("d", 4, "第三章"),
        ],
        work_id="demo",
        max_seen_order=5,
    )

    assert [item["unit_id"] for item in packed.anchors] == ["a", "c"]
    assert [item["unit_id"] for item in packed.adjacent_context] == ["b"]
    assert all(item["order"] <= 5 for item in packed.anchors + packed.adjacent_context)
    assert {item["reason"] for item in packed.dropped} == {
        DROP_SPOILER,
        DROP_DUPLICATE,
        DROP_NOT_ADJACENT,
    }
    assert packed.source_anchors[-1]["role"] == "adjacent"


def test_context_packer_stops_when_token_budget_is_exhausted() -> None:
    packed = ContextPacker(token_budget=4, chars_per_token=1).pack(
        [evidence("large", 1, text="超过预算的正文")],
        work_id="demo",
        max_seen_order=1,
    )

    assert packed.anchors == []
    assert packed.adjacent_context == []
    assert packed.token_estimate == 0
    assert packed.dropped == [{"unit_id": "large", "order": 1, "reason": DROP_TOKEN_BUDGET}]

def test_context_packer_limits_adjacent_context_to_one_low_priority_item() -> None:
    packed = ContextPacker(token_budget=200, primary_limit=1, adjacent_limit=1).pack(
        [
            evidence("anchor", 3),
            evidence("left", 2),
            evidence("right", 4),
        ],
        work_id="demo",
        max_seen_order=4,
    )

    assert [item["unit_id"] for item in packed.anchors] == ["anchor"]
    assert [item["unit_id"] for item in packed.adjacent_context] == ["left"]
    assert {item["unit_id"] for item in packed.dropped} == {"right"}
    assert packed.dropped[0]["reason"] == DROP_LOWER_RELEVANCE
