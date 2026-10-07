# 工作电脑快速接手指南

更新/本地核对：2026-10-08（Asia/Shanghai）。范围：整个 StoryPal 项目及检索优化研究。先读根目录[从这里开始](../../START_HERE.md)，无需先重跑历史模型实验。

## A. 选一条接手路径

| 目的 | 最小准备 |
| --- | --- |
| 了解进度/继续改代码 | 克隆主仓库，读 START_HERE 与相应设计/实验报告 |
| 跑隔离程序测试 | Python 3.12环境、固定nanobot加九个补丁、chatbot集成包及相应测试依赖 |
| 跑阅读器和故事检索 | 上述代码，再恢复私有 `story_mem/data/wandering_earth/`；FTS模式无需Embedding权重 |
| 续接自己的旧聊天/记忆/进度 | 完整迁移实例目录（包括配置旁的sessions和workspace）、恢复浏览器client-id；在新机重新登录 |
| 分析已完成检索实验 | 公开报告/聚合JSON即可读结论；逐例分析需私下恢复同源排名/分数/账本，不新增评分 |

以下部署步骤核对的是Windows PowerShell。推荐新电脑也用 `D:/StoryPal` 和原模型路径，减少会话命名空间与索引模型路径差异。换盘时按D节修改路径。首次新机完整启动尚未在第二台真实电脑执行；本次已验证固定源码的补丁重放、配置构造与文档命令入口。

## B. 恢复公开代码和构建环境

### B1. 固定三个代码来源

新机先安装Git、Conda和Bun，建立Python 3.12环境。后续每步失败即停止并修正，不继续带错安装。Git/Bun/Conda安装方式按本机公司环境处理。以下假设 `D:/StoryPal` 尚不存在：

```powershell
git clone https://github.com/MoidzzZ/StoryPal.git D:/StoryPal
Set-Location D:/StoryPal
conda env create -f ./chatbot/environment.yml
conda activate storypal-chatbot

git clone https://github.com/Pilgrimage19/offline-story-pipeline story_mem
git -C story_mem checkout --detach f60c987414992be56c1b5b1ec68d7ff963c35d17

New-Item -ItemType Directory -Force .runtime
New-Item -ItemType Directory -Force .runtime/nanobot
git clone https://github.com/HKUDS/nanobot.git .runtime/nanobot/source-build
git -C .runtime/nanobot/source-build checkout --detach 9ecdc4533f935bfd7cae9b8cbe651e77eec07cd7
```

主仓库使用最新master，包含2026-10-05实验提交 `ba47d2f` 及本次交接更新。StoryMem固定版本包含渐进视图与Evidence名称线索；后续若升级，先运行受影响测试并更新版本清单。以上checkout只用于刚克隆的目录，已有工作目录先检查未提交改动。

### B2. 按顺序打九个补丁

在主仓库根目录执行，遇到错误立即停止：

```powershell
$ProjectRoot = (Get-Location).Path
$PatchedSource = Join-Path $ProjectRoot '.runtime/nanobot/source-build'
$PatchNames = @(
  'storypal-persona-view.patch',
  'storypal-dream-write-allowlist.patch',
  'storypal-tool-allowlist.patch',
  'storypal-reader.patch',
  'storypal-paragraph-markers.patch',
  'storypal-codex-model-catalog.patch',
  'storypal-runtime-context-replay.patch',
  'storypal-reading-checkpoint.patch',
  'storypal-empty-tool-registry.patch'
)
foreach ($PatchName in $PatchNames) {
  $PatchPath = Join-Path $ProjectRoot "patches/nanobot/$PatchName"
  git -C $PatchedSource apply --check $PatchPath
  if ($LASTEXITCODE -ne 0) { throw "补丁检查失败：$PatchName" }
  git -C $PatchedSource apply $PatchPath
  if ($LASTEXITCODE -ne 0) { throw "补丁应用失败：$PatchName" }
}
```

