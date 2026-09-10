# StoryPal Chatbot 开发进度

> 本文档是 Chatbot 工作的持续维护入口。每次开始或结束一项工作时更新状态、证据、决策、用户核验结果和 TODO。  
> 最后更新：2026-09-11（Asia/Shanghai）

## 0. 2026-09-11：结构化陪读记忆接入

- 已接入协作方 `StoryMemory` 的安全章节位置、断读回顾、人物／术语状态和情节线状态接口；所有请求均携带 `max_seen_order`，不能借结构化字段越过防剧透边界。
- Chatbot 新增 `reading_location`：用户明确说已读完某章时，才将该章节末尾设为会话边界；新增 `story_context`：只为断读回顾、状态追问和情节线追问提供内部线索。
- 产品规则：结构化记忆不直接展示给读者，也不替代原文。涉及“发生了什么／为什么”时，仍须通过 `search_story` 或 `get_story_evidence` 回到已读原文证据。
- 已完成 fake 行为覆盖及真实《流浪地球》只读验收：首个可选章节的边界为 order 26，回顾快照也为 26，未越界；完整 Chatbot 测试 19 项通过。
- 待用户核验：运行中的 WebUI 工作区现有 `AGENTS.md` 是用户可编辑文件，尚未强制覆盖。因此新工具已进入运行配置，但运行时人设说明仍需用户确认后同步或由用户手动合并。
## 1. 当前结论

- 当前已有可运行的 nanobot + StoryPal 集成 PoC：独立 Conda 环境、本地 WebUI、Luna-only 模型约束、分层 persona、会话状态、显式 Notes、滚动压缩和 8 项自有测试均已落地；Web 搜索真实链路已通过，WebUI 已增加三个只读 persona 文档页；真实 Story Store 与语义历史检索仍未实现。
- 合作者的 offline-story-pipeline 已具备可接入的 V0 StoryMemory：JSONL 为事实源、SQLite FTS5 和可选本地向量索引为可重建检索层；Chatbot 只需依赖 list_works、search、get_unit 三个接口，不读取其内部数据库。
- Chatbot V0 采用一个有最大调用次数限制的 Chat Agent loop，不增加独立 Query Analyzer、Router 或 State Tracker。
- 本阶段不等待 Story Memory 的最终存储设计。Chatbot 只依赖薄 `StoryMemory` 接口，并先用 fake/mock 实现完成其他能力。
- 优先完成：基本聊天、recent context、有界多工具调用、session state、history memory adapter、Notes、Web abstraction、trace 和测试。
- 当前首选改为先做 **`HKUDS/nanobot` 复用可行性 PoC**：复用其 Python Agent loop、WebUI、会话分支、模型配置、session compaction、人格文件、长期记忆框架、原生工具和 runtime context 扩展点；StoryPal 只补剧情状态、Notes、StoryMemory adapter、记忆策略与必要的行为约束。
- LibreChat 降为重型备选：它的消费级聊天平台更完整，但 MongoDB、MeiliSearch、RAG API 和独立 StoryPal service 的组合对当前原型偏重。
- 如果 nanobot PoC 证明其 WebUI 体验或记忆改造成本不可接受，再比较 LibreChat 与小型自建 core；不再默认先自建整套聊天平台。
- 正式 PoC 前需要将固定版本的 nanobot 拉到本地，但作为只读上游基线保存，不直接把 StoryPal 代码写进上游目录；优先使用 SDK、native tools 和 runtime context 扩展，只有确实需要修改核心时才决定 fork。
- 不直接复用 `LLM-Live2D-Desktop-Assitant` 的 Chatbot 核心。该仓库目前因 DMCA 无法正常获取；可见的旧版缓存代码也主要是单次 LLM 流式回复和 TTS/Live2D 流水线，不具备本项目要求的有界多步 Agent loop。

## 2. 已阅读的项目材料

| 文档 | 与 Chatbot 相关的确定要求 | 状态 |
| --- | --- | --- |
| `online_chatbot_engineering.md` | 单一 Agent loop；Story / Recent / History / Notes 分层；Story、State、Memory、Notes、Web tools；trace 与 20–30 个真实 case | 已读 |
| `offline_story_pipeline_engineering.md` | Chatbot 只通过本地 `StoryMemory` adapter 读取；暂不依赖内部 schema；evidence 至少包含 `work_id/story_unit_id/order/text/score/metadata` | 已读 |
| `CODEX_CHATBOT_AUDIT.md` | 先审计现有 Chatbot，再做最小改造；要求输出架构、能力、风险、复用点和开发计划 | 已读；因当前无源码，代码审计待补 |

## 3. 工作范围

### 本阶段负责

- 文本 Chatbot 主链与流式输出接口；
- OpenAI-compatible 模型适配，首版兼容云端 API、Ollama 或 LM Studio 一类兼容端点；
- 有界 function-calling loop；
- native tool registry、参数校验、错误回传和逐工具限额；
- `active_work/current_anchor/max_seen_order` session state；
- Recent Context、History Memory、Notes 三层边界；
- `search_memory/read_notes/write_note/web_search`；
- Story tools 的接口、fake/mock 与联调契约；
- 每轮 trajectory、错误和状态变化记录；
- 单元测试、集成测试和 bad-case 记录。

### 暂不深入

- Story Store 的内部 schema、分块、索引、embedding 和数据库选型；
- 独立 Router、Query Analyzer、State Tracker；
- EverOS、复杂用户画像、Reflection、Foresight；
- Skills / Workflow；
- Live2D、ASR、TTS、唤醒词和电脑控制；
- 高德、推荐系统和生产级分布式服务。

## 4. 参考项目调研

### 4.1 `ylxmf2005/LLM-Live2D-Desktop-Assitant`

调研日期：2026-09-01。

- GitHub 仓库当前返回 DMCA takedown，无法正常 clone；不能把它当作稳定依赖或可靠代码来源。
- 其 README 也说明维护重心已转移到上游 `Open-LLM-VTuber/Open-LLM-VTuber`。
- 可见缓存中的 `module/conversation_manager.py` 走的是：用户输入 → `llm.chat_iter()` → 流式文本 → 分句 TTS/播放。
- 可见缓存中的工具处理依赖在文本流里识别特定 JSON/标记；没有通用 tool schema、observation 回灌后的多步模型调用，也没有最大 tool-call 边界。
- Electron/WebSocket、流式分句、语音打断等思路可供未来桌面陪伴层参考，但不是当前 Chatbot 核心的合适起点。

结论：**当前不复制该项目代码。** 如果未来要做 Live2D/语音桌面层，再单独评估合法、仍可获取的上游实现。

### 4.2 上游 `Open-LLM-VTuber/Open-LLM-VTuber`

本次核对版本：commit `992309c0aa19845960228f880013d4685fde93b5`（2026-05-15），主仓库为 MIT；Live2D 样例资产另有独立许可。

值得借鉴：

- `AgentInterface` 将对话、打断和从历史恢复会话分开；
- `BasicMemoryAgent` 支持异步流式输出和 OpenAI/Claude 工具结果回灌；
- provider、Agent、会话处理、MCP 和前端传输有清楚的模块边界；
- 工具执行状态可作为事件推送给前端；
- 对话日志可本地持久化。

不直接复用或必须重写的部分：

- `BasicMemoryAgent` 的工具交互使用 `while True`，未见明确的 turn/tool-call 上限；
- basic memory 是整段消息列表，历史恢复后直接继续注入，没有独立长期检索、token budget 或 `search_memory`；
- `ToolExecutor` 主要面向 MCP server，Story、State、History、Notes 这类内部工具不适合全部包装成 MCP；
- chat history 采用整份 JSON 读写，适合简单记录，不适合作为长期检索层；
- 仓库没有发现测试目录，不适合作为本项目质量基线；
- 整体包含 ASR/TTS/Live2D/VAD/多 Agent 等大量当前不需要的依赖。

结论：**参考接口与事件设计，不整体 fork；Chatbot 核心采用更小的自有实现。** 如确需搬运 MIT 代码，必须逐文件记录来源、commit、修改和许可证声明。

参考链接：

- https://github.com/ylxmf2005/LLM-Live2D-Desktop-Assitant
- https://github.com/Open-LLM-VTuber/Open-LLM-VTuber
- https://github.com/github/dmca/blob/master/2026/07/2026-07-20-live2d.md

### 4.3 可直接复用的 Chatbot 平台比较

调研日期：2026-09-01。结论按 StoryPal 当前需求排序。

