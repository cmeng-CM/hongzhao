# Skill: memory-collect

## 边界

- 用户明确表达采集意图时运行：「采集记忆」「collect 记忆」「把 auto-memory 收进 hongzhao」「清理客户端记忆池」等；仅查询、阅读客户端记忆时不调用。
- 永不自动触发：无定时、无会话隐式调用；采集必须显式发起（设计 D-C08）。
- **严格只读（D-C28，硬边界而非选项）**：本 skill 与引擎对**客户端侧零写能力**——不删事实文件、不动 MEMORY.md 一个字节、不剪目录、不存在任何开启这些行为的选项；**不向用户询问任何客户端改动事宜**。采集只做单向抽取：客户端记忆 → hongzhao raw＋账本。空池/悬空索引行只在清单里只读报告，不治理。
- 分工不可越界：引擎（`hongzhao collect`）管解析、增量计算、格式校验与落盘（纯确定性）；本 skill 只承担语义层——判重、判重要、定 scope/project/topic/summary、写两个证据字段。
- 重要性终审=人：CHECKPOINT 未获确认不得进入 apply；空洞或牵强的证据字段（why 写不出具体价值）应主动建议 discard（设计 D-C06）。
- 只经引擎写 raw；不编译（采集后提醒用户另行 memory-compile）、不改 compiled、不动已 done 的 raw、不删 unparsable 文件。
- `project_id` 只能引用 hongzhao 注册表现存项目；池目录与项目的映射按池名语境判断（池名常对应工作目录名，可对照注册表与项目契约），判不准时在 CHECKPOINT 呈报由人定。

## 命令与根目录

- 只读增量清单：`hongzhao collect --client <客户端> [--source-dir P] [--out F] [--pool 池名]…`
- 按决策落盘：`hongzhao collect --apply <decision-file> --client <客户端>`（只写 hongzhao 侧：raw → 账本 → auto-commit；**客户端侧零写入**）
- 落盘预演：`hongzhao collect --apply <file> --dry-run`（全量校验、打印计划、零写入）
- 记忆根判定与诊断：`hongzhao root`；账本位于 `<root>/collect/<client>/ledger.yaml`。
- manifest 与 decision file 是临时产物：放会话临时目录（不入记忆根、不入被采集的客户端目录），会话结束可清理。

## 协议（会话协议 v4）

0. **自识客户端（第一步，必做）**：确定你正运行在哪个客户端（ZCode / Claude Code / 其他），采集**本客户端自己**的记忆池——`--client zcode` 或 `--client claude_code`，绝不在 A 客户端里采 B 客户端。当前受支持源：`zcode`（`~/.zcode/cli/memories/projects`）与 `claude_code`（`~/.claude/projects`，池目录为项目路径 slug、文件格式与 ZCode 同构）；运行在 Codex/Pi 等暂不支持的客户端时，明确呈报「当前客户端暂不支持采集」并停止，不采别家的池。
1. **跑增量**：`hongzhao collect --client <本客户端> --out <临时路径>`（分批可加 `--pool <池名>`，可重复）；向用户报告摘要（池数/条目/待处理/解析失败/空池）。首次采集≈全量待处理属正常（账本冷启动）。**空池首次呈报后静默**（不批复述）。
2. **语义提取**（模型，第一道自审）：读 `compiled/memory-index.yaml` 与相关有效视图建立全局视野；manifest 的 `mentioned_in` 字段是引擎给的判重线索（哪些 raw 正文点名了本条目），**必看但须核实原文**，不代决策。逐候选判定：
   - **收编**（absorb）：长期事实/偏好/决策/经验才收；正文改写为档案语气（去会话性、保事实与来源）；定 scope 与 project_id（对照注册表）、topic（kebab-case）、summary（单行 ≤300）、kind（默认映射 `user→profile`、`feedback→preference`、`project/reference→memory`，人可改）、activation（默认 on-demand，bootstrap 慎用——进每会话注入）。
   - **弃用**（discard）：一次性过程记录、已过时结论、与既有记忆无增量的内容；给一句话理由。
   - **两证据字段每条必填**：`why`（为什么值得留，一句话具体价值）+ `similar`（最相似的 mem-id 或 raw 文件名或 none，加差异点）。
   - **分批节奏**（用户已确认）：**弃用大批 + 收编小批**——弃用类可整池汇总处理；收编类 ≤10 条详审一批。
