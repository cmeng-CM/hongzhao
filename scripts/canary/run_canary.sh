#!/usr/bin/env bash
# 影子 canary（§8）：从生产 vault 只读镜像两份副本（old=原引擎、new=新引擎+新 config 键），
# 只比较 validate 与 compile 的四项指标（health/issue code 集合/产物路径清单/effective 计数）；
# doctor 单独断言：新 doctor 仅允许 LEGACY_MARKER 白名单且 exit 0。
# 根守卫：每轮先 `hongzhao root --json` 断言命中副本根（不限 source，F-1/A-04 口径）。
# 用法：run_canary.sh --round <名称>；结果追加至工作目录 canary-log.md。
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VAULT="${HONGZHAO_CANARY_VAULT:-$HOME/workspace/obsidian/obsidian-repository}"
MEMREL="60-Agent-Memory"
WORK="$REPO/.delivery/2026-10-28-开源启动"
ROUND="unnamed"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --round) ROUND="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

TMP="$(mktemp -d)"
OLD="$TMP/shadow-old"; NEW="$TMP/shadow-new"
trap 'rm -rf "$TMP"' EXIT

# ① 只读镜像到 vault 根（含 29-CM 等 vault 条目；排除 .git）
for dst in "$OLD" "$NEW"; do
  mkdir -p "$dst"
  rsync -a --exclude='.git' --exclude='.obsidian' "$VAULT/" "$dst/"
done

python3 - "$OLD" "$NEW" <<'PY'
# ② 副本改写：external 绝对路径→沙箱等价假项目（带有效契约）；clients 全 disabled；
#    new 副本 config 加 output + knowledge_root: ".."
import sys, uuid
from pathlib import Path
import yaml

old, new = Path(sys.argv[1]), Path(sys.argv[2])

