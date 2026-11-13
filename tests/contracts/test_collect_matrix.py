# -*- coding: utf-8 -*-
"""独立合同测试（作者未参与实现；design 第 7 章要求）。

hongzhao v0.4 客户端记忆采集（collect）合同矩阵（design
.delivery/2026-11-13-客户端记忆采集/design.md v2，已批准）：

- 4.3 条目状态转换矩阵 S1–S17 逐行（真实目录树驱动 collect/apply/文件变化）；
- 4.3 组合约束 W1–W3 崩溃窗口 + after-deletes 点（E-C5，双条件故障注入
  HONGZHAO_TEST=1 + HONGZHAO_FAULT=<point>，子进程硬崩溃）；
- 8 章验收项 E-C6（删源条件语义）、E-C7（端到端）、E-C8（MEMORY.md 行尾纪律）、
  E-C12/E-C14（compile 对拍）、D-C18（apply auto-commit）；
- v3/D-C22 保留源模式（decision `delete_source: false`：absorb 不删源、不动
  MEMORY.md、账本记 `source: kept`、kept 同 hash 在场豁免 residue；缺省 true=v2 行为）。

纪律（design 第 7 章「合同测试作者 ≠ 实现者」）：
- 全部走真实文件系统 + 子进程 CLI（sys.executable -m hongzhao，包公开入口），
  不 mock 文件层、不 import 引擎内部实现；kit 与源池 fixture 本文件自建，
  不 import tests/unit；
- 崩溃注入与 compile 对拍一律子进程；结果核对仅读产物文件（YAML/字节）。
约定：注释中文、断言英文（对齐 tests/contracts/conftest.py）。
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# 常量与 fixture 文本
# ---------------------------------------------------------------------------

# registry 供 absorb 校验用的已知 project_id（proj-<UUID> 形态；scope=project 时引擎强制在册）
KNOWN_PROJECT_ID = "proj-3f2a1c0d-0000-4000-8000-5f6d7e8f9a0b"

# 池目录名仿真实 ZCode 池形态 <pool>-<16hex>
POOL_A = "alpha-a1b2c3d4e5f60718"
POOL_B = "beta-b2c3d4e5f6071890"
POOL_G = "gamma-c3d4e5f60718a1b2"
POOL_E1 = "eolcr-d4e5f60718a1b2c3"
POOL_E2 = "eolmx-e5f60718a1b2c3d4"
POOL_P = "delta-f60718a1b2c3d4e"

# 事实文件（frontmatter 形态对齐 2.1 实测：name/description/metadata.type）
FACT_A = (
    "---\n"
    "name: fact-a\n"
    "description: Fact A description line\n"
    "metadata:\n"
    "  node_type: memory\n"
    "  type: project\n"
    "---\n"
    "\n"
    "Fact A body.\n"
)
FACT_A2 = FACT_A + "Appended line changes the hash.\n"  # 内容变化（h′）用
FACT_B = (
    "---\n"
    "name: fact-b\n"
    "description: Fact B description line\n"
    "metadata:\n"
    "  type: feedback\n"
    "---\n"
    "\n"
    "Fact B body.\n"
)
FACT_B2 = FACT_B + "Appended line changes the hash.\n"
FACT_C = (
    "---\n"
    "name: fact-c\n"
    "description: Fact C description line\n"
    "metadata:\n"
    "  type: reference\n"
    "---\n"
    "\n"
    "Fact C body.\n"
)
FACT_D = (
    "---\n"
    "name: fact-d\n"
    "description: Fact D description line\n"
    "metadata:\n"
    "  type: user\n"
    "---\n"
    "\n"
    "Fact D body.\n"
)

# MEMORY.md 索引：fact-a 双行（重复行）+ fact-b + 悬空行（E-C1 面，本文件作干扰项）
MEMORY_MD_A = (
    "# Memory Index\n"
    "- [Fact A](fact-a.md) — hook a\n"
    "- [Fact B](fact-b.md) — hook b\n"
    "- [Fact A dup](fact-a.md) — hook a again\n"
    "- [Gone](gone.md) — dangling line\n"
)
# 吸收 fact-a（全部精确匹配行删除）后的期望字节
MEMORY_MD_A_AFTER_ABSORB_A = (
    "# Memory Index\n"
    "- [Fact B](fact-b.md) — hook b\n"
    "- [Gone](gone.md) — dangling line\n"
)
MEMORY_MD_G = "- [Fact C](fact-c.md) — hook c\n"

CRASH_EXIT = 70  # os._exit(70)（collect._crash，design 7 章故障注入机制）


# ---------------------------------------------------------------------------
# 子进程 CLI（真实入口：sys.executable -m hongzhao）
# ---------------------------------------------------------------------------


def run_cli(args, root, cwd=None, env_extra=None, timeout=120):
    """同步执行一条真实 CLI 命令；根注入 $HONGZHAO_ROOT + 显式 --root，清除外部故障注入变量。"""
    env = os.environ.copy()
    env["HONGZHAO_ROOT"] = str(Path(root).resolve())
    env.pop("HONGZHAO_TEST", None)
    env.pop("HONGZHAO_FAULT", None)
    if env_extra:
        env.update({k: str(v) for k, v in env_extra.items()})
    cmd = [sys.executable, "-m", "hongzhao", *[str(a) for a in args]]
    return subprocess.run(
        cmd,
        cwd=str(Path(cwd if cwd is not None else root).resolve()),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def out_of(res):
    return (getattr(res, "stdout", "") or "") + (getattr(res, "stderr", "") or "")


def fault_env(point):
    """双条件故障注入（对齐 contracts 先例）：HONGZHAO_TEST=1 且 HONGZHAO_FAULT=<point>。"""
    return {"HONGZHAO_TEST": "1", "HONGZHAO_FAULT": point}


def collect_run(root, source, out_file=None):
    args = ["--root", root, "collect", "--source-dir", source]
    if out_file is not None:
        args += ["--out", out_file]
    return run_cli(args, root)


def apply_run(root, source, decision_file, env_extra=None):
    return run_cli(
        ["--root", root, "collect", "--apply", decision_file, "--source-dir", source],
        root, env_extra=env_extra,
    )


def compile_run(root):
    return run_cli(["--root", root, "compile"], root)


def validate_run(root):
    return run_cli(["--root", root, "validate"], root)


# ---------------------------------------------------------------------------
# kit / 源池 fixture（自建，不 import tests/unit）
# ---------------------------------------------------------------------------


def write_file(path: Path, text: str) -> None:
    """按原文落盘（newline='' 固定字节，CRLF/CR 由文本自身携带）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def make_kit(tmp_path: Path, *, with_git_key=True, auto_commit=False,
             with_project_contract=True) -> Path:
    """最小可用 kit：config schema 2（8 paths 键）+ registry（含已知 project）+ 知识 registry 空骨架。"""
    root = tmp_path / "kit"
    for sub in ("raw", "registry", "compiled", "render"):
        (root / sub).mkdir(parents=True)
    config = {
        "schema_version": 2,
        "paths": {
            "raw": "raw",
            "memory_index": "compiled/memory-index.yaml",
            "project_registry": "registry/project-registry.yaml",
            "knowledge_registry": "registry/knowledge-registry.yaml",
            "current_state": "compiled/current-state.md",
            "corrections": "compiled/corrections.md",
            "bootstrap": "render/bootstrap.md",
            "knowledge_map": "compiled/knowledge-map.md",
        },
        "skills": ["memory-write", "memory-compile"],
        "clients": {
            "zcode": {
                "enabled": False,
                "bridge_path": "~/nonexistent-hongzhao-contract-AGENTS.md",
                "skills_root": str(tmp_path / "skills"),
                "mode": "import",
            }
        },
    }
    if with_git_key:
        config["git"] = {"auto_commit": auto_commit}
    write_file(root / "config.yaml", yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    projwork = tmp_path / "projwork"
    projwork.mkdir(exist_ok=True)
    registry = {
        "schema_version": 2,
        "projects": [
            {
                "project_id": KNOWN_PROJECT_ID,
                "location": {"kind": "external", "path": str(projwork.resolve())},
                "registered_at": "2026-11-01",
                "last_checked_at": "2026-11-01",
            }
        ],
    }
    write_file(root / "registry" / "project-registry.yaml",
               yaml.safe_dump(registry, allow_unicode=True, sort_keys=False))
    write_file(root / "registry" / "knowledge-registry.yaml",
               yaml.safe_dump({"schema_version": 2, "knowledge": []}, sort_keys=False))
    if with_project_contract:
        # 让 validate 全绿：已注册项目需要一份合法契约（否则 CONTRACT_MISSING degraded）
        frontmatter = {
            "schema_version": 2,
            "project_id": KNOWN_PROJECT_ID,
            "project_key": "projwork",
            "project_name": "projwork",
            "purpose": "Fixture project for contract tests",
            "current_state": "Stable",
            "next_action": "None",
            "status": "active",
            "activation": "on-demand",
            "entrypoints": [],
            "updated_at": "2026-11-01",
        }
        write_file(projwork / "project-view.md",
                   "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
                   + "---\n\n# projwork\n\nFixture contract body.\n")
    return root


def make_pool(source: Path, pool: str, facts: dict, memory_md=None) -> None:
    """建一个池：memory/<fact>.md + 可选 MEMORY.md（原文字节）。"""
    memory = source / pool / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    for name, text in facts.items():
        write_file(memory / name, text)
    if memory_md is not None:
        write_file(memory / "MEMORY.md", memory_md)


def make_source(tmp_path: Path) -> Path:
    """默认双事实池（S 矩阵多数行的基线场景）。"""
    source = tmp_path / "projects"
    source.mkdir()
    make_pool(source, POOL_A, {"fact-a.md": FACT_A, "fact-b.md": FACT_B}, memory_md=MEMORY_MD_A)
    return source


def key_of(pool: str, filename: str) -> str:
    return f"{pool}/memory/{filename}"


def sha_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ledger_path(root: Path) -> Path:
    return Path(root) / "collect" / "zcode" / "ledger.yaml"


def ledger_entries(root: Path) -> dict:
    path = ledger_path(root)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("entries") or {}


def raw_files(root: Path) -> list:
    return sorted((Path(root) / "raw").glob("*.md"))


def write_decision(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / f"decision-{uuid.uuid4().hex[:8]}.yaml"
    write_file(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def absorb_decision(key: str, entry_hash: str, **override) -> dict:
    decision = {
        "key": key,
        "hash": entry_hash,
        "action": "absorb",
        "scope": "project",
        "project_id": KNOWN_PROJECT_ID,
        "topic": "contract-topic",
        "kind": "memory",
        "activation": "on-demand",
        "summary": "Contract test summary line.",
        "body": "Rewritten fact body for the archive layer.",
        "evidence": {"why": "long-term fact missing from the archive",
                     "similar": {"ref": "none", "diff": "no close match"}},
    }
    decision.update(override)
    return decision


def discard_decision(key: str, entry_hash: str, reason: str = "session-scoped note") -> dict:
    return {"key": key, "hash": entry_hash, "action": "discard", "reason": reason}


def collect_manifest(tmp_path: Path, root: Path, source: Path, tag: str = "m") -> dict:
    """跑真实 collect 并解析 manifest（--out 落盘副本）。"""
    out_file = tmp_path / f"manifest-{tag}-{uuid.uuid4().hex[:6]}.yaml"
    res = collect_run(root, source, out_file=out_file)
    assert res.returncode == 0, f"collect must exit 0; got {res.returncode}; output: {out_of(res)}"
    return yaml.safe_load(out_file.read_text(encoding="utf-8"))


def pending_map(manifest: dict) -> dict:
    return {e["key"]: e for e in manifest["pending"]}


def residue_map(manifest: dict) -> dict:
    return {e["key"]: e for e in manifest["residue"]}


def strip_volatile(text: str) -> str:
    """剥离时间戳行（generated_at / compile-diff 的 baseline note），幂等对拍口径。"""
    lines = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("generated_at:"):
            continue
        if stripped.startswith("baseline: baseline generated at"):
            continue
        lines.append(line)
    return "".join(lines)


# ---------------------------------------------------------------------------
# 4.3 状态矩阵 S1–S17 逐行
# ---------------------------------------------------------------------------


def _row_s01(tmp_path):
    """S1：不在账本 + 扫描 present(h) → pending(h)，进 manifest.pending。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s01")
    pend = pending_map(manifest)
    key_a, key_b = key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-b.md")
    assert key_a in pend and key_b in pend, f"S1: fresh entries must be pending; got {sorted(pend)}"
    assert pend[key_a]["hash"] == sha_of(source / POOL_A / "memory" / "fact-a.md"), (
        "S1: pending hash must equal the file content hash"
    )
    assert manifest["summary"]["residue"] == 0, "S1: fresh scan must report no residue"
    assert not ledger_path(root).exists(), "S1: pure collect must not create a ledger"


def _row_s02(tmp_path):
    """S2：pending(h) + apply absorb 成功 → absorbed(h)→raw（写 raw→记账→删源）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s02")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    res = apply_run(root, source, decision)
    assert res.returncode == 0, f"S2: absorb apply must exit 0; output: {out_of(res)}"
    assert "absorbed:" in res.stdout, f"S2: absorbed line expected; got: {res.stdout}"

    raws = raw_files(root)
    assert len(raws) == 1, f"S2: exactly one raw expected; got {[p.name for p in raws]}"
    record = ledger_entries(root).get(key_a)
    assert record and record["state"] == "absorbed", f"S2: ledger must record absorbed; got {record}"
    assert record["raw"] == f"raw/{raws[0].name}", "S2: ledger raw must point at the written file"
    assert record["hash"] == pending_map(manifest)[key_a]["hash"], "S2: ledger hash must equal the decided source hash"
    assert not (source / POOL_A / "memory" / "fact-a.md").exists(), "S2: source fact must be deleted"
    memory_md = (source / POOL_A / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert "fact-a.md" not in memory_md, "S2: all fact-a index lines must be pruned"
    assert (source / POOL_A / "memory" / "fact-b.md").exists(), "S2: sibling fact must survive"


def _row_s03(tmp_path):
    """S3：pending(h) + apply discard → discarded(h)，不删源。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s03")
    key_b = key_of(POOL_A, "fact-b.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [discard_decision(key_b, pending_map(manifest)[key_b]["hash"])]})
    memory_before = (source / POOL_A / "memory" / "MEMORY.md").read_bytes()
    res = apply_run(root, source, decision)
    assert res.returncode == 0, f"S3: discard apply must exit 0; output: {out_of(res)}"
    record = ledger_entries(root).get(key_b)
    assert record and record["state"] == "discarded" and record["reason"] == "session-scoped note", (
        f"S3: ledger must record discarded with reason; got {record}"
    )
    assert "raw" not in (record or {}), "S3: discarded entry must not reference a raw"
    assert (source / POOL_A / "memory" / "fact-b.md").exists(), "S3: discard must NOT delete the client file"
    after = (source / POOL_A / "memory" / "MEMORY.md").read_bytes()
    assert after == memory_before, "S3: discard must not touch MEMORY.md"


def _row_s04(tmp_path):
    """S4：pending(h) + apply 时文件 hash≠h → 报 STALE 跳过，条目保持 pending。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s04")
    key_a = key_of(POOL_A, "fact-a.md")
    stale_hash = pending_map(manifest)[key_a]["hash"]
    write_file(source / POOL_A / "memory" / "fact-a.md", FACT_A2)  # 决策后内容漂移
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, stale_hash)]})
    res = apply_run(root, source, decision)
    assert res.returncode == 1, f"S4: stale entry must exit 1; got {res.returncode}; output: {out_of(res)}"
    assert "APPLY_ENTRY_STALE" in out_of(res), f"S4: APPLY_ENTRY_STALE expected; got: {out_of(res)}"
    assert key_a not in ledger_entries(root), "S4: stale entry must not enter the ledger"
    assert raw_files(root) == [], "S4: stale entry must not write a raw"
    assert (source / POOL_A / "memory" / "fact-a.md").exists(), "S4: drifted file must be kept"
    again = collect_manifest(tmp_path, root, source, tag="s04b")
    assert key_a in pending_map(again), "S4: entry must stay pending at the new hash"
    assert pending_map(again)[key_a]["hash"] != stale_hash, "S4: reflow must carry the new hash"