| 候选 | 对话平台与配置 | 上下文压缩 / 长期记忆 | 人设 | 工具接入 | 许可与代价 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| LibreChat | 完整 Web UI、多会话、streaming、模型与 Agent Builder、YAML 配置 | 内置自动 checkpoint summarization，可配置阈值、保留最近 turns/tokens；另有用户 memory agent | Agent instructions、Model Specs、starter prompts | MCP、OpenAPI Actions、内置 Web；Agent recursion limit 可配 | MIT；Docker 默认包含 MongoDB、MeiliSearch、RAG API，偏重 | 重型备选 |
| Open WebUI | 平台最完整，模型、聊天、知识、工具、Notes 和参数配置成熟 | 内置滚动 context compaction；保留最近消息并保存摘要 checkpoint；另有主动 memory tools | account/model/chat 三层 system prompt 与变量 | native tools、Functions、MCP | 0.6.6+ 为带品牌限制的非 OSI 许可 | 功能够，但暂不作为产品底座 |
| SillyTavern | 单用户本地部署相对轻；陪伴聊天 UI 成熟 | Summarize 扩展、Chat Vectorization、Data Bank | Character Card、示例对话、Author's Note、Lorebook 最强 | 主要靠扩展或自定义 API，通用 Agent tool loop 较弱 | AGPL-3.0 | 可做人设/陪伴体验参考，不选作主工程底座 |
| AnythingLLM | 桌面与 Docker 均成熟；配置、RAG、Agent 较完整 | 已有后台自动 memory extraction，但未找到同等清晰的滚动对话 checkpoint 机制 | Workspace system prompt、变量与个性化 memory | Skills、MCP、开发者 API | MIT；功能重心偏文档/RAG | 备选，不优于 LibreChat |
| Letta | Agent 平台和 API 完整，但不是最轻的消费级聊天壳 | memory-first，支持 archival memory、searchable history 和 sliding-window compaction | persona/human memory blocks 可动态维护 | 原生 tools | Apache-2.0；会把记忆策略深度绑定到 Letta | 适合以后单独评估 memory backend，不作为第一层 UI |

LibreChat 与 StoryPal 的建议连接方式：

```text
LibreChat
├─ UI / chat history / streaming / model config
├─ checkpoint summarization / user memory
├─ StoryPal Agent instructions
└─ MCP or OpenAPI tools
       ↓ 携带 user_id + conversation_id
StoryPal Companion Service
├─ StorySessionState
├─ Notes
├─ StoryMemory adapter
├─ 可选的 HistoryMemory adapter
└─ structured trace
```

LibreChat 的 YAML-defined MCP server 支持把 `LIBRECHAT_USER_ID` 以及请求体中的 `conversationId/messageId` 放入 URL 或 header，因此 StoryPal 状态可以按用户和会话隔离，不必做全局状态。

### 4.4 `nano*` 与 HelloAgents 补充调研

调研日期：2026-09-01。已下载源码进行只读检查，而不只依据项目首页说明。

| 候选 | 实际定位 | 可直接获得的能力 | 关键问题 | StoryPal 结论 |
| --- | --- | --- | --- | --- |
| `HKUDS/nanobot` | Python 自托管 Agent runtime + 浏览器 WebUI | 多会话/分支、streaming、模型配置、工具活动、OpenAI-compatible API、MCP/原生工具、token 触发 session compaction、`SOUL.md`/`USER.md`/`MEMORY.md`、runtime context provider、较完整测试 | 默认 `max_tool_iterations=200`，必须降到约 6；Dream 默认可改写 `SOUL.md`，不符合稳定人设；旧历史主要靠 grep，不是语义检索；WebUI 偏 Agent 工作台 | **新的首选 PoC**；MIT，可 fork，但必须收紧 loop、冻结人格、替换记忆检索策略 |
| `nanogpt-community/nanochat` | SvelteKit 消费级 Chat UI | 多会话、streaming、Assistant system prompt、单会话压缩、跨会话记忆、远程 MCP、Web 搜索；工具循环硬上限 5；MIT | 模型、压缩和长期记忆都调用 Nano-GPT 专用 API；需要 Bun + Postgres；跨会话记忆是每用户单一压缩文本，没有 evidence/source 分层；测试文件较少 | **界面型第二候选**；若接受 Nano-GPT 绑定可很快出 Demo，否则替换 provider/memory 的成本不低于改 nanobot WebUI |
| `jjyaoao/HelloAgents` | Python Agent 教学/工程框架，无现成 Chat UI | `HistoryManager`、TokenCounter、summary + 最近 N 轮、SessionStore、SSE、ToolResponse、熔断、TraceLogger、有界 ReAct loop | 默认“简单摘要”只保存消息数量，内容会丢失；智能摘要偏任务工程语义且默认关闭；没有可直接用的对话平台；CC BY-NC-SA 4.0 限制商业使用并要求相同方式共享 | **只参考设计，不复制代码、不作为产品底座**；若要直接使用必须先取得商业授权 |
| `datawhalechina/hello-agents` | 系统化教程与章节示例 | 适合学习 Agent、memory、context engineering 的概念和实现路径 | 不是一个精简、可部署的 Chatbot 产品；示例和章节多于产品化边界 | 作为教材，不进入原型候选 |
| `nanocoai/NanoClaw` | 容器隔离的消息渠道 Agent 系统 | 消息平台、persona template、memory、定时任务、容器隔离；MIT | 重点是 Slack/WhatsApp 等渠道与安全容器；不是简洁浏览器 Chatbot 壳，技术栈和部署边界更重 | 不选作首版；以后做多渠道或强隔离时再看 |
| `karpathy/nanochat` | 从 tokenizer、预训练到推理的 LLM 训练实验框架 | 极简训练/评测/推理链 | “chat”主要指训练后 CLI 对话，不提供我们需要的平台、工具、长期记忆或人设系统 | 明确排除 |

本次源码证据：

- nanobot 核对 commit `9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`；仓库包含约 460 个测试文件，WebUI 为 React/TypeScript，核心为 Python。
- nanobot `ContextBuilder` 每轮组合 `AGENTS.md`、`SOUL.md`、`USER.md`、`MEMORY.md`、session summary 和 runtime context；runtime context provider 可以直接注入 StoryPal 的 `active_work/current_anchor/max_seen_order`，不必先包装成 MCP。
- nanobot session compaction 会保留摘要和原始尾部，并提供 session context 查看；它与 Dream 长期记忆整理是两条不同路径，方向上符合“Recent / Checkpoint / Durable Memory 分层”。
- nanobot 的 memory skill 明确说明旧历史默认通过 grep 搜索 `history.jsonl`。这对精确关键词有用，但不足以支持“找回用户过去相似观点”，因此 StoryPal 仍需 `HistoryMemory` adapter。
- nanobot Dream 默认管理 `SOUL.md`、`USER.md`、`MEMORY.md`。StoryPal 初期关闭 Dream；用户随后明确要求允许其持续改进自身与用户认识、但不得改动故事记忆，因此现已启用受约束版本，只允许写 `SOUL.md`/`USER.md`。
- nanogpt-community/nanochat 核对 commit `6809e09a2842468ff17b30209fe76b16b2879d62`；其 streaming 主链确实有最多 5 轮的 tool-result 回灌，并能执行用户配置的远程 MCP，不只是 README 宣传。
- nanochat 的 context compression 和 persistent memory 都调用 Nano-GPT 的 `/api/v1/memory`；跨会话记忆表每个用户保存一个 `content` 文本。它能快速做通用聊天 Demo，但无法直接满足带来源的 episode/观点检索，也不能只靠更换 OpenAI-compatible base URL 完成去供应商绑定。
- HelloAgents 核对 commit `5432566d01ea1c2095c4a717fe2a010aa1c3b0bd`；`ReActAgent` 默认 `max_steps=5`，这一有界设计值得借鉴。
- HelloAgents 默认简单压缩只生成“对话轮数/消息数”统计；只有打开 `enable_smart_compression` 才会调用摘要模型保存任务目标、决策和待办。其摘要模板偏编码任务，不适合原样用于陪伴对话。

参考链接：

- https://github.com/HKUDS/nanobot
- https://github.com/HKUDS/nanobot/blob/main/docs/concepts.md
- https://github.com/HKUDS/nanobot/blob/main/docs/guides/ai-agent-memory.md
- https://github.com/nanogpt-community/nanochat
- https://github.com/jjyaoao/HelloAgents
- https://github.com/jjyaoao/HelloAgents/blob/main/docs/context-engineering-guide.md
- https://github.com/datawhalechina/hello-agents
- https://github.com/nanocoai/nanoclaw
- https://github.com/karpathy/nanochat

## 5. 建议架构

### 5.1 首选：复用 nanobot

PoC 首先验证以下闭环：

