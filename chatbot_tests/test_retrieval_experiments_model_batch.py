import pytest

from retrieval_experiments.model_batch import ATTEMPT, SCOPE, RequestBudget, run_path, user_prompt
from retrieval_experiments.replay import RUNTIME


def request(budget, case="R14", role="role", model="gpt-6-luna", attempt=None):
    scope = SCOPE.set((case, role))
    marker = ATTEMPT.set({"sent": False} if attempt is None else attempt)
    try:
        return budget.admit(model, {"model": model})
    finally:
        ATTEMPT.reset(marker)
        SCOPE.reset(scope)


def test_persisted_role_budget_counts_failures_and_cannot_reset_on_resume(tmp_path):
    path = tmp_path / "ledger.jsonl"
    budget = RequestBudget(path)
    for i in range(3):
        assert request(budget) == i + 1
        budget.append({"event": "end", "request_no": i + 1, "status": "failed"})
    resumed = RequestBudget(path)
    with pytest.raises(RuntimeError, match="exhausted"):
        request(resumed)
    assert resumed.total == 3


def test_transport_resend_and_wrong_model_are_rejected_before_counting(tmp_path):
    budget = RequestBudget(tmp_path / "ledger.jsonl")
    attempt = {"sent": False}
    request(budget, attempt=attempt)
    with pytest.raises(RuntimeError, match="resend"):
        request(budget, attempt=attempt)
    with pytest.raises(RuntimeError, match="Unapproved"):
        request(budget, model="gpt-6-sol")
    assert budget.total == 1


def test_total_budget_and_sol_one_request_limit(tmp_path):
    budget = RequestBudget(tmp_path / "ledger.jsonl")
    from retrieval_experiments.model_batch import CASES
    for case in CASES:
        request(budget, case, "user", "gpt-6-sol")
        for _ in range(3):
            request(budget, case)
    assert budget.total == 24
    with pytest.raises(RuntimeError, match="exhausted"):
        request(budget, "R14", "user", "gpt-6-sol")


def test_generation_prompt_has_no_gold_fields_and_run_cannot_read_live_sessions():
    prompt = user_prompt({"raw_user": "甲为什么变冷？", "visible_context": "只给问题",
                          "required_units": ["secret-unit"], "gold_rewrite": "secret-rewrite",
                          "source_route": "secret-route"})
    assert not any("secret" in item["content"] for item in prompt)
    assert run_path(RUNTIME / "isolated" / "approved") == (RUNTIME / "isolated" / "approved").resolve()
    with pytest.raises(ValueError, match="isolated"):
        run_path(RUNTIME / "live-sessions")


@pytest.mark.asyncio
async def test_isolated_native_loop_saves_scope_and_has_only_read_only_story_tools(tmp_path):
    from nanobot.providers.base import LLMProvider, LLMResponse
    from retrieval_experiments.model_batch import build_loop, selected_cases
    from storypal_chatbot.query_capture import IsolatedQueryCapture, export_query

    class Stub(LLMProvider):
        def __init__(self):
            super().__init__(provider_name="test")
            self.calls = 0

        def get_default_model(self):
            return "openai-codex/gpt-6-luna"

        async def chat(self, messages, **kwargs):
            self.calls += 1
            assert "用户已确认阅读状态" in messages[-1]["content"]
            return LLMResponse(content="隔离接线验证，不算真实模型结果", finish_reason="stop")

    root = tmp_path / "experiments"
    batch = root / "isolated" / "test"
    provider = Stub()
    case = selected_cases()[0]
    loop, key, owner, service = build_loop(batch, case, provider)
    capture = IsolatedQueryCapture(case_id=case["case_id"], session_key=key, root=root)
    try:
        assert set(loop.tools.tool_names) == {"search_story", "story_context", "get_story_evidence"}
        await loop.process_direct("老师说的五步怎么排？", session_key=key, sender_id=owner, hooks=[capture])
        path = capture.seal(transcript=loop.sessions._get_session_path(key), output=batch / "receipt.json")
        exported = export_query(path, root=root)
        assert exported["origin"] == "synthetic" and exported["decision"] == "skip"
        assert exported["max_order"] == 26 and provider.calls == 1
    finally:
        await loop.aclose()