def _row_s05(tmp_path):
    """S5：pending(h) 未出现在 decision → 无动作，下次 collect 仍冒出（未决语义）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s05")
    key_a, key_b = key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-b.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    res = apply_run(root, source, decision)
    assert res.returncode == 0, f"S5: partial apply must exit 0; output: {out_of(res)}"
    first = collect_manifest(tmp_path, root, source, tag="s05b")
    second = collect_manifest(tmp_path, root, source, tag="s05c")
    assert key_b in pending_map(first), "S5: undecided entry must stay pending (next collect)"
    assert key_b in pending_map(second), "S5: undecided entry must reappear on every collect"
    assert key_b not in ledger_entries(root), "S5: undecided entry must not enter the ledger"
    # 幂等：同源未变时重复 collect 剥离 generated_at 后逐字节一致（design 4.2）
    a_file = tmp_path / f"manifest-idem-{uuid.uuid4().hex[:4]}.yaml"
    b_file = tmp_path / f"manifest-idem-{uuid.uuid4().hex[:4]}.yaml"
    assert collect_run(root, source, out_file=a_file).returncode == 0
    assert collect_run(root, source, out_file=b_file).returncode == 0
    assert strip_volatile(a_file.read_text(encoding="utf-8")) == strip_volatile(b_file.read_text(encoding="utf-8")), (
        "S5: repeated collect must be byte-identical after stripping generated_at"
    )


def _row_s06(tmp_path):
    """S6：absorbed(h) + 扫描 absent → absorbed(h)（终态，不进任何清单）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s06")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    assert apply_run(root, source, decision).returncode == 0
    assert not (source / POOL_A / "memory" / "fact-a.md").exists(), "S6 premise: source deleted by absorb"
    after = collect_manifest(tmp_path, root, source, tag="s06b")
    assert key_a not in pending_map(after), "S6: absorbed+absent must not be pending"
    assert key_a not in residue_map(after), "S6: absorbed+absent must not be residue"
    record = ledger_entries(root).get(key_a)
    assert record and record["state"] == "absorbed", "S6: ledger keeps absorbed as terminal state"


