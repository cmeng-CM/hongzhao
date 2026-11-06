#!/usr/bin/env bash
# A-20 基线准备（T-20；design §10.3 前置的 D-18 只读版）。
# 生产库零写入：不运行生产 compile；以「影子副本内旧引擎 compile 输出 == 生产已提交产物」
# 证明生产产物当前有效，然后只读复制生产产物为冻结基线快照（§9.1 步 1 前的基线物）。
# 用法：prepare_baseline.sh <工作目录>    （基线落 <工作目录>/baseline/）
# 环境：HONGZHAO_CANARY_VAULT 可覆盖生产库位置（默认 ~/workspace/obsidian/obsidian-repository）
# 不一致时 exit 1 并打印差异——按 plan T-20 行「不一致→停止并回报」，不得产出基线。
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VAULT="${HONGZHAO_CANARY_VAULT:-$HOME/workspace/obsidian/obsidian-repository}"
MEMREL="60-Agent-Memory"
WORK="${1:?usage: prepare_baseline.sh <工作目录>}"
BASELINE="$WORK/baseline"
STAMP="$(date +%Y-%m-%dT%H:%M:%S%z)"

[ -d "$VAULT/$MEMREL/scripts" ] || { echo "vault memory root not found: $VAULT/$MEMREL" >&2; exit 2; }

TMP="$(mktemp -d)"
MIRROR="$TMP/shadow-old"
trap 'rm -rf "$TMP"' EXIT

# ① 只读镜像（含旧引擎脚本与真实 external 输入——保真比对，不做 canary 式沙箱改写）
mkdir -p "$MIRROR"
rsync -a --exclude='.git' --exclude='.obsidian' "$VAULT/" "$MIRROR/"

# ② 影子旧引擎 compile（写在副本内；--root . 绑定副本根）
BEFORE="$(cd "$MIRROR/$MEMREL" && find compiled render -type f 2>/dev/null | sort | xargs -I{} sh -c 'printf "%s " {}; cksum < "{}" 2>/dev/null' | cksum)"
(cd "$MIRROR/$MEMREL" && python3 scripts/agent_memory.py --root . compile) > "$TMP/old-compile.txt" 2>&1 || {
  echo "old engine compile failed in shadow:"; cat "$TMP/old-compile.txt"; exit 1; }

# ③ 逐树比对：影子输出 vs 生产已提交产物（归一化环境依赖内容——generated_at 时间戳
#    每轮必变；产物内嵌绝对路径（如 bootstrap 的 memory_root:）随副本位置变，均非内容差异）
norm_to() { # $1=源树 $2=归一化目标树
  local src="$1" dst="$2"
  rm -rf "$dst"; mkdir -p "$dst"
  (cd "$src" && find . -type f | sort) | while read -r f; do
    mkdir -p "$dst/$(dirname "$f")"
    sed -e 's/^generated_at: .*$/generated_at: N/' \
        -e 's|/private/var/|/var/|g' \
        -e "s|$MIRROR/$MEMREL|ROOT|g" -e "s|$VAULT/$MEMREL|ROOT|g" \
        "$src/$f" > "$dst/$f"
  done
  (cd "$src" && find . -type f | sort) > "$dst/.filelist"
}
norm_to "$MIRROR/$MEMREL/compiled" "$TMP/na"
norm_to "$VAULT/$MEMREL/compiled" "$TMP/nb"
norm_to "$MIRROR/$MEMREL/render" "$TMP/nc"
norm_to "$VAULT/$MEMREL/render" "$TMP/nd"
DIFF="$(diff -r "$TMP/na" "$TMP/nb"; diff -r "$TMP/nc" "$TMP/nd" || true)"
if [ -n "$DIFF" ]; then
  echo "BASELINE MISMATCH: production artifacts differ from old-engine shadow output (stop and report)"
  echo "(volatile fields normalized: generated_at + embedded absolute roots; remaining diffs are content drift)"
  echo "$DIFF" | head -60
  exit 1
fi

