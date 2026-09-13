# 剧情陪伴 AI：Online Chatbot 工程文档（V0）

> 面向负责 **Online Chatbot** 的开发者。  
> 当前已经有一个“带 memory 和简单 tools 的 Chatbot 原型”，但需要先在本地核验真实实现。  
> V0 的核心策略是：**尽量复用现有 Chat Agent，新增 Story / Memory / Notes / Web 能力，不提前拆成 Router / Query Analyzer / State Tracker 工作流。**

---

## 1. 产品定位

这是一个 **剧情陪伴 Chatbot**。

用户第一次阅读 / 观看 / 游玩故事时，可以随时：

- 回忆前文；
- 吐槽人物或事件；
- 讨论动机和因果；
- 记录自己的猜测；
- 之后回看自己曾经的观点；
- 从故事延伸到现实科学、文化、作者与作品背景。

AI 需要同时利用：

```text
Story Memory
+ Recent Conversation
+ History Memory
+ Explicit Notes
+ External Knowledge
```

它不是角色扮演 Agent，也不是单纯小说 QA。

---

# 2. 当前与未来

当前 V0：

```text
Offline Story Pipeline
        ↓
Local Static Story Memory
        ↓
Online Chat Agent
```

未来：

```text
Text / Subtitle / Game / VLM
        ↓
Realtime / Incremental Story Reader
        ↓
Story Memory Update
        ↓
Online Chat Agent
```

因此 Chatbot 只依赖 `StoryMemory` 能力，不依赖离线小说管线内部结构。

---

# 3. V0 总体架构

当前采用一个 **bounded Chat Agent loop**：

```text
User
 ↓
Chat Agent
 │
 │ 看到：
 │ - original user query
 │ - recent conversation
 │ - current session state
 │ - tool observations
 │
 ├─ search_story ?
 ├─ set_active_work ?
 ├─ update_story_progress ?
 ├─ search_memory ?
 ├─ read_notes ?
 ├─ write_note ?
 ├─ web_search ?
 ├─ existing tools ?
 │
 ↓
根据 Observation 再决定下一步
 ↓
最终自然回复
```

核心是：

> **LLM 根据当前上下文和工具结果动态决定下一步 action，并能多步闭环。**

V0 不要求显式输出经典 ReAct 的 Thought / Action / Observation 文本，但 function-calling loop 本质上是 ReAct-style Agent Loop。

建议限制每轮最大 tool calls，例如 4–6 次，避免无限循环。

---

# 4. V0 不引入独立 Query Analyzer / Router / State Tracker

不要提前改成：

```text
Query Analyzer
→ Router
→ Story Workflow
→ Memory Workflow
→ Generator
```

也不要单独增加：

```text
State Tracker
→ Agent
```

原因：

- 状态判断本身也需要理解 Story；
- 单独 State Tracker 很可能重复调用剧情检索；
- 前置 Query rewrite 会把 Agent 的工具选择权转移到 workflow；
- 当前工具数量还少，没有必要做 dynamic tool routing；
- 应先观察真实 Agent trajectory，再决定哪些稳定模式值得 workflow 化。

V0 让同一个 Agent 从用户原始输入开始完成整轮推理。

---

# 5. Session State

当前明确三个字段：

```python
@dataclass
class StorySessionState:
    active_work: str | None
    current_anchor: int | None
    max_seen_order: int | None
```

## 5.1 `active_work`

当前主要阅读 / 讨论的作品。

可能值：

```text
wandering_earth
support_humanity
earth_fire
```

Agent 根据用户输入、上下文和作品列表自行判断是否需要调用：

```text
set_active_work
```

## 5.2 `current_anchor`

用户当前正在看的位置。

例如用户已经读到 80，后来翻回第 30 段：

```text
current_anchor = 30
max_seen_order = 80
```

## 5.3 `max_seen_order`

用户确认已经经历过的最远位置，主要用于 spoiler boundary。

