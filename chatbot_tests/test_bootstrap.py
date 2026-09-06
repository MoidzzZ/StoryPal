from __future__ import annotations

import json

from storypal_chatbot.bootstrap import (
    LUNA_PRESET,
    apply_storypal_defaults,
    configure,
    lock_to_codex_luna,
)


def test_defaults_are_bounded_and_preserve_provider_secret(tmp_path):
    config = {
        "agents": {"defaults": {"maxToolIterations": 200}},
        "providers": {"custom": {"apiKey": "keep-me"}},
    }

    result = apply_storypal_defaults(config, tmp_path / "workspace")

    defaults = result["agents"]["defaults"]
    assert defaults["maxToolIterations"] == 6
    assert defaults["dream"]["enabled"] is True
    assert defaults["dream"]["editableFiles"] == ["SOUL.md", "USER.md"]
    assert result["gateway"]["heartbeat"]["enabled"] is False
    assert result["tools"]["restrictToWorkspace"] is True
    assert result["tools"]["exec"]["enable"] is False
    assert result["providers"]["custom"]["apiKey"] == "keep-me"


def test_configure_installs_persona_without_overwriting_existing_file(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({}), encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SOUL.md").write_text("custom soul", encoding="utf-8")

    written = configure(config_path, workspace)

    assert (workspace / "SOUL.md").read_text(encoding="utf-8") == "custom soul"
    assert (workspace / "AGENTS.md") in written
    assert "StoryPal" in (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert '故事检索决策（由主 Agent 直接完成）' in (workspace / 'AGENTS.md').read_text(encoding='utf-8')
    assert '不新增独立的 Query Analyzer、Router 或第二次模型调用' in (workspace / 'AGENTS.md').read_text(encoding='utf-8')
    assert (workspace / "prompts" / "dream.md") in written


def test_luna_only_has_one_preset_and_no_fallbacks():
    config = {
        "agents": {
            "defaults": {
                "modelPreset": "old",
                "fallbackModels": ["other"],
            }
        },
        "modelPresets": {"old": {"model": "openai-codex/gpt-5.6-sol"}},
    }

    result = lock_to_codex_luna(config)

    assert list(result["modelPresets"]) == [LUNA_PRESET]
    preset = result["modelPresets"][LUNA_PRESET]
    assert preset["provider"] == "openai_codex"
    assert preset["model"] == "openai-codex/gpt-5.6-luna"
    defaults = result["agents"]["defaults"]
    assert defaults["modelPreset"] == LUNA_PRESET
    assert defaults["fallbackModels"] == []
    assert defaults["dream"]["modelOverride"] == LUNA_PRESET
