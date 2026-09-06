# StoryPal 工具白名单补丁

- 上游：HKUDS/nanobot，固定 commit `9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`。
- 原因：原生 `tools` 配置只能逐类关闭 Web、命令、文件等工具；cron、子 Agent、跨会话消息与目标管理等核心工具仍会注册并暴露给模型。
- 改动：为 `ToolsConfig` 加入可选 `allowedTools`。未配置时保持 nanobot 默认行为；配置列表时，每轮对话在模型请求前只保留该列表中的工具，因此未授权工具既不出现在模型的函数定义中，也不能由该轮调用。
- StoryPal 当前白名单：`story_state`、`search_story`、`get_story_evidence`、`read_notes`、`write_note`。
- 回放：在 `.reference/nanobot` 检出上述 commit 后应用 `storypal-tool-allowlist.patch`，再在 `storypal-chatbot` Conda 环境执行 `python -m pip install --no-deps --editable D:\StoryPal\.reference\nanobot`，最后重启 gateway。
- 回归：`python -m pytest chatbot_tests/test_nanobot_tool_allowlist.py -q -p no:cacheprovider`。测试以假模型截取实际每轮传给 AgentRunner 的注册表，断言只包含上述五个工具，不发起网络或模型请求。