def _row_s07(tmp_path):
    """S7：absorbed(h) + 扫描 present(h) → 进 manifest.residue（含 raw 引用）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s07")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    assert apply_run(root, source, decision).returncode == 0
    # 模拟删源未完成的残留（W2 终态等价形态）：同内容文件回到源
    write_file(source / POOL_A / "memory" / "fact-a.md", FACT_A)
    after = collect_manifest(tmp_path, root, source, tag="s07b")
    residue = residue_map(after)
    assert key_a in residue, f"S7: same-hash survivor must be reported as residue; got {sorted(residue)}"
    record = ledger_entries(root)[key_a]
    assert residue[key_a]["hash"] == record["hash"], "S7: residue hash must equal the ledger hash"
    assert residue[key_a]["raw"] == record["raw"], "S7: residue must carry the ledger raw reference"
    assert key_a not in pending_map(after), "S7: residue entry must not re-enter pending"


def _row_s08(tmp_path):
    """S8：absorbed(h) + cleanup 且 hash=h → 删文件 + MEMORY.md 行。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s08")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    assert apply_run(root, source, decision).returncode == 0
    write_file(source / POOL_A / "memory" / "fact-a.md", FACT_A)  # 回到 residue
    ledger_hash = ledger_entries(root)[key_a]["hash"]
    cleanup = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": [],
                                        "cleanup": [{"key": key_a, "hash": ledger_hash}]})
    res = apply_run(root, source, cleanup)
    assert res.returncode == 0, f"S8: cleanup apply must exit 0; output: {out_of(res)}"
    assert "deleted source:" in res.stdout, f"S8: delete line expected; got: {res.stdout}"
    assert not (source / POOL_A / "memory" / "fact-a.md").exists(), "S8: residue file must be deleted"
    memory_md = (source / POOL_A / "memory" / "MEMORY.md").read_bytes()
    assert b"fact-a.md" not in memory_md, "S8: fact-a index lines must be pruned"
    assert b"(fact-b.md)" in memory_md and b"gone.md" in memory_md, "S8: unrelated lines must survive"
    final = collect_manifest(tmp_path, root, source, tag="s08b")
    assert key_a not in residue_map(final) and key_a not in pending_map(final), (
        "S8: cleanup must converge the entry out of every list"
    )


def _row_s09(tmp_path):
    """S9：absorbed(h) + cleanup 时 hash≠h 或 absent → 跳过/报告（条目保持 absorbed）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s09")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    assert apply_run(root, source, decision).returncode == 0
    write_file(source / POOL_A / "memory" / "fact-a.md", FACT_A)
    ledger_hash = ledger_entries(root)[key_a]["hash"]
    ledger_before = ledger_path(root).read_bytes()

    # (a) cleanup 时文件被并发修改（当前 hash ≠ 账本/决策 hash）→ MISMATCH 报告 + 文件保留
    write_file(source / POOL_A / "memory" / "fact-a.md", FACT_A2)
    mismatch = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": [],
                                         "cleanup": [{"key": key_a, "hash": ledger_hash}]})
    res = apply_run(root, source, mismatch)
    assert res.returncode == 1, f"S9a: delete mismatch must exit 1; got {res.returncode}; output: {out_of(res)}"
    assert "APPLY_DELETE_MISMATCH" in res.stdout, f"S9a: APPLY_DELETE_MISMATCH expected; got: {res.stdout}"
    assert (source / POOL_A / "memory" / "fact-a.md").exists(), "S9a: mismatched file must be kept"
    assert ledger_path(root).read_bytes() == ledger_before, "S9a: ledger must stay untouched"
    reflow = collect_manifest(tmp_path, root, source, tag="s09b")
    assert key_a in pending_map(reflow), "S9a: changed content must reflow as pending (S10 linkage)"

    # (b) cleanup 时文件已 absent → 跳过（无失败），条目保持 absorbed 终态（S6）
    (source / POOL_A / "memory" / "fact-a.md").unlink()
    absent = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": [],
                                       "cleanup": [{"key": key_a, "hash": ledger_hash}]})
    res2 = apply_run(root, source, absent)
    assert res2.returncode == 0, f"S9b: cleanup of absent file must skip cleanly; output: {out_of(res2)}"
    assert "APPLY_DELETE_MISMATCH" not in res2.stdout, "S9b: absent cleanup is a skip, not a mismatch"
    record = ledger_entries(root).get(key_a)
    assert record and record["state"] == "absorbed", "S9b: ledger must keep absorbed (terminal)"


def _row_s10(tmp_path):
    """S10：absorbed(h) + 扫描 present(h′) → pending(h′) 回流重审。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s10")
    key_a = key_of(POOL_A, "fact-a.md")
    old_hash = pending_map(manifest)[key_a]["hash"]
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, old_hash)]})
    assert apply_run(root, source, decision).returncode == 0
    write_file(source / POOL_A / "memory" / "fact-a.md", FACT_A2)  # 新内容 h′
    after = collect_manifest(tmp_path, root, source, tag="s10b")
    pend = pending_map(after)
    assert key_a in pend, f"S10: changed content must reflow to pending; got {sorted(pend)}"
    assert pend[key_a]["hash"] != old_hash and pend[key_a]["hash"] == sha_of(source / POOL_A / "memory" / "fact-a.md"), (
        "S10: reflow must carry the new content hash"
    )
    assert key_a not in residue_map(after), "S10: changed content is pending, not residue"


def _row_s11(tmp_path):
    """S11：discarded(h) + 扫描 present(h) → 无动作、不冒回。"""
    source = tmp_path / "projects"
    source.mkdir()
    make_pool(source, POOL_B, {"fact-b.md": FACT_B}, memory_md="- [Fact B](fact-b.md) — hook b\n")
    root = make_kit(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s11")
    key_b = key_of(POOL_B, "fact-b.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [discard_decision(key_b, pending_map(manifest)[key_b]["hash"])]})
    assert apply_run(root, source, decision).returncode == 0
    first = collect_manifest(tmp_path, root, source, tag="s11b")
    second = collect_manifest(tmp_path, root, source, tag="s11c")
    for tag, m in (("first", first), ("second", second)):
        assert key_b not in pending_map(m), f"S11: discarded must not resurface as pending ({tag})"
        assert key_b not in residue_map(m), f"S11: discarded must not be reported as residue ({tag})"
    assert m["summary"]["pending"] == 0 and m["summary"]["residue"] == 0, (
        "S11: same-hash discarded entry stays suppressed on every collect"
    )
    assert (source / POOL_B / "memory" / "fact-b.md").exists(), "S11: client file must survive"


def _row_s12(tmp_path):
    """S12：discarded(h) + 扫描 present(h′) → pending(h′) 回流重审。"""
    source = tmp_path / "projects"
    source.mkdir()
    make_pool(source, POOL_B, {"fact-b.md": FACT_B})
    root = make_kit(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s12")
    key_b = key_of(POOL_B, "fact-b.md")
    old_hash = pending_map(manifest)[key_b]["hash"]
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [discard_decision(key_b, old_hash)]})
    assert apply_run(root, source, decision).returncode == 0
    write_file(source / POOL_B / "memory" / "fact-b.md", FACT_B2)
    after = collect_manifest(tmp_path, root, source, tag="s12b")
    pend = pending_map(after)
    assert key_b in pend and pend[key_b]["hash"] != old_hash, (
        "S12: changed content after discard must reflow at the new hash"
    )


def _row_s13(tmp_path):
    """S13：任意条目文件解析失败 → unparsable（不入账本），只报错清单。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    broken_key = key_of(POOL_A, "broken.md")
    write_file(source / POOL_A / "memory" / "broken.md", "plain body without frontmatter\n")
    manifest = collect_manifest(tmp_path, root, source, tag="s13")
    unparsable_keys = {u["key"] for u in manifest["unparsable"]}
    assert broken_key in unparsable_keys, f"S13: unparsable file must be listed; got {unparsable_keys}"
    assert broken_key not in pending_map(manifest), "S13: unparsable must not enter pending"
    # unparsable 条目不可被 apply 吸收：不在扫描条目中 → STALE，且永不入账
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(broken_key, sha_of(source / POOL_A / "memory" / "broken.md"))]})
    res = apply_run(root, source, decision)
    assert res.returncode == 1, f"S13: apply on unparsable entry must fail entry-level; output: {out_of(res)}"
    assert "APPLY_ENTRY_STALE" in res.stdout, f"S13: STALE expected for unparsable; got: {res.stdout}"
    assert broken_key not in ledger_entries(root), "S13: unparsable entry must never enter the ledger"
    assert (source / POOL_A / "memory" / "broken.md").exists(), "S13: unparsable file must be kept (report only)"


def _row_s14(tmp_path):
    """S14：账本缺失 → collect/apply 视为全 unseen（冷启动全量候选）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    assert not ledger_path(root).exists(), "S14 premise: cold-start kit has no ledger"
    manifest = collect_manifest(tmp_path, root, source, tag="s14")
    pend = pending_map(manifest)
    assert sorted(pend) == [key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-b.md")], (
        f"S14: cold start must surface every parsed entry as pending; got {sorted(pend)}"
    )
    assert manifest["summary"]["residue"] == 0, "S14: cold start has no residue"
    # 冷启动 apply 同样可用（无账本 → 空 map 起步）
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pend[key_a]["hash"])]})
    res = apply_run(root, source, decision)
    assert res.returncode == 0, f"S14: cold-start apply must work; output: {out_of(res)}"
    assert ledger_entries(root)[key_a]["state"] == "absorbed", "S14: apply must create the ledger"


