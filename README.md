# StoryPal

## 启动本机 Chatbot

以下命令针对已配置的本地开发环境。公开仓库不包含 `.runtime/`、`.reference/`、`story_mem/` 或小说原文；新克隆需要先准备 nanobot 基座、应用 [StoryPal 补丁](patches/nanobot/README.md)，并按 [StoryMemory 接入说明](chatbot/STORY_PIPELINE_INTEGRATION.md) 放置本地数据。

启动前确认 Conda 中的 `nanobot-ai` 是从**已应用全部 StoryPal 补丁的源码副本**安装，而非仅从上游参考目录安装。只更新网页资源、不切换 Python 安装源，会导致“人格与规则”页面有三个卡片却无法显示文档。当前本机补丁副本为 `.runtime/nanobot/source-build/`；其准备与安装顺序见补丁说明。

在 PowerShell 中执行：

```powershell
conda activate storypal-chatbot
nanobot gateway --background --config D:\StoryPal\.runtime\nanobot\storypal\config.json --workspace D:\StoryPal\.runtime\nanobot\storypal\workspace
nanobot webui --yes --config D:\StoryPal\.runtime\nanobot\storypal\config.json --workspace D:\StoryPal\.runtime\nanobot\storypal\workspace
```

浏览器打开 http://127.0.0.1:8765 。

### 选择对话模型

当前默认 **GPT-6 Luna**（`storypal-luna`），保留 **GPT-5.6 Luna**（`storypal-luna-5-6`）手动可选。在聊天输入框旁点击当前模型标识，选择另一个预设；该选择只影响当前会话，保存在会话元数据中，刷新／重启后可恢复。新会话使用全局默认。

如需改变新会话的默认，在「设置 → 模型」调整默认调用顺序，保持其中只有所选的一项；不要把第二个预设加入自动回退顺序。运行时只允许上述两种 Codex Luna，其他型号会被拒绝；新增可选型号需同时维护 `chatbot/src/storypal_chatbot/model_policy.py` 和配置，不能只改网页列表。当前两种型号均保持 `medium`，无自动回退；Dream 单独固定使用 `storypal-luna`，不随会话选择切换。

新安装应额外应用 [模型目录补丁](patches/nanobot/codex-model-catalog.md)。现有用户不要为了切换模型重新执行整套初始化或强制覆盖人格文档。

已确认完整已读位置后，每轮会自动带入预算内的渐进故事视图，原文工具仍按需查证；这不是全书摘要或已验证的人物因果图。新安装还需同步 StoryMem 的 `get_progressive_view` 接口并应用 [临时上下文回放补丁](patches/nanobot/runtime-context-replay.md)。本机已更新源码，后端变更需要重启 gateway，无需改用户进度或重新初始化。

按日互动经历已接低频抽取与 `recall_interaction_history(query)` 语义回忆；只覆盖已提取、当前用户／作品／已读范围内的经历，不等于搜索全部原始历史。新环境可安装 `pip install -e './chatbot[episodic]'` 并在启动进程前设置 `STORYPAL_EPISODE_MODEL` 为本地BGE-M3目录；本机默认 `D:/models/BAAI/bge-m3`，不自动联网下载。`STORYPAL_EPISODE_THRESHOLD` 默认0.55、`STORYPAL_EPISODE_TOKEN_BUDGET` 默认1000估算tokens，改后重启gateway；阈值尚未标定。只新增回忆工具到现有白名单，不要强制覆盖用户人格文件。详细边界、开关与测试见 [情景记忆](docs/architecture/STORYPAL_EPISODIC_MEMORY.md)。

共读压缩现在支持保留观点、修正与未解问题。新安装应用 [共读归档补丁](patches/nanobot/reading-checkpoint.md)；模板在工作区 `prompts/consolidator_archive.md`，默认只补缺失文件，已有自定义不覆盖。它复用原有压缩调用，不自动写入阅读手账或 Note；一条隔离压缩续聊已跑通，不代表全面体验通过。还需应用 [空工具注册表修复](patches/nanobot/empty-tool-registry.md)，防止空白名单意外回退默认工具。

