"""真实验收入口的预算回归：仅替身传输，不读取凭据或联网。"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("manual_recheck", Path(__file__).with_name("manual_journal_recheck.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_budget_preflight_is_offline_and_persistent():
    runner.preflight()


@pytest.mark.asyncio
async def test_transport_scope_endpoint_resend_and_two_request_cap(tmp_path, monkeypatch):
    import nanobot.providers.openai_codex_provider as module
    sent = []
    async def fake(url, headers, body, *args, **kwargs):
        sent.append(body)
        return SimpleNamespace(finish_reason="stop", usage=None)
    monkeypatch.setattr(module, "_request_codex", fake)
    budget = runner.Budget(tmp_path / "ledger.jsonl")
    st, at = runner.STAGE.set("recheck"), runner.ATTEMPT.set({"sent": False})
    body = {"model": "gpt-6-luna"}
    try:
        with runner.transport(budget):
            with pytest.raises(RuntimeError):
                await module._request_codex("https://unapproved.invalid", {}, body)
            assert budget.total == 0 and not sent
            await module._request_codex(module.DEFAULT_CODEX_URL, {}, body)
            with pytest.raises(RuntimeError):
                await module._request_codex(module.DEFAULT_CODEX_URL, {}, body)
            runner.ATTEMPT.set({"sent": False})
            with pytest.raises(RuntimeError):
                await module._request_codex(module.DEFAULT_CODEX_URL, {}, body)
            runner.STAGE.set("continuation")
            await module._request_codex(module.DEFAULT_CODEX_URL, {}, body)
            runner.ATTEMPT.set({"sent": False})
            with pytest.raises(RuntimeError):
                await module._request_codex(module.DEFAULT_CODEX_URL, {}, body)
        assert len(sent) == runner.Budget(budget.path).total == 2
        assert module._request_codex is fake
    finally:
        runner.STAGE.reset(st)
        runner.ATTEMPT.reset(at)
