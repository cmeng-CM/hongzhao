#  回滚演练脚本（rollback drill）

- 验收项：（design ）「回滚后无双块」；对应  回滚表步 1–5。
- 性质：**沙箱演练**（ 对象）。只在沙箱内执行，**绝不在生产 vault、生产客户端
  全局文件上执行**（永不 checkout 生产数据；本脚本只回滚代码与配置）。
- 通过标准（全部满足，总时长 ≤30 分钟）：
  1. 每个客户端规则文件**仅一个** `agent-memory:` 块、**零** `hongzhao:` 块；
  2. 旧引擎 `doctor` 绿（exit 0）；
  3. 回滚后 `config.yaml` 不含 `output:` / `knowledge_root:` 段（旧引擎可读）；
  4. 新增文件（`.hongzhao-manifest.json`、`.hongzhao.lock`）已被单独 `rm`，不在 checkout 清单内。

## 0. 前置（沙箱准备）

```bash
set -euo pipefail

# SANDBOX：空沙箱目录；ANCHOR_TAG：切换步 2 打的 git 锚点 tag（沙箱仓内）
: "${SANDBOX:?set SANDBOX to an empty sandbox directory}"
: "${ANCHOR_TAG:?set ANCHOR_TAG to the pre-switch git anchor tag}"
# 沙箱内旧引擎副本（旧引擎从副本自带 scripts/agent_memory.py 运行）
OLD_ENGINE="$SANDBOX/vault/scripts/agent_memory.py"
# 客户端规则文件的沙箱替身（四个：三预置 + 自定义 dsh）
CLIENT_FILES=(
  "$SANDBOX/home/.claude/CLAUDE.md"
  "$SANDBOX/home/.codex/AGENTS.md"
  "$SANDBOX/home/.zcode/AGENTS.md"
  "$SANDBOX/home/.dsh/AGENTS.md"
)

# 沙箱初始状态 = 「切换完成后」：
#  - 客户端替身文件：块外正文 + 一个旧 agent-memory: 块 + 一个新 hongzhao: 块（模拟双块残留的最坏形态）
#  - vault 副本：git 仓、含 ANCHOR_TAG；config.yaml 已加 output/knowledge_root 两段；
#    已有 .hongzhao-manifest.json 与 .hongzhao.lock；compiled/** 与 render/bootstrap.md 为新引擎英文产物
# （构造脚本由  沙箱基建提供；本演练从该状态起跑）

count_block() { # 统计文件中某代托管块的 start 标记数
  grep -c "<!-- $1:start -->" "$2" || true
}
```

## 1. 删客户端文件中的 `hongzhao:` 托管块（含标记行）

旧引擎只识别 `agent-memory:`；不删则其后追加旧块 → 双块注入且旧 doctor 假绿。

```bash
for f in "${CLIENT_FILES[@]}"; do
  cp "$f" "$f.pre-rollback"
  # 删除整块（macOS sed；Linux 用 sed -i）
  sed -i '' '/<!-- hongzhao:start -->/,/<!-- hongzhao:end -->/d' "$f"
  # 此断言
  [ "$(count_block hongzhao "$f")" = "0" ] || { echo "FAIL: hongzhao block remains in $f"; exit 1; }
done
echo "step1 ok: zero hongzhao blocks"
```

## 2. 删 config 中 `output:` / `knowledge_root:` 段

旧引擎精确键集校验，不删即 fatal。

```bash
python3 - "$SANDBOX/vault/config.yaml" <<'PY'
import sys, yaml
p = sys.argv[1]
data = yaml.safe_load(open(p, encoding="utf-8"))
data.pop("output", None)
data.pop("knowledge_root", None)
yaml.safe_dump(data, open(p, "w", encoding="utf-8"), sort_keys=False, allow_unicode=True)
PY
# 此断言：两段键不存在
! grep -qE '^(output|knowledge_root):' "$SANDBOX/vault/config.yaml" || { echo "FAIL: new config sections remain"; exit 1; }
echo "step2 ok: config readable by the old engine"
```

## 3. checkout 回锚点（新增文件单独 rm，不进 checkout 清单）

`git checkout <tag> -- 新增路径` 会因 pathspec 不匹配使整条命令失败，故排除新增文件。

```bash
cd "$SANDBOX/vault"
git checkout "$ANCHOR_TAG" -- . ':!.hongzhao-manifest.json' ':!.hongzhao.lock'
rm -f .hongzhao-manifest.json .hongzhao.lock
# 此断言：工作区对锚点干净（数据目录除外：raw/registry/契约永不 checkout，）
git status --porcelain -- config.yaml scripts README.md | grep -q . && { echo "FAIL: tracked files not restored"; exit 1; }
[ ! -e .hongzhao-manifest.json ] && [ ! -e .hongzhao.lock ] || { echo "FAIL: new files not removed"; exit 1; }
echo "step3 ok: rolled back to anchor"
```

## 4. 旧引擎全量重建（幂等）

```bash
cd "$SANDBOX/vault"
python3 "$OLD_ENGINE" compile
python3 "$OLD_ENGINE" bridge-install --all
```

## 5. 最终断言（ 出口）

```bash
for f in "${CLIENT_FILES[@]}"; do
  # ① 每文件仅一个 agent-memory: 块
  [ "$(count_block agent-memory "$f")" = "1" ] || { echo "FAIL: agent-memory block count != 1 in $f"; exit 1; }
  # ② 零 hongzhao: 块
  [ "$(count_block hongzhao "$f")" = "0" ] || { echo "FAIL: hongzhao block remains in $f"; exit 1; }
  # ③ 块外内容不变（回滚不得动块外）
  diff <(sed '/<!-- agent-memory:start -->/,/<!-- agent-memory:end -->/d' "$f.pre-rollback") \
       <(sed '/<!-- agent-memory:start -->/,/<!-- agent-memory:end -->/d' "$f") \
    || { echo "FAIL: out-of-block content changed in $f"; exit 1; }
done
# ④ 旧 doctor 绿
python3 "$OLD_ENGINE" doctor
echo " drill PASSED"
```

## 断言清单（逐项打勾）

| # | 断言 | 结果 |
| --- | --- | --- |
| 1 | 每客户端文件 `hongzhao:start` 计数 = 0 | ☐ |
| 2 | 每客户端文件 `agent-memory:start` 计数 = 1 | ☐ |
| 3 | 每客户端文件块外内容与回滚前一致 | ☐ |
| 4 | config 无 `output:` / `knowledge_root:` | ☐ |
| 5 | git 对锚点干净；`.hongzhao-manifest.json` / `.hongzhao.lock` 已 rm | ☐ |
| 6 | `raw/`、`registry/`、`compiled/`、`render/`、契约目录零 checkout | ☐ |
| 7 | 旧引擎 `doctor` exit 0 | ☐ |
| 8 | 总时长 ≤ 30 分钟（ 门） | ☐ |

## 红线

- 永不把本脚本指向生产 vault 或真实客户端全局文件（`~/.claude/CLAUDE.md` 等）。
- 永不 checkout 生产数据目录；回滚只回代码与配置。
- 任一断言失败即停止并回报，不得带病继续。