`.runtime/nanobot/source-build`必须有自己的Git根（上一步clone即有），不要把裸源码拷贝到主仓库子目录后直接执行 `git apply`，它可能按父仓库路径跳过补丁。重复执行补丁会失败；不要跳过报错继续安装。

本次从固定commit导出隔离源码、建立独立Git根，九个补丁全部成功重放，涉及27个文件；遍历固定源码与本机运行副本，没有缺文件或额外Python/TypeScript源文件。归一化CRLF后只差一处Python注释和两个TSX末尾空行，没有可执行源码差异。人格页补丁已有两条EOF空行告警，未阻止应用。哈希见[清单](WORK_COMPUTER_MANIFEST.json)。不需复制有历史修改的 `.reference/nanobot`。

### B3. 安装并构建WebUI

```powershell
python -m pip install -e './.runtime/nanobot/source-build[api]'
python -m pip install -e './chatbot[episodic]'
python -m pip install -r ./story_mem/code/requirements-vector.txt

Push-Location .runtime/nanobot/source-build/webui
try {
  bun install --frozen-lockfile
  if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
  bun run build
  if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
} finally { Pop-Location }

python -m pip show nanobot-ai storypal-chatbot
python -c "import nanobot, storypal_chatbot; print(nanobot.__file__); print(storypal_chatbot.__file__)"
python -m pip check
Test-Path .runtime/nanobot/source-build/nanobot/web/dist/index.html
```

`nanobot`导入路径必须指向补丁副本，`storypal_chatbot`指向本仓库chatbot。同名 `nanobot-ai 0.3.0` 的PyPI包不能代替补丁源码。仅FTS体验可暂不安装episodic/vector依赖，经历语义回忆届时不可验收。

本机观察到的包版本写在清单中，属于环境记录，不是完整依赖锁；安装声明仍以各pyproject/requirements为准。算法真实jieba路线还需要 `jieba==0.42.1`、资源观察需psutil，Qwen需torch/transformers；只读报告无需安装这些。不要为接手默认下载或重新加载模型。

## C. 恢复故事数据、权重与已有实验

### C1. 从旧电脑私下拷贝

先停止旧机的实例或在无写入窗口做一致快照。使用可信的私有传输/移动硬盘，数据不进入公开Git：

| 旧机路径 | 目的与恢复要求 |
| --- | --- |
| `D:/StoryPal/story_mem/data/wandering_earth/` | 拷贝整个作品目录，保留01_normalized、02_segmented、03_extracted、渐进状态、05_index等。不要只拷一份story.db |
| `D:/StoryPal/story_mem/raw_text/` | 后续重跑离线处理才需要原始输入；阅读器读取已有分段/规范化产物，不直接读取这个目录 |
| `D:/StoryPal/.runtime/nanobot/storypal/workspace/` | 包括自定义人格、prompts、skills、隐藏身份文件和`.storypal/`内进度、手账、Note、经历、索引和水位 |
| `D:/StoryPal/.runtime/nanobot/storypal/sessions/` | JSONL原始聊天与运行checkpoint，位于config旁，不在workspace里；整目录保留命名空间及`.workspace`标记 |
| `D:/StoryPal/.runtime/nanobot/storypal/webui/`、`media/` | 如需恢复界面历史/附件，一并私下拷贝存在的目录 |
| `D:/StoryPal/.runtime/nanobot/storypal/config.json` | 已有设置含敏感信息；可私下恢复后审查绝对路径，在新机重新登录。也可按D节创建独立新实例 |
| `D:/models/BAAI/bge-m3/` | Dense故事检索和经历回忆的本地模型；完整拷贝模型/Tokenizer等文件 |
| `D:/models/Qwen/Qwen3-Reranker-0.6B/` | 仅离线重排研究使用，运行Chatbot无需此模型 |
| `D:/StoryPal/.runtime/retrieval-experiments/` | 若继续逐例分析/续跑，完整保留排名、严格得分、队列、进度和预算账本；含私有材料，不提交Git |
| `.runtime/isolated/`中需要的批次 | 可选私下保留原始合成验证trace；阅读公开结果报告无需这些 |