V0 不需要对状态更新做生产级严格校验；只要 Agent 能借 Story retrieval 大致定位并合理更新即可。

---

# 6. Story Memory

Story Pipeline 最终通过本地文件 / DB 与 Chatbot 通信。

```text
Offline Story Pipeline
        ↓
Local Story Store
        ↓
Python StoryMemory Adapter
        ↓
Chat Agent Tool
```

当前不需要 Story HTTP Service / MCP。

## 6.1 临时 Adapter

```python
class StoryMemory:
    def list_works(self) -> list[dict]:
        ...

    def search(
        self,
        query: str,
        *,
        work_id: str | None = None,
        max_order: int | None = None,
        top_k: int = 8,
        filters: dict | None = None,
    ) -> list[dict]:
        ...

    def get_unit(
        self,
        work_id: str,
        story_unit_id: str,
    ) -> dict | None:
        ...
```

返回 Evidence 至少包含：

```text
work_id
story_unit_id
order
text
score
metadata
```

`story_unit_id` 只是稳定剧情单元 ID，不默认等于 chunk 编号。最终含义由 Offline Pipeline 决定。

---

# 7. Agent 如何使用 Story Tool

Agent 负责自己判断：

- 当前用户是否在聊故事；
- 是否需要查 Story；
- 用什么 query 查；
- 是否需要基于 Story hit 更新 progress；
- 是否还需要再次检索前文。

例如：

```text
用户：
“我刚看到刘欣开始搞地下气化这里了，前面是不是有人劝过他？”
```

可能 trajectory：

```text
search_story("刘欣开始地下煤炭气化实验")
→ 得到当前位置候选

update_story_progress(...)

search_story("此前有人是否劝阻刘欣以及具体原因")
→ evidence

answer
```

Story Tool 的 query 是 Agent reasoning 的一部分，不由前置 Analyzer 生成。

---

# 8. Story State Tools

V0 暂定：

```text
search_story
set_active_work
update_story_progress
```

可选：

```text
list_story_works
```

作品只有三部时，也可以直接把作品清单放在 Agent context 中，不一定注册额外 Tool。

`update_story_progress` 可以接收 Story retrieval 返回的 `story_unit_id/order`。

因为这是 Demo，不需要严格证明每次 update 都完全无误；重点是让自然语言描述能够映射到一个合理剧情位置。

---

# 9. Conversation Memory：明确拆成三层

```text
Recent Context
History Memory
Notes
```

这三者不要混成一个概念。

---

## 9.1 Recent Context

当前上下文窗口里的最近若干轮消息。

用途：

```text
“我们刚才在聊什么？”
```

不需要 retrieval。

---

## 9.2 History Memory

过去对话的自动长期记忆。

大致流程：

```text
Conversation
    ↓
buffer / chunk
    ↓
达到阈值
    ↓
后台 extraction / indexing
    ↓
Persistent History Memory
```

Agent 只需要一个主要读取工具：

```text
search_memory(query)
```

历史记忆的自动写入 / chunk / extraction 不需要 Agent 每轮手动调用。

### Agent 可以多次 reformulate query

例如：

```text
“我之前是不是就说过他肯定会出问题？”
```

Agent 可以先：

```text
search_memory("用户以前认为这个角色会出问题")
```

如果召回不好，再结合：

```text
active_work = 地火
recent context = 刘欣
```

重新查询：

```text
search_memory("用户此前是否预测《地火》中刘欣的地下煤炭气化行为会造成严重后果")
```

建议每轮限制 memory search 2–3 次。

这属于小型 agentic retrieval，而不是前置 Query Analyzer。

---

## 9.3 Notes

Notes 是显式用户记忆：

```text
“帮我记一下……”
“这个点先记着”
“我猜后面……”
```

V0 直接使用本地文件即可。

Agent Tools：

```text
read_notes
write_note
```

一个 note 可以很轻：

