# CODEX：已有 Chatbot 本地核验与改造决策任务

> 将本文件放到现有 Chatbot 仓库根目录交给 Codex。  
> **第一轮只做代码审计、smoke test 和开发建议，不要立刻大规模重构。**

---

# 0. 项目背景

这是一个已经存在的 Chatbot 原型，已知过去实现过：

- 基本聊天；
- memory；
- 一些简单 tools。

现在要把它扩展成“剧情陪伴 AI”。

另一位开发者负责 Offline Story Pipeline，并会输出一个本地静态 Story Store。Chatbot 直接通过本地文件 / 数据库读取，不需要 HTTP Story Service。

当前 V0 架构已经确定：

> **优先保留一个 Chat Agent，由它基于原始用户输入、对话上下文、session state 和 tool observations 动态选择工具，并可多步闭环调用。**

请不要默认增加 Query Analyzer / Router / State Tracker。

---

# 1. 你的任务

请完成：

1. 核验仓库当前真实能力；
2. 找出 Chat Agent / Chat Loop 主路径；
3. 找出现有 memory 的读写与 retrieval；
4. 找出 tool calling / dispatch；
5. 判断是否已经支持“Tool Result → 再次 LLM → 再 Tool”的多步 loop；
6. 判断如何以最小修改接入 StoryMemory；
7. 判断如何加入 Story Session State；
8. 判断现有 memory 是否继续使用，还是需要 Adapter / EverOS；
9. 判断 Notes 本地文件工具如何加入；
10. 判断现有工具系统如何接 Tavily MCP / Web Search；
11. 给出最小改造方案；
12. **不要因为偏好某个 Agent Framework 而重写整个项目。**

---

# 2. 先完整阅读仓库

请检查：

- README；
- dependency files；
- `.env.example` / config；
- 主入口；
- API server / UI；
- model client；
- system prompt；
- conversation/session state；
- memory；
- tools；
- tests；
- logging / tracing。

允许使用：

```bash
find
rg
grep
tree
pytest
```

如果可以安全运行，请进行最小 smoke test。

不要修改真实 secret。

---

# 3. 输出真实代码架构

不要猜测，请根据实际代码画出：

```text
Entry
→ Chat Handler
→ Context Build
→ Model Call
→ Tool Call
→ Tool Result
→ Model Call Again ?
→ Response
→ Memory Write ?
```

对每一步列出：

```text
文件路径
类 / 函数名
当前职责
```

---

# 4. 重点核验：当前到底是不是 Agent Loop

请回答：

1. 每轮消息从哪里进入？
2. Agent / model 是否看到完整 recent conversation？
3. system prompt 在哪里构造？
4. model provider 是什么？
5. 是否 streaming？
6. tool calling 是否原生 function calling？
7. tool result 如何回传给模型？
8. 一轮是否允许连续调用多个 tool？
9. 是否存在：

```text
LLM
→ tool
→ observation
→ LLM
→ another tool
→ ...
→ answer
```

10. 当前最大 tool calls / retry 限制是什么？
11. 如果没有 bounded loop，最小修改如何加入？
12. tool failure / timeout 如何处理？
13. 是否 async？

如果当前只是：

```text
单次模型调用
→ 一个 Tool
→ 直接回答
```

请明确指出它距离 V0 Agent Loop 还缺什么。

---

# 5. 不要新增 Query Analyzer / Router / State Tracker

当前 V0 不希望变成：

```text
Query Analyzer
→ Router
→ Tool Workflows
→ Generator
```

也不希望：

```text
State Tracker
→ Agent
```

理由是 Story 状态判断本身往往依赖 Story retrieval，拆出去容易重复一遍 Agent reasoning。

当前希望：

```text
Original User Query
+ Recent Context
+ Session State
        ↓
     Chat Agent
        ↓
动态 Tool Calls
        ↓
Final Answer
```

如果你认为当前代码确实必须拆 workflow，请给出具体代码证据和原因。

---

# 6. Story Session State

需要在现有 session / conversation state 中加入：

```text
active_work
current_anchor
max_seen_order
```

含义：

```text
active_work
= 当前主要阅读 / 讨论的作品

current_anchor
= 用户当前正在看的剧情位置

max_seen_order
= 用户确认已经看过的最远剧情位置
```

例如用户读到 80 后翻回前文：

```text
current_anchor = 30
max_seen_order = 80
```