根目录原始规划附件（`StoryPal_项目深化开发规划.docx`、`RAG全链路增强_5h+Agent记忆系统_StoryPal代码审计版.pdf`、`Agent_Harness_v2_核验清单与预期目标.md`）以及`output/`中的历史导出未纳入代码仓库；需要原始附件时可私下迁移。当前可追踪的需求、架构、验收与讲述版本以docs及result.md为准。

实例目录中logs/进程锁/后台进程状态不作为新机可用服务恢复；从停机备份恢复数据后由新机正常启动。不要把旧Conda环境、node_modules、前端构建输出和旧机后台进程当成可迁移安装。

### C2. 核对同一事实源

```powershell
(Get-FileHash ./story_mem/data/wandering_earth/03_extracted/units_extracted.jsonl -Algorithm SHA256).Hash.ToLower()
```

实验源必须是108单元，SHA256应为：

```text
30196aab51d91b5c5b564517d6e3f32933bbf9cc4edcf23dd230cc7a19c83c6b
```

阅读器还需要 `02_segmented/units.jsonl`、`01_normalized/text.txt` 和 `01_normalized/meta.json`，并校验段落行号与正文一致。渐进视图缺有效快照时不能注入最终全书状态。缺这些应恢复备份，不能用mock抽取替换当前正式实验源。

现有 `05_index/vectors.lance`及其元数据一起恢复。故事查询Embedding模型名来自索引元数据；仅改 `STORYPAL_EPISODE_MODEL` 不会改故事索引中的模型路径。优先保持旧 `D:/models/BAAI/bge-m3`，改路径时先检查实际元数据和模型身份，不伪改来源hash。恢复不了模型时先设FTS模式。

BGE官方revision与Qwen完整文件SHA清单在[版本清单](WORK_COMPUTER_MANIFEST.json)。Qwen完整身份SHA为 `0180200f7b2a476c9be0c4a5bd9a8278a703552d5d9b483d65a7d3c8659d23cd`；旧100对试运行分数不满足完整身份证明，不能混入严格570对。

### C3. 实验接手无需重新消耗计算

[公开聚合快照](../research/retrieval/RESULTS_SNAPSHOT_2026_10_05.json)包含六路、60种固定装包配置和十种同池Qwen配置的分组指标、改善/损失及成本，不含逐对运行分数或原文。这是既有结果导出，不是2026-10-08新实验。

需要逐例分析时，恢复本地 `.runtime/retrieval-experiments/`，按版本清单核对关键文件SHA。在资料齐全后，下面仅分析既有严格分数，不加载神经模型：

```powershell
python -X utf8 -m retrieval_experiments.score_queue analyze --queue .runtime/retrieval-experiments/qwen-expanded-20261004.queue.json --output .runtime/retrieval-experiments/qwen-analysis-work-computer-new.json
```

输出使用新名字，不覆盖已有文件。缺排名/原文/完整模型身份文件时先恢复，不能假造缓存或让analyze变成run。当前57问/570对已完整结束；600尝试/1200评分秒是原全局上限，已用570次/1002.636152秒。迁移不创建新预算，也不要求补齐600次；保留原队列、分数、events和所有模型请求账本，不清零/换队列来恢复额度。

## D. 配置新机并启动

### D1. 路径环境

每个启动服务的终端先执行（修改为本机实际路径）：

```powershell
conda activate storypal-chatbot
Set-Location D:/StoryPal
$StoryPalConfig = Join-Path (Get-Location).Path '.runtime/nanobot/storypal/config.json'
$StoryPalWorkspace = Join-Path (Get-Location).Path '.runtime/nanobot/storypal/workspace'
$env:STORYPAL_STORY_ROOT = Join-Path (Get-Location).Path 'story_mem'
$env:STORYPAL_PIPELINE_CODE_PATH = Join-Path $env:STORYPAL_STORY_ROOT 'code'
$env:STORYPAL_STORY_DATA_ROOT = Join-Path $env:STORYPAL_STORY_ROOT 'data'
$env:STORYPAL_STORY_RETRIEVAL = 'fts'
$env:STORYPAL_EPISODE_MODEL = 'D:/models/BAAI/bge-m3'
$env:STORYPAL_AUTO_NOTE = '0'
$env:STORYPAL_AUTO_EPISODE = '0'
$env:STORYPAL_AUTO_JOURNAL_REVIEW = '0'
```

