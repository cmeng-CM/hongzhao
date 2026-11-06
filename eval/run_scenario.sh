#!/usr/bin/env bash
# 场景运行器（受控批）：搭 kit → 喂 transcript → 引擎命令收产物 → score 判分
# 用法：run_scenario.sh <layer> <scenario_id> <attempt> <agent_report_dir>
# agent_report_dir 由执行 agent 预先写好：kit/（执行后的记忆根）、report.txt（模型汇报原文）、meta.json
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LAYER="$1"; SID="$2"; ATTEMPT="$3"; AGENT_DIR="$4"
RUN_ROOT="$REPO/eval/results/runs"
RUN_DIR="$RUN_ROOT/scenario-$SID/attempt-$ATTEMPT"
mkdir -p "$RUN_DIR"

# ① 搭 seed kit（从 agent 报告复制或 hongzhao init）
KIT="$RUN_DIR/kit"
rm -rf "$KIT"
if [ -d "$AGENT_DIR/kit" ]; then
  cp -R "$AGENT_DIR/kit" "$KIT"
else
  /tmp/hz-rel/venv-pypi/bin/hongzhao init "$KIT" > /dev/null 2>&1 || python3 -B "$REPO/eval/init_kit.py" "$KIT"
fi

# ② 引擎产物收尾（validate/compile 已由 agent 在其 kit 上跑过；这里仅收 diff 证据）
cp -f "$AGENT_DIR/report.txt" "$RUN_DIR/report.txt" 2>/dev/null || true
cp -f "$AGENT_DIR/meta.json" "$RUN_DIR/meta.json" 2>/dev/null || true

# ③ expected.yaml 由 definitions 生成（若有 record_asserts 专项脚本则一并跑）
python3 -B "$REPO/eval/export_expected.py" --layer "$LAYER" --scenario "$SID" --out "$RUN_DIR/expected.yaml"

# ④ 判分
python3 -B "$REPO/eval/score.py" --run "$RUN_DIR"
