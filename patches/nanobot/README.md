# nanobot 补丁

本目录只保留可重放的 nanobot 最小补丁及说明。目前有四组：

- `storypal-persona-view.patch` / `persona-view.md`：网页只读浏览 `SOUL.md`、`AGENTS.md`、`USER.md`；
- `storypal-dream-write-allowlist.patch` / `dream-write-allowlist.md`：限制 Dream 的持久文件写入；
- `storypal-tool-allowlist.patch` / `tool-allowlist.md`：按配置收紧每轮可见工具；
- `storypal-reader.patch` / `reader.md`：桌面阅读器、鉴权原文接口及本机用户标识。

本机运行时应先从固定上游基线建立**独立源码副本**，依次应用人格页、Dream 写入限制、工具白名单、阅读器四个补丁，再将该副本以 editable 模式安装到 `storypal-chatbot` Conda 环境并构建其 WebUI。当前工作机的副本为 `.runtime/nanobot/source-build/`（不提交）；`.reference/nanobot/` 仅作为上游参考，不能因为它和补丁副本同为 `0.3.0` 就混用。若出现“人格与规则”卡片能打开、正文却显示不可读取，先检查 `python -m pip show nanobot-ai` 的 `Editable project location` 是否指向已打补丁的副本。

增加补丁前需确认：

1. 配置、Python SDK、原生工具、Hook 或运行时上下文均不足以实现需求；
2. 增加 StoryPal 回归测试；
3. 记录上游 commit 和修改原因；
4. 保持补丁最小，并更新 `THIRD_PARTY_NOTICES.md`。