这是新机安装核对阶段的FTS/后台关闭设置，避免初次带入旧会话后触发维护模型调用；不表示生产默认被算法改为FTS。实际产品默认故事检索auto、自动Note/经历维护开启、异步手账复核关闭。上述环境只在当前终端有效，后台服务继承启动时环境，改变后需重启。

模型与向量元数据恢复核对完毕，再将 `STORYPAL_STORY_RETRIEVAL='auto'`；auto可回退FTS/扫描，要检查实际路线。故事生产Embedding未显式固定CPU，会依环境选择设备；实验强制CPU不等于生产设备已改。经历回忆默认阈值0.55/token预算1000，尚未标定。

### D2. 二选一：恢复旧实例或创建新实例

**恢复旧实例：**完成C节私下迁移，检查配置内workspace绝对路径，保留人格/手账/Note和已有workspace身份。不要重新运行 `--force-persona`。建议先在新机配置的 `agents.defaults.dream.enabled` 设为false，安装核对完后按需要恢复；别修改旧机正式配置。若同盘同路径恢复，命名空间最容易保持一致。

**创建全新实例：**以下仅用于config尚不存在的情况（已有时停止，避免覆盖）。

```powershell
python -c "from pathlib import Path; from nanobot.config.schema import Config; from nanobot.config.loader import save_config; p=Path('.runtime/nanobot/storypal/config.json'); assert not p.exists(), 'config already exists'; p.parent.mkdir(parents=True, exist_ok=True); save_config(Config(), p)"
storypal-chatbot-configure --config $StoryPalConfig --workspace $StoryPalWorkspace --luna-only
python -c "import json; from pathlib import Path; p=Path('.runtime/nanobot/storypal/config.json'); d=json.loads(p.read_text(encoding='utf-8')); d['agents']['defaults']['dream']['enabled']=False; d['gateway']['host']='127.0.0.1'; d['gateway']['port']=18790; p.write_text(json.dumps(d, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')"
```

配置器默认GPT-6 Luna，手动可选GPT-5.6 Luna，medium、最多6轮工具迭代、无自动回退、12项业务工具；正常Dream固定6 Luna，上述安装核对阶段暂时禁用。全新实例没有旧进度和个人记忆。

### D3. 新机登录、启动与只读检查

```powershell
nanobot provider login openai-codex --config $StoryPalConfig
nanobot webui --yes --port 8765 --gateway-port 18790 --config $StoryPalConfig --workspace $StoryPalWorkspace
```

按新机登录流程完成授权。WebUI命令配置本机通道、启动后台gateway并打开浏览器；页面 `http://127.0.0.1:8765`，health `http://127.0.0.1:18790/health`。初始化时不要发送实验聊天。WebUI设置中应有 `storypal-luna` 和 `storypal-luna-5-6`；模型可用性由账户实际目录决定。不要为了绕过目录问题取消运行时模型白名单。

在另一个已激活环境的终端先重复D1的路径变量设置，再检查：

```powershell
Invoke-WebRequest http://127.0.0.1:18790/health
nanobot gateway status --config $StoryPalConfig --workspace $StoryPalWorkspace
```

网页中检查人格内容可显示、阅读器可读取正文；这两项不调用聊天模型。只有health200不能证明故事数据/鉴权/模型回答已通过。旧机历史52/52和51/51不是本次新电脑测试成绩。

停止服务需显式执行：

```powershell
nanobot gateway stop --config $StoryPalConfig --workspace $StoryPalWorkspace
```