3. **预演门（必过）**：decision 文件生成后先跑 `hongzhao collect --apply <file> --dry-run`，引擎校验全部条目（STALE/重复/字段/项目映射）零问题才进入人审；有报错先修再呈。
4. **CHECKPOINT（全中文呈现，人终审）**：先给**动作图例**（见下），再两张表——
   - **收编详表**（逐行）：「序号｜客户端记忆｜入库定位（全局/项目 × 偏好/经验 × 按需/注入）｜主题（落盘标识）｜一句话摘要｜为什么值得留｜与库内最相似条目的差异」
   - **弃用汇总**（按证据类型合并行）：「证据类型（如「已被库内条目合并来源点名」）｜条目数｜代表条目｜对应库内条目」
   - **不询问、不呈现任何客户端改动选项**（严格只读是硬边界）；CHECKPOINT 只审「收什么/弃什么」。**未获确认不得进入 apply**。
5. **落盘**：按拍板改 decision → `hongzhao collect --apply <file>` → 核对引擎报告 → 汇报，并**提醒新 raw 待 memory-compile**。

### 动作图例（CHECKPOINT 必附）

| 动作 | 中文 | 对客户端池的影响 |
|---|---|---|
| absorb | 收编 | **零改动**——只写 hongzhao raw＋账本；客户端文件与索引原样 |
| discard | 弃用 | **零改动**——只记账不再冒回；客户端文件与索引原样 |

## 决策文件模板

```yaml
schema_version: 1
client: zcode                  # 本批采集的客户端（= 调用方）
manifest_basis: <本批 manifest 路径>   # 可选，仅溯源
decisions:
  - key: <pool>/memory/<file>.md       # 与 manifest 完全一致
    hash: sha256:…                     # 与 manifest 完全一致
    action: absorb
    scope: project
    project_id: proj-<UUID>            # scope=project 必填且须在注册表
    topic: kebab-case-topic
    kind: memory
    activation: on-demand
    summary: "单行 ≤300 字符"
    body: |
      改写后的档案正文（引擎会追加来源脚注，无需自写）
    evidence:
      why: 一句话具体价值
      similar: {ref: "mem-… 或 raw 文件名或 none", diff: "与最相似条目的差异点"}
  - key: …
    hash: …
    action: discard
    reason: 一句话
```

## 引擎报告处置

- `APPLY_ENTRY_STALE`：决策后源文件已变（hash 不符）——正常防护，条目下次 collect 以新 hash 回流重审，无需处理。
- `APPLY_ENTRY_DUPLICATE`：同批重复 key 或已决策同 hash——检查是否重复 apply。
- `APPLY_PROJECT_UNKNOWN`：project_id 不在注册表——改映射或改 scope 后重出该条。
- `APPLY_RAW_INVALID`：summary 超长/多行、topic 非法、kind/activation 越枚举——按引擎报错改字段重出该条。
- `APPLY_DECISION_INVALID`（含「client-side write fields are removed」）：decision 里出现了 delete_source/slim_index/cleanup/prune_empty_pools 等已移除字段——删除该字段，严格只读形态下它们不存在。
- `COLLECT_LEDGER_INVALID`：账本损坏——呈报用户，由用户决定修复或删账本（删=回到全量候选，安全方向）。

## 输出

只报告：manifest 摘要、本批 CHECKPOINT 结果、apply 后 absorbed/discarded/stale/失败计数、待 compile 提醒；每次 apply 后明示「客户端侧零改动」。不声称已编译、已进 bootstrap。
