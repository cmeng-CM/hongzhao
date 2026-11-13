# Skill: memory-collect

## 边界

- 用户明确表达采集意图时运行：「采集记忆」「collect 记忆」「把 auto-memory 收进 hongzhao」「清理客户端记忆池」等；仅查询、阅读客户端记忆时不调用。
- 永不自动触发：无定时、无会话隐式调用；删源有破坏性，采集必须显式发起（设计 D-C08）。
- 分工不可越界：引擎（`hongzhao collect`）管解析、增量计算、格式校验、落盘与条件删源（纯确定性）；本 skill 只承担语义层——判重、判重要、定 scope/project/topic/summary、写两个证据字段。
- 重要性终审=人：CHECKPOINT 未获确认不得进入 apply；空洞或牵强的证据字段（why 写不出具体价值）应主动建议 discard（设计 D-C06）。
- **删源是可选项而非默认承诺**（设计 D-C22）：decision 顶层 `delete_source` 控制——`true`=收编后删客户端源与索引行（破坏性，CHECKPOINT 须显式确认）；`false`=保留客户端原始记录（只写 raw+记账，不动客户端任何文件）。按用户既定策略选择；用户未确立策略时在 CHECKPOINT 一并问明。保留源策略下 cleanup 与 prune_empty_pools 不主动提议。
- 只经引擎写 raw；不编译（采集后提醒用户另行 memory-compile）、不改 compiled、不动已 done 的 raw、不删 unparsable 文件、不改 ZCode 客户端本体。
- `project_id` 只能引用 hongzhao 注册表现存项目；池目录与项目的映射按池名语境判断（池名常对应工作目录名，可对照注册表与项目契约），判不准时在 CHECKPOINT 呈报由人定。

## 命令与根目录

- 只读增量清单：`hongzhao collect [--client zcode] [--source-dir P] [--out F]`
- 按决策落盘：`hongzhao collect --apply <decision-file>`（写 raw → 记账 → hash 条件删源 → auto-commit）
- 落盘预演：`hongzhao collect --apply <file> --dry-run`（全量校验、打印计划、零写入）
- 记忆根判定与诊断：`hongzhao root`；账本位于 `<root>/collect/<client>/ledger.yaml`。
- manifest 与 decision file 是临时产物：放会话临时目录（不入记忆根、不入被采集的客户端目录），会话结束可清理。

## 四步协议

1. **跑增量**：`hongzhao collect --out <临时路径>`；向用户报告摘要（pools/files/pending/residue/unparsable/empty_pools）。首次采集≈全量 pending 属正常（账本冷启动）。
2. **语义提取**（模型，第一道自审）：读 `compiled/memory-index.yaml` 与 `compiled/effective-memory/` 相关视图、`render/bootstrap.md` 建立全局视野；逐候选判定：
   - absorb：长期事实/偏好/决策/经验才收；正文改写为档案语气（去会话性、保事实与来源）；定 scope 与 project_id（对照注册表）、topic（kebab-case）、summary（单行 ≤300）、kind（默认映射 `user→profile`、`feedback→preference`、`project/reference→memory`，人可改）、activation（默认 on-demand，bootstrap 慎用——它会进每会话注入）。
   - discard：一次性过程记录、已过时结论、与既有记忆无增量的内容；给一句话 reason。
   - **两证据字段每条必填**（人审轻量化的关键）：`why`（为什么值得留，一句话说清具体价值）+ `similar`（与哪条已有记忆最相似：mem-id 或 raw 文件名或 none，加差异点）。
   - **分批**：每批 ≤10 条或单池一批；residue 默认全部列入 cleanup；unparsable 与空池呈报用户定夺，不自行处置。
3. **CHECKPOINT**：把本批清单贴对话等人确认，表格列「#｜池/文件｜动作｜scope→project｜kind/act｜topic｜摘要｜为什么留｜最相似&差异」；秒级逐条 确认/改/砍；**未获确认不得进入 apply**。
4. **落盘**：按拍板写 decision file（模板见下）→ `hongzhao collect --apply <file>` → 核对引擎报告（absorbed/discarded/stale/失败计数与 residue 变化）→ 向用户汇报，并**提醒新 raw 待 memory-compile**。

## 决策文件模板

```yaml
schema_version: 1
client: zcode
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
cleanup:                                # residue 补删（可空；保留源策略下不主动提议）
  - {key: …, hash: sha256:…}
prune_empty_pools: []                   # 空池修剪（用户点头才列；保留源策略下不主动提议）
delete_source: true                     # false=收编不删源（保留客户端原始记录）；按用户策略定，缺省 true
```

## 引擎报告处置

- `APPLY_ENTRY_STALE`：决策后源文件已变（hash 不符）——正常防护，条目下次 collect 以新 hash 回流重审，无需处理。
- `APPLY_ENTRY_DUPLICATE`：同批重复 key 或已决策同 hash——检查是否重复 apply。
- `APPLY_DELETE_MISMATCH`：删源窗口源被并发修改——文件保留为 residue，下轮 cleanup 补删。
- `APPLY_PROJECT_UNKNOWN`：project_id 不在注册表——改映射或改 scope 后重出该条。
- `APPLY_RAW_INVALID`：summary 超长/多行、topic 非法、kind/activation 越枚举——按引擎报错改字段重出该条。
- `COLLECT_LEDGER_INVALID`：账本损坏——呈报用户，由用户决定修复或删账本（删=回到全量候选，安全方向）。

## 输出

只报告：manifest 摘要、本批 CHECKPOINT 结果、apply 后 absorbed/discarded/stale/失败/residue 计数、待 compile 提醒。不声称已编译、已进 bootstrap；删源后果（客户端侧该条不再注入）在 CHECKPOINT 时已向用户呈明。
