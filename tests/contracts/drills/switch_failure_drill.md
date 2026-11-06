#  切换步 3/4 失败恢复演练脚本（switch failure drill）

- 验收项：（design ）：①装错版本 → vault 零改动；②变更集应用中途失败 →
  删新段 + checkout 回锚点后旧引擎可跑。
- 性质：**沙箱演练**（ 对象）。只在沙箱内执行；「vault」均指沙箱内的 vault 副本，
  **绝不在生产 vault 上执行**。
- 对应  切换步骤：步 3（先装新引擎、校验版本）与步 4（打变更集）。

## 0. 前置（沙箱准备）

```bash
set -euo pipefail

: "${SANDBOX:?set SANDBOX to an empty sandbox directory}"
: "${ANCHOR_TAG:?set ANCHOR_TAG to the pre-switch git anchor tag}"
: "${EXPECTED_VERSION:?set EXPECTED_VERSION to the pinned rc version, e.g. 0.1.0rc1}"

VAULT="$SANDBOX/vault"
OLD_ENGINE="$VAULT/scripts/agent_memory.py"
# ①装错版本用：一个版本号不匹配的 hongzhao 安装（uv tool 环境或 venv 均可）
WRONG_HONGZHAO="${WRONG_HONGZHAO:?set WRONG_HONGZHAO to a hongzhao install whose --version mismatches}"

manifest() { # 生产侧零改动判定的基线：沙箱 vault 全部跟踪文件的内容指纹
  cd "$VAULT" && git ls-files -z | xargs -0 sha256sum | sha256sum
}
```

## 1. 场景①：装错版本（步 3 检查点失败 → 直接停止、零损失）

```bash
BASELINE="$(manifest)"

# 步 3：先装新引擎（此处故意装错版本），随后版本检查
ACTUAL_VERSION="$("$WRONG_HONGZHAO" --version | awk '{print $NF}')"
if [ "$ACTUAL_VERSION" != "$EXPECTED_VERSION" ]; then
  echo "version mismatch: $ACTUAL_VERSION != $EXPECTED_VERSION -> STOP (vault untouched)"
  STOPPED=1
fi
[ "${STOPPED:-0}" = "1" ] || { echo "FAIL: drill premise broken (versions match)"; exit 1; }

# 此断言①：vault 零改动（不批不切、版本不符零损失）
[ "$(manifest)" = "$BASELINE" ] || { echo "FAIL: vault changed despite version-mismatch stop"; exit 1; }
echo "scenario-1 PASSED: vault byte-identical after failed step 3"
```

## 2. 场景②：变更集应用中途失败（步 4 中断 → 回锚点 → 旧引擎可跑）

```bash
# 2.1 模拟步 4 中途失败：config 已加新段、命令替换只做了一半即中止
cd "$VAULT"
python3 - config.yaml <<'PY'
import sys, yaml
p = sys.argv[1]
data = yaml.safe_load(open(p, encoding="utf-8"))
data["output"] = {"link_style": "markdown", "link_prefix": "60-Agent-Memory/"}
data["knowledge_root"] = ".."
yaml.safe_dump(data, open(p, "w", encoding="utf-8"), sort_keys=False, allow_unicode=True)
PY
echo 'hongzhao compile' >> README.md   # 命令替换进行到一半的中间态
# —— 此处注入失败（演练即停在这里，模拟进程中断）——

# 2.2 失败处置（ 步 4 失败处置行）：删 config 新段 + checkout 回锚点
python3 - config.yaml <<'PY'
import sys, yaml
p = sys.argv[1]
data = yaml.safe_load(open(p, encoding="utf-8"))
data.pop("output", None)
data.pop("knowledge_root", None)
yaml.safe_dump(data, open(p, "w", encoding="utf-8"), sort_keys=False, allow_unicode=True)
PY
git checkout "$ANCHOR_TAG" -- .
# 新增文件不进 checkout 清单，单独 rm（同回滚演练步 3）
rm -f .hongzhao-manifest.json .hongzhao.lock

# 此断言②a：恢复到锚点状态
git status --porcelain | grep -q . && { echo "FAIL: working tree not restored"; exit 1; }
! grep -qE '^(output|knowledge_root):' config.yaml || { echo "FAIL: new config sections remain"; exit 1; }

# 此断言②b：旧引擎可跑（回锚点后 validate 正常执行，退出码为 0 或体检类 1，而非 fatal）
set +e
python3 "$OLD_ENGINE" validate
RC=$?
set -e
[ "$RC" -le 1 ] || { echo "FAIL: old engine fatal after recovery (rc=$RC)"; exit 1; }
echo "scenario-2 PASSED: recovered to anchor, old engine runs"
```

## 断言清单（逐项打勾）

| # | 断言 | 结果 |
| --- | --- | --- |
| 1 | 步 3 版本不符即停止，沙箱 vault 全部跟踪文件指纹不变（零改动） | ☐ |
| 2 | 中途失败后删 `output:`/`knowledge_root:` 段成功 | ☐ |
| 3 | `git checkout $ANCHOR_TAG -- .` 后工作区干净 | ☐ |
| 4 | 新增文件（manifest/lock）单独 rm、未进 checkout 清单 | ☐ |
| 5 | 恢复后旧引擎 `validate` 非 fatal（rc ≤ 1） | ☐ |
| 6 | `raw/`、`registry/`、契约目录零 checkout | ☐ |
| 7 | 总时长 ≤ 30 分钟（与回滚演练合并计， 门） | ☐ |

## 红线

- 永不把 `VAULT`/`SANDBOX` 指向生产 vault；本演练只验证恢复路径，不触生产。
- 场景②的「中途失败」必须在真实中断点停住（不能跳过中间态直接恢复），
  否则验证的不是失败恢复路径。
- 任一断言失败即停止并回报。
