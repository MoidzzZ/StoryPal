from importlib.resources import files

from nanobot.agent.context import ContextBuilder

from storypal_chatbot.bootstrap import install_persona


def test_companion_persona_is_installed_from_packaged_template(tmp_path):
    workspace = tmp_path / "workspace"
    installed = install_persona(workspace)
    soul = workspace / "SOUL.md"
    template = files("storypal_chatbot").joinpath("persona/SOUL.md").read_text(
        encoding="utf-8"
    )

    assert soul in installed
    assert soul.read_text(encoding="utf-8") == template
    assert "一起读故事的人（v0.2）" in template
    assert "<example>" in template
    assert "虚构练习" in template


def test_persona_install_preserves_existing_custom_voice(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    soul = workspace / "SOUL.md"
    soul.write_text("用户自己维护的口吻", encoding="utf-8")

    installed = install_persona(workspace)

    assert soul not in installed
    assert soul.read_text(encoding="utf-8") == "用户自己维护的口吻"


def test_context_builder_reads_updated_voice_on_next_build(tmp_path):
    install_persona(tmp_path)
    builder = ContextBuilder(tmp_path)
    first = builder.build_system_prompt(include_memory=False)

    assert "一起读故事的人（v0.2）" in first
    assert first.count("## SOUL.md") == 1

    soul = tmp_path / "SOUL.md"
    soul.write_text("# 隔轮更新的共读口吻", encoding="utf-8")
    second = builder.build_system_prompt(include_memory=False)

    assert "隔轮更新的共读口吻" in second
    assert "一起读故事的人（v0.2）" not in second