请判断：

- 当前 session state 在哪里；
- 如何最小修改增加字段；
- 是否需要持久化；
- 当前 Demo 里放内存 / local file / DB 哪个最合适。

不需要生产级事务安全。

---

# 7. StoryMemory 临时接口

不要自行设计 Offline Story DB 内部结构。

暂时只假设：

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

返回至少包含：

```json
{
  "work_id": "earth_fire",
  "story_unit_id": "stable-id",
  "order": 72,
  "text": "...",
  "score": 0.9,
  "metadata": {}
}
```

`story_unit_id` 只是稳定剧情单元 ID，不要假设它就是 chunk number。

Story Pipeline 会自行探索最终存储形态。

---

# 8. 需要新增的 Story / State Tools

请判断当前 Tool Registry 中最小接入方式。

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

Agent 应能做到：

```text
用户自然语言描述当前位置
→ search_story 找剧情位置
→ observation 含 story_unit_id/order
→ 判断是否确实表达了阅读进度
→ update_story_progress
```

这是 Agent 自己的 tool trajectory，不需要单独 State Tracker。

因为是 Demo，不需要做复杂严格校验。

---

# 9. 重点核验现有 Memory

请从代码回答以下问题。

## 9.1 写入

- 每轮都写吗？
- 写 raw message / chunk / summary / fact？
- 什么时候触发？
- 是否异步？
- 是否持久化？

## 9.2 存储

- memory only？
- JSON / Markdown？
- SQLite？
- Vector DB？
- 其他？

## 9.3 Retrieval

- embedding？
- BM25？
- metadata？
- top-k？
- rerank？
- raw user query 直接搜？
- 有无 query rewrite？

## 9.4 Context

- memory hits 如何进入 prompt？
- 和 recent conversation 如何组合？
- 是否有 token budget？

## 9.5 Maintenance

- chunk / summary / extraction？
- update / merge / delete？
- profile？
- conflict handling？

---

# 10. Conversation Memory 最终逻辑分层

无论现有代码怎么写，改造后希望概念上区分：

```text
Recent Context
History Memory
Notes
```

## Recent Context

当前几轮，直接进上下文。

## History Memory

自动长期处理和 RAG。

Agent 读取工具：

```text
search_memory(query)
```

Agent 应允许根据第一次 retrieval observation 自己改写 query 再搜一次。

V0 可以限制一轮最多 2–3 次 `search_memory`。

## Notes

显式本地笔记，由 Tool 读写：

```text
read_notes
write_note
```

预测可以表示成：

```text
write_note(type="prediction", ...)
```

而不是另做一个 Prediction Tool。

---

# 11. ConversationMemory Adapter

请判断现有 memory 是否容易抽成类似：

```python
class ConversationMemory:
    def search(self, query: str, top_k: int = 8) -> list[dict]:
        ...

    def ingest(...):
        ...

    def flush(...):
        ...
```

后续 backend 可能是：

```text
现有 memory
EverOS
简单 local backend
```

Chat Agent 主流程不要深度依赖某一个 memory SDK。

---

# 12. EverOS 评估原则

不要默认必须接 EverOS。

### Case A：现有 memory 已够用

如果已经有：

- persistence；
- chunk / extraction；
- retrieval；
- 相对干净的接口；

则优先复用。

### Case B：现有 memory 很弱

例如：

- 只有 recent history；
- 没持久化；
- 没 retrieval；
- 很难维护；

再评估 EverOS。

### Case C：部分可用

先包 Adapter，再逐步替换。

如果使用 EverOS，V0 优先考虑：

```text
Episode
Atomic Fact
Hybrid Retrieval
Persistence
```

不要急着上 Profile / Reflection / Foresight。

---

# 13. Notes 本地工具

请提出最简单可靠的实现。

可以是：

```text
notes/
├ general.jsonl
├ wandering_earth.jsonl
├ support_humanity.jsonl
└ earth_fire.jsonl
```

或其他更适合当前项目的形式。

最低工具：

```text
read_notes
write_note
```

Note 最好可带：

```text
work_id
note_type
content
story_anchor
created_at
```

V0 直接 native local tool，不要实现 MCP Server。

---

# 14. External Web / MCP

V0 希望提供一个统一 `web_search` 能力。

候选：Tavily MCP。

请判断现有工具系统：

