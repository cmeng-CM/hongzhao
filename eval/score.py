#!/usr/bin/env python3
"""hongzhao 模型测试判分器（v2，P0 修复后）。

与 v1 的差异：
- A2 expected 单一真源：判分时从 eval/scenarios/*/definitions.py 现取，不再读运行目录的冻结副本
  （旧 expected.yaml 降级为审计快照，判分忽略）；
- A3 退出码独立取证：默认由判分器自身以只读 `validate` 复跑取引擎真实 rc（不信 meta 自报）；
  少数场景（L5 桥接/系统类）的退出码语义属于其专属命令，回退 meta 并标注 exit_source=meta；
- A1 语义断言接入 eval/checks.py（门纪律/对账/转义等从散文变代码）；
- A5 有失败退出码 1（可作 CI 门禁）；scenario id 归一化（剥 -aN 后缀）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
# 退出码语义属于场景专属命令（doctor/skills/uninstall/bridge）而非 validate 的场景 → 用 meta 自报并标注
META_EXIT = {"S3", "S4", "E15", "E16", "E17", "E18", "E19", "E20", "E22", "E23", "E24", "E25", "E34"}


def check(cond, label, actual=None):
    return {"check": label, "pass": bool(cond), "actual": actual if actual is not None else ("<absent>" if cond is False else "present")}


# ── 场景定义（单一真源） ──

_DEFINITIONS: dict[str, dict] | None = None


def load_definitions() -> dict[str, dict]:
    global _DEFINITIONS
    if _DEFINITIONS is None:
        _DEFINITIONS = {}
        for layer_dir in sorted((REPO / "eval" / "scenarios").glob("L*")):
            defs = layer_dir / "definitions.py"
            if not defs.is_file():
                continue
            spec = importlib.util.spec_from_file_location(f"defs_{layer_dir.name}", defs)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for name in dir(mod):
                obj = getattr(mod, name)
                if isinstance(obj, dict) and "id" in obj and "expected" in obj and obj.get("layer") == layer_dir.name:
                    _DEFINITIONS[obj["id"]] = obj
    return _DEFINITIONS


def normalize_scenario_id(sid: str) -> str:
    return re.sub(r"-a\d+$", "", sid or "")


# ── 引擎独立取证（A3） ──

def engine_validate(kit: Path) -> tuple[int | None, str]:
    src = str(REPO / "src")
    code = (
        "import sys; sys.path.insert(0, %r); from hongzhao.cli import main; "
        "raise SystemExit(main(['--root', %r, 'validate']))" % (src, str(kit))
    )
    try:
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        return proc.returncode, (proc.stdout + proc.stderr)[-400:]
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


# ── 机械断言（expected → 引擎产物） ──

def score_view(kit: Path, view_rel: str, spec: dict) -> list[dict]:
    path = kit / view_rel
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    out = [check(n in text, f"view {view_rel} contains {n!r}") for n in spec.get("contains", [])]
    out += [check(n not in text, f"view {view_rel} excludes {n!r}") for n in spec.get("excludes", [])]
    return out


def score_expectations(kit: Path, meta: dict, expected: dict, sid: str) -> list[dict]:
    results: list[dict] = []
    index = None
    idx_path = kit / "compiled" / "memory-index.yaml"
    if idx_path.is_file():
        try:
            index = yaml.safe_load(idx_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return [check(False, "memory-index loadable", str(exc))]
    # 退出码（A3）
    want_exit = expected.get("exit", 0)
    if sid in META_EXIT:
        results.append(check(meta.get("last_exit") == want_exit, f"exit(meta) == {want_exit}", meta.get("last_exit")))
    else:
        rc, diag = engine_validate(kit)
        if rc is None:
            results.append(check(False, "engine validate rerunnable", diag))
        else:
            results.append(check(rc == want_exit, f"exit(engine validate) == {want_exit}", rc))
    if index is None:
        # 未编译：excludes 按「不在视图」通过；需要产物的断言如实 fail
        for view, spec in (expected.get("views") or {}).items():
            if spec.get("contains"):
                results.append(check(False, f"view {view} exists (compiled)"))
            results += score_view(kit, view, {"excludes": spec.get("excludes", [])})
        for section in (expected.get("diff") or {}):
            results.append(check(False, f"compile diff exists (section {section})"))
        for rid in (expected.get("records") or {}):
            results.append(check(False, "memory-index required for record assert", rid))
    else:
        if expected.get("health"):
            results.append(check(index.get("health") == expected["health"], f"health == {expected['health']}", index.get("health")))
        for rid, fields in (expected.get("records") or {}).items():
            entry = (index.get("records") or {}).get(rid)
            if fields == "absent":
                results.append(check(not entry, f"record {rid} absent"))
                continue
            results.append(check(bool(entry), f"record {rid} exists"))
            for field, want in fields.items():
                results.append(check((entry or {}).get(field) == want, f"{rid}.{field} == {want!r}", (entry or {}).get(field)))
        for view, spec in (expected.get("views") or {}).items():
            results += score_view(kit, view, spec)
        diff_path = kit / "compiled" / "last-compile-diff.md"
        diff_text = diff_path.read_text(encoding="utf-8") if diff_path.is_file() else ""
        for section, count in (expected.get("diff") or {}).items():
            results.append(check(f"## {section} ({count})" in diff_text, f"diff has '{section} ({count})'"))
    # 汇报锚（读运行目录 report.txt，经 meta.report_path 或同目录）
    if expected.get("report_contains"):
        local = kit.parent / "report.txt"
        rp = Path(meta.get("report_path", "")) if meta.get("report_path") else None
        src = local if local.is_file() else (rp if rp and rp.is_file() else None)
        text = src.read_text(encoding="utf-8") if src else ""
        results += [check(n in text, f"model report mentions {n!r}") for n in expected["report_contains"]]
    return results


# ── 单次运行判分 ──

def score_run(run_dir: Path) -> dict:
    meta_path = run_dir / "meta.json"
    if not meta_path.is_file():
        return {"run": str(run_dir), "error": "missing meta.json"}
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    sid = normalize_scenario_id(meta.get("scenario"))
    defs = load_definitions().get(sid)
    kit = run_dir / "kit"
    report_path = run_dir / "report.txt"
    report = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
    if defs is None:
        return {"run": str(run_dir), "scenario": sid, "error": f"no definition for {sid}"}
    if not kit.is_dir():
        return {"run": str(run_dir), "scenario": sid, "error": "kit dir missing"}
    checks = score_expectations(kit, meta, defs["expected"], sid)
    import checks as checks_mod  # 语义断言执行器（A1）
    checks += checks_mod.run_checks(sid, kit, meta, report)
    passed = sum(1 for c in checks if c["pass"])
    return {
        "run": str(run_dir),
        "scenario": sid,
        "client": meta.get("client"),
        "attempt": meta.get("attempt"),
        "passed": passed == len(checks) and len(checks) > 0,
        "score": f"{passed}/{len(checks)}",
        "failures": [c for c in checks if not c["pass"]],
    }


def iter_runs(suite: Path):
    import re as _re
    runs_root = suite.parent / "results" / "runs"
    if runs_root.is_dir():
        for sc in sorted(runs_root.glob("scenario-*")):
            yield from sorted(p for p in sc.iterdir() if p.is_dir() and _re.fullmatch(r"attempt-\d+", p.name))


def main() -> int:
    parser = argparse.ArgumentParser(description="hongzhao model-test scorer (v2)")
    parser.add_argument("--suite", default="eval/scenarios")
    parser.add_argument("--run", default=None)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args()

    if args.run:
        results = [score_run(Path(args.run))]
    else:
        results = [score_run(r) for r in iter_runs(Path(args.suite))]
        if not results:
            print(json.dumps({"note": "no runs found", "results": []}, ensure_ascii=False))
            return 0
    failed = [r for r in results if not r.get("passed")]
    summary = {"total_runs": len(results), "passed_runs": len(results) - len(failed), "failed_runs": len(failed), "results": results}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failed else 0  # A5：有失败 rc1（CI 门禁）


if __name__ == "__main__":
    sys.exit(main())
