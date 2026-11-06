#  合同测试包报告（tests/contracts

| 项 | 内容 |
| --- | --- |
| 生成 | 2026-10-29，合同测试作者=干净上下文独立 agent（作者≠实现者） |
| 只读材料 | design.md **v3.6**（  契约生命周期全文、 验收矩阵、 合同包）；plan.md v1.1（ 、  行）；p1-briefs.md（ 起草指令、 fixture 清单） |
| 入口约定 | 真实 CLI（`subprocess` 调用；优先已安装 `hongzhao` 可执行文件，未装时回退 `python -c "from hongzhao.cli import main; …"`——与 console-script 同一公开入口，非引擎内部）；真实文件系统、真实多进程；不 mock 引擎、不 import 引擎内部模块 |
| 根注入 | 每次调用显式设 `$HONGZHAO_ROOT`（ 序②，直读不回落），cwd=记忆根；外部 `HONGZHAO_TEST/HONGZHAO_FAULT` 默认清除防串扰 |
| 数据 | 每例在 `tmp_path` 自建最小记忆库并自清理；**绝不读写 vault 生产库**； 例外地读环境变量 `HONGZHAO_PARITY_FIXTURE` 指向的只读副本，缺变量即 skip |
| 语言 | 注释中文、断言英文 |

## ① 用例 ↔ A ↔ 状态行映射表

### test_contract_matrix.py（16 例，参数化 id=case_01…case_16，逐行对应 design  状态对照表 #1–#16）

| 用例 |  行 | R / C / A同id / A同key / B同key | 命中 | 断言（结果列） |
| --- | --- | --- | --- | --- |
| case_01 | #1 | 无 / X / 无 / 无 / 无 | J1-a | exit 0；registry 恰 1 条且 `project_id`=X、location 解析到参数路径；项目根契约逐字节不改写；不新建 central |
| case_02 | #2 | 无 / X / 无 / 无 / 有（id≠X） | J1-n | `CONTRACT_KEY_DUPLICATE`；零写入（registry+契约逐字节不变） |
| case_03 | #3 | 无 / X / 无 / 有（id≠X） / — | J1-c | `CONTRACT_KEY_DUPLICATE`；零写入 |
| case_04 | #4 | 无 / X / 有 X / — / — | J1-i | `CONTRACT_DUPLICATE`；零写入 |
| case_05 | #5 | I（I≠X）/ X / — / — / — | J1-d | `CONTRACT_DUPLICATE`（路径已被另一 id 登记）；零写入、不新增第二个 id |
| case_06 | #6 | 无 / X / — / — / —（X 已登记在另一路径） | J1-d | `CONTRACT_DUPLICATE`（复制目录）；零写入 |
| case_07 | #7 | I=X / X / 无 / 无 / 无 | J1-a／J1-b | 无 `--key`：登记（仍 1 条 id=X、契约不变、无 central）；`--key`≠X.key：`KEY_CONFLICT` 零写入 |
| case_08 | #8 | I / 无 / 有 I / — / — | J2／KEY_CONFLICT | `--purpose` 更新生效（id 仍 I）；`--key` 不符：`KEY_CONFLICT` 零写入（R6 M7①） |
| case_09 | #9 | I / 无 / 无 I / 有（id≠I） / — | J3 | `KEY_CONFLICT`；零写入 |
| case_10 | #10 | I / 无 / 无 I / 无 / 有（id≠I） | J3 | `KEY_CONFLICT`（R6 M2）；零写入 |
| case_11 | #11 | I / 无 / 无 I / 无 / 无 | J3 | exit 0；补建 central（`project_id`=I、字段落盘）；registry 仍恰 1 条；不新建第二份契约 |
| case_12 | #12 | 无 / 无 / — / 有 K（id 未登记） / 无 | J4 | `--key`+`--yes` 认领：registry 恰 1 条且 id=central 的 id、location 指向参数路径；central 逐字节不变 |
| case_13 | #13 | 无 / 无 / — / 有 K（id 未登记） / 有（id≠central） | J4 | `KEY_CONFLICT`；零写入 |
| case_14 | #14 | 无 / 无 / — / 有 K（id 已登记在别处） / — | J5 | `KEY_CONFLICT`；零写入（「输出占用者」无文本级断言：输出形态设计未定） |
| case_15 | #15 | 无 / 无 / — / 无 / 有 | J6 | `KEY_CONFLICT`（R6 M2）；零写入 |
| case_16 | #16 | 无 / 无 / — / 无 / 无 | J6 | exit 0；新建：registry 恰 1 条（id 为 `proj-` 形态、external+绝对路径=参数路径）+ `projects/<K>/` 契约（id 一致、字段落盘） |