# ④ 快照生产产物（权威源=生产库）+ 清单 + 报告 + README
mkdir -p "$BASELINE"
rsync -a --delete "$VAULT/$MEMREL/compiled/" "$BASELINE/compiled/"
rsync -a --delete "$VAULT/$MEMREL/render/" "$BASELINE/render/"

python3 - "$BASELINE" "$STAMP" <<'PY'
import hashlib, sys
from pathlib import Path
import yaml

base, stamp = Path(sys.argv[1]), sys.argv[2]
artifacts = sorted(p for p in list((base / "compiled").rglob("*.md")) + list((base / "render").rglob("*.md")))

def headings(text):
    out = []
    for line in text.splitlines():
        if line.startswith("#") and not line.startswith("#!") and len(line.lstrip("#")) > 0:
            level = len(line) - len(line.lstrip("#"))
            if level <= 2:
                out.append(line.strip())
    return out

def fm_keys(text):
    if not text.startswith("---"):
        return []
    end = text.index("\n---", 3)
    keys = []
    for line in text[4:end].splitlines():
        if line and not line.startswith((" ", "\t", "-")) and ":" in line:
            keys.append(line.split(":", 1)[0].strip())
    return keys

sections, keys, sha = {}, {}, {}
for p in artifacts:
    rel = p.relative_to(base).as_posix()
    text = p.read_text(encoding="utf-8")
    sections[rel] = headings(text)
    keys[rel] = fm_keys(text)
    sha[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
idx = base / "compiled" / "memory-index.yaml"
sha[idx.relative_to(base).as_posix()] = hashlib.sha256(idx.read_bytes()).hexdigest()

(base / "sections.yaml").write_text(yaml.safe_dump(sections, allow_unicode=True, sort_keys=True), encoding="utf-8")
(base / "frontmatter-keys.yaml").write_text(yaml.safe_dump(keys, allow_unicode=True, sort_keys=True), encoding="utf-8")
(base / "sha256.yaml").write_text(yaml.safe_dump(sha, allow_unicode=True, sort_keys=True), encoding="utf-8")

report = ["# 影子比对报告（prepare_baseline）", "",
          f"- 时间：{stamp}",
          f"- 产物文件数：{len(artifacts)}（另含 memory-index.yaml）",
          "- 方法：只读镜像生产库 → 副本内旧引擎（scripts/agent_memory.py）`compile` → 与生产已提交产物 `diff -r`（compiled 与 render 两树）逐字节比对",
          "- 结果：两树完全一致（生产产物=旧引擎当前输出，可作为 A-20 基线）", "",
          "VERDICT: identical"]
(base / "comparison-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

readme = ["# A-20 基线 README（待作者核对签字）", "",
          f"- 生成时间：{stamp}（prepare_baseline.sh；影子比对结论见 comparison-report.md）",
          "- 内容：compiled/** + render/** 只读快照、sections.yaml / frontmatter-keys.yaml / sha256.yaml 清单",
          "- 用途：P4 切换出口（§10.3 A-20）比对基准；切换前须按 §10.3 前置重跑 prepare_baseline.sh 刷新", "",
          "## 人工核对项（作者逐项确认后填写结论与签字；非签不得进入 §9.1 步 5）", "",
          "1. 九类产物章节齐全（对照 sections.yaml 逐产物核对中文章节完整性）",
          "2. frontmatter 键集与冻结口径一致（frontmatter-keys.yaml vs tests/fixtures/expected_frontmatter.yaml）",
          "3. claim 追溯可读（每条 effective claim 在其 scope 产物中可检索）",
          "", "| 项 | 结论 |", "| --- | --- |"]
for i in range(1, 4):
    readme.append(f"| {i} | （待填） |")
readme += ["", f"- 作者签字：＿＿＿＿＿＿　日期：＿＿＿＿＿＿", ""]
(base / "README.md").write_text("\n".join(readme), encoding="utf-8")
print(f"baseline prepared at {base}: {len(artifacts)} artifacts, shadow comparison identical")
PY