- 是否已经支持 MCP；
- 如果不支持，接一个 MCP client 的改动多大；
- 是否更适合先写 native wrapper；
- 如何保持 `web_search` abstraction，避免主流程绑死 Tavily。

接入后需要对中文 query 做 smoke test。

当前不需要高德地图和推荐系统。

---

# 15. Tools 总表

请核验现有 tools 后，给出如何合并到以下目标能力：

```text
Story / State
- search_story
- set_active_work
- update_story_progress

History Memory
- search_memory

Notes
- read_notes
- write_note

External
- web_search

Existing Useful Tools
- 保留真正有用的现有功能
```

不要为了数量增加工具。

---

# 16. Trace / Logging

请检查当前是否已有：

- logger；
- request / session id；
- model trace；
- tool trace；
- memory trace。

V0 希望至少保存：

```text
original user query
session state before
LLM tool call
Tool arguments
Tool result
如果 Agent 改写 query，保留新 query
state update
final answer
session state after
```

这非常重要，因为后续是否增加 Router / Workflow / Skill 要根据真实 trajectory 决定。

---

# 17. Tests

查找已有 tests。

如果没有，开发计划至少加入：

## Unit

- StoryMemory mock；
- session state；
- notes read/write；
- memory adapter；
- max tool-call stop。

## Integration

- 单次 story retrieval；
- `search_story → update_story_progress → answer`；
- multi-tool call；
- `search_memory` query reformulation；
- notes write/read；
- web call；
- basic no-spoiler case。

第一轮审计不要直接生成大量测试代码。

---

# 18. Future：不要现在实现，但架构要能容纳

后续可能增加：

## Skills

- Story Recap Skill；
- Prediction Review Skill；
- Story-to-Reality Skill。

这些应从真实重复 trajectory 中抽取，不是现在先写。

## Local Notes MCP

未来可把 native Notes Tools 包成独立 Local MCP Server。

## 高德 MCP

现实地点 / 路线 / 天气需求变多后再接。

## Router / Dynamic Tool Exposure

工具很多、tool choice 出现稳定错误后再增加。

不要在 V0 提前实现。

---

# 19. 最终输出两个文件

## `CHATBOT_AUDIT.md`

必须包含：

### A. Current Architecture
真实代码结构和调用路径。

### B. Existing Capabilities
逐项说明：

- chat；
- Agent / tool loop；
- memory；
- tools；
- persistence；
- session；
- streaming；
- tracing；
- tests；
- MCP capability。

### C. Problems / Risks
按：

```text
Blocker
High
Medium
Low
```

### D. Reusable Components
明确哪些应该保留。

### E. StoryMemory Integration Point
说明最小接入位置。

### F. Memory Assessment
现有 History Memory：

```text
保留 / 改造 / 替换 / 需要进一步测试
```

### G. Agent Loop Assessment
当前是否支持真正的多步 Tool Observation 闭环。

---

## `CHATBOT_DEVELOPMENT_PLAN.md`

按照最小改造优先：

```text
Phase 0
目标
涉及文件
新增文件
风险
验收

Phase 1
...
```

至少覆盖：

1. 保留 / 修复 bounded Agent Loop；
2. StoryMemory 接入；
3. Story Session State；
4. Conversation Memory Adapter；
5. Notes；
6. Web Search / MCP；
7. Trace；
8. Integration Tests。

---

# 20. 最终 Decision

审计结束后明确选一个：

```text
A. 在现有架构上直接扩展
B. 保留核心 Chat Loop，局部重构 Memory / Tools / State
C. 现有代码质量较差，建议局部重写
D. 必须重写 Chatbot
```

**D 必须有充分代码证据才能选择。**

---

# 21. 工程原则

1. 不猜测代码能力；
2. 所有判断引用真实文件 / 函数；
3. 不因为现代框架更潮而迁移；
4. 最小修改优先；
5. 保留一个主要 Chat Agent；
6. 不新增独立 Query Analyzer / Router / State Tracker，除非代码事实证明必要；
7. Story Memory 与 Conversation Memory 分离；
8. History Memory 与 Notes 分离；
9. Story schema 不锁死；
10. Memory backend 不锁死；
11. 内部状态能力优先 native tools；
12. 外部独立服务再考虑 MCP；
13. V0 是 Demo，不做生产级过度工程；
14. 后续是否 Workflow / Skill 化，要根据真实 Agent trace 决定。
