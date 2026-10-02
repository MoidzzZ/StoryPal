# StoryPal 工具白名单补丁

- 上游：HKUDS/nanobot，固定 commit `9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`。
- 原因：原生 `tools` 配置只能逐类关闭 Web、命令、文件等工具；cron、子 Agent、跨会话消息与目标管理等核心工具仍会注册并暴露给模型。
- 改动：为 `ToolsConfig` 加入可选 `allowedTools`。未配置时保持 nanobot 默认行为；配置列表时，每轮对话在模型请求前只保留该列表中的工具，因此未授权工具既不出现在模型的函数定义中，也不能由该轮调用。
- StoryPal 当前 11 项白名单由 `chatbot/src/storypal_chatbot/bootstrap.py` 和本地配置维护；旧五工具列表只是历史回归夹具，不是现行产品清单。空列表需同时应用 [空工具注册表修复](empty-tool-registry.md)，否则后续回退可能重新暴露默认工具。
- 回放：从上述固定 commit 建立独立源码副本，按本目录 README 顺序应用所有补丁，将该副本 editable 安装到 storypal-chatbot Conda 环境并重启 gateway。本机使用 `.runtime/nanobot/source-build/`，参考工作区有历史本地改动，不应直接重置或用作运行源。
- 回归：`python -m pytest chatbot_tests/test_nanobot_tool_allowlist.py -q -p no:cacheprovider`。测试以假模型截取实际每轮传给 AgentRunner 的注册表，断言只包含上述五个工具，不发起网络或模型请求。