```json
{
  "work_id": "earth_fire",
  "type": "prediction",
  "content": "用户认为刘欣的实验后面会出问题",
  "story_anchor": {
    "story_unit_id": "...",
    "order": 72
  }
}
```

`prediction` 不需要单独做 Tool，作为 `write_note` 的 `type` 即可。

---

# 10. EverOS 的定位

EverOS 只是 **History Memory Backend 候选之一**，不是整个 Conversation Memory 架构。

Chatbot 最好依赖一个 Adapter：

```python
class ConversationMemory:
    def search(self, query: str, top_k: int = 8) -> list[dict]:
        ...

    def ingest(...):
        ...

    def flush(...):
        ...
```

后端可以是：

```text
现有 prototype memory
EverOS
简单 local memory
```

先由 Codex 审计现有实现再决定是否替换。

如果接 EverOS，V0 更关注：

```text
Episode
Atomic Fact
Hybrid Retrieval
Persistence
```

暂时不急：

```text
Profile
Reflection
Foresight
Agent Case / Skill
```

避免过早把用户随剧情变化的观点压成稳定 persona。

---

# 11. 当前 Agent Tool Set

## Story / State

```text
search_story
set_active_work
update_story_progress
```

## History Memory

```text
search_memory
```

## Notes

```text
read_notes
write_note
```

## External

```text
web_search
```

加上现有 Chatbot 已经具备且仍有意义的简单工具。

---

# 12. External Web：V0 推荐 Tavily MCP

V0 把以下需求先统一为一个 Web capability：

```text
现实科学知识
概念解释
历史文化背景
作者 / 作品资料
影视改编资料
```

建议先尝试 Tavily MCP。

注意：

- 中文搜索是否足够好，需要用真实 query 做 smoke test；
- Chatbot 代码最好依赖自己的 `web_search` abstraction，不要深度绑死 Tavily；
- 如果中文召回明显不理想，再替换 backend。

示例问题：

```text
“地下煤炭气化现实里真的有人做过吗？”
“氦闪是什么？”
“刘慈欣什么时候写的《地火》？”
“《流浪地球》后来有哪些影视改编？”
```

---

# 13. 当前不做的外部工具

## 高德地图 MCP

先搁置。

以后现实题材 / 城市内容增多后，可统一覆盖：

```text
地点
POI
距离
路线
天气
```

## Recommendation

先完全搁置。

推荐需要结合：

```text
用户偏好
+ 当前作品理解
+ 外部候选
+ ranking
```

不是当前 V0 的重点。

---

# 14. Context Assembly

Agent 每轮至少可获得：

```text
System Prompt
+ Session State
+ Recent Conversation
+ Original User Query
+ Tool Observations
```

Story / Memory / Web 不需要每轮都预取；由 Agent 按需调用。

这与预定义 RAG workflow 的区别是：

> retrieval 是 Agent action，而不是每轮固定步骤。

---

# 15. Trace / Logging

必须尽量记录 Agent trajectory，后续才能判断哪些行为值得 workflow 化。

每轮建议记录：

```text
original user query
session state before
每次 tool call
每次 tool args / reformulated query
每次 tool observation
state update
final answer
session state after
```

尤其关注：

- Agent 是否不必要调用 Story；
- 是否忘记 update progress；
- 是否误更新 progress；
- search_memory 是否需要反复 query；
- 是否乱用 Web；
- 哪些调用模式高度重复。

---

# 16. V0 Eval / Bad Cases

三篇作品实际聊天测试约 20–30 个 case。

覆盖：

### Story
- 前文回忆；
- 人物动机；
- 因果；
- 模糊指代；
- 多段 evidence。

### State
- 切换作品；
- “我刚看到……”更新位置；
- 回看前文时 `current_anchor` 回退；
- `max_seen_order` 保持最远位置。

### History Memory
- 用户过去观点；
- 用户观点变化；
- 多次 reformulation 后找回旧对话。

### Notes
- 显式记笔记；
- 记录预测；
- 后续读回。

### Web
- 从小说设定延伸到现实。

