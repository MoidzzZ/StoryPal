# 进度驱动的手账异步复核

更新：2026-10-03。代码`journal_recheck.py`，运行入口仍是`search_reading_journal`的runtime provider，不加工具、不迁移框架。状态：程序接通，已通过1条授权合成场景的真实复核＋主Agent承接；复杂语义未验收，默认关闭。

## 1. 业务契约

读者可能先猜“她救人不意味着认可实验”，后来读到新行动。系统要记住当时的判断，补新依据并允许理解变化，而不是事后把旧预测换成正确答案。

- 原手账继续保存用户明确表达；复核结果独立存，永远`provisional=true`。
- `supports`表示当前提供材料支持原想法，`weakens`表示出现削弱它的依据，`unknown`表示本次材料不足；不是最终对错。问题类条目也只作为证据帮助／不足，不声称得到唯一答案。
- 只使用已确认完整单元边界，不读取未读内容。情绪暂停时不强推报告；用户明确要求才修订原手账。

## 2. 简单工作流

1. 旧JournalReviewObserver首次建立基线；完整已读order增长后的下一轮，产生最多3条／1800正文字符旧问题或预测。段内位置变化、未确认提议不触发。
2. 只有`STORYPAL_AUTO_JOURNAL_REVIEW=1`且真实websocket请求具有owner／会话／回合和允许的Luna runtime时，将候选与原条目版本摘要排队；不接受模型提供owner或进度。
3. `.storypal/journal_rechecks/<owner哈希>.json`保存pending作业和reviews。一次用户观察最多启动该owner一批；同owner在途不会重复启动。首版不主动定时轮询，关闭开关不为新进度积压作业；重新开启可继续已存在pending。
4. asyncio后台线程调用明确FTS故事路径（可能有既有扫描回退），每条直接用手账content检索；复用服务端过滤和原ContextPacker。此处尚无语义query改写或检索算法改进，不暗示稳定召回。
5. 合并最多5个原文单元，原文总前缀6000字符、单元前缀1800字符；不发送summary，纯分隔符／空正文不作剧情证据。JSON、规则和候选另占tokens，字符上限不是完整请求token预算。
6. 一次provider.chat逻辑调用，无工具、无外层自动重试，输出JSON reviews。目标max_tokens=1600不代表当前Codex provider的服务端输出硬上限；底层传输仍可能重发，不承诺物理网络恰好一次。
7. 严格验证目标恰好覆盖候选且不重复、analysis≤400字符、最多5条短引文（每条≤200字符，逐字来自本次可见前缀）。supports／weakens至少引用一条新已读范围的原文；引文存在不证明分析语义正确。
8. 在取证后、模型后、来源复核后检查当前owner／作品／进度及条目版本。用户修订／删除、重置或换作品使旧作业superseded；原文核心字段hash改变使作业failed。检索score不同不算原文变化。
9. 一份JSON原子替换写入completed结果。主Agent下一回合最多收到一个未通知完成项（replay=false）；显式查询返回仍匹配当前版本／边界的最近3条reviews。不自动改原手账、Note、经历、SOUL／USER或StoryMem。

## 3. 结果字段与溯源

`review_id/job_id/entry_id/entry_revision/work_id/previous_order/max_order/status/analysis/evidence_refs/reviewer/provisional/created_at/source_session/source_turn_id`。每个引用保留`unit_id/order/quote/source_digest`；会话标识哈希化，原条目ID＋版本摘要指向该用户手账版本。

事实源版本按work、unit、order、raw_text生成，不使用排序score；保存前再次读同单元校验。来源变化后不会自动重写旧结果，但历史reviews只代表当时来源，不保证日后数据修改后仍成立；重新取原文时需要核对。

## 4. 失败、恢复和限制

- 网络／解析／非法引用／模型未完整结束等标failed，只保存错误类别，不反复每轮重试；下一次新进度可产生新作业。首版没有失败重试UI。
- 任务取消／进程中止保留pending，重启后下一用户请求可恢复，可能再发请求。completed状态与稳定作业ID防重复保存，不等于外部模型调用幂等。
- 存档损坏不覆盖；失败不撤销已确认进度。候选游标与作业队列不是跨文件事务，排队前后断电仍可能漏事件，显式手账查询兜底。
- 进度回退隐藏后期review；手账修订／删除后旧review不作为当前结果返回，但旧作业／review可保留审计正文。删除手账并未完整删除这些历史、聊天或经历，完整隐私删除仍TODO。
- 首版FTS未必找齐相关材料；unknown不表示原文没有。没有多轮Agentic查询、相关性门控、ANN、持久任务框架或完整并发控制。
- 代码默认关闭，正式运行环境未启用；首轮程序接线没有真实模型或Embedding调用，后续两次合成真实验收详见下节；均没有真实用户资料／小说发送。正式启用前仍需单独核验材料范围和调用预算。

## 5. 验收

程序覆盖独立结果、原观点不变、owner／作品／已读隔离、quote／目标／输出校验、无新证据不能支持或削弱、空检索unknown、重启pending恢复、取消、在途改条目／原文／进度、重复观察、损坏队列、完成通知不回放。全部人工合成原文和替身provider，真正服务和packer接线，不代表模型语义准确率。

已按用户新授权完成2次GPT-6 Luna物理请求：复核1次＋原生主Loop承接1次。新合成工作区手动设进度10→12，合成Backend供证；保存supports＋新原文quote，主Agent收到实际review并保留暂定、不改手账。前后进度和原条目相同，正式开关仍关闭。脚本`chatbot_tests/manual_journal_recheck.py`缺省只离线检查，显式授权参数及新run-name才能外发，传输账本每阶段限1／总2、禁止重发；该守卫只用于此验收，不代表生产provider具备相同硬上限。详见[结果](../../result.md)。

连续长聊／压缩／跨会话、真实FTS召回及复杂预测另验；本次未注册写工具，不证明模型主动写入权限判断已通过。用户评价“有没有帮助”比自动支持标签更重要，不因小样成功自动开启后台。