def _row_s15(tmp_path):
    """S15：账本损坏 → collect/apply 双双 fatal exit 2 [COLLECT_LEDGER_INVALID]；删账本回冷启动。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    (root / "collect" / "zcode").mkdir(parents=True)
    corrupt = root / "collect" / "zcode" / "ledger.yaml"
    write_file(corrupt, "not: [valid\n")
    corrupt_bytes = corrupt.read_bytes()

    res = collect_run(root, source)
    assert res.returncode == 2, f"S15: corrupt ledger must fatal collect with exit 2; got {res.returncode}"
    assert "COLLECT_LEDGER_INVALID" in out_of(res), f"S15: error code expected; got: {out_of(res)}"

    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, sha_of(source / POOL_A / "memory" / "fact-a.md"))]})
    res2 = apply_run(root, source, decision)
    assert res2.returncode == 2, f"S15: corrupt ledger must fatal apply with exit 2; got {res2.returncode}"
    assert "COLLECT_LEDGER_INVALID" in out_of(res2), f"S15: apply error code expected; got: {out_of(res2)}"
    assert corrupt.read_bytes() == corrupt_bytes, "S15: fatal path must not rewrite the ledger"
    assert raw_files(root) == [], "S15: fatal path must not write raw files"

    # 删除损坏账本 = 回到 S14 冷启动（安全方向：重新候选而非丢失）
    corrupt.unlink()
    res3 = collect_run(root, source)
    assert res3.returncode == 0, f"S15: after removing the corrupt ledger collect must recover; got: {out_of(res3)}"


def _row_s16(tmp_path):
    """S16：pending(h) + apply 时文件 absent → 报 STALE 跳过（与 S4 同走漂移不吸收）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s16")
    key_a = key_of(POOL_A, "fact-a.md")
    stale_hash = pending_map(manifest)[key_a]["hash"]
    (source / POOL_A / "memory" / "fact-a.md").unlink()  # 决策后文件消失
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, stale_hash)]})
    res = apply_run(root, source, decision)
    assert res.returncode == 1, f"S16: absent-at-apply must exit 1; got {res.returncode}; output: {out_of(res)}"
    assert "APPLY_ENTRY_STALE" in res.stdout, f"S16: APPLY_ENTRY_STALE expected; got: {res.stdout}"
    assert key_a not in ledger_entries(root), "S16: absent entry must not enter the ledger"
    assert raw_files(root) == [], "S16: absent entry must not write a raw"


def _row_s17(tmp_path):
    """S17：discarded(h) + 扫描 absent → discarded(h)（终态，不进任何清单）。"""
    source = tmp_path / "projects"
    source.mkdir()
    make_pool(source, POOL_B, {"fact-b.md": FACT_B})
    root = make_kit(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s17")
    key_b = key_of(POOL_B, "fact-b.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [discard_decision(key_b, pending_map(manifest)[key_b]["hash"])]})
    assert apply_run(root, source, decision).returncode == 0
    (source / POOL_B / "memory" / "fact-b.md").unlink()  # 客户端自删已弃用条目（正常）
    after = collect_manifest(tmp_path, root, source, tag="s17b")
    assert key_b not in pending_map(after), "S17: discarded+absent must not be pending"
    assert key_b not in residue_map(after), "S17: discarded+absent must not be residue"
    assert after["summary"]["pending"] == 0 and after["summary"]["residue"] == 0, (
        "S17: entry appears in no manifest list (terminal)"
    )
    record = ledger_entries(root).get(key_b)
    assert record and record["state"] == "discarded", "S17: ledger keeps discarded as terminal state"


ROW_HANDLERS = {
    1: _row_s01, 2: _row_s02, 3: _row_s03, 4: _row_s04, 5: _row_s05, 6: _row_s06,
    7: _row_s07, 8: _row_s08, 9: _row_s09, 10: _row_s10, 11: _row_s11, 12: _row_s12,
    13: _row_s13, 14: _row_s14, 15: _row_s15, 16: _row_s16, 17: _row_s17,
}


@pytest.mark.parametrize("row", [pytest.param(n, id=f"S{n:02d}") for n in range(1, 18)])
def test_collect_state_matrix_row(row, tmp_path):
    """逐行执行 design 4.3 状态矩阵第 row 行（真实 CLI、真实目录树）。"""
    ROW_HANDLERS[row](tmp_path)


# ---------------------------------------------------------------------------
# E-C5：写序崩溃窗口 W1–W3 + after-deletes（双条件故障注入，子进程硬崩溃）
# ---------------------------------------------------------------------------


def _assert_crash(res, point):
    assert res.returncode == CRASH_EXIT, (
        f"E-C5[{point}]: fault injection must hard-crash with exit {CRASH_EXIT}; "
        f"got rc={res.returncode}; output: {out_of(res)}"
    )
    assert f"fault-injection: crashing at {point}" in (res.stderr or ""), (
        f"E-C5[{point}]: crash marker expected on stderr; got: {res.stderr}"
    )


def test_E_C5_W1_crash_after_raws(tmp_path):
    """W1（after-raws）：raw 已写、账本未记 → 条目仍 pending；复 apply 收敛（宁重复不丢失）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="w1")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    res = apply_run(root, source, decision, env_extra=fault_env("after-raws"))
    _assert_crash(res, "after-raws")

    # 崩溃后磁盘状态：raw 在、账本无记录、源文件在、条目仍 pending
    assert len(raw_files(root)) == 1, "E-C5[W1]: raw must already be on disk"
    assert not ledger_path(root).exists(), "E-C5[W1]: ledger must not exist yet (raw first, ledger second)"
    assert (source / POOL_A / "memory" / "fact-a.md").exists(), "E-C5[W1]: source must survive (deletes not reached)"
    after = collect_manifest(tmp_path, root, source, tag="w1b")
    assert key_a in pending_map(after), "E-C5[W1]: entry must stay pending after the crash (no silent loss)"
    assert key_a not in residue_map(after), "E-C5[W1]: unrecorded entry must not be residue"

    # 恢复：普通 apply 重放同一决策 → 收敛；崩溃残留 raw 保留（重复候选可见，模型判重消化）
    recovery = apply_run(root, source, decision)
    assert recovery.returncode == 0, f"E-C5[W1]: recovery apply must exit 0; output: {out_of(recovery)}"
    assert len(raw_files(root)) == 2, (
        "E-C5[W1]: crash-residual raw plus recovery raw must both persist (duplicate over loss)"
    )
    record = ledger_entries(root).get(key_a)
    assert record and record["state"] == "absorbed", "E-C5[W1]: recovery must record absorbed"
    assert (Path(root) / record["raw"]).is_file(), "E-C5[W1]: ledger raw must point at a real file"
    assert not (source / POOL_A / "memory" / "fact-a.md").exists(), "E-C5[W1]: recovery must finish the delete"
    final = collect_manifest(tmp_path, root, source, tag="w1c")
    assert key_a not in pending_map(final) and key_a not in residue_map(final), (
        "E-C5[W1]: entry must converge out of every list"
    )


def test_E_C5_W2_crash_after_ledger(tmp_path):
    """W2（after-ledger）：账本已记 absorbed、删源未做 → collect 报 residue；cleanup 补删收敛。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="w2")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    memory_before = (source / POOL_A / "memory" / "MEMORY.md").read_bytes()
    res = apply_run(root, source, decision, env_extra=fault_env("after-ledger"))
    _assert_crash(res, "after-ledger")

    # 崩溃后磁盘状态：账本已记 absorbed、源文件在、raw 在、MEMORY.md 未动
    record = ledger_entries(root).get(key_a)
    assert record and record["state"] == "absorbed", f"E-C5[W2]: ledger must hold absorbed; got {record}"
    assert len(raw_files(root)) == 1, "E-C5[W2]: raw must be on disk"
    assert (source / POOL_A / "memory" / "fact-a.md").exists(), "E-C5[W2]: source must survive"
    assert (source / POOL_A / "memory" / "MEMORY.md").read_bytes() == memory_before, (
        "E-C5[W2]: index rewrite must not have happened (deletes not reached)"
    )
    after = collect_manifest(tmp_path, root, source, tag="w2b")
    residue = residue_map(after)
    assert key_a in residue, f"E-C5[W2]: collect must report residue; got {sorted(residue)}"
    assert residue[key_a]["raw"] == record["raw"], "E-C5[W2]: residue must reference the absorbed raw"
    assert key_a not in pending_map(after), "E-C5[W2]: recorded entry must not re-enter pending"

    # 恢复：cleanup 决策补删 → 双份窗口收敛
    cleanup = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": [],
                                        "cleanup": [{"key": key_a, "hash": record["hash"]}]})
    recovery = apply_run(root, source, cleanup)
    assert recovery.returncode == 0, f"E-C5[W2]: cleanup recovery must exit 0; output: {out_of(recovery)}"
    assert not (source / POOL_A / "memory" / "fact-a.md").exists(), "E-C5[W2]: cleanup must delete the source"
    assert b"fact-a.md" not in (source / POOL_A / "memory" / "MEMORY.md").read_bytes(), (
        "E-C5[W2]: cleanup must prune the index lines"
    )
    final = collect_manifest(tmp_path, root, source, tag="w2c")
    assert key_a not in residue_map(final), "E-C5[W2]: residue must converge to zero"