1. nanobot WebUI 启动并连接一个 OpenAI-compatible 模型；
2. 用 `SOUL.md` 和 `AGENTS.md` 建立第一版 StoryPal 人设与行为约束；Dream 只允许小幅更新 `SOUL.md`/`USER.md`，故事记忆、阅读状态和 `memory/MEMORY.md` 保持不可写；
3. 将 `max_tool_iterations` 从默认 200 收紧到 6，并验证达到上限仍能给出解释性回答；
4. 配置低阈值 session compaction，验证摘要后仍保留最近完整对话、tool call/result 边界和必要关系语境；
5. 通过原生 Tool + runtime context provider 接一个 fake StoryPal adapter，验证会话状态注入、连续调用和 structured observation；
6. 验证 session JSONL、compaction summary、工具事件和必要 trajectory 可以审计；
7. 单独验证长期记忆：不接受 grep 作为最终方案，只把它当 fallback，并接入 `HistoryMemory` adapter 的最小检索实现。

只有这些关键点证明 nanobot 不适合时，才进入 LibreChat 或自建 fallback。

### 5.2 重型备选：LibreChat

如果 nanobot WebUI 很难简化成陪伴产品界面，或其 session/memory 行为需要大规模 fork，则用 LibreChat 做第二个 PoC。LibreChat 保留此前确认的优势：成熟聊天 UI、自动 checkpoint summarization、用户 memory、Agent instructions、MCP/Actions 和可配置 recursion limit；代价是部署与跨服务状态管理更重。

### 5.3 最后 Fallback：自建小型 Chatbot core

```text
CLI / API
   ↓
ChatService
   ├─ ContextBuilder
   │    ├─ SessionState
   │    └─ RecentContext
   ├─ BoundedAgentLoop (默认最多 6 次 tool calls)
   │    ├─ ModelClient (OpenAI-compatible)
   │    └─ ToolRegistry
   │         ├─ Story / State（先 fake StoryMemory）
   │         ├─ History Memory
   │         ├─ Notes
   │         └─ Web
   ├─ ConversationMemory adapter
   └─ TraceStore
```

首版实现原则：

- core 不依赖 FastAPI、MCP 或某个具体 memory SDK；
- native tools 和外部 tools 共用统一定义，但执行后端可以不同；
- 每次 tool call 都把结构化 observation 回传模型；
- 达到上限、参数错误或工具失败时，Agent 仍应生成可解释的最终答复；
- recent context 不经过 retrieval；history 必须通过 `search_memory`；notes 只由显式意图读写；
- 所有 Story 查询默认携带 `active_work` 和允许时的 `max_seen_order`，但具体过滤由 Story adapter 负责；
- 先保存结构化 JSONL trace，避免首版引入完整 observability 平台。

### 5.4 对话记忆的目标设计

无论采用 nanobot、LibreChat 还是自建，都不把“记忆”做成一个混合文本块：

```text
完整原始对话（永久保存、可审计）
├─ Recent Window：最近 4–8 轮原文
├─ Rolling Checkpoint：更早对话的结构化压缩
├─ History Retrieval：按当前问题检索相关旧对话/观点
└─ Explicit Notes：用户明确要求记住的内容
```

滚动压缩建议：

- 在上下文达到模型窗口约 70%–80% 时触发；
- 保留最近 30%–40% 或至少 4–8 轮原文；
- 只压缩更早的完整 turn，不截断 tool call 与 tool result；
- checkpoint 保存：正在讨论的主题、用户观点及变化、未解决问题、重要指代、关系/语气变化和必要的剧情锚点；
- checkpoint 不覆盖原始对话，可重新生成；
- system prompt、工具定义、人设和当前 session state 每轮重新组装，永远不被摘要掉；
- 长期 memory extraction 与 checkpoint 分开：前者存可跨会话检索的稳定事实，后者只保证当前长对话连续。

首版长期记忆应避免自动写入“用户性格结论”。优先保存带来源的 episode / 用户明确陈述 / 观点变化；每条至少有 `content/source_message_ids/created_at/work_id/confidence`，冲突时保留新旧版本而不是静默覆盖。

### 5.5 人设提示词的目标设计

人设采用分层、版本化配置，不写成一篇无法测试的长 prompt：

```text
Identity（稳定身份与关系定位）
+ Product Contract（剧情陪伴，不假装知道未检索内容）
+ Style（语气、长度、互动方式）
+ Story Safety（防剧透与证据边界）
+ Memory Policy（什么能记、什么不能推断）
+ Tool Policy（何时查 Story / Memory / Web / Notes）
+ Session State（动态注入）
+ Relevant Memory / Notes（动态注入）
```

原则：

- 稳定人设与用户记忆分开；不能因为用户一时观点就改写角色本身；
- 只保留少量高质量示例对话，示例用于“怎么说”，规则用于“必须怎么做”；
- prompt 有版本号，可在 bad cases 中记录使用版本并回归测试；
- 角色可以有鲜明语气，但对剧情事实要引用检索证据，对不确定内容要明确表达不确定；
- 动态“关系状态”单独存储，不能混进不可追溯的总结。

### 5.6 上游源码与本项目代码边界

需要先将 nanobot 固定版本拉到本地，原因是 README 无法替代以下验证：Windows 启动、无密钥 WebUI、配置生成、session compaction、工具上限、Dream 开关、SDK 扩展点和测试基线。

建议目录：

```text
D:\StoryPal\
├─ .reference\nanobot\          # 固定 commit 的只读上游 clone，不写 StoryPal 业务代码
├─ chatbot\                     # StoryPal 自有集成层、tools、memory adapter、persona
├─ chatbot_tests\               # StoryPal 自有测试和 bad cases
├─ .runtime\nanobot\           # 本地 config/session/log/secret，未来加入 ignore
├─ patches\nanobot\            # 只有必须修改上游时才记录最小 patch
└─ THIRD_PARTY_NOTICES.md       # 上游版本、来源、MIT 许可和实际复用文件记录
```

执行约束：

- 上游先固定到已审查 commit `9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`，不跟随 `main` 自动更新；
- `.reference/nanobot` 默认只读使用，不在其中直接开发 StoryPal 功能；
- API key 只放 `.runtime` 或环境变量，示例配置只写占位符；
- 先尝试“pip/SDK 依赖 + 外部扩展”，不立即复制整个源码进入产品包；
- 发现必须修改核心时，先形成独立 patch 和回归测试，再决定维护 fork；
- 上游升级必须重新跑 compaction、tool loop、persona、memory 和 Windows smoke tests。

### 5.7 当前 skills 与工具边界

固定版本共带 11 个内置 skills。按本机依赖判断，`clawhub`、`cron`、`image-generation`、`memory`、`my`、`skill-creator`、`update-setup`、`weather` 在技术上可加载；`github` 缺少 `gh`、`summarize` 缺少对应命令、`tmux` 不适用于 Windows。这里的“可加载”不等于“适合交给陪伴 Chatbot”。

- `cron`：创建一次性或周期性任务/提醒；它不是对话摘要，也不是 Heartbeat。首版可以保留为可选能力，但应要求用户明确表达提醒意图。
- `my`：查看模型、上下文窗口、工具配置、子代理状态等运行信息，也能修改部分设置。StoryPal 已禁用它，避免聊天角色自行切换模型、改工具或暴露内部运行细节，并维持 Luna-only 约束。
- 通用命令执行工具：当前禁用。陪伴 Chatbot 不需要任意执行本机程序、安装包或读写任意路径；禁用可显著缩小提示注入与误操作范围。代价是依赖 shell 的内置 weather/github/summarize 等 skill 不能原样使用，所需功能应改成权限更小的专用工具。

当前 gateway 仍注册 14 个工具：`create_goal`、`cron`、`list_sessions`、`message`、`read_session`、`search_sessions`、`send_session_message`、`spawn`、`update_goal`、`web_fetch`、`web_search`、`read_notes`、`story_state`、`write_note`。下一步需建立明确 allowlist：保留 StoryPal/Notes/Web 和必要的会话读取，可选保留 cron；移除目标管理、子代理和跨会话发消息等工作型能力。

2026-09-04 已用 Luna 完成真实 Web 搜索 smoke：模型只调用一次 `web_search`，查询 `OpenAI GPT-5.6 Luna official documentation`，返回 5 项候选并正确选出 3 个 OpenAI 官方页面，未调用其他工具。说明当前搜索链路可用；中文召回和失败降级仍需单独测试。

### 5.8 摘要、回放与长期检索

nanobot 的 session compaction 是“当前长对话续接”机制，不是成熟的语义长期记忆库：

