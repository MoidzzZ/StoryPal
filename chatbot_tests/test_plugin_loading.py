from nanobot.agent.tools.loader import ToolLoader


def test_all_storypal_tools_are_discoverable():
    plugins = ToolLoader()._discover_plugins()

    assert set(plugins) >= {"story_state", "read_notes", "write_note"}
