"""Apply the safe StoryPal prototype defaults to an existing nanobot config."""

from __future__ import annotations

import argparse
import json
from importlib.resources import files
from pathlib import Path
from typing import Any


PERSONA_FILES = (
    "AGENTS.md",
    "SOUL.md",
    "USER.md",
    "HEARTBEAT.md",
    "prompts/dream.md",
)
LUNA_PRESET = "storypal-luna"


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value


def apply_storypal_defaults(config: dict[str, Any], workspace: Path) -> dict[str, Any]:
    agents = _mapping(config, "agents")
    defaults = _mapping(agents, "defaults")
    defaults.update(
        {
            "workspace": str(workspace.resolve()),
            "maxToolIterations": 6,
            "maxConcurrentSubagents": 1,
            "botName": "StoryPal",
            "botIcon": "📖",
            "timezone": "Asia/Shanghai",
            "timezoneMode": "manual",
            "idleCompactAfterMinutes": 15,
        }
    )
    dream = _mapping(defaults, "dream")
    dream.update(
        {
            "enabled": True,
            "editableFiles": ["SOUL.md", "USER.md"],
        }
    )

    gateway = _mapping(config, "gateway")
    _mapping(gateway, "heartbeat")["enabled"] = False

    tools = _mapping(config, "tools")
    tools["allowedTools"] = ["story_state", "reading_location", "search_story", "get_story_evidence", "story_context", "read_notes", "write_note", "read_reading_notebook", "write_reading_notebook"]
    tools["restrictToWorkspace"] = True
    for key in ("exec", "file", "cliApps", "my"):
        _mapping(tools, key)["enable"] = False
    return config


def lock_to_codex_luna(config: dict[str, Any]) -> dict[str, Any]:
    """Make GPT-5.6 Luna the sole configured model with no automatic fallback."""
    config["modelPresets"] = {
        LUNA_PRESET: {
            "provider": "openai_codex",
            "model": "openai-codex/gpt-5.6-luna",
            "maxTokens": 8192,
            "contextWindowTokens": 272000,
            "temperature": 0.1,
            "reasoningEffort": "medium",
        }
    }
    defaults = _mapping(_mapping(config, "agents"), "defaults")
    defaults.update(
        {
            "modelPreset": LUNA_PRESET,
            "model": "openai-codex/gpt-5.6-luna",
            "provider": "openai_codex",
            "fallbackModels": [],
            "reasoningEffort": "medium",
        }
    )
    _mapping(defaults, "dream")["modelOverride"] = LUNA_PRESET
    return config


def install_persona(workspace: Path, *, force: bool = False) -> list[Path]:
    workspace.mkdir(parents=True, exist_ok=True)
    source_root = files("storypal_chatbot").joinpath("persona")
    written: list[Path] = []
    for name in PERSONA_FILES:
        destination = workspace / name
        if destination.exists() and not force:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source_root.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8")
        written.append(destination)
    return written


def configure(
    config_path: Path,
    workspace: Path,
    *,
    force_persona: bool = False,
    luna_only: bool = False,
) -> list[Path]:
    if not config_path.is_file():
        raise FileNotFoundError(
            f"nanobot config not found: {config_path}. Start a fresh WebUI once before configuring StoryPal."
        )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    apply_storypal_defaults(config, workspace)
    if luna_only:
        lock_to_codex_luna(config)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config_path)
    return install_persona(workspace, force=force_persona)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--force-persona", action="store_true")
    parser.add_argument(
        "--luna-only",
        action="store_true",
        help="Use OpenAI Codex OAuth with GPT-5.6 Luna and no fallback models.",
    )
    args = parser.parse_args()
    written = configure(
        args.config.resolve(),
        args.workspace.resolve(),
        force_persona=args.force_persona,
        luna_only=args.luna_only,
    )
    print(f"StoryPal defaults applied to {args.config.resolve()}")
    print(f"Persona files written: {len(written)}")


if __name__ == "__main__":
    main()
