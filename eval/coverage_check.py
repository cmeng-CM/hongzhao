#!/usr/bin/env python3
"""覆盖检查（P0-A4）：45 场景定义 vs 运行归档，缺跑即退出码 1（可进 CI）。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval"))

from score import load_definitions, iter_runs  # noqa: E402


def main() -> int:
    defs = load_definitions()
    runs_root = REPO / "eval" / "scenarios"
    ran: dict[str, int] = {}
    for run_dir in iter_runs(runs_root):
        sid = run_dir.parent.name.removeprefix("scenario-")
        ran[sid] = ran.get(sid, 0) + 1
    missing = sorted(set(defs) - set(ran))
    zero_meta = sorted(sid for sid in ran if not (runs_root.parent / "results" / "runs" / f"scenario-{sid}").is_dir())
    print(f"definitions: {len(defs)} scenarios | archived runs: {sum(ran.values())} across {len(ran)} scenarios")
    for sid in sorted(defs):
        print(f"  {sid}: {ran.get(sid, 0)} attempt(s)")
    if missing:
        print(f"MISSING RUNS: {missing}")
        return 1
    print("coverage: OK (every defined scenario has >=1 attempt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
