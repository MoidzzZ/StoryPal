# nanobot 补丁

本目录只保留可重放的 nanobot 最小补丁及说明。目前有九组：

- `storypal-persona-view.patch` / `persona-view.md`：网页只读浏览 `SOUL.md`、`AGENTS.md`、`USER.md`；
- `storypal-dream-write-allowlist.patch` / `dream-write-allowlist.md`：限制 Dream 的持久文件写入；
- `storypal-tool-allowlist.patch` / `tool-allowlist.md`：按配置收紧每轮可见工具；
- `storypal-reader.patch` / `reader.md`：桌面阅读器、鉴权原文接口及本机用户标识。
- `storypal-paragraph-markers.patch` / `reader.md`：逐段段尾标记；在阅读器补丁之后应用。
- `storypal-codex-model-catalog.patch` / `codex-model-catalog.md`：更新目录客户端版本，使在线目录列出 GPT-6 Luna；安装说明中的五组 UI/权限补丁之后，再应用这一独立 provider 补丁。
- `storypal-runtime-context-replay.patch` / `runtime-context-replay.md`：允许临时来源退出旧消息回放，保留原始历史与其他来源，跨轮失效旧 provider 私有状态；在上述六组之后应用，无需重建网页。
- `storypal-reading-checkpoint.patch` / `reading-checkpoint.md`：复用安全工作区模板读取，为归档增加中文共读摘要覆盖入口；在上述七组后应用，无需重建网页。
- `storypal-empty-tool-registry.patch` / `empty-tool-registry.md`：空白名单不回退默认全集，工具执行与附加上下文都保持禁用；在上述八组后应用。

本机运行时应先从固定上游基线建立**独立源码副本**，依次应用人格页、Dream 写入限制、工具白名单、阅读器、段落标记、模型目录、临时上下文回放、共读归档、空工具注册表九个补丁，再将该副本以 editable 模式安装到 `storypal-chatbot` Conda 环境并构建其 WebUI。当前工作机的副本为 `.runtime/nanobot/source-build/`（不提交）；`.reference/nanobot/` 仅作为上游参考，不能因为它和补丁副本同为 `0.3.0` 就混用。参考工作区有历史本地改动，复现必须从上方固定 commit 而非直接复制参考目录开始。若出现“人格与规则”卡片能打开、正文却显示不可读取，先检查 `python -m pip show nanobot-ai` 的 `Editable project location` 是否指向已打补丁的副本。

增加补丁前需确认：

1. 配置、Python SDK、原生工具、Hook 或运行时上下文均不足以实现需求；
2. 增加 StoryPal 回归测试；
3. 记录上游 commit 和修改原因；
4. 保持补丁最小，并更新 `THIRD_PARTY_NOTICES.md`。