def test_E_C5_W3_crash_mid_deletes(tmp_path):
    """W3（mid-deletes）：删源进行中部分已删 → 已删者终态、未删者 residue；重跑 cleanup 幂等收敛。"""
    root = make_kit(tmp_path)
    source = tmp_path / "projects"
    source.mkdir()
    make_pool(source, POOL_A, {"fact-a.md": FACT_A, "fact-c.md": FACT_C}, memory_md=MEMORY_MD_A)
    manifest = collect_manifest(tmp_path, root, source, tag="w3")
    pend = pending_map(manifest)
    key_a, key_c = key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-c.md")
    # 两条都 absorb：删源按决策序执行，首条删除后注入崩溃
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": [
        absorb_decision(key_a, pend[key_a]["hash"]),
        absorb_decision(key_c, pend[key_c]["hash"], topic="contract-topic-c"),
    ]})
    memory_before = (source / POOL_A / "memory" / "MEMORY.md").read_bytes()
    res = apply_run(root, source, decision, env_extra=fault_env("mid-deletes"))
    _assert_crash(res, "mid-deletes")

    # 崩溃后磁盘状态：首条已删（absent → S6 终态）、次条仍在（→ residue）、账本双 absorbed
    assert not (source / POOL_A / "memory" / "fact-a.md").exists(), "E-C5[W3]: first delete must have happened"
    assert (source / POOL_A / "memory" / "fact-c.md").exists(), "E-C5[W3]: second delete must not have happened"
    entries = ledger_entries(root)
    assert entries[key_a]["state"] == "absorbed" and entries[key_c]["state"] == "absorbed", (
        "E-C5[W3]: ledger must hold both absorbed records"
    )
    assert len(raw_files(root)) == 2, "E-C5[W3]: both raws must be on disk"
    assert (source / POOL_A / "memory" / "MEMORY.md").read_bytes() == memory_before, (
        "E-C5[W3]: index rewrite must not have happened mid-deletes"
    )
    after = collect_manifest(tmp_path, root, source, tag="w3b")
    assert key_c in residue_map(after), "E-C5[W3]: undeleted survivor must be residue"
    assert key_a not in residue_map(after) and key_a not in pending_map(after), (
        "E-C5[W3]: deleted entry is terminal (absent absorbed)"
    )
    dangling_files = {d["file"] for d in after["dangling_index"]}
    assert "fact-a.md" in dangling_files, (
        "E-C5[W3]: index line of the deleted file is dangling (index untouched mid-crash)"
    )

    # 恢复：cleanup 决策补删 survivor → 文件层幂等收敛（残留悬空行属客户端索引面，仅报告）
    cleanup = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": [],
                                        "cleanup": [{"key": key_c, "hash": entries[key_c]["hash"]}]})
    recovery = apply_run(root, source, cleanup)
    assert recovery.returncode == 0, f"E-C5[W3]: cleanup recovery must exit 0; output: {out_of(recovery)}"
    assert not (source / POOL_A / "memory" / "fact-c.md").exists(), "E-C5[W3]: survivor must be deleted"
    final = collect_manifest(tmp_path, root, source, tag="w3c")
    assert final["summary"]["residue"] == 0 and final["summary"]["pending"] == 0, (
        "E-C5[W3]: both entries must converge out of every list"
    )


def test_E_C5_after_deletes_crash(tmp_path):
    """after-deletes 点：源已删、raw 在磁盘；恢复仅需普通 collect/apply（无遗留动作）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="ad")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    res = apply_run(root, source, decision, env_extra=fault_env("after-deletes"))
    _assert_crash(res, "after-deletes")

    # 崩溃后磁盘状态：源已删、索引行已清、raw 在、账本 absorbed（仅 auto-commit 未发生）
    assert not (source / POOL_A / "memory" / "fact-a.md").exists(), "E-C5[after-deletes]: source must be deleted"
    memory_md = (source / POOL_A / "memory" / "MEMORY.md").read_bytes()
    assert b"fact-a.md" not in memory_md, "E-C5[after-deletes]: index lines must already be pruned"
    assert len(raw_files(root)) == 1, "E-C5[after-deletes]: raw must be on disk"
    record = ledger_entries(root).get(key_a)
    assert record and record["state"] == "absorbed", "E-C5[after-deletes]: ledger must hold absorbed"
    # raw 进 git 保底由 D-C18 用例覆盖（本用例 kit 非 git 仓库）

    # 恢复：普通 collect 收敛 + 空 apply 无遗留动作
    after = collect_manifest(tmp_path, root, source, tag="adb")
    assert key_a not in pending_map(after) and key_a not in residue_map(after), (
        "E-C5[after-deletes]: entry must already be terminal"
    )
    empty = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": []})
    noop = apply_run(root, source, empty)
    assert noop.returncode == 0, f"E-C5[after-deletes]: empty apply must be a clean no-op; output: {out_of(noop)}"


# ---------------------------------------------------------------------------
# E-C6：删源条件语义（hash 双检）
# ---------------------------------------------------------------------------


def test_E_C6_conditional_delete_semantics(tmp_path):
    """E-C6：cleanup hash 不符 → 文件保留 + [APPLY_DELETE_MISMATCH] + exit 1；absorb hash 不符 → 步骤 2 即 STALE。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)

    # 面 1：cleanup 条目在场、当前文件 hash 与账本/决策 hash 不符
    manifest = collect_manifest(tmp_path, root, source, tag="ec6")
    key_a, key_b = key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-b.md")
    first = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                      "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    assert apply_run(root, source, first).returncode == 0
    write_file(source / POOL_A / "memory" / "fact-a.md", FACT_A)  # 回到 residue
    record = ledger_entries(root)[key_a]
    memory_before = (source / POOL_A / "memory" / "MEMORY.md").read_bytes()
    ledger_before = ledger_path(root).read_bytes()
    write_file(source / POOL_A / "memory" / "fact-a.md", FACT_A2)  # 删源窗口内容漂移
    cleanup = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": [],
                                        "cleanup": [{"key": key_a, "hash": record["hash"]}]})
    res = apply_run(root, source, cleanup)
    assert res.returncode == 1, f"E-C6: delete mismatch must exit 1; got {res.returncode}; output: {out_of(res)}"
    assert "APPLY_DELETE_MISMATCH" in res.stdout, f"E-C6: APPLY_DELETE_MISMATCH expected; got: {res.stdout}"
    drifted = source / POOL_A / "memory" / "fact-a.md"
    assert drifted.exists() and drifted.read_text(encoding="utf-8") == FACT_A2, (
        "E-C6: drifted file must be kept byte-for-byte"
    )
    assert (source / POOL_A / "memory" / "MEMORY.md").read_bytes() == memory_before, (
        "E-C6: MEMORY.md must stay untouched on delete mismatch"
    )
    assert ledger_path(root).read_bytes() == ledger_before, "E-C6: ledger must stay untouched on mismatch"
    reflow = collect_manifest(tmp_path, root, source, tag="ec6b")
    assert key_a in pending_map(reflow), "E-C6: drifted content must reflow for re-review (S10)"

    # 面 2：absorb 决策 hash 与当前文件不符 → 校验序步骤 2 即 STALE（不进删源）
    stale_hash = sha_of(source / POOL_A / "memory" / "fact-b.md")
    write_file(source / POOL_A / "memory" / "fact-b.md", FACT_B2)  # 决策后内容漂移
    absorb = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                       "decisions": [absorb_decision(key_b, stale_hash)]})
    res2 = apply_run(root, source, absorb)
    assert res2.returncode == 1, f"E-C6: stale absorb must exit 1; output: {out_of(res2)}"
    assert "APPLY_ENTRY_STALE" in res2.stdout, f"E-C6: step-2 STALE expected; got: {res2.stdout}"
    assert key_b not in ledger_entries(root), "E-C6: stale absorb must not enter the ledger"
    assert len(raw_files(root)) == 1, "E-C6: no extra raw may appear for the stale absorb (only the first absorb)"


# ---------------------------------------------------------------------------
# E-C7：端到端（collect → 混合 decision → apply）
# ---------------------------------------------------------------------------