1. 达到 token 压力或空闲 15 分钟后，在完整 user turn 边界切分；最近至少 8 条原始消息继续回放，避免拆开 tool call/result；
2. 摘要模型收到旧摘要（若存在）、待归档对话、工具调用及结果、system/persona/skills/tools 和压缩规则；
3. 摘要规则要求保留当前目标、状态、已完成约束、阻塞、下一步和必要的精确 ID/路径/命令；事实按 `[permanent]`、`[durable]`、`[ephemeral]`、`[correction]` 分类，并去重、以最新纠正为准；
4. 工具轨迹会进入摘要输入，但不会逐条原样复制。只有影响后续的调用结果、错误、决定、ID 和阻塞应被保留；审计必须读取原始 session JSONL，不能只信摘要；
5. 摘要写入 session metadata 的 `_last_summary`，同时追加到 `memory/history.jsonl`。下一轮它会以 `[Archived Context Summary]` 重新放进 system context，后面再拼接最近原文；
6. provider 失败、输出为空或错误返回时，会退化为有界的原始 checkpoint，并保留原始归档，不会直接删除历史。

摘要块的输入大小不是固定值。token 压力触发时，每次归档“从上次归档位置到安全 user-turn 边界”的可变长度旧前缀，并固定保留最近至少 8 条原始消息；空闲压缩则处理截至启动压缩时捕获到的全部未归档消息。更新方式是滚动增量合并：把“上一版摘要 + 本次新增归档消息”交给 Luna，生成一份新的完整摘要并替换 `_last_summary`，而不是不断在旧摘要末尾追加文本。摘要输出受当前模型生成上限约束（StoryPal 当前为 8192 tokens），但实际长度由内容决定。

已有 `/api/sessions/{key}/context` 可返回摘要预览、归档/回放消息数和 token 估计，但当前前端还没有对应可视化页。`search_sessions`/`read_session` 能检索历史，但只是对原始可见 user/assistant 文本做字面子串搜索；本地用“反英雄”已成功命中。它不是同义词或语义检索，因此“完全不能检索”并不准确，准确表述应是“可做字面搜索，但没有成熟语义召回”。

现阶段不需要先部署独立向量数据库。建议先实现 StoryPal 自有 `HistoryMemory` adapter，以 SQLite 保存带来源的 episode/事实/观点及修订关系，并启用 FTS5 全文检索；在真实 case 证明字面召回不足后，再加 embedding 候选与重排。数据量或多用户并发明显增长后才考虑 Qdrant/pgvector。摘要负责连续性，HistoryMemory 负责跨会话按需召回，两者不能互相替代。

### 5.9 Dream

Dream 是 nanobot 的后台长期记忆整理器，不是“做梦式回复”。它定时读取 `memory/history.jsonl` 的新增内容，并在 workspace Git 中提交实际文件差异、推进处理游标；默认周期约 2 小时。

用户已要求启用 Dream，让 StoryPal 持续改进自身和对用户的认识，同时不改动故事相关记忆。当前运行配置因此为：每 2 小时执行、明确使用 `storypal-luna`、仅允许写 `SOUL.md` 与 `USER.md`。新的 `prompts/dream.md` 禁止保存或改写剧情事实、人物关系、情节进展、作品解读、阅读锚点、剧透信息和敏感信息。核心层新增可写文件白名单；实测对 `memory/MEMORY.md` 的写入被拒绝且原文不变。`.storypal/**`、Story Store、Notes 和阅读状态原本就不在 Dream 的写权限内。

Dream 仍可在 workspace 的 `skills/` 下整理真正重复出现的非故事工作流，这属于“改进自身”的一部分；受约束提示要求至少重复出现两次、不得承载故事内容。若后续发现 skill 自修改也造成漂移，可再单独关闭。

## 6. 分阶段规划

| 阶段 | 目标 | 主要产物 | 验收 |
| --- | --- | --- | --- |
| Phase 0 | 固化需求和技术骨架 | 本文档、候选比较、配置约定 | 已确认优先寻找带平台、压缩记忆和人设配置的可复用壳子；候选调研已完成 |
| Phase 0.25 | 固定上游基线 | 本地只读 clone、commit/许可记录、目录隔离、无密钥启动检查和上游测试清单 | 能复现已审查版本；上游源码、StoryPal 代码和运行数据互不混写 |
| Phase 0.5 | nanobot 复用 PoC | 隔离的本地运行、StoryPal persona、compaction 配置、收紧的工具上限、runtime context 与 fake tool | 能连续聊天、压缩旧消息、保持稳定人设并执行多步工具；记录资源占用和必须改造点 |
| Phase 1 | 固化采用/放弃决策 | `CHATBOT_AUDIT.md`、最终集成边界；需要时补 LibreChat 对照 PoC 或自建 core 骨架 | 明确选择 nanobot fork、LibreChat shell 或自建 fallback，并有运行证据 |
| Phase 2 | 跑通 bounded Agent loop | ToolRegistry、tool schema/dispatch、最大 6 次边界、tool error observation | 支持 `LLM → tool → observation → LLM → another tool → answer`；不会无限循环 |
| Phase 3 | 完成非 Story 本地能力 | Session state、ConversationMemory adapter、Notes、持久化 | 能查旧观点、显式写/读笔记、重启后数据仍在 |
| Phase 4 | 完成外部 Web 能力 | `web_search` abstraction、一个可替换 backend、中文 smoke cases | 现实知识问题能调用 Web；失败时可降级；主流程不绑定供应商 |
| Phase 5 | Story 联调占位 | `StoryMemory` protocol、fake adapter、Story/State tools | 不依赖真实 Story Store 即可验证工具轨迹、进度更新和防剧透参数传递 |
| Phase 6 | Trace 与测试 | JSONL trajectory、unit/integration tests、bad-case 模板 | 关键路径自动化通过；能复盘每次工具参数、结果与状态变化 |
| Phase 7 | 接真实 Story Store | adapter 实现与三篇作品联调 | 由 Story Pipeline 交付格式后执行；不反向修改其内部 schema |

## 7. 当前正在进行

状态：**Phase 1 PoC 可用，Phase 5 可开始真实单篇联调 — Pipeline 的 V0 Adapter 已核验可接。下一步是收紧工具 allowlist、实现薄 StoryMemory tool adapter，并补防剧透、人设一致性、上限降级与 HistoryMemory 用例。**

本轮完成：

