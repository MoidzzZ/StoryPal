"""只测试型号配置和选择链路；不调用真实模型或读取用户资料。"""

import pytest

from nanobot.config.schema import Config
from nanobot.providers.openai_codex_provider import OPENAI_CODEX_CATALOG_CLIENT_VERSION, _parse_openai_codex_models
from nanobot.webui.settings_models import model_settings_payload, update_agent_model_settings
from storypal_chatbot.bootstrap import lock_to_codex_luna
from storypal_chatbot.model_policy import DEFAULT_MODEL, LEGACY_MODEL, LUNA_PRESET, LEGACY_LUNA_PRESET


def _oauth_status(_spec):
    return {"configured": True, "account": None, "expires_at": None, "login_supported": True}


def test_webui_exposes_two_luna_presets_and_switches_default_without_fallback():
    config = Config.model_validate(lock_to_codex_luna({}))
    payload = model_settings_payload(config, oauth_status=_oauth_status)
    visible = {item["name"]: item["model"] for item in payload["model_presets"] if not item["is_default"]}
    assert visible == {LUNA_PRESET: DEFAULT_MODEL, LEGACY_LUNA_PRESET: LEGACY_MODEL}
    assert payload["agent"]["model"] == DEFAULT_MODEL
    assert payload["model_call_order"] == [LUNA_PRESET]
    assert update_agent_model_settings(config, {"model_preset": [LEGACY_LUNA_PRESET]}, oauth_status=_oauth_status)
    assert config.resolve_preset().model == LEGACY_MODEL
    assert config.agents.defaults.fallback_models == []
    assert update_agent_model_settings(config, {"model_preset": [LUNA_PRESET]}, oauth_status=_oauth_status)
    assert config.resolve_preset().model == DEFAULT_MODEL


def test_catalog_version_and_parser_include_gpt6_luna():
    assert OPENAI_CODEX_CATALOG_CLIENT_VERSION == "0.159.2"
    models = _parse_openai_codex_models({"models": [
        {"slug": "gpt-6-luna", "visibility": "list"},
        {"slug": "gpt-5.6-luna", "visibility": "list"},
        {"slug": "private-model", "visibility": "hide"},
    ]})
    assert {model.id for model in models} == {DEFAULT_MODEL, LEGACY_MODEL}


@pytest.mark.asyncio
async def test_session_model_choice_routes_to_selected_luna_and_survives_reload(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import ToolsConfig
    from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse
    from nanobot.providers.factory import ProviderSnapshot
    from nanobot.session.model_selection import model_preset_from_metadata
    from storypal_chatbot.tools import ResolveReadingLocationTool

    class RecordingProvider(LLMProvider):
        def __init__(self, model):
            super().__init__(provider_name="openai_codex")
            self.model = model
            self.generation = GenerationSettings(max_tokens=256, temperature=0.1)
            self.calls = []

        async def chat(self, messages, tools=None, model=None, **kwargs):
            self.calls.append(model)
            return LLMResponse(content="测试回复", finish_reason="stop")

        def get_default_model(self):
            return self.model

    config = Config.model_validate(lock_to_codex_luna({}))
    providers = {name: RecordingProvider(preset.model) for name, preset in config.model_presets.items()}

    def load_preset(name):
        preset = config.model_presets[name]
        return ProviderSnapshot(provider=providers[name], model=preset.model,
                                context_window_tokens=preset.context_window_tokens,
                                signature=(name, preset.model))

    registry = ToolRegistry()
    registry.register(ResolveReadingLocationTool(tmp_path))
    loop = AgentLoop(bus=MessageBus(), provider=providers[LUNA_PRESET], workspace=tmp_path,
                     model=DEFAULT_MODEL, model_preset=LUNA_PRESET,
                     model_presets=config.model_presets, preset_snapshot_loader=load_preset,
                     tool_registry=registry,
                     tools_config=ToolsConfig(allowed_tools=["resolve_reading_location"]))
    loop.schedule_background = lambda coro: coro.close()
    session_key = "sdk:luna-selection-test"
    try:
        loop.set_session_model_preset(session_key, LEGACY_LUNA_PRESET)
        assert (await loop.process_direct("仅核验路由", session_key=session_key)).content == "测试回复"
        loop.sessions.invalidate(session_key)
        assert model_preset_from_metadata(loop.sessions.get_or_create(session_key).metadata) == LEGACY_LUNA_PRESET
        loop.set_session_model_preset(session_key, LUNA_PRESET)
        await loop.process_direct("切回默认型号", session_key=session_key)
        assert providers[LEGACY_LUNA_PRESET].calls == [LEGACY_MODEL]
        assert providers[LUNA_PRESET].calls == [DEFAULT_MODEL]
    finally:
        await loop.aclose()