def rewrite(copy: Path, *, new_config: bool) -> None:
    mem = copy / "60-Agent-Memory"
    reg_path = mem / "registry" / "project-registry.yaml"
    reg = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
    for i, entry in enumerate(reg.get("projects", [])):
        loc = entry.get("location", {})
        if loc.get("kind") == "external":
            fake = copy / "sandbox-fake" / f"proj-{i}"
            fake.mkdir(parents=True, exist_ok=True)
            pid = entry.get("project_id") or f"proj-{uuid.uuid4()}"
            key = f"fake-{i}"
            (fake / "project-view.md").write_text(
                "---\nschema_version: 2\nproject_id: %s\nproject_key: %s\nproject_name: Sandbox Fake %d\n"
                "purpose: sandbox stand-in\ncurrent_state: ok\nnext_action: none\nstatus: active\n"
                "activation: on-demand\nentrypoints: []\nupdated_at: 2026-10-29\n---\nbody\n" % (pid, key, i),
                encoding="utf-8",
            )
            loc["path"] = str(fake)
    reg_path.write_text(yaml.safe_dump(reg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    cfg_path = mem / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    for settings in cfg.get("clients", {}).values():
        settings["enabled"] = False
    if new_config:
        cfg["output"] = {"link_style": "markdown"}
        cfg["knowledge_root"] = ".."
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")

rewrite(old, new_config=False)
rewrite(new, new_config=True)
PY

# ③ 新引擎 venv（非可编辑，防 egg-info 污染仓库）
VENV="$TMP/venv"
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q "$REPO"

# ④ 根守卫（两副本）：root == 副本记忆根，不限 source
for copy in "$OLD" "$NEW"; do
  expected="$(cd "$copy/$MEMREL" && pwd -P)"
  guard=$(HONGZHAO_ROOT="$expected" "$VENV/bin/hongzhao" root --json)
  echo "$guard" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['root']==sys.argv[1], d" "$expected" \
    || { echo "root guard FAILED for $copy"; exit 1; }
done

# ④b 生产零变化基线：客户端全局文件与 vault 根外知识/外部目标前后必须逐字节一致（§8）
SNAP="$TMP/prod-snap.txt"
python3 - "$VAULT" > "$SNAP" <<'PYSNAP'
import hashlib, os, sys
from pathlib import Path
import yaml
vault = Path(sys.argv[1])
cfg = yaml.safe_load((vault / "60-Agent-Memory" / "config.yaml").read_text(encoding="utf-8"))
for name, settings in sorted(cfg.get("clients", {}).items()):
    p = Path(os.path.expanduser(settings["bridge_path"]))
    if p.is_file():
        print(f"{p}:{hashlib.sha256(p.read_bytes()).hexdigest()}")
PYSNAP

(cd "$OLD/$MEMREL" && python3 scripts/agent_memory.py --root . validate) > "$TMP/old-validate.txt" 2>&1 || true
(cd "$OLD/$MEMREL" && python3 scripts/agent_memory.py --root . compile)  > "$TMP/old-compile.txt" 2>&1 || true
(cd "$NEW/$MEMREL" && "$VENV/bin/hongzhao" --root . validate) > "$TMP/new-validate.txt" 2>&1 || true
(cd "$NEW/$MEMREL" && "$VENV/bin/hongzhao" --root . compile)  > "$TMP/new-compile.txt" 2>&1 || true

# ⑥ doctor 单独断言（新引擎，new 副本）：仅 LEGACY_MARKER 白名单，exit 0
(cd "$NEW/$MEMREL" && "$VENV/bin/hongzhao" --root . doctor) > "$TMP/new-doctor.txt" 2>&1
DOCTOR_EXIT=$?
LEGACY_BASELINE=$(python3 - "$VAULT" <<'PY'
# 基线：生产客户端文件中含旧代标记的数量（只读）
import sys
from pathlib import Path
vault = Path(sys.argv[1])
cfg = vault / "60-Agent-Memory" / "config.yaml"
import yaml, os
count = 0
for settings in yaml.safe_load(cfg.read_text(encoding="utf-8")).get("clients", {}).values():
    p = Path(os.path.expanduser(settings["bridge_path"]))
    if p.is_file() and "<!-- agent-memory:start -->" in p.read_text(encoding="utf-8"):
        count += 1
print(count)
PY
)
DOCTOR_ISSUES=$(grep -cE '^(degraded|warning|info) ' "$TMP/new-doctor.txt" || true)
DOCTOR_LEGACY=$(grep -c 'LEGACY_MARKER' "$TMP/new-doctor.txt" || true)
DOCTOR_OTHER=$(grep -E '^(degraded|warning|info) ' "$TMP/new-doctor.txt" | grep -vc LEGACY_MARKER || true)
if [[ "$DOCTOR_EXIT" -ne 0 || "$DOCTOR_OTHER" -ne 0 || "$DOCTOR_LEGACY" -ne "$LEGACY_BASELINE" ]]; then
  echo "doctor whitelist assertion FAILED (exit=$DOCTOR_EXIT legacy=$DOCTOR_LEGACY baseline=$LEGACY_BASELINE other=$DOCTOR_OTHER)"
  cat "$TMP/new-doctor.txt"; exit 1
fi

# ⑦ 四项零差异比较
python3 - "$OLD/$MEMREL" "$NEW/$MEMREL" "$TMP" <<'PY'
import re, sys
from pathlib import Path
import yaml

old, new, tmp = (Path(p) for p in sys.argv[1:4])

def codes(path: Path) -> set[str]:
    return set(re.findall(r"\[([A-Z_]+)\]", path.read_text(encoding="utf-8")))

def health(root: Path) -> str:
    idx = root / "compiled" / "memory-index.yaml"
    return str((yaml.safe_load(idx.read_text(encoding="utf-8")) or {}).get("health", "?"))

def effective(root: Path) -> int:
    idx = root / "compiled" / "memory-index.yaml"
    records = (yaml.safe_load(idx.read_text(encoding="utf-8")) or {}).get("records", {})
    rows = records.values() if isinstance(records, dict) else records
    return sum(1 for r in rows if isinstance(r, dict) and r.get("effective") is True)

def product_paths(root: Path) -> set[str]:
    out = set()
    for base in ("compiled", "render"):
        for p in (root / base).rglob("*"):
            if p.is_file():
                out.add(str(p.relative_to(root)))
    return out

diffs = []
if health(old) != health(new):
    diffs.append(f"health: old={health(old)} new={health(new)}")
if codes(tmp / "old-validate.txt") != codes(tmp / "new-validate.txt"):
    diffs.append(f"issue codes: old={sorted(codes(tmp / 'old-validate.txt'))} new={sorted(codes(tmp / 'new-validate.txt'))}")
if product_paths(old) != product_paths(new):
    diffs.append(f"product paths: only-old={sorted(product_paths(old) - product_paths(new))} only-new={sorted(product_paths(new) - product_paths(old))}")
if effective(old) != effective(new):
    diffs.append(f"effective counts: old={effective(old)} new={effective(new)}")

if diffs:
    print("CANARY DIFF:")
    for d in diffs:
        print("  " + d)
    (tmp / "diff-summary.txt").write_text("\n".join(diffs), encoding="utf-8")
    sys.exit(1)
import os as _os


def contracts_parseable(root: Path) -> int:
    reg = yaml.safe_load((root / "registry" / "project-registry.yaml").read_text(encoding="utf-8"))
    n = 0
    for e in reg.get("projects", []):
        loc = e.get("location", {})
        p = Path(_os.path.expanduser(loc["path"])) if loc.get("kind") == "external" else root / loc.get("path", "")
        if (p / "project-view.md").is_file():
            n += 1
    return n
print(f"canary metrics: health={health(new)} effective={effective(new)} products={len(product_paths(new))} contracts-parseable={contracts_parseable(old)}/{contracts_parseable(new)} issue-codes={sorted(codes(tmp / 'new-validate.txt'))}")
PY

# ⑦b 生产零变化断言
python3 - "$VAULT" "$SNAP" <<'PYCHK'
import hashlib, os, sys
from pathlib import Path
import yaml
vault, snap = Path(sys.argv[1]), Path(sys.argv[2])
before = dict(line.rstrip("\n").split(":", 1) for line in snap.read_text().splitlines() if ":" in line)
cfg = yaml.safe_load((vault / "60-Agent-Memory" / "config.yaml").read_text(encoding="utf-8"))
for name, settings in sorted(cfg.get("clients", {}).items()):
    p = Path(os.path.expanduser(settings["bridge_path"]))
    digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "<missing>"
    assert before.get(str(p)) == digest, f"PRODUCTION CLIENT FILE CHANGED: {p}"
print("production client files unchanged")
PYCHK

# ⑧ 记录轮次
RESULT="PASS"
METRICS=$(python3 -c "
import yaml
from pathlib import Path
idx = yaml.safe_load((Path('$NEW/$MEMREL/compiled/memory-index.yaml')).read_text(encoding='utf-8'))
rows = idx.get('records', {}); rows = rows.values() if isinstance(rows, dict) else rows
import os as _os
reg = yaml.safe_load((Path('$NEW/$MEMREL/registry/project-registry.yaml')).read_text(encoding='utf-8'))
cp = sum(1 for e in reg.get('projects', []) if (((Path('$NEW')/e['location']['path']) if e['location']['kind']=='vault' else Path(e['location']['path'].replace('~', _os.environ['HOME'])))/'project-view.md').is_file())
print(f\"health={idx.get('health')} effective={sum(1 for r in rows if isinstance(r, dict) and r.get('effective') is True)} contracts={cp}\")")
{
  echo "| $(date '+%Y-%m-%d %H:%M:%S') | $ROUND | $RESULT | $METRICS | legacy-doctor=$DOCTOR_LEGACY/$LEGACY_BASELINE |"
} >> "$WORK/canary-log.md"
echo "canary: $RESULT ($ROUND, $METRICS)"