- 通读三份现有工程文档；
- 确认当前仓库没有可审计的 Chatbot 源码；
- 核对指定参考仓库的可用性、旧代码主链和许可风险；
- 下载并检查仍可维护的上游项目的 Agent、memory、tool executor、history 和 session 相关代码；
- 形成“自建小核心、按需借鉴外围设计”的建议；
- 创建本进度文档。
- 比较 LibreChat、Open WebUI、SillyTavern、AnythingLLM 与 Letta 的平台、记忆、人设、工具、许可和复杂度；
- 确认 LibreChat 原生支持自动 checkpoint summarization、用户 memory、Agent instructions、MCP/Actions 和可配置 recursion limit；
- 确认 LibreChat 能向 MCP 服务转发 `user_id` 与 `conversationId`，可支持 StoryPal 会话状态隔离；
- 下载并核对 nanobot、Datawhale Hello-Agents 教程仓库和独立 HelloAgents 框架源码；
- 比较 nanobot、NanoClaw、Karpathy nanochat 与 HelloAgents 的真实定位，排除“名字像 Chatbot、实际是训练或渠道框架”的候选；
- 补充下载并核对 `nanogpt-community/nanochat`，确认它与 Karpathy 的同名项目完全不同：前者是 MIT Chat UI，已有 5 轮 MCP tool loop 与两类 memory，但核心能力绑定 Nano-GPT 专用接口；
- 确认 nanobot 已有 WebUI、会话分支、session compaction、人格/用户/长期记忆分层、原生工具、runtime context provider 和 MIT 许可；
- 发现 nanobot 的默认 200 次工具迭代、Dream 自动改写人格、grep 历史检索三个必须先处理的风险；
- 确认 HelloAgents 有有界 loop 和 context engineering，但默认简单摘要丢内容、缺少 Chat UI，并受 CC BY-NC-SA 非商业/相同方式共享限制；
- 将首选 PoC 从 LibreChat 调整为“nanobot fork + StoryPal adapter”，LibreChat 保留为重型备选。
- 明确正式 PoC 需要本地固定 nanobot 源码版本，但先作为只读 reference，不把 StoryPal 业务代码直接写进上游仓库；
- 制定 `.reference/nanobot`、`chatbot`、`chatbot_tests`、`.runtime/nanobot` 和 `patches/nanobot` 的目录边界与升级规则。
- 已将 nanobot commit `9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7` 拉到 `.reference/nanobot`，源码工作区干净，未修改上游文件；
- 已建立 `.gitignore`、`THIRD_PARTY_NOTICES.md`、StoryPal Chatbot/测试占位说明和 nanobot patch 约束；
- 已核对 nanobot 包版本为 `0.3.0`、要求 Python 3.11+；系统 PATH 仅有 Python 3.7.8 且没有 Node/npm，不应直接使用系统运行时；
- 用户指出本机已有 Conda 后，已停止使用临时 venv，改为专用 Conda 环境 `storypal-chatbot`；原有 `api` 环境没有被修改；
- 因当前 Conda channel 无法联网创建全新环境，先离线克隆 `api` 环境到 `storypal-chatbot`，再只在新环境中安装 nanobot；这个环境可用于 PoC，但包含多余基础包，网络恢复后应根据锁定清单重建干净环境；
- 已使用固定 reference 源码构建 nanobot 0.3.0 与内嵌 WebUI，并安装到 `D:\Void\Tools\conda\envs\storypal-chatbot`；构建期间只在 `.runtime/nanobot/source-build` 暂存副本中增加 pnpm 11 兼容配置，没有修改 `.reference/nanobot`；
- `nanobot --version`、`--help`、Python import 与 `pip check` 均通过；从克隆环境移除了一个与 nanobot 无关的旧 `zhipuai` 包后，依赖检查无冲突；
- 已验证 `onboard` 能在 `.runtime` 中生成独立 config、workspace、`AGENTS.md`、`SOUL.md`、`USER.md`、`MEMORY.md` 和 `history.jsonl`；未写入真实模型 key；
- 已验证无 provider 时，使用全新 config 路径执行 `nanobot webui --no-open --yes` 可以启动本地设置页；WebUI 与 gateway health 均返回 HTTP 200，服务只绑定 `127.0.0.1`；
- 已发现首启顺序差异：若先单独 `onboard` 再用 `webui --yes`，无 provider 时会被拦截；直接让 `webui` 创建新 config 则可先进入 Settings 配模型；集成启动脚本需采用后一条路径；
- 已收集并运行 auto-compact、WebUI 首启支持和 gateway smoke 共 105 项上游测试：所有测试断言显示通过并到达 100%，但 Windows 下测试进程未自行退出，需人工中断清理，记录为上游资源回收问题；
- `.reference/nanobot` 在所有构建、安装和测试后仍保持干净，未写入 StoryPal 业务代码或 secret。
- 已创建独立 `storypal-chatbot` Python 包，并通过 `nanobot.tools` entry point 接入 `story_state`、`read_notes`、`write_note`，不需要修改 nanobot 上游；
- 已实现按 session 隔离的 `active_work/current_anchor/max_seen_order` 本地状态；`max_seen_order` 默认只允许单调增加，并在每轮作为 data-only runtime context 注入，明确标注防剧透边界；
- 已实现按用户隔离的显式 Notes：只有明确调用才写入，支持读取、添加和按 ID 删除，保存来源 session 与时间；这不是自动用户画像；
- 已创建 v0.1 `SOUL.md`、`AGENTS.md`、`USER.md` 和禁用型 `HEARTBEAT.md`，稳定身份、产品契约、记忆策略、工具规则和动态状态分层保存；
- 已创建 `storypal-chatbot-configure`：保留 provider/secret，只把工具迭代上限设为 6、并发子代理设为 1、关闭 Heartbeat、限制 workspace，并关闭命令执行、通用文件、CLI Apps 和 `my` 自修改工具；Dream 后续按用户确认改为受约束启用；
- StoryPal 自有测试 8 项全部通过，覆盖安全配置、Luna-only preset/fallback、persona 不覆盖用户自定义、状态隔离与单调边界、非 Luna 请求拦截、runtime context、Notes 用户隔离以及三个插件可发现性；`pip check` 仍无冲突；
- 已增加最小 `chatbot/environment.yml`，只声明 Python 3.12、pip 和测试依赖；nanobot 继续从固定 reference 构建，避免同版本号的 PyPI 包静默替换已审计 commit；
- 用应用后的真实 config 启动 gateway，日志确认三个 StoryPal 插件被注册，Heartbeat disabled，健康端点正常；Dream 后续已作为唯一 system cron job 启用；当前仍有 14 个工具，除 StoryPal/Web 外还包含 nanobot 的 cron、subagent、session 等工具，后续需要工具 allowlist 或更小宿主边界。
- 用户选择 OpenAI Codex OAuth，并要求只允许 Luna；已增加 `--luna-only` 配置约束：唯一 preset 为 `openai-codex/gpt-5.6-luna`、`fallbackModels=[]`、reasoning effort 为 medium，同时保持模型自修改工具关闭。账户是否实际开放 Luna 需 OAuth 登录后以在线模型目录和一次 smoke call 核验；
- 已成功复用用户现有 Codex OAuth，远程账户模型目录明确包含 Luna；最小真实请求返回 `LUNA_OK`，日志显示运行模型保持 `openai-codex/gpt-5.6-luna → openai-codex/gpt-5.6-luna`；
- 为避免 WebUI 管理员误建其他 preset 后发生调用，`story_state` 的每轮 runtime context provider 增加服务端模型守卫：resolved model 不是 Luna 时在模型请求前直接拒绝，而不是 fallback；
- Luna 三轮真实工具链已通过：先调用 `story_state` 写入阅读进度，再在用户明确“请记住”后调用 `write_note`，下一轮调用 `read_notes` 准确读回；没有出现重复调用或无关工具；
- 跨会话 Notes 的真实模型读取因隐私边界暂停：它会把已保存偏好再次发送给外部模型，需要用户明确同意；在此之前只用不含真实用户信息的合成数据验证 compaction；
- 使用 24 条完全虚构的合成消息完成一次真实 Luna idle compaction：摘要已生成并持久化，原始 24 条消息没有删除，模型可见 replay window 保留最近 8 条（4 个 user/assistant 轮次）；本地复核确认摘要同时包含首项 `FACT-01` 与末项 `FACT-12`。首次 smoke 的报告脚本误读 SDK 未公开字段而在摘要完成后退出 1，已改用公开 metadata 检查且不重复产生模型调用；
- 已以显式后台生命周期启动 StoryPal gateway；WebUI `http://127.0.0.1:8765`、健康接口 `http://127.0.0.1:18790/health` 均返回 HTTP 200，且只绑定本机 `127.0.0.1`；退出日志跟随窗口后服务保持运行；
- 用户已明确允许：当其主动要求回忆 Notes 时，可将匹配的 Notes 内容发送给 Codex Luna；随后用一个全新 session 完成跨会话验证，Luna 调用 `read_notes` 并准确返回此前显式保存的“角色偏好”，没有新增个人信息；
- 已审计 11 个内置 skills 与 14 个实际注册工具：`cron` 是提醒/周期任务工具；`my` 是运行态自省与设置工具，已禁用；通用命令执行因本机安全、提示注入和 Luna-only 边界继续禁用；
- 已用真实 Luna 会话完成 Web 搜索 smoke：仅调用一次 `web_search`，成功返回并筛选 OpenAI 官方 Luna 文档；
- 已核对 compaction 的精确输入、切分、回放和持久化：工具调用/结果会进入摘要输入，重要结果可进入摘要，但原始工具轨迹仍以 session JSONL 为审计真相；摘要会在后续轮次重新注入上下文；
- 已确认 `search_sessions` 支持字面历史检索并用“反英雄”命中，但没有语义召回；HistoryMemory 首版采用 SQLite + FTS5，暂不引入独立向量数据库；
- 已按用户要求启用受约束 Dream：固定使用 Luna、每 2 小时运行，只允许写 `SOUL.md`/`USER.md`；`memory/MEMORY.md`、`.storypal/**`、Story Store、Notes 与阅读状态均不可写；
- 已在 nanobot 设置页实现并部署“人格与规则”只读页面，包含 `SOUL.md`、`AGENTS.md`、`USER.md` 三个标签；后端只允许这三个固定文件、限制每份 128,000 字符并拒绝工作区外路径；
- 页面改动的后端测试、前端组件测试、TypeScript 检查、定向 lint 和生产构建均通过；更新后的 Conda 包已安装，gateway/WebUI 分别返回健康与 HTTP 200，运行态实际读取到三份文件；
- `.reference/nanobot` 继续保持上游基线不变；核心 UI 与 Dream 白名单改动分别记录为 `storypal-persona-view.patch` 和 `storypal-dream-write-allowlist.patch`，并通过 `git apply --check`。
- WebUI 出现的 Password 是本地 bootstrap secret，不是 OpenAI/Codex 账户密码；已在当前 in-app browser 完成连接并确认“人格与规则”页面可见。secret 只保存在本地 runtime config 和浏览器 localStorage，不写入文档或提交。
- Dream 白名单的 2 项定向回归测试通过，StoryPal 自有 8 项测试与 `pip check` 通过，运行态测试确认 `memory/MEMORY.md` 写入被拒绝且原文保持不变；整份上游 Dream 测试中的 8 项 `test-model` 用例会被已安装的 StoryPal Luna-only runtime provider 拦截，属于测试入口点隔离问题，另外 41 项通过，不作为 Dream 白名单失败处理。
- 启用 Dream 前后已核对游标：`.dream_cursor=5`、最新 history cursor=5、待处理条目为 0，因此此前的合成 smoke 历史不会在首轮 Dream 中被误写为用户信息；只处理启用后的新归档内容。
- WebUI 文案已同步改为“页面只读；受约束的 Dream 可更新身份与用户认识，故事记忆保持不可写”，定向前端测试 1 项、TypeScript 检查和生产构建通过，浏览器刷新后已实际显示。

