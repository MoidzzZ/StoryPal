# nanobot 补丁

本目录只保留可重放的 nanobot 最小补丁及说明。目前有四组：

- `storypal-persona-view.patch` / `persona-view.md`：网页只读浏览 `SOUL.md`、`AGENTS.md`、`USER.md`；
- `storypal-dream-write-allowlist.patch` / `dream-write-allowlist.md`：限制 Dream 的持久文件写入；
- `storypal-tool-allowlist.patch` / `tool-allowlist.md`：按配置收紧每轮可见工具；
- `storypal-reader.patch` / `reader.md`：桌面阅读器、鉴权原文接口及本机用户标识。

增加补丁前需确认：

1. 配置、Python SDK、原生工具、Hook 或运行时上下文均不足以实现需求；
2. 增加 StoryPal 回归测试；
3. 记录上游 commit 和修改原因；
4. 保持补丁最小，并更新 `THIRD_PARTY_NOTICES.md`。