在桌面浏览器的聊天页点击右上角「阅读原文」，可在同一页阅读《流浪地球》并划选段落带入聊天。每段末尾的「读到这里」可发起精确段尾进度标记；也可在章末点「我已读完本章」，两者都需在聊天中再次确认才写入。滚动位置仅保存在本机浏览器，用于下次续读；浏览器也保留一个本机标识，让聊天侧已确认进度在刷新后仍对应同一用户。滚动和选中原文不会更改防剧透边界。段落落在 StoryUnit 中间时，系统只开放该段之前的原文，不把整个单元标记为已读。首版暂不适配手机，已确认位置暂不在阅读器中高亮。

WebUI 的登录密码不写入项目文档；本机配置位置是：

`D:\StoryPal\.runtime\nanobot\storypal\config.json`

其中 `channels.websocket.tokenIssueSecret` 是密码，
`channels.websocket.websocketRequiresToken` 决定是否要求密码。

停止服务：

```powershell
conda activate storypal-chatbot
nanobot gateway stop --config D:\StoryPal\.runtime\nanobot\storypal\config.json --workspace D:\StoryPal\.runtime\nanobot\storypal\workspace
```

## 本地 Story Memory

阅读手账现支持对话中明确新增、修订、删除；修订保留原观点与不同阅读位置，删除不等于擦除旧聊天。确认进度推进后，下一轮可获得少量旧问题／预测作为回看候选，未自动判定对错。见[手账设计与边界](docs/architecture/STORYPAL_READING_JOURNAL.md)及[五分钟核验](docs/operations/READING_JOURNAL_ACCEPTANCE.md)。

Note每轮注入当前有效Markdown；显式temporary只在创建会话生效，跨会话不注入，原记录保留。开放观察在新归档的联合维护中可修订／停用，始终待验证，不自动升级为稳定偏好；同文件维护历史不注入。新快照不回放，旧版历史兼容迁移仍待做。详见[Note生命周期](docs/architecture/STORYPAL_NOTE_MAINTENANCE.md)。

压缩后的后台维护共用一次 Note／按日经历抽取调用，首次启用不回扫旧归档，每次用户请求最多处理一个新归档批次。可用进程环境 `STORYPAL_AUTO_NOTE=0` 或 `STORYPAL_AUTO_EPISODE=0` 分别暂停类别；两个全关时暂停但不删除水位，重开可能继续待处理归档。按需回忆工具已接通，一条授权合成归档→空白新会话验证通过；不代表全部长聊或自动压缩流程已验收。细节见 [情景记忆说明](docs/architecture/STORYPAL_EPISODIC_MEMORY.md)。

开发验收可使用 [隔离查询导出](docs/operations/AGENT_QUERY_CAPTURE.md)，显式核对真实工具参数并保留查询来源；不会自动扫描或导出正式聊天。公开实验与真实体验的限制见 [result.md](result.md)。

连续讨论方法使用 nanobot 原生常驻 Skill：工作区 `skills/continuous-story-discussion/SKILL.md`，模板在 `chatbot/src/storypal_chatbot/persona/skills/`。它在每次构建 system 时自动注入一次，不需要开放文件工具或增加模型请求；已有自定义文件不覆盖。若要关闭，可将名称 `continuous-story-discussion` 加入本机配置 `agents.defaults.disabledSkills`；不要为更新此 Skill 强制重装人格。

`story_mem/` 是本地联调目录，当前含合作者的 offline-story-pipeline
参考副本。它被 Git 忽略，不会提交；实际作品数据导出也应放在这里。

StoryMemory 接入设计见 `chatbot/STORY_PIPELINE_INTEGRATION.md`。

## 文档导航

完整文档地图见 [docs/README.md](docs/README.md)：

- `docs/product/`：读者体验、产品场景与后续功能规划；
- `docs/architecture/`：Chatbot 与 StoryMemory 的工程契约；
- `docs/operations/`：持续开发进度、核验记录和 TODO；
- `docs/research/`：调研、模型审阅、数据可用性分析和历史接口需求。