当前已实现可运行的 Chatbot 集成逻辑，但仍没有真实 Story Store、语义 HistoryMemory 或成品级陪伴 UI；nanobot 上游源码保持未修改，OAuth 与 WebUI secret 只保存在忽略提交的本地 runtime 配置中。

## 8. 用户核验记录

以下只记录用户明确确认过的内容，不把开发者自行判断写成“已核验”。

| 日期 | 核验内容 | 结果 | 影响 |
| --- | --- | --- | --- |
| 2026-09-01 | 优先寻找可直接复用的对话 AI 壳；即使不做语音，也应尽量具备滑动窗口记忆压缩、对话平台和常用配置 | 已确认 | 技术路线从“默认自建”改为“先验证成熟平台” |
| 2026-09-01 | 特别关注对话记忆与人设提示词质量 | 已确认 | PoC 验收必须覆盖滚动摘要、长期记忆边界和人设一致性 |
| 2026-09-01 | 扩大原型调研范围，特别检查 `nano*` 项目和 Hello-Agents/HelloAgents | 已确认 | 新增源码级对比，不把“教程、模型训练项目、渠道 Agent”误当作可直接复用 Chatbot 壳 |
| 2026-09-02 | 更新开发计划，并判断是否需要先将候选源码拉到本地 | 已确认 | 新增 Phase 0.25；正式 PoC 前固定上游版本并完成本地基线检查 |
| 2026-09-03 | 项目运行环境应优先使用现有 Conda，而不是另建普通 venv | 已确认 | 专用环境定名为 `storypal-chatbot`；`.runtime` 只保存构建暂存、配置、会话和日志，不再作为主 Python 环境 |
| 2026-09-03 | 使用现有 OpenAI Codex OAuth，但 StoryPal 只允许调用 GPT-5.6 Luna | 已确认 | 唯一 preset、空 fallback、禁用自修改，并在每轮模型调用前校验 resolved model；非 Luna 直接阻断 |
| 2026-09-04 | 用户主动要求回忆 Notes 时，允许把匹配的 Notes 内容发送给 Codex Luna | 已确认 | 可验证按用户隔离的跨会话显式记忆；Notes 仍不自动注入，也不用于自动画像 |
| 2026-09-04 | 同意在网页补充 `SOUL.md`、`AGENTS.md`、`USER.md` 三个浏览页面 | 已确认 | 已按单一“人格与规则”设置页、三个只读标签实现并部署；等待用户进行视觉和内容核验 |
| 2026-09-04 | 开启 Dream，让 StoryPal 持续改进自身和对用户的认识，但不得改动故事相关记忆 | 已确认 | Dream 已启用并固定使用 Luna；只允许写 `SOUL.md`/`USER.md`，故事状态、Story Store、Notes、`memory/MEMORY.md` 均不可写 |

### 待用户核验

- 是否同意以 `HKUDS/nanobot` 作为第一个直接复用 PoC，并将 LibreChat 保留为备选；
- 是否同意默认从 OpenAI-compatible provider 开始，保留 Ollama/LM Studio 兼容配置；
- 是否同意暂不复制被下架仓库代码，只参考其交互思路；
- 是否同意 Story 侧先用 fake/mock，不阻塞其他功能开发。

## 9. TODO

### 立即执行

- [x] 建立 `.reference/nanobot`、`chatbot`、`chatbot_tests`、`.runtime/nanobot` 和 `patches/nanobot` 目录边界；
- [x] 将 nanobot 拉取到 `.reference/nanobot` 并固定 commit `9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7`；
- [x] 增加 `THIRD_PARTY_NOTICES.md`，记录来源、commit、MIT 许可、修改与复用边界；
- [x] 检查 Python/Node 版本并选定隔离运行时；
- [x] 创建专用 Conda 环境 `storypal-chatbot`，从固定源码构建并安装 nanobot 0.3.0；
- [x] 运行无需真实 API key 的 CLI、配置生成、WebUI 首启与健康接口 smoke test，并记录首启顺序和 Windows 清理问题；
- [x] 运行 auto-compact、WebUI 首启支持和 gateway smoke 相关的 105 项上游测试断言；
- [x] 先通过 SDK/entry-point 扩展层接入三个 StoryPal 工具，不修改 `.reference/nanobot`；
- [x] 已接通 OpenAI Codex OAuth / GPT-5.6 Luna，并完成最小请求、三轮真实工具链和跨会话 Notes 轨迹；
- [ ] 已将 `max_tool_iterations` 配成 6；待接模型后测试正常连续调用、重复调用和上限降级；
- [x] 已建立 StoryPal v0.1 分层 persona，并按用户确认启用受约束 Dream；Heartbeat 继续关闭；
- [ ] 累积足够真实历史后检查首轮 Dream diff，验证只更新 `SOUL.md`/`USER.md` 且没有故事内容或无依据用户推断；
- [x] 已执行真实 Luna idle compaction，验证滚动 checkpoint、最近 8 条消息保留和原始 JSONL 不被覆盖；
- [x] 已实现并用 Luna 验证 `story_state` native plugin 与 runtime context provider；真实 Story 查询仍保持 fake/adapter 边界；
- [x] 为 nanobot 内置工具增加 allowlist；首版只暴露 StoryPal 的故事状态、检索、证据和显式 Notes 五项工具，Web 与通用 Agent 工具均不默认开放。
- [x] 已确认 nanobot WebUI 可本机访问，并增加 `SOUL.md`、`AGENTS.md`、`USER.md` 三个只读浏览标签；
- [ ] 请用户核验“人格与规则”页面的视觉、文案和三份文件内容；继续评估需要隐藏/改名的工作台功能；
- [ ] 设计 `HistoryMemory` adapter，避免把 grep 当作唯一长期回忆路径；
- [ ] 将结果、资源占用、必须改源码的点和 bad cases 写入审计文档；
- [ ] 决定正式采用 nanobot；若失败，再进行 LibreChat 对照 PoC 或转入自建 fallback。

### 后续

- [x] 增加 `StorySessionState` 的本地 PoC 与 runtime context；
- [ ] 增加 ConversationMemory adapter 和首个简单持久化 backend；
- [x] 增加显式、按用户隔离的 `read_notes/write_note` PoC；
- [ ] 增加 `web_search` abstraction，并做中文 smoke test；
- [ ] 增加 fake `StoryMemory` 和 Story/State tools；
- [ ] 与真实 Story Store 联调；
- [ ] 准备 20–30 个真实聊天 case；
- [ ] 保存至少 5 个完整 bad-case trajectories；
- [ ] 根据轨迹再决定是否需要 Router、Workflow、Skills 或更强 memory backend。

## 10. 风险与阻塞