至少保存 5 个 bad cases 和完整 trajectory。

---

# 17. 开发顺序

## Phase 0：本地审计现有 Chatbot

先运行 `../research/CODEX_CHATBOT_AUDIT.md`。

## Phase 1：保留原 Chat Agent

确认：

- 多轮聊天；
- function/tool calling；
- 是否支持连续 tool call；
- memory；
- tools；
- session；
- trace。

## Phase 2：接 StoryMemory

- 本地打开 Story DB / files；
- 添加 `search_story`；
- 增加三个 Story State 字段；
- 添加 `set_active_work / update_story_progress`。

## Phase 3：整理 Conversation Memory

明确：

```text
Recent / History / Notes
```

先复用已有 History Memory；不足时再评估 EverOS。

## Phase 4：Notes

实现：

```text
read_notes
write_note
```

本地文件持久化即可。

## Phase 5：Web MCP

接 Tavily，并用中文问题 smoke test。

## Phase 6：Trace + Eval

跑真实对话，根据 trajectory 再决定后续优化。

---

# 18. Future：Skills / Workflow 化

V0 不实现 Skills。

先让 Agent 自由使用工具并收集真实 trajectory；如果出现稳定、多次重复的多工具行为，再抽成 Skill / Workflow。

优先候选：

## Story Recap Skill

```text
读取 progress
→ 检索已看剧情
→ spoiler-safe recap
```

## Prediction Review Skill

```text
read_notes(type=prediction)
→ 根据 story_anchor
→ 检索现在已经看过的后续剧情
→ 判断哪些预测已经可验证
```

## Story-to-Reality Skill

```text
search_story
+ web_search
→ 明确区分 fictional setting 与 real-world evidence
→ 对比回答
```

原则：

> **先有真实重复 pattern，再 Skill 化。**

---

# 19. Future：Local Notes MCP

V0 Notes 只是 native local tools：

```text
read_notes
write_note
→ local files
```

后续如果希望 Notes 成为独立可复用能力，可以包装成：

```text
Local Companion Notes MCP
```

例如：

```text
list_notes
read_note
write_note
delete_note
```

届时可以被多个 Agent Client 共用。

当前不需要为了“更 MCP”而增加额外服务。

---

# 20. Future：Router / Tool Filtering

如果后续工具数量明显增加，或者 trace 表明 Agent 经常做出稳定的错误 tool choice，可以增加轻量 Router。

优先只做：

```text
dynamic tool exposure
```

而不是：

```text
前置改写每个 tool query
```

Agent 仍应保留具体工具调用与 query reformulation 权限。

---

# 21. MCP 总体原则

当前原则：

```text
内部、高频、与状态紧耦合
→ native tools

外部独立服务
→ MCP 优先
```

因此 V0：

```text
Native
├ Story
├ Story State
├ History Memory Search
└ Notes

MCP
└ Tavily Web Search
```

Future：

```text
高德 MCP
Local Notes MCP
其他外部服务
```

---

# 22. V0 Definition of Done

- [ ] 已审计现有 Chatbot；
- [ ] 保留一个主要 Chat Agent Loop；
- [ ] Agent 支持连续、多工具调用；
- [ ] 有最大 tool-call 边界；
- [ ] 接入本地 StoryMemory；
- [ ] 支持 `active_work / current_anchor / max_seen_order`；
- [ ] 支持 `search_story / set_active_work / update_story_progress`；
- [ ] History Memory 可通过 `search_memory` 查询；
- [ ] Agent 可自行 reformulate memory query；
- [ ] Notes 有 `read_notes / write_note`；
- [ ] Web Search 可用；
- [ ] Story / History / Notes 三类记忆边界清楚；
- [ ] 保存基本 Agent trajectory；
- [ ] 三篇小说完成实际聊天测试；
- [ ] 至少记录 5 个 bad cases；
- [ ] V0 不新增独立 Query Analyzer / Router / State Tracker。
