# 阅读手账：修订、删除与进度回看

更新：2026-10-03。本轮实现于nanobot业务薄层，不增加工具数／独立模型调用。

## 1. 产品用途与边界

手账存用户明确要留下的作品感受、问题和预测，而不是剧情事实。Note保存剧情外交互约定；checkpoint负责近期讨论交接；日经历保留压缩后的互动经过。四者不自动双写。读到新线索时，AI应把“你当时怎么想”与当前依据对照，而非重复剧情、替作品圆场或静默修正旧预测。

## 2. 工具输入与输出

仍为`search_reading_journal`、`save_journal_entry`两个公开工具，白名单共12项。

| 调用 | 输入 | 输出／处理 |
| --- | --- | --- |
| search_reading_journal | query可选，work_id可选 | 当前owner／作品／完整已读范围下的安全版本；正文包含匹配，最近20项、total、truncated。不是语义检索 |
| save_journal_entry 默认add | entry_type=reaction/question/prediction，content，work_id可选，source_quote可选 | 新条目id、正文、创建时间、阅读位置、来源。未知位置记0，不推进进度 |
| save_journal_entry revise | action=revise、entry_id、content、source_quote；work_id可选 | 原ID及类型不变，原版本入revisions；新正文带新的时间、阅读位置、会话／回合／用户摘录。不能在更早或无确认范围修订后期条目 |
| save_journal_entry delete | action=delete、entry_id、source_quote；work_id可选 | status=deleted或absent；删除该owner／作品下整条手账及其版本。重复删除安全，absent不表示成功找到他人记录 |

写入参数不允许客户端指定owner或阅读边界。revise/delete必须有可信本轮turn_id，source_quote是本轮用户原话的非空逐字子串（最多500字符）；这只证明引用存在，不能自动证明用户授权语义，仍由主Agent规则判断“明确要求”。新增兼容旧调用，source_quote可选；新增意图主要由提示规则约束，不能宣称机器强制确认。

先查到唯一entry_id；用户只说“有点猜错了”不是自动修订许可。新增／修订content最多2000字符。action参数缺省add，条件必填项由执行器验证；Tool JSON Schema没有强制嵌套工作流。单回合稳定操作摘要去重，revision重试不重复存版本；变更内容视为新操作，不提供跨文件事务／并发版本锁。

## 3. 持久化与防剧透

每用户一份`.storypal/reading_notebook/<owner哈希>.json`，原子替换；重启恢复。每次修订保留原快照及各自anchor_order；查询按当前边界投影最后一个可见版本，历史版本也按边界过滤。比如10时的猜测在20时被修订，重置到10只返回10时的原观点，不附20时正文。该规则仅约束手账读取，不能擦掉已见的对话／摘要／日经历。

删除移除手账条目和全部revision，不留同库软删除正文。旧聊天、checkpoint、trace、日经历可能仍有原话；不能对用户声称“系统全部遗忘”。完整隐私删除链为TODO。

## 4. 进度推进后的回看候选

`search_reading_journal`的runtime_context_provider挂一个轻量JournalReviewObserver；每轮只读本地进度和小JSON。首次仅建立owner＋work基线，不回扫启用前旧历史。后续完整已读order增长时，下一用户回合准备至多3个open问题／预测、正文合计1800字符，带旧锚点和新增已读区间。超过预算整项跳过；近创建条目优先，不保证全手账公平覆盖。段内滚动／未确认提议／同order段尾推进不触发。

候选与游标分别存`.storypal/journal_review/<owner哈希>.json`（游标无正文）及原手账；无新进度不重复注入，重启游标恢复。块replay=false，轨迹存储保留，旧快照不回放。进度重置降低order时只重设基线，不注入后期观点。准备失败不撤销进度，提示失败不伪装语义核验成功。

这是**延后到下一回合的候选准备，不是独立后台模型校验**。主Agent按当前聊天选择是否回应：相关时结合新故事视图；缺具体依据才查证；情绪暂停不强推。没有证据不宣布推翻，不自动改status或手账。首次启用不触发历史检查，模型失败／用户打断时游标可能已经消费；不保证必达，显式查询仍可恢复。持久任务、语义相关筛选、可追溯的独立复核结果与用户确认后归档是后续包，不能把当前提示当成“预测已核验”。

## 5. 验证与下一步

定向49/49、8.68s：手账生命周期12项及既有工具、bootstrap、Skill、人格、runtime回放、白名单。原生Loop＋替身provider两回合验证只新增候选不新增模型调用，第二回合旧候选消失。全部人工合成，无真实小说／用户聊天、Embedding、GPU或真实provider请求；不宣称模型理解／自然度通过。

真人方法见[手账验收](../operations/READING_JOURNAL_ACCEPTANCE.md)。下一步先核验候选是否有帮助，再做可追溯的异步复核；保留原预测，用新增已读证据记录支持／削弱／仍未知，而非自动给唯一文学答案。