「结果」列中文说明（如「登记 registry（沿用 X）」）不进断言： 规定用户可见输出全英文，
断言落在错误码标识符（原文）与可观察的文件系统结果上。行 #7/#8 为双结果行，用例内覆盖两种形态。

### 其余文件

| 文件 :: 用例 | A | 状态行/注入点 | 断言要点 |
| --- | --- | --- | --- |
| test_crash.py :: test_a11_1_crash_after_registry_write_retry_hits_j3 | ① | `after-registry-write` | 崩溃后重试（不带 `--key`，原 key=目录名 slug）命中 J3：契约补建、id 与 registry 条目相同、registry 仍只一条、不新建第二份、不误认领他人 orphan（放一个无关 orphan 全程不变） |
| test_crash.py :: test_a11_2_manual_central_delete_retry_hits_j3 | ② | 手工删 central | 重试同①：补建、同 id、仍一条 |
| test_crash.py :: test_a11_3_nonascii_dir_retry_without_key_field_invalid | ③ | `after-registry-write` | 非 ASCII 目录名 + 崩溃后不带 `--key` 重试 → `FIELD_INVALID`、输出提示传 `--key`、零写入（R6 M6） |
| test_crash.py :: test_a11_4_mid_contract_write_takeover_residual_dir | ④ | `mid-contract-write` | mkdir 后 replace 前崩溃留下 `projects/<K>/`；重试命中 J3 接管残留、成功补建、无 `.project-view.md.*` 残留（R7 P1） |
| test_crash.py :: test_a12_1_j6_contract_write_failure_rolls_back | ① | `contract-write` | 刚加的 registry 条目被删除、`projects/<K>/` 不留空目录/临时文件、零契约、**exit 2**、锁释放（随后 register 立即成功） |
| test_crash.py :: test_a12_2_j2_contract_write_failure_atomic | ② | `contract-write` | 契约逐字节不变（原子替换未发生）、registry 仅 `last_checked_at` 变化（其余字段逐项相等）、锁释放（重试更新生效） |
| test_unregister.py :: test_a13_1_default_deletes_registry_and_central | ① | — | dry-run 默认零写入；`--yes` 删 registry+central |
| test_unregister.py :: test_a13_2_keep_contract_leaves_orphan | ② | — | registry 删、central 逐字节保留、输出含 `CONTRACT_ORPHAN` 提示与 orphan 线索 |
| test_unregister.py :: test_a13_3_delete_project_contract_only | ③ | — | 项目根契约被删、registry 删、不产生/不动 central（构造=已注册_项目根） |
| test_unregister.py :: test_a13_4_mutually_exclusive_flags_rejected | ④ | — | `INVALID_FLAG_COMBINATION`；零写入 |
| test_unregister.py :: test_a13_5_project_root_state_prints_residual_path | ⑤ | — | registry 删、项目根契约保留且**打印该路径** |
| test_unregister.py :: test_a13_6_unregister_orphan_registry_side_only | ⑥ | — | 「仅删 registry」语义：registry 保持空且逐字节不变、central 保留、打印 orphan 路径（见 ⑥张力记录） |
| test_unregister.py :: test_a13_7_crash_after_registry_delete_leaves_orphan | ⑦ | `after-registry-delete` | 崩溃留下 orphan（central 在、registry 无）；`doctor` exit 1、报 `CONTRACT_ORPHAN`、附 `project-unregister` 清理命令 |
| test_alias.py :: test_a33_legacy_signature_registry_only_upsert |  | — | 旧签名 `project-register proj-<UUID> --kind vault --path <root 相对路径>`：registry 条目与原引擎语义一致（vault+原样相对路径）、**零契约文件读写**、打印 deprecation 提示与新写法 |
| test_alias.py :: test_alias_enforces_i1_conflict_zero_write | /（R6 M1） | — | 别名同样执行 ：路径已登记为另一 id → `CONTRACT_DUPLICATE` 零写入 |
| test_concurrency.py :: test_a34_1_same_path_single_id | ① | 真实 flock | 8 进程同路径：全部 exit 0（先到 J6、后到 J2）、恰 1 条 registry、1 份契约、同一 `project_id`；附带断言 `<root>/.hongzhao.lock` 存在 |
| test_concurrency.py :: test_a34_2_eight_distinct_paths_no_loss | ② | 真实 flock | 8 条目无丢失、id 无重复、每项目各有 central 且 id 一致 |
| test_concurrency.py :: test_a34_3_distinct_cache_env_still_exclusive | ③ | 真实 flock | 各进程不同 `$HONGZHAO_CACHE` 仍互斥（锁绑定记忆根，R6 M4）：仍恰 1 条/1 份/同 id |
| test_existing_data.py :: test_a25_validate_reports_no_field_too_long |  | `HONGZHAO_PARITY_FIXTURE` | 对只读副本跑 validate：零 `FIELD_TOO_LONG`；validate 只读（registry 逐字节不变）；缺环境变量 skip 并注明原因 |
| test_existing_data.py :: test_a25_invariants_i1_i2_hold |  | `HONGZHAO_PARITY_FIXTURE` | （无两条 location 解析同一路径）、（central+已登记契约无同 key 异 id）零违规 |
| drills/rollback_drill.md |  | 沙箱演练 | 回滚五步可执行脚本+断言清单：每客户端文件仅一个 `agent-memory:` 块、零 `hongzhao:` 块、旧 doctor 绿；不进 CI、不跑生产 |
| drills/switch_failure_drill.md |  | 沙箱演练 | 步 3 装错版本→vault 零改动（指纹不变）；步 4 中途失败→删新段+checkout 回锚点→旧引擎 validate 非 fatal |