| 级别 | 风险/阻塞 | 当前处理 |
| --- | --- | --- |
| Blocker | 当前无已有 Chatbot 源码，无法完成“保留或改造现有代码”的审计 | 默认按绿地最小实现规划；若另有仓库，应先补充后重新审计 |
| High | 指定参考仓库已被 DMCA 下架 | 不复制、不依赖；仅记录已公开可验证的架构信息 |
| High | 本地小模型的 function calling 稳定性差异很大 | ModelClient 与 Agent loop 分离；允许 OpenAI-compatible 云端/本地后端切换；用集成 case 验证 |
| High | LibreChat 默认部署包含 MongoDB、MeiliSearch、RAG API，可能超出单机 Demo 所需复杂度 | PoC 记录内存/磁盘/启动依赖，并验证能否关闭非必要组件 |
| High | nanobot 默认 `max_tool_iterations=200`，与文档要求的有界小循环不一致 | PoC 第一项就固定为 6，并增加达到上限后的集成测试 |
| High | nanobot Dream 自动更新 `SOUL.md`/`USER.md` 可能造成人设漂移或错误用户推断 | 已按用户要求启用，但增加核心可写文件白名单和 StoryPal 专用 Dream prompt；固定 Luna，禁止故事/敏感内容，首轮实际 diff 仍需复核 |
| High | HelloAgents 采用 CC BY-NC-SA 4.0，不适合未获授权的商业产品复用 | 不复制代码；只独立实现通用设计思想；如必须使用则先取得书面商业授权 |
| High | nanogpt-community/nanochat 的模型和 memory API 与 Nano-GPT 服务绑定，难以直接接本地 Ollama/LM Studio | 只作为界面型备选；除非确认接受该供应商，否则不进入第一轮 PoC |
| High | 复用平台的升级可能改变 Agent、memory 或 summarization 行为 | 固定版本；关键行为写集成测试；StoryPal 数据留在独立 service |
| Medium | nanobot 旧历史默认为 grep 检索，中文同义表达和观点回忆召回不足 | 保留原始 JSONL；增加 `HistoryMemory` adapter，先做关键词 + embedding/FTS 可替换策略和真实召回 case |
| Medium | nanobot WebUI 偏 Agent 工作台，不一定符合陪伴聊天体验 | PoC 只评估最小隐藏/主题改造；若必须大改，转用 LibreChat 或自有前端 |
| Medium | 即使关闭 exec/file/CLI Apps，nanobot gateway 仍注册 cron、spawn、goal、跨 session message 等通用 Agent 工具 | 接模型前先研究可维护的工具 allowlist；若公共配置/SDK 无法限制，再以一个带回归测试的最小上游 patch 或自有 SDK 宿主解决 |
| Medium | 本机未发现 Ollama 命令，Ollama 默认端口 11434 与 LM Studio 常用端口 1234 均未监听 | 真实聊天需要用户选择已有云端/OpenAI-compatible provider，或先安装并启动一个本地模型服务 |
| Medium | 当前 Conda 环境由已有 `api` 环境离线克隆，包含与 PoC 无关的包 | 仅作为本地验证环境；维护最小依赖清单，网络可用时重建干净的 `storypal-chatbot` 环境 |
| Medium | Windows 下 gateway smoke 用例断言完成后 pytest 未自动退出；CLI stop 在有跟随客户端时也会超时 | 启动器负责先断开本地跟随客户端再停止网关；补一条 Windows 生命周期回归测试，并向上游隔离问题 |
| Medium | 在已安装 StoryPal entry points 的环境中跑 nanobot 上游 AgentLoop 单测时，测试用 `test-model` 会被 Luna-only provider 拦截 | StoryPal 与白名单定向测试分别通过；后续为上游测试创建不加载 StoryPal entry points 的隔离测试环境 |
| Medium | history memory 可能过早复杂化 | 先做 adapter 和简单 backend，用召回 case 决定是否引入 EverOS/向量库 |
| Medium | Web 中文召回和供应商可用性不确定 | 保持 `web_search` abstraction，首个 backend 只做 smoke test，不写死 Tavily |
| Medium | Story Store 交付格式尚未确定 | 只依赖文档中的 protocol/evidence，使用 fake adapter 开发 |

## 11. 更新规则

每次更新本文档时：

1. 更新“最后更新”时间；
2. 在“当前正在进行”只保留真实进行中的工作和本轮证据；
3. 完成项同时更新阶段表和 TODO；
4. 用户明确确认后才写入“用户核验记录”；
5. 新技术决策写明原因、替代方案和影响；
6. 发现 bad case 时记录输入、session state、tool trajectory、输出、预期和修复状态。

## 2026-09-05：BM25 StoryMemory 工具

- 已在 StoryPal 自己的 `story_memory.py` 固化 Backend Protocol、Evidence 安全过滤和 FTS-only provider；上游 Pipeline 仅通过其 Adapter 使用。
- 已增加 `search_story` 与 `get_story_evidence` native tools。前者固定请求 top-5：返回前三条主证据，并只在第 4/5 名与主证据同章节且 `order` 相邻时纳入 `adjacent_context`；后者按 ID 读取仍受当前 `max_seen_order` 硬限制。两者均不会推进阅读进度。
- 已增加功能级测试：缺失进度拒绝、跨作品/超进度结果二次过滤、跨章节邻居拒绝、rank 4/5 邻接补充、直接证据读取防剧透、session state 不被搜索改写、真实《流浪地球》BM25 provenance。
- 已安装 LanceDB 0.38.0、sentence-transformers 5.7.0 与 PyArrow 到 `storypal-chatbot` Conda 环境，`pip check` 通过。当前 BM25 工具显式使用 FTS，不启用向量。Lance 表可打开并按 `ord <= max_order` 过滤；语义查询仍缺构建索引时使用的本地 `D:\models\BAAI\bge-m3` 模型文件，按当前范围不下载。
- Chatbot 回归测试 14 项通过；gateway 已重启并实际注册 `search_story`、`get_story_evidence`，总注册工具数为 16。
## 2026-09-05：官方 BGE-M3 与首轮检索对照

- 已从 Hugging Face 官方发布者 `BAAI` 下载并固定 `BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181` 到 `D:\models\BAAI\bge-m3`。主权重按官方文件大小与 SHA-256 完整性校验后加载成功；中文查询编码为归一化 1024 维向量，与既有 LanceDB 索引一致。
- 新增 `chatbot_tests/story_retrieval_goldens.json`：10 条中文可维护用例，覆盖明确事实、语义改写、立场动机、解释推理、事件描述、后果追问和两类防剧透边界。
- 新增 `chatbot_tests/evaluate_story_retrieval.py`：固定同一语料、边界与 top-k，输出 BM25/FTS 与 BGE-M3/LanceDB 的命中率、耗时、返回单元和防剧透违规数。
- 首次实测：9 条有金标用例中，FTS 与向量的前 1 命中率均为 66.7%，前 3/5 命中率均为 88.9%，两者均为 0 次防剧透违规。FTS 热查询约 1–7 ms；BGE-M3 首次加载查询约 13.8 s、热查询约 34–46 ms。两者遗漏用例不同，后续在扩展金标集后评估 RRF，不立即上线。
## 2026-09-05：真实对话式检索金标扩展

- 金标集已从 10 条扩展为 24 条，其中 22 条具有可判定原文单元。场景覆盖：口语化事实提问、记忆核对、指代消歧、人物动机、困惑澄清、事件前因/后果、情绪化回顾、进度内总结及防剧透追问。
- 每条用例保存“用户原话”“可选对话上下文”“消歧后的检索查询”“阅读边界”和“期望单元”。这将聊天理解与证据检索分开评估，避免把模糊口语直接检索的失败误判为索引失败。
- 在同一语料与边界下重跑：BM25 前 1/3/5 命中率为 59.1% / 72.7% / 77.3%；BGE-M3 向量为 86.4% / 95.5% / 100%；两者均 0 次防剧透违规。向量对口语化概念、动机和长程回顾明显更强；R07“反物质炸弹用于处理何种威胁”仍未进向量前三，保留为优化与 RRF 验证用例。
## 2026-09-05：会话级故事工具冒烟测试

- 在本地模拟 WebUI 会话完成完整路径：空状态 → 设置《流浪地球》`max_seen_order=20` → 中文检索 → 读取 `we-0018` → 尝试读取 `we-0022`。检索返回的所有单元均在边界内；越界读取被拒绝；检索不改变阅读进度。
- 协作仓库本轮再次 fetch，未发现新的远端提交。
- 当前 `search_story` 仍固定使用 BM25/FTS；向量检索已完成离线质量验证，尚未改变线上工具行为。
## 2026-09-05：主 Agent 检索决策与真实 Luna 验收

- 复核工程文档后确认：V0 不新增独立 Query Analyzer / Router / State Tracker。检索词由主 Agent 根据最近对话、阅读状态和工具结果直接组织；本轮未增加第二次模型调用。
- 已在源人格规则及运行时 workspace 增加中文检索决策契约：何时检索、如何消歧口语化指代、何时先共情/澄清、检索结果仅作证据、禁止借检索探查未读剧情。引导测试固定该约束。
- 真实 Luna 隔离会话验收：阅读边界为 26 时，用户问“老师刚才说的五步怎么排”；Luna 将其改写为包含“人类逃亡五步、刹车、加速、逃逸、减速”的查询，调用一次 `search_story`，并正确依据 `we-0023` 给出五步。此前发现模型将阅读进度误填为 `chapter` 条件；已移除当前不必要的公开 `chapter` 参数，避免空检索。 
- 本地 gateway 已重新启动，PID 29272、端口 18790，WebUI 将使用新规则与参数契约。
## 2026-09-05：后续开发规划

