"""15次合成验收预算与阶段调度：离线替身，不读取认证。"""
from types import SimpleNamespace

import pytest
import manual_memory_acceptance as batch
import manual_journal_recheck as guard


def test_preflight_fixed_roles_and_persistent_total():
    assert list(batch.STAGES.values()).count("gpt-6-luna") == 12
    assert list(batch.STAGES.values()).count("gpt-6-sol") == 3
    batch.preflight()


@pytest.mark.asyncio
async def test_failed_transport_is_counted_and_cannot_be_resent(tmp_path, monkeypatch):
    import nanobot.providers.openai_codex_provider as module
    calls = []
    async def failing(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("合成网络失败")
    monkeypatch.setattr(module, "_request_codex", failing)
    budget = batch.Budget(tmp_path / "ledger.jsonl")
    st, at = guard.STAGE.set("C1-archive"), guard.ATTEMPT.set({"sent": False})
    try:
        with guard.transport(budget):
            with pytest.raises(RuntimeError, match="合成网络失败"):
                await module._request_codex(module.DEFAULT_CODEX_URL, {}, {"model": "gpt-6-luna"})
            guard.ATTEMPT.set({"sent": False})
            with pytest.raises(RuntimeError, match="超额"):
                await module._request_codex(module.DEFAULT_CODEX_URL, {}, {"model": "gpt-6-luna"})
        assert len(calls) == batch.Budget(budget.path).total == 1
    finally:
        guard.STAGE.reset(st)
        guard.ATTEMPT.reset(at)


@pytest.mark.asyncio
async def test_logical_extra_call_is_rejected_before_provider(tmp_path, monkeypatch):
    stages = []
    async def fake(**kwargs):
        stages.append(guard.STAGE.get())
        return "替身完成"
    monkeypatch.setattr(guard, "provider", lambda root: SimpleNamespace(chat=fake))
    model = batch.routed_provider(tmp_path)
    async def two_calls():
        assert await model.chat() == "替身完成"
        with pytest.raises(RuntimeError, match="禁止追加"):
            await model.chat()
    await batch.within(["C3-pause"], two_calls)
    assert stages == ["C3-pause"]
    with pytest.raises(RuntimeError, match="禁止追加"):
        await model.chat()