打开网页后Ctrl+C通常只退出日志查看，不停止后台gateway。恢复日常后台维护时再按需求打开Note/经历和Dream，正式手账异步复核继续默认关闭；开启会产生额外模型调用。

### D4. 续接同一个读者的两个身份

- 浏览器localStorage键 `storypal.webui.client-id.v1` 是读者标识，决定进度、手账、Note和经历对应的owner；不是WebUI登录密码。新电脑通常会产生新值。
- 需要恢复旧owner时，只在个人私有渠道从旧浏览器相同站点取出这个键值，登录新机页面后在同站点开发者工具中设置这个键并刷新（关闭旧WebSocket连接）。不把值写到Git或项目文档，不修改记录中的owner来合并数据。恢复后先核对进度/手账，再开始聊天。
- workspace也有自己的隐藏 `.nanobot/workspace-id`，与config旁 `sessions/<workspace-id>/.workspace` 共同定位历史。连同目录完整复制。若换盘且旧记录路径在新机不存在，原生逻辑可按移动更新标记；若两个不同workspace路径都存在，会当作复制分配新命名空间，旧会话不会自动出现。先备份并保持单一目标路径，不手工批量重命名/拼接会话。
- 原始聊天保留不等于已进入经历索引。没有抽取过的历史不能通过经历语义回忆自动找回；新浏览器找不到旧Note也要先查身份/路径，再判断算法问题。

## E. 最新进度与接着做什么

| 项目 | 完成记录 | 剩余重点 |
| --- | --- | --- |
| 应用连续记忆 | 10-04受影响程序52/52、43.03s；15次独立授权合成请求，12 Luna+3 Sol | 真人共读与自然归档，真实Embedding竞争召回，复杂观点归属 |
| 检索任务 | 30业务目标/60表达/16事件组，23故事+4记忆+3不检索；标签均待独立复核 | 人工核验必要集合/替代集合，两种表达不计独立样本 |
| 新18问 | Dense默认13/18，RRF11/18，RRF Top5互补12/18；结构3/18 | H21-b、H23/H24等反例；池外缺失与装包缺失分开处理 |
| Qwen严格队列 | 57问/570对完成，旧28故事问同Top10输入18→21/28，开发26→27/27；6改善3损失 | 约18秒/问CPU评分成本，不直接上线；新18问未进此队列 |
| 算法验证 | 10-05程序51/51、4.29s；6240装包行边界/预算与旧结果一致性核对 | 独立语义金标0，成对最终回答、真实记忆/无需检索Agent及跨作品未完成 |

下一次开发优先用[真人验收指南](STAGE1_USER_ACCEPTANCE_GUIDE.md)收口产品，再结合[实验经历](../research/retrieval/EXPERIENCE.md)和[最新过程报告](../research/retrieval/HEAVY_CPU_2026_10_05.md)确定算法路线。模拟用户继续GPT-6 Sol，角色扮演/复核GPT-6 Luna，主应用的人格/已读边界/工具白名单和预算保持可比较。后续9次Luna核验、可选9次Sol模拟和36次成对回答只是历史提案，尚未执行；新机迁移没有授权它们。

## F. 给新电脑开发助手的交接内容

可直接复制：

> 请先阅读START_HERE.md、docs/operations/WORK_COMPUTER_QUICKSTART.md、版本清单和对应分支的最新进度报告。整个项目包括StoryPal应用、独立story_mem后端、固定nanobot源码加九个补丁，以及检索优化研究。先核对Git状态、安装源与本地数据/模型/实例身份，不覆盖已有私有数据。应用真人验收仍待完成；算法57问570对Qwen已结束，新18问未重排，独立语义金标0、标签provisional，生产默认尚未替换。继续记录过程、坏例和成本；模拟用户用GPT-6 Sol，角色扮演用GPT-6 Luna。读取公开报告和离线程序检查可先进行，不自动重跑模型、外发材料或重置旧预算。