收集总数：**36 例**（16 + 6 + 7 + 2 + 3 + 2）；drills 为脚本文档，不进收集。

## ② 红测声明

- 编写时点（2026-10-29）CLI **尚未实现** `project-register` / `project-unregister` /
  `project-check` / `doctor` 等契约相关子命令：本包全部用例「红」表现为**入口缺失**
  （argparse `invalid choice`，rc=2 且无预期错误码），属预期状态。
-  落地真实 CLI 后，红应转为「按预期断言失败」；由  实现负责转绿。
- **本作者不为转绿修改任何断言**（断言文本、错误码、结构性预期均不变）。实现期内如确需
  触碰本包，仅限 ⑤ 节所列 fixture 数据构造层，且须经 RB-02 复核（plan ：转绿后复核
  测试意图仍覆盖 16 例与 4 个注入点）。

## ③ 作者声明

本包由干净上下文的独立 agent 撰写：未参与、也不会参与 hongzhao 引擎实现（作者≠
实现者）；仅依据只读的设计/计划/简报材料编写，未参考任何实现代码。本机验证仅运行
`--collect-only` 与整套红测运行确认（见 ⑥），未为转绿做任何修改。

## ④ 覆盖说明

1. **② 只能靠 hook（design  原文照录）**：「②（写失败后契约逐字节不变、
   锁已释放）只能靠 hook 验证——构造该状态无法覆盖，已在合同包报告中声明。」本包用
   `HONGZHAO_TEST=1` + `HONGZHAO_FAULT=contract-write` 在真实入口注入实现。