- 已创建 `CHATBOT_NEXT_PHASE_PLAN.md`，将下一阶段排序为：工具 allowlist → 向量策略配置与 FTS 降级 → 真实 Luna 轨迹 → 多作品金标与 RRF 离线评估 → HistoryMemory → 陪读功能扩展。
- 再次明确 V0 暂缓独立 Query Analyzer / Router；主 Agent 直接负责上下文消歧与工具选择。
## 2026-09-05：工具白名单收敛

- 已确认 nanobot 原生配置可关闭 Web、命令、文件等类别，但无法统一隐藏 cron、子 Agent、跨会话消息、目标管理等核心工具；因此按既定边界增加最小、可回放的 `allowedTools` 补丁。
- `tools.allowedTools` 未配置时保持 nanobot 原行为；配置后在每轮模型调用前构造受限注册表，未授权工具不会出现在函数定义中，亦不能被该轮执行。StoryPal 当前仅允许 `story_state`、`search_story`、`get_story_evidence`、`read_notes`、`write_note`。
- 已以本地 `.reference/nanobot` 的可编辑安装方式应用补丁并重启 gateway（127.0.0.1:18790）。注册日志仍会显示底层加载的工具数量，这是装载诊断；实际模型可见工具由每轮过滤决定。
- 新增无网络、无真实模型的行为回归测试 `chatbot_tests/test_nanobot_tool_allowlist.py`：截取真实 AgentRunner 入参，确认只剩五项白名单工具。将 pytest 临时目录置于 `.runtime/test-tmp` 后，聊天机器人全量回归 15 项通过。
- 补丁、回放步骤与维护说明见 `patches/nanobot/storypal-tool-allowlist.patch`、`patches/nanobot/tool-allowlist.md`；`THIRD_PARTY_NOTICES.md` 已同步更新。
## 2026-09-05：首次阅读陪读体验复盘

- 从产品角度确认：现有 `Notes` 只应保存用户明确要求记住的长期偏好；它不适合作品阅读过程中的反应、疑问与猜测，也不应被 Dream 混入人格或故事事实。
- 已新增 `CHATBOT_FIRST_READING_EXPERIENCE.md`，定义无剧透首次打开、自然陪读循环、独立阅读手账（反应/问题/预测）、预测核验边界与首轮验收场景。
- 后续功能优先级调整为：阅读定位友好化 → 已读范围短回顾 → 阅读手账 → 预测核验 → 真实轨迹，再根据真实需求实现 HistoryMemory；检索策略接入仍作为底层并行工作，但不应取代陪读体验验证。

- 已将“初次阅读陪读”准则同步至源码人格模板和运行时 workspace：只讨论已读范围；困惑先用已读文本澄清；情绪先回应；猜测、问题与感受必须经用户确认才记录；不得暗示后续答案。`bootstrap.py` 也会在新配置时写入五项工具白名单。
- 本轮完整 Chatbot 回归测试：15 项通过。
## 2026-09-06：StoryMemory 完整抽取数据同步

- 已从协作仓库 `origin/main` 快进同步至 `4d264d9`（`data: publish full LLM-extracted story artifacts`）。本轮包含完整《流浪地球》LLM 抽取结果、SQLite FTS5 与 LanceDB 索引重建，以及提取诊断、实体/情节线约束和检索评估能力。
- `StoryMemory` Adapter 的冻结接口未变化；仍支持 `auto`、`vector`、`fts`。完整抽取现在有 108 个单元，`llm_errors.json` 为空；向量索引为本机 `D:\models\BAAI\bge-m3`、1024 维，索引源哈希已更新。
- Chatbot 的本地 StoryMemory 回归 6 项通过。真实检索冒烟确认：`vector`、`fts` 都可返回证据；向量在 `max_order=2` 时仅返回 order 1、2，未出现防剧透越界。
- 当前 Chatbot 仍显式使用 FTS 后端，因此完整数据已可用但尚未改变线上检索策略。下一项可在 Chatbot 适配层接入协作方的 `auto`（向量优先、FTS 降级）模式，并补充策略可观察性与回归测试。
## 2026-09-06：Luna 对完整故事单元的产品审阅

- 已用 GPT-5.6 Luna 审阅完整抽取的 108 个单元、字段样本、向量/FTS 与边界证据；完整原文记录于 `LUNA_STORY_UNIT_REVIEW_2026-09-06.md`。
- 结论与既有产品方向一致：优先支持已读范围内即时解释、阅读反应/问题承接、预测暂存与用户主动核验；阅读手账必须独立于长期 Notes。
- Luna 明确指出：`summary`、原始人物/地点/关键词仅适合作为内部证据或检索线索，未清洗前不应直接展示；样本中人物字段混入概念，空标签也不能等同于无实体。
- 新增硬性实现要求：所有手账读取、展示、核验和生成都必须由 `active_work` 与 `order <= max_seen_order` 在数据层共同过滤，不能只依赖提示词。

## 2026-09-06：完整故事单元内容可用性分析

- 已完成 108 个《流浪地球》单元的字段覆盖、长度、章节分布和标签形态审计，结论记录于 `STORY_UNIT_USABILITY_ANALYSIS_2026-09-06.md`；所有单元均非降级，均具备原文、摘要、近因事件与状态快照。
- 可先用于“已读范围解释、定位、带证据回应”；不将原始摘要、人物/地点/关键词、状态快照直接展示。人物字段已有关系组合、群体与组织混入，须先清洗。
- 新识别的边界风险：用户读到单元中部时，单纯 `order <= max_seen_order` 会放出该单元余下内容。首版阅读位置应只提交“完整读完的单元”，或在后续增加行/段落锚点。
- 后续按“auto 检索策略与可观察性 → 阅读位置与短回顾 → 独立阅读手账 → 真实轨迹与标签清洗审计”的顺序推进；手账长期锚点需带作品版本/源哈希与锚点文本，不能只存会随切分变化的 `unit_id`。
## 2026-09-06：向量优先检索策略接入

- Chatbot 已将默认协作方后端从显式 `fts` 切换为 `auto`：优先本地 BGE-M3 + LanceDB；模型、索引或依赖不可用时由冻结适配器依次退回 FTS5、事实源扫描。也可用环境变量 `STORYPAL_STORY_RETRIEVAL=vector|fts|auto` 显式覆盖。
- 保留 `PipelineFtsBackend` 作为测试/兼容入口；工具返回的 `retrieval` 表示配置策略而非一次调用实际命中的降级分支。协作方当前冻结接口未暴露实际策略，因此已记录为接口需求，不能让前端或模型将 `auto` 误读成“本次一定使用了向量”。
- 完整 Chatbot 回归现为 16 项通过；真实 `auto` 冒烟查询“为什么人类要建造地球发动机”返回 `we-0003`、`we-0008`、`we-0009`，全部不超过 `max_seen_order=20`。
## 2026-09-06：阅读手账 v1

- 已新增独立 `ReadingNotebookStore` 与两个受限工具：`read_reading_notebook`、`write_reading_notebook`。它们只保存用户明确确认的 `reaction`、`question`、`prediction`，不使用长期 Notes 的文件或语义。
- 读取时按用户、`active_work` 和 `anchor_order <= max_seen_order` 共同过滤；写入前强制要求已有作品和防剧透边界，并记录当时阅读锚点。当前不做自动核验或自动人格抽取。
- 已注册为 nanobot 插件并更新运行时 allowlist；网关已重启。全套回归为 18 项通过。
- 仍不邀请用户做首次阅读体验：现有阅读位置依旧需要内部 `max_seen_order`。已将“章节/位置映射”和“实际检索分支诊断”需求写入 `STORYMEMORY_INTERFACE_REQUEST.md`；待该接口可用后，可补自然语言阅读定位并开始首轮体验。
## 2026-09-06：阅读手账真实 Luna 验收

- 已在独立开发会话 `storypal-notebook-acceptance-20260906` 完成真实 Luna 轨迹：模型按顺序调用 `story_state(set)`、`write_reading_notebook(add)`、`read_reading_notebook`，将“地球停止自转的画面让我很不安”作为 `reaction` 写入并确认读取成功。
- 这是 Agent 对真实工具注册、白名单、运行时状态与存储隔离的联合验收；不使用用户会话，也不改变故事事实或正式阅读进度。