def test_E_C7_end_to_end(tmp_path):
    """E-C7：absorb+discard+cleanup+prune_empty_pools 混合轮次；raw 全过 validate、账本/删源/索引逐字节核对。"""
    root = make_kit(tmp_path)
    source = tmp_path / "projects"
    source.mkdir()
    memory_md_p1 = (
        "# Memory Index\n"
        "- [Fact A](fact-a.md) — hook a\n"
        "- [Fact B](fact-b.md) — hook b\n"
        "- [Fact A dup](fact-a.md) — hook a again\n"
        "- [Fact D](fact-d.md) — hook d\n"
        "- [Gone](gone.md) — dangling line\n"
    )
    expected_memory_p1_final = (
        "# Memory Index\n"
        "- [Fact B](fact-b.md) — hook b\n"
        "- [Gone](gone.md) — dangling line\n"
    )
    make_pool(source, POOL_A, {"fact-a.md": FACT_A, "fact-b.md": FACT_B, "fact-d.md": FACT_D},
              memory_md=memory_md_p1)
    make_pool(source, POOL_G, {"fact-c.md": FACT_C}, memory_md=MEMORY_MD_G)
    make_pool(source, POOL_P, {}, memory_md="")  # 空壳池：仅 0 字节 MEMORY.md

    # 阶段 1：先吸收 fact-d 并复放同内容文件 → 制造 residue（供 cleanup 走完整混合轮）
    manifest1 = collect_manifest(tmp_path, root, source, tag="ec7a")
    pend1 = pending_map(manifest1)
    assert manifest1["summary"]["empty_pools"] == 1, "E-C7 premise: one empty pool expected"
    key_a = key_of(POOL_A, "fact-a.md")
    key_b = key_of(POOL_A, "fact-b.md")
    key_c = key_of(POOL_G, "fact-c.md")
    key_d = key_of(POOL_A, "fact-d.md")
    phase1 = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": [
        absorb_decision(key_d, pend1[key_d]["hash"], topic="contract-topic-d"),
    ]})
    res1 = apply_run(root, source, phase1)
    assert res1.returncode == 0, f"E-C7 phase1 must exit 0; output: {out_of(res1)}"
    write_file(source / POOL_A / "memory" / "fact-d.md", FACT_D)  # residue：同 hash 文件回到源

    # 阶段 2：混合决策轮（absorb×2 + discard×1 + cleanup×1 + prune×1）
    manifest2 = collect_manifest(tmp_path, root, source, tag="ec7b")
    pend2, residue2 = pending_map(manifest2), residue_map(manifest2)
    assert key_d in residue2, "E-C7 premise: fact-d must be residue before the mixed round"
    decision = write_decision(tmp_path, {
        "schema_version": 1,
        "client": "zcode",
        "decisions": [
            absorb_decision(key_a, pend2[key_a]["hash"]),                       # scope=project（在册）
            absorb_decision(key_c, pend2[key_c]["hash"], scope="global",
                            project_id=None, topic="contract-topic-c"),          # scope=global
            discard_decision(key_b, pend2[key_b]["hash"], reason="session noise"),
        ],
        "cleanup": [{"key": key_d, "hash": residue2[key_d]["hash"]}],
        "prune_empty_pools": [POOL_P],
    })
    res = apply_run(root, source, decision)
    assert res.returncode == 0, f"E-C7 mixed apply must exit 0; output: {out_of(res)}"
    for marker in ("absorbed:", "discarded:", "deleted source:", "pruned empty pool:"):
        assert marker in res.stdout, f"E-C7: '{marker}' expected in apply report; got: {res.stdout}"

    # raw 全部通过 hongzhao validate 语义（CLI 全 kit 校验）
    val = validate_run(root)
    assert val.returncode == 0, f"E-C7: validate must pass on absorbed raws; output: {out_of(val)}"
    assert "validation: degraded" not in val.stdout, f"E-C7: health must not degrade; got: {val.stdout}"
    assert "[RAW_" not in val.stdout, f"E-C7: no raw-schema issues expected; got: {val.stdout}"

    # 账本记账正确：absorbed 带 raw、discarded 带 reason
    entries = ledger_entries(root)
    assert entries[key_a]["state"] == "absorbed" and (Path(root) / entries[key_a]["raw"]).is_file()
    assert entries[key_c]["state"] == "absorbed" and (Path(root) / entries[key_c]["raw"]).is_file()
    assert entries[key_d]["state"] == "absorbed" and (Path(root) / entries[key_d]["raw"]).is_file()
    assert entries[key_b]["state"] == "discarded" and entries[key_b]["reason"] == "session noise"
    raw_a = (Path(root) / entries[key_a]["raw"]).read_text(encoding="utf-8")
    assert f"> 来源：ZCode auto-memory {key_a}（" in raw_a, "E-C7: raw must carry the provenance footnote"

    # 源文件删除语义：absorbed/cleanup 删、discard 留、空壳池修剪
    assert not (source / POOL_A / "memory" / "fact-a.md").exists(), "E-C7: absorbed fact-a source deleted"
    assert not (source / POOL_A / "memory" / "fact-d.md").exists(), "E-C7: cleaned fact-d source deleted"
    assert not (source / POOL_G / "memory" / "fact-c.md").exists(), "E-C7: absorbed fact-c source deleted"
    assert (source / POOL_A / "memory" / "fact-b.md").exists(), "E-C7: discarded fact-b source kept (S3)"
    assert not (source / POOL_P).exists(), "E-C7: empty pool must be pruned"

    # MEMORY.md：被 absorb 文件的全部索引行（含重复行）删除，其余行逐字节保留
    assert (source / POOL_A / "memory" / "MEMORY.md").read_bytes() == expected_memory_p1_final.encode("utf-8"), (
        "E-C7: MEMORY.md must equal the expected surviving lines byte-for-byte"
    )
    assert (source / POOL_G / "memory" / "MEMORY.md").read_bytes() == b"", (
        "E-C7: gamma index had no fact-c survivors (single line removed, file becomes empty)"
    )

    # 轮次收敛：全决策后同源再 collect → pending=0、residue=0
    final = collect_manifest(tmp_path, root, source, tag="ec7c")
    assert final["summary"]["pending"] == 0 and final["summary"]["residue"] == 0, (
        f"E-C7: converged collect expected; got summary={final['summary']}"
    )


# ---------------------------------------------------------------------------
# E-C8：MEMORY.md 行尾纪律（行级原字节拼接，不用主导行尾策略）
# ---------------------------------------------------------------------------


def _eol_case(tmp_path, memory_md: str, expected_kept: str, tag: str) -> None:
    root = make_kit(tmp_path)
    source = tmp_path / "projects"
    source.mkdir()
    pool = POOL_E1 if tag == "crlf" else POOL_E2
    make_pool(source, pool, {"a.md": FACT_A, "b.md": FACT_B}, memory_md=memory_md)
    manifest = collect_manifest(tmp_path, root, source, tag=tag)
    key_a = key_of(pool, "a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    res = apply_run(root, source, decision)
    assert res.returncode == 0, f"E-C8[{tag}]: apply must exit 0; output: {out_of(res)}"
    got = (source / pool / "memory" / "MEMORY.md").read_bytes()
    assert got == expected_kept.encode("utf-8"), (
        f"E-C8[{tag}]: unmatched lines must keep their original bytes; "
        f"expected {expected_kept.encode('utf-8')!r}; got {got!r}"
    )


def test_E_C8_pure_crlf_memory_md(tmp_path):
    """E-C8（纯 CRLF）：改写后未匹配行原字节保留（CRLF 不被归一）。"""
    memory_md = (
        "# Memory Index\r\n"
        "- [A](a.md) — one\r\n"
        "- [B](b.md) — keep\r\n"
        "- [A](a.md) — dup\r\n"
    )
    expected = "# Memory Index\r\n- [B](b.md) — keep\r\n"
    _eol_case(tmp_path, memory_md, expected, tag="crlf")


def test_E_C8_mixed_endings_memory_md(tmp_path):
    """E-C8（混合行尾 CR/LF/CRLF 交错）：行级过滤原字节拼接，每行保留自身行尾。"""
    memory_md = (
        "# Memory Index\r"
        "- [A](a.md) — one\n"
        "- [B](b.md) — keep\r\n"
        "- [A](a.md) — dup\r"
    )
    expected = "# Memory Index\r- [B](b.md) — keep\r\n"
    _eol_case(tmp_path, memory_md, expected, tag="mixed")


# ---------------------------------------------------------------------------
# E-C12 / E-C14：compile 对拍（零回归 ≠ 零纳入）
# ---------------------------------------------------------------------------


def _snapshot_compiled(root: Path) -> dict:
    snapshot = {}
    for base in ("compiled", "render"):
        directory = Path(root) / base
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                snapshot[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
    return snapshot


def _seed_raw(root: Path) -> None:
    ident = uuid.uuid4()
    frontmatter = {
        "schema_version": 2,
        "id": f"mem-{ident}",
        "created": "2026-11-01",
        "source": "user",
        "topic": "seed-topic",
        "kind": "memory",
        "scope": "global",
        "activation": "on-demand",
        "record_type": "source",
        "summary": "Seed record to give the compile baseline real content.",
        "compile_status": "done",
        "supersedes": [],
    }
    name = f"2026-11-01_seed-topic_{str(ident).replace('-', '')[:8]}.md"
    write_file(Path(root) / "raw" / name,
               "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
               + "---\n\nSeed body.\n")


def test_E_C12_empty_apply_leaves_compile_untouched(tmp_path):
    """E-C12：compile 基线 → 空决策 apply → 再 compile：剥离 generated_at 后字节一致。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    _seed_raw(root)
    first = compile_run(root)
    assert first.returncode == 0, f"E-C12: baseline compile #1 must exit 0; output: {out_of(first)}"
    second = compile_run(root)  # 二次编译进入稳定基线（首轮 diff 无前序基线）
    assert second.returncode == 0, f"E-C12: baseline compile #2 must exit 0; output: {out_of(second)}"
    baseline = _snapshot_compiled(root)
    assert baseline and "compiled/memory-index.yaml" in baseline, (
        f"E-C12 premise: baseline compile must produce outputs; got {sorted(baseline)}"
    )

    empty = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": []})
    res = apply_run(root, source, empty)
    assert res.returncode == 0 and "nothing to do" in res.stdout, (
        f"E-C12: empty apply must be a clean no-op; output: {out_of(res)}"
    )
    assert not (Path(root) / "collect").exists(), "E-C12: empty apply must not even create the ledger"

    third = compile_run(root)
    assert third.returncode == 0, f"E-C12: post-apply compile must exit 0; output: {out_of(third)}"
    after = _snapshot_compiled(root)
    assert sorted(after) == sorted(baseline), (
        f"E-C12: compile output file set must be unchanged; "
        f"only-in-baseline={sorted(set(baseline) - set(after))}, only-in-after={sorted(set(after) - set(baseline))}"
    )
    for rel in baseline:
        assert strip_volatile(after[rel]) == strip_volatile(baseline[rel]), (
            f"E-C12: compiled output must stay byte-identical after stripping generated_at: {rel}"
        )


def test_E_C14_absorbed_raw_enters_compile(tmp_path):
    """E-C14：单条 absorb → compile：新 raw 正常纳入 memory-index（零回归 ≠ 零纳入）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    base = compile_run(root)
    assert base.returncode == 0, f"E-C14: baseline compile must exit 0; output: {out_of(base)}"

    manifest = collect_manifest(tmp_path, root, source, tag="ec14")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": [
        absorb_decision(key_a, pending_map(manifest)[key_a]["hash"]),
    ]})
    res = apply_run(root, source, decision)
    assert res.returncode == 0, f"E-C14: absorb apply must exit 0; output: {out_of(res)}"
    ledger_record = ledger_entries(root)[key_a]

    compiled = compile_run(root)
    assert compiled.returncode == 0, f"E-C14: compile after absorb must exit 0; output: {out_of(compiled)}"
    index = yaml.safe_load((Path(root) / "compiled" / "memory-index.yaml").read_text(encoding="utf-8"))
    records = index.get("records", {})
    matches = [rid for rid, entry in records.items() if entry.get("path") == ledger_record["raw"]]
    assert len(matches) == 1, f"E-C14: absorbed raw must appear exactly once in memory-index; got {sorted(records)}"
    entry = records[matches[0]]
    assert entry["topic"] == "contract-topic" and entry["compile_status"] == "new", (
        f"E-C14: index entry must carry the decision topic and pending status; got {entry}"
    )
    assert index.get("health") != "degraded", f"E-C14: health must not degrade; got {index.get('health')}"


# ---------------------------------------------------------------------------
# D-C18：apply 成功后的 auto-commit（git.auto_commit 缺省开启）
# ---------------------------------------------------------------------------


def _git(root: Path, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)


def test_D_C18_apply_auto_commits_kit(tmp_path):
    """D-C18：真实 git kit（auto_commit 缺省开启）apply 含 absorb → 提交信息以 hongzhao collect apply 开头、账本与 raw 入库。"""
    root, source = make_kit(tmp_path, with_git_key=False), make_source(tmp_path)  # 缺省开启：config 不含 git 键
    assert _git(root, "init").returncode == 0, "D-C18 premise: git init must succeed"
    assert _git(root, "config", "user.name", "hongzhao-contract-test").returncode == 0
    assert _git(root, "config", "user.email", "contract@test.invalid").returncode == 0

    manifest = collect_manifest(tmp_path, root, source, tag="c18")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": [
        absorb_decision(key_a, pending_map(manifest)[key_a]["hash"]),
        discard_decision(key_of(POOL_A, "fact-b.md"), pending_map(manifest)[key_of(POOL_A, "fact-b.md")]["hash"]),
    ]})
    res = apply_run(root, source, decision)
    assert res.returncode == 0, f"D-C18: apply must exit 0; output: {out_of(res)}"
    assert "auto-commit:" in res.stdout, f"D-C18: auto-commit line expected; got: {res.stdout}"

    log = _git(root, "log", "-1", "--format=%s")
    assert log.returncode == 0, f"D-C18: git log must succeed; got: {log.stderr}"
    subject = log.stdout.strip()
    assert subject.startswith("hongzhao collect apply"), (
        f"D-C18: commit subject must start with 'hongzhao collect apply'; got: {subject!r}"
    )
    tracked = set(_git(root, "ls-files").stdout.split())
    ledger_record = ledger_entries(root)[key_a]
    assert "collect/zcode/ledger.yaml" in tracked, f"D-C18: ledger must be committed; tracked={sorted(tracked)}"
    assert ledger_record["raw"] in tracked, f"D-C18: raw must be committed; expected {ledger_record['raw']}"
    status = _git(root, "status", "--porcelain")
    assert status.returncode == 0 and status.stdout.strip() == "", (
        f"D-C18: working tree must be clean after auto-commit; got: {status.stdout!r}"
    )


# ---------------------------------------------------------------------------
# v3/D-C22：保留源模式（design v3 变更记录 + 3.3 决策表 D-C22 + 4.3 v3 注记 + 5.3/6.1）
# ---------------------------------------------------------------------------


def write_ledger(root: Path, entries: dict) -> None:
    """fixture 层手写整份账本（构造旧账本/非法账本形态）。"""
    payload = {"schema_version": 1, "client": "zcode", "updated_at": "2026-11-13",
               "entries": entries}
    write_file(ledger_path(root), yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))


def test_D_C22_keep_mode_end_to_end(tmp_path):
    """D-C22 端到端：delete_source=false → absorb 只写 raw+记账（source=kept），源与 MEMORY.md 字节不动，collect 全清。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    memory_before = (source / POOL_A / "memory" / "MEMORY.md").read_bytes()
    fact_a_path = source / POOL_A / "memory" / "fact-a.md"
    fact_a_before = fact_a_path.read_bytes()
    manifest = collect_manifest(tmp_path, root, source, tag="d22a")
    pend = pending_map(manifest)
    key_a, key_b = key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-b.md")
    decision = write_decision(tmp_path, {
        "schema_version": 1, "client": "zcode", "delete_source": False,
        "decisions": [
            absorb_decision(key_a, pend[key_a]["hash"]),
            discard_decision(key_b, pend[key_b]["hash"]),
        ],
    })
    res = apply_run(root, source, decision)
    assert res.returncode == 0, f"D-C22: keep-mode apply must exit 0; output: {out_of(res)}"
    assert "deleted source" not in res.stdout, f"D-C22: no delete may happen in keep mode; got: {res.stdout}"

    # 客户端原始记录全部保留（absorb 保留 + discard 本就不删），MEMORY.md 一个字节不动
    assert fact_a_path.read_bytes() == fact_a_before, "D-C22: kept fact file must stay byte-identical"
    assert (source / POOL_A / "memory" / "fact-b.md").exists(), "D-C22: discard keeps the source (S3)"
    assert (source / POOL_A / "memory" / "MEMORY.md").read_bytes() == memory_before, (
        "D-C22: MEMORY.md must not be touched at all in keep mode"
    )

    # raw 落盘 + 账本记 source=kept
    assert len(raw_files(root)) == 1, "D-C22: keep mode still writes the raw"
    entries = ledger_entries(root)
    assert entries[key_a]["state"] == "absorbed" and entries[key_a]["source"] == "kept", (
        f"D-C22: absorbed entry must record source=kept; got {entries.get(key_a)}"
    )
    assert (Path(root) / entries[key_a]["raw"]).is_file(), "D-C22: ledger raw must point at a real file"

    # collect 全清：kept 同 hash 在场 = 正常终态（不 pending、不 residue）；discarded 同 hash 不冒回
    after = collect_manifest(tmp_path, root, source, tag="d22b")
    assert after["summary"]["pending"] == 0 and after["summary"]["residue"] == 0, (
        f"D-C22: kept terminal + discarded suppressed must leave a fully clean manifest; got {after['summary']}"
    )
    assert key_a not in pending_map(after) and key_a not in residue_map(after), (
        "D-C22: kept entry must appear in no list (normal terminal state)"
    )


def test_D_C22_kept_then_edit_reflows(tmp_path):
    """D-C22+S10：kept 条目内容变化仍以新 hash 回流 pending；再次 keep 吸收覆盖账本记录。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="d22c")
    key_a = key_of(POOL_A, "fact-a.md")
    old_hash = pending_map(manifest)[key_a]["hash"]
    keep = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "delete_source": False,
                                     "decisions": [absorb_decision(key_a, old_hash)]})
    assert apply_run(root, source, keep).returncode == 0

    # 内容变化 → 新 hash 回流重审（S10 不因 keep 模式豁免）
    write_file(source / POOL_A / "memory" / "fact-a.md", FACT_A2)
    reflow = collect_manifest(tmp_path, root, source, tag="d22d")
    pend = pending_map(reflow)
    assert key_a in pend and pend[key_a]["hash"] != old_hash, (
        "D-C22: edited kept entry must reflow to pending at the new hash"
    )
    assert reflow["summary"]["residue"] == 0, "D-C22: changed content is pending, not residue"

    # 再次 keep 吸收新 hash：覆盖旧记录（6.1 同 key 多次决策），仍保留源、终态全清
    second = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "delete_source": False,
                                       "decisions": [absorb_decision(key_a, pend[key_a]["hash"],
                                                                     topic="contract-topic-2")]})
    res = apply_run(root, source, second)
    assert res.returncode == 0, f"D-C22: re-absorb must exit 0; output: {out_of(res)}"
    entries = ledger_entries(root)
    assert entries[key_a]["hash"] == pend[key_a]["hash"] and entries[key_a]["source"] == "kept", (
        "D-C22: re-decision must overwrite the ledger record at the new hash, still kept"
    )
    fact_a = source / POOL_A / "memory" / "fact-a.md"
    assert fact_a.exists() and fact_a.read_text(encoding="utf-8") == FACT_A2, (
        "D-C22: re-absorb in keep mode must keep the edited source byte-identical"
    )
    final = collect_manifest(tmp_path, root, source, tag="d22e")
    assert key_a not in pending_map(final) and key_a not in residue_map(final), (
        "D-C22: kept re-absorb must converge the entry out of every list"
    )
    assert final["summary"]["pending"] == 1, (
        f"D-C22: only the never-decided fact-b stays pending (S5); got {final['summary']}"
    )


def test_D_C22_default_true_writes_source_deleted(tmp_path):
    """D-C22 缺省回归：delete_source 缺省/显式 true 均为 v2 行为（删源 + 账本 source=deleted）；旧账本缺 source 视为 deleted。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="d22f")
    pend = pending_map(manifest)
    key_a, key_b = key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-b.md")

    # 面 1：决策不带 delete_source 键（缺省 true）→ 删源 + source=deleted
    # （文件删除/索引行清除面已由 S02/E-C7 既有用例覆盖，此处聚焦 v3 新增的账本字段）
    implicit = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pend[key_a]["hash"])]})
    res1 = apply_run(root, source, implicit)
    assert res1.returncode == 0, f"D-C22: default apply must exit 0; output: {out_of(res1)}"
    assert not (source / POOL_A / "memory" / "fact-a.md").exists(), (
        "D-C22: default (no delete_source key) must keep v2 delete behavior"
    )
    assert ledger_entries(root)[key_a]["source"] == "deleted", (
        "D-C22: default path must record source=deleted"
    )

    # 面 2：显式 delete_source: true → 同 v2 行为
    explicit = write_decision(tmp_path, {"schema_version": 1, "client": "zcode", "delete_source": True,
                                         "decisions": [absorb_decision(key_b, pend[key_b]["hash"])]})
    res2 = apply_run(root, source, explicit)
    assert res2.returncode == 0, f"D-C22: explicit-true apply must exit 0; output: {out_of(res2)}"
    assert not (source / POOL_A / "memory" / "fact-b.md").exists(), (
        "D-C22: explicit delete_source=true must delete the source"
    )
    assert ledger_entries(root)[key_b]["source"] == "deleted", (
        "D-C22: explicit-true path must record source=deleted"
    )

    # 面 3：旧账本（v2 形态，条目缺 source 字段）+ 同 hash 文件在场 → 仍按 deleted 报 residue
    write_file(source / POOL_A / "memory" / "fact-a.md", FACT_A)  # 同内容文件回到源
    ledger_data = yaml.safe_load(ledger_path(root).read_text(encoding="utf-8"))
    del ledger_data["entries"][key_a]["source"]  # 手工降级为 v2 旧账本形态
    write_file(ledger_path(root), yaml.safe_dump(ledger_data, allow_unicode=True, sort_keys=False))
    legacy = collect_manifest(tmp_path, root, source, tag="d22g")
    assert key_a in residue_map(legacy), (
        "D-C22: legacy ledger entry without source must be treated as deleted (residue applies)"
    )


def test_D_C22_keep_mode_does_not_gate_explicit_cleanup(tmp_path):
    """D-C22：keep 模式只豁免本次 absorbed 的删源；显式 cleanup 清单照常执行（引擎能力不变）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="d22h")
    pend = pending_map(manifest)
    key_a, key_b = key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-b.md")

    # 预置 residue：v2 吸收 fact-a 后同内容文件回到源
    setup = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                      "decisions": [absorb_decision(key_a, pend[key_a]["hash"])]})
    assert apply_run(root, source, setup).returncode == 0
    write_file(source / POOL_A / "memory" / "fact-a.md", FACT_A)
    ledger_hash = ledger_entries(root)[key_a]["hash"]
    memory_before = (source / POOL_A / "memory" / "MEMORY.md").read_bytes()

    # keep 模式决策：absorb fact-b（保留）+ 显式 cleanup fact-a（补删）
    mixed = write_decision(tmp_path, {
        "schema_version": 1, "client": "zcode", "delete_source": False,
        "decisions": [absorb_decision(key_b, pend[key_b]["hash"])],
        "cleanup": [{"key": key_a, "hash": ledger_hash}],
    })
    res = apply_run(root, source, mixed)
    assert res.returncode == 0, f"D-C22: keep-mode apply with explicit cleanup must exit 0; output: {out_of(res)}"
    assert "deleted source:" in res.stdout, (
        f"D-C22: explicit cleanup must still delete in keep mode; got: {res.stdout}"
    )
    assert not (source / POOL_A / "memory" / "fact-a.md").exists(), "D-C22: cleanup target must be deleted"
    fact_b = source / POOL_A / "memory" / "fact-b.md"
    assert fact_b.exists(), "D-C22: keep-mode absorb target must survive"
    assert (source / POOL_A / "memory" / "MEMORY.md").read_bytes() == memory_before, (
        "D-C22: keep-mode round must not rewrite MEMORY.md (no index line removed)"
    )
    entries = ledger_entries(root)
    assert entries[key_a]["source"] == "deleted" and entries[key_b]["source"] == "kept", (
        "D-C22: ledger must record per-decision provenance (setup deleted, keep-mode kept)"
    )
    final = collect_manifest(tmp_path, root, source, tag="d22i")
    assert final["summary"]["pending"] == 0 and final["summary"]["residue"] == 0, (
        f"D-C22: mixed keep+cleanup round must converge; got {final['summary']}"
    )


def test_D_C22_ledger_source_enum_and_flag_validation(tmp_path):
    """D-C22 校验面：账本 source ∉ {deleted,kept} → COLLECT_LEDGER_INVALID（collect/apply 双面）；合法枚举通过且 kept 豁免 residue；delete_source 非布尔 → APPLY_DECISION_INVALID。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    key_a, key_b = key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-b.md")

    # 面 1：非法 source 枚举 → collect fatal exit 2，apply 同口径 fatal，零写入
    write_ledger(root, {
        key_a: {"hash": "sha256:" + "0" * 64, "state": "absorbed",
                "raw": "raw/2026-11-13_x_0000000000000000.md",
                "decided_at": "2026-11-13", "source": "vanished"},
    })
    corrupt_bytes = ledger_path(root).read_bytes()
    res = collect_run(root, source)
    assert res.returncode == 2, f"D-C22: invalid ledger source must fatal collect; got {res.returncode}"
    assert "COLLECT_LEDGER_INVALID" in out_of(res), f"D-C22: error code expected; got: {out_of(res)}"
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, sha_of(source / POOL_A / "memory" / "fact-a.md"))]})
    res2 = apply_run(root, source, decision)
    assert res2.returncode == 2, f"D-C22: invalid ledger source must fatal apply; got {res2.returncode}"
    assert "COLLECT_LEDGER_INVALID" in out_of(res2), f"D-C22: apply error code expected; got: {out_of(res2)}"
    assert ledger_path(root).read_bytes() == corrupt_bytes, "D-C22: fatal path must not rewrite the ledger"
    assert raw_files(root) == [], "D-C22: fatal path must not write raw files"

    # 面 2：合法枚举（kept+deleted 并存）→ 解析通过；manifest 层 kept 豁免 residue、deleted 照报
    write_ledger(root, {
        key_a: {"hash": sha_of(source / POOL_A / "memory" / "fact-a.md"), "state": "absorbed",
                "raw": "raw/2026-11-13_x_1111111111111111.md",
                "decided_at": "2026-11-13", "source": "kept"},
        key_b: {"hash": sha_of(source / POOL_A / "memory" / "fact-b.md"), "state": "absorbed",
                "raw": "raw/2026-11-13_x_2222222222222222.md",
                "decided_at": "2026-11-13", "source": "deleted"},
    })
    res3 = collect_run(root, source)
    assert res3.returncode == 0, f"D-C22: valid source enum must pass; got: {out_of(res3)}"
    valid_bytes = ledger_path(root).read_bytes()
    manifest = collect_manifest(tmp_path, root, source, tag="d22j")
    assert key_a not in residue_map(manifest) and manifest["summary"]["pending"] == 0, (
        "D-C22: kept entry at the same hash must be exempt from residue"
    )
    assert key_b in residue_map(manifest), "D-C22: deleted entry at the same hash must still be residue"

    # 面 3：decision delete_source 非布尔 → APPLY_DECISION_INVALID（fatal exit 2，零写入）
    bad_flag = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "delete_source": "false", "decisions": []})
    res4 = apply_run(root, source, bad_flag)
    assert res4.returncode == 2, f"D-C22: non-bool delete_source must fatal; got {res4.returncode}"
    assert "APPLY_DECISION_INVALID" in out_of(res4), f"D-C22: error code expected; got: {out_of(res4)}"
    assert ledger_path(root).read_bytes() == valid_bytes, "D-C22: invalid flag must not touch the ledger"