2. **4 个故障注入点全覆盖**：`after-registry-write`（①③）、`mid-contract-write`
   （④）、`contract-write`（①②）、`after-registry-delete`（⑦）；双条件
   gating由 conftest 统一注入且默认清除外部值。
3. **退出码断言策略**：设计明示处精确断言（成功路径 exit 0；① exit 2；doctor
   degraded exit 1）；其余失败路径只断言非零 + 错误码标识符（错误码表未逐码绑定退出码）。
4. **双结果行（#7/#8）**：对照表结果列本身双形态，用例内以两次独立调用分别覆盖。
5. **零写入断言**：所有失败路径对「registry + config + 全部 central 契约 + 相关项目根
   契约」做前后逐字节比对（`snapshot_state`）；写后回滚类（①、②）按设计语义
   断言（条目删除/仅 last_checked_at 变化），不做整文件字节比对——引擎重序列化空骨架
   不承诺与 fixture 字节一致。
6. **设计文本张力记录（不改断言、交 RB-02 复核）**：⑥「仅删 registry 并打印 orphan
   路径」与  状态机边「orphan --unregister(仅删 registry)--> 终态_central残留」一致
   （central 保留），但与  doctor 修复命令括注「project-unregister <key>（删孤儿
   central）」存在张力；本测试按前者（⑥ + 状态机，两处规范文本）执行。
7. ****（重复/孤儿/缺失的读取排除语义）不在本包：按 p1-briefs  归属
   `tests/unit/test_contracts_read.py`），本包仅 ⑦ 顺带断言 doctor 报
   `CONTRACT_ORPHAN`。

## ⑤ fixture 与格式推断（供 RB-02 在  转绿前核对；属数据层，非断言）

作者按任务约定不读 vault 生产库，以下 fixture 格式依 design 文本推断，集中在
`tests/contracts/conftest.py`，如与冻结 schema 有出入应修 fixture 而非断言：

| 项 | 推断 | 依据 |
| --- | --- | --- |
| config `paths` 8 键名 | raw / project_registry / knowledge_registry / memory_index / effective_memory / knowledge_map / current_state / bootstrap | 「paths 8 必填、语义同现状」+ // 引用的实际文件名 |
| registry 落盘形状 | `schema_version: 2` + `projects:` 条目列表；条目 4 字段 `project_id` / `location{kind,path}` / `registered_at` / `last_checked_at` | 「条目仅 4 字段、location.kind∈{vault,external}」+ 「registry 不存 key」「刷新 last_checked_at」；列表键名 `projects` 为推断项 |
| 契约 frontmatter | 11 字段（schema_version=2、project_id、project_key、project_name、purpose、current_state、next_action、status、activation、entrypoints、updated_at） | 「契约 frontmatter 字段来源」表 +  必填字段 |
| registry 读取容错 | 列表键容忍 `projects/entries/records`；location 容忍嵌套/扁平 | 降低 fixture 键名推断风险；断言不依赖容错分支 |

## ⑥ 本机验证记录（作者运行，2026-10-29）

```
cd <repo> && python3 -m venv /tmp/t16v \
  && /tmp/t16v/bin/pip install -q -e ".[dev]" \
  && /tmp/t16v/bin/python -m pytest tests/contracts/ --collect-only -q
→ 36 tests collected（exit 0；可见 test_state_matrix_row[case_01]…[case_16]）

/tmp/t16v/bin/python -m pytest tests/contracts/ -q
→ 34 failed, 2 skipped（ 两例因 HONGZHAO_PARITY_FIXTURE 未设置而 skip，符合预期）
→ 失败形态抽查（case_01）：hongzhao: error: argument command: invalid choice: 'project-register'
  = 入口缺失（ 预期红），非测试自身缺陷
```

验证环境注意：沙箱 `/tmp/t16v` 内 `hongzhao` 未加入 PATH 时自动走 `python -c` 回退
（同一公开入口 `hongzhao.cli:main`）；两种入口对本包断言等价。
