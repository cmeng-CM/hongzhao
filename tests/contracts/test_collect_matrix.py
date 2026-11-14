# -*- coding: utf-8 -*-
"""独立合同测试（作者未参与实现；design 第 7 章要求）。

hongzhao v0.4 客户端记忆采集（collect）合同矩阵——**设计 v6 基线**
（.delivery/2026-11-13-客户端记忆采集/design.md v6，D-C28 严格只读采集）：

- 4.3 条目状态转换矩阵 S1–S17 逐行（按 v6 注记后生效的语义；S8/S9 随 cleanup
  写路径整体移除，不再成行）；S2 = absorb 只写 raw＋记账、客户端零改动；
  S7 = absorbed 同 hash 在场＝正常终态，manifest 无 residue 字段（顶层与
  summary 均无）；
- 4.3 组合约束 W1/W2 崩溃窗口（v6 故障注入点收敛为 after-raws / after-ledger，
  E-C5；W3 与 after-deletes 随删源路径移除）；
- v6/D-C28 已移除的四个客户端写字段（delete_source / slim_index / cleanup /
  prune_empty_pools）逐字段拒绝：[APPLY_DECISION_INVALID] exit 2、零写入、
  错误文案含 "client-side write fields are removed"；
- D-C27 双客户端：--client zcode|claude_code（未知客户端报支持清单）、
  claude_code 源端到端（raw source=claude-code、脚注标签 Claude Code、
  账本分目录）；
- v6 复 apply 语义：同决策重放 = APPLY_ENTRY_DUPLICATE（源永在，不双写）；
- E-C7 端到端（v6：raw 合法、账本正确、客户端目录树逐字节不变、重复索引行
  仍在——因为只读）、E-C12/E-C14 compile 对拍、D-C18 auto-commit（提交信息
  absorbed=N discarded=M，无 cleaned）、D-C24 mentioned_in、D-C25 --pool 过滤
  与子命令级 --dry-run、CLI UTF-8 回归。

纪律（design 第 7 章「合同测试作者 ≠ 实现者」）：
- 全部走真实文件系统 + 子进程 CLI（sys.executable -m hongzhao，包公开入口），
  不 mock 文件层、不 import 引擎内部实现；kit 与源池 fixture 本文件自建，
  不 import tests/unit；
- 崩溃注入与 compile 对拍一律子进程；结果核对仅读产物文件（YAML/字节）；
- 客户端侧零写是 v6 核心合同：多处用整个 projects 目录树的前后字节快照对拍
  （文件字节＋目录清单，最强断言）。
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

# 池目录名仿真实形态：ZCode <pool>-<16hex>；CC 为项目路径 slug
POOL_A = "alpha-a1b2c3d4e5f60718"
POOL_B = "beta-b2c3d4e5f6071890"
POOL_G = "gamma-c3d4e5f60718a1b2"
POOL_P = "delta-f60718a1b2c3d4e"
POOL_CC = "-Users-cm-workspace-demo-app"

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

# MEMORY.md 索引（S 矩阵基线池）：fact-a 双行（重复行）+ fact-b + 悬空行
MEMORY_MD_A = (
    "# Memory Index\n"
    "- [Fact A](fact-a.md) — hook a\n"
    "- [Fact B](fact-b.md) — hook b\n"
    "- [Fact A dup](fact-a.md) — hook a again\n"
    "- [Gone](gone.md) — dangling line\n"
)
# E-C7 富 fixture：池 A 索引为纯 CRLF（v6 下只读面也必须原字节保留）
MEMORY_MD_RICH_A = (
    "# Memory Index\r\n"
    "- [Fact A](fact-a.md) — hook a\r\n"
    "- [Fact B](fact-b.md) — hook b\r\n"
    "- [Fact D](fact-d.md) — hook d\r\n"
    "- [Fact A dup](fact-a.md) — hook a again\r\n"
    "- [Gone](gone.md) — dangling line\r\n"
)
# E-C7 富 fixture：池 G 索引为混合行尾（CR / LF 交错）
MEMORY_MD_RICH_G = "# Memory Index\r- [Fact C](fact-c.md) — hook c\n"

CRASH_EXIT = 70  # os._exit(70)（collect._crash，design 7 章故障注入机制）
# v6/D-C28：summary 冻结键集——residue 已随概念一并移除
SUMMARY_KEYS = {"pools", "files", "pending", "unparsable", "empty_pools"}


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
        # CI windows 维护注记：CLI 已强制 UTF-8 输出，父进程必须显式按 UTF-8 解码
        # ——text=True 缺省走 locale（cp1252）严格解码中文清单必炸 UnicodeDecodeError
        encoding="utf-8",
        errors="replace",
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


def ledger_path(root: Path, client: str = "zcode") -> Path:
    return Path(root) / "collect" / client / "ledger.yaml"


def ledger_entries(root: Path, client: str = "zcode") -> dict:
    path = ledger_path(root, client)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("entries") or {}


def raw_files(root: Path) -> list:
    return sorted((Path(root) / "raw").glob("*.md"))


def snapshot_tree(base: Path) -> dict:
    """整个目录树快照：文件→字节、目录→None（相对 POSIX 路径为键）。

    v6/D-C28 最强断言的基础：对拍前后快照即证明客户端侧一个字节、一个条目
    都没变（含空目录的存废）。
    """
    snap: dict[str, object] = {}
    for path in sorted(Path(base).rglob("*")):
        rel = path.relative_to(base).as_posix()
        snap[rel] = path.read_bytes() if path.is_file() else None
    return snap


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


def assert_manifest_v6(manifest: dict, where: str) -> None:
    """v6 形状锁：manifest 顶层与 summary 都无 residue 字段，summary 键集冻结。"""
    assert "residue" not in manifest, f"{where}: manifest must not carry a residue field (v6/D-C28)"
    assert "residue" not in manifest["summary"], f"{where}: summary must not carry residue (v6/D-C28)"
    assert set(manifest["summary"]) == SUMMARY_KEYS, (
        f"{where}: summary key set must equal the v6 frozen set {sorted(SUMMARY_KEYS)}; "
        f"got {sorted(manifest['summary'])}"
    )


# ---------------------------------------------------------------------------
# 4.3 状态矩阵逐行（v6 注记后语义；S8/S9 已随 cleanup 写路径移除）
# ---------------------------------------------------------------------------


def _row_s01(tmp_path):
    """S1：不在账本 + 扫描 present(h) → pending(h)，进 manifest.pending；纯 collect 零写入。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s01")
    pend = pending_map(manifest)
    key_a, key_b = key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-b.md")
    assert key_a in pend and key_b in pend, f"S1: fresh entries must be pending; got {sorted(pend)}"
    assert pend[key_a]["hash"] == sha_of(source / POOL_A / "memory" / "fact-a.md"), (
        "S1: pending hash must equal the file content hash"
    )
    assert_manifest_v6(manifest, "S1")
    assert not ledger_path(root).exists(), "S1: pure collect must not create a ledger"


def _row_s02(tmp_path):
    """S2（v6）：pending(h) + apply absorb → absorbed(h)→raw；写 raw→记账，客户端零改动。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    tree_before = snapshot_tree(source)
    manifest = collect_manifest(tmp_path, root, source, tag="s02")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    res = apply_run(root, source, decision)
    assert res.returncode == 0, f"S2: absorb apply must exit 0; output: {out_of(res)}"
    assert "absorbed:" in res.stdout and "client side untouched" in res.stdout, (
        f"S2: absorbed report line expected; got: {res.stdout}"
    )

    raws = raw_files(root)
    assert len(raws) == 1, f"S2: exactly one raw expected; got {[p.name for p in raws]}"
    record = ledger_entries(root).get(key_a)
    assert record and record["state"] == "absorbed", f"S2: ledger must record absorbed; got {record}"
    assert record["raw"] == f"raw/{raws[0].name}", "S2: ledger raw must point at the written file"
    assert record["hash"] == pending_map(manifest)[key_a]["hash"], (
        "S2: ledger hash must equal the decided source hash"
    )
    assert "source" not in record, "S2: v6/D-C28 ledger entries must not carry a source field"
    # v6/D-C28 核心断言：absorb＝raw＋记账，客户端目录树逐字节不变
    assert snapshot_tree(source) == tree_before, (
        "S2: absorb must leave the whole client tree byte-identical (strict read-only)"
    )
    memory_md = (source / POOL_A / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert memory_md.count("(fact-a.md)") == 2, (
        "S2: duplicate fact-a index lines must still be present (read-only collection)"
    )


def _row_s03(tmp_path):
    """S3：pending(h) + apply discard → discarded(h)；仅记账，客户端零改动。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    tree_before = snapshot_tree(source)
    manifest = collect_manifest(tmp_path, root, source, tag="s03")
    key_b = key_of(POOL_A, "fact-b.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [discard_decision(key_b, pending_map(manifest)[key_b]["hash"])]})
    res = apply_run(root, source, decision)
    assert res.returncode == 0, f"S3: discard apply must exit 0; output: {out_of(res)}"
    assert "discarded:" in res.stdout and "client side untouched" in res.stdout, (
        f"S3: discarded report line expected; got: {res.stdout}"
    )
    record = ledger_entries(root).get(key_b)
    assert record and record["state"] == "discarded" and record["reason"] == "session-scoped note", (
        f"S3: ledger must record discarded with reason; got {record}"
    )
    assert "raw" not in (record or {}), "S3: discarded entry must not reference a raw"
    assert snapshot_tree(source) == tree_before, (
        "S3: discard must leave the whole client tree byte-identical (ledger only)"
    )


def _row_s04(tmp_path):
    """S4：pending(h) + apply 时文件 hash≠h → 报 STALE 跳过，条目保持 pending。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    tree_before = snapshot_tree(source)
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
    assert (source / POOL_A / "memory" / "fact-a.md").read_text(encoding="utf-8") == FACT_A2, (
        "S4: drifted file must be kept with its drifted bytes"
    )
    again = collect_manifest(tmp_path, root, source, tag="s04b")
    assert key_a in pending_map(again), "S4: entry must stay pending at the new hash"
    assert pending_map(again)[key_a]["hash"] != stale_hash, "S4: reflow must carry the new hash"


def _row_s05(tmp_path):
    """S5：pending(h) 未出现在 decision → 无动作，下次 collect 仍冒出（未决语义）＋幂等。"""
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
    """S6：absorbed(h) + 扫描 absent（客户端自删）→ absorbed(h) 终态，不进任何清单。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="s06")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    assert apply_run(root, source, decision).returncode == 0
    (source / POOL_A / "memory" / "fact-a.md").unlink()  # v6：源永在，absent 只能是客户端自删
    after = collect_manifest(tmp_path, root, source, tag="s06b")
    assert key_a not in pending_map(after), "S6: absorbed+absent must not be pending"
    assert_manifest_v6(after, "S6")
    assert after["summary"]["pending"] == 1, (
        f"S6: only the never-decided fact-b stays pending; got {after['summary']}"
    )
    record = ledger_entries(root).get(key_a)
    assert record and record["state"] == "absorbed", "S6: ledger keeps absorbed as terminal state"


def _row_s07(tmp_path):
    """S7（v6）：absorbed(h) + 扫描 present(h) → absorbed(h) 正常终态；无 residue 概念，不冒回。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    tree_before = snapshot_tree(source)
    manifest = collect_manifest(tmp_path, root, source, tag="s07")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    assert apply_run(root, source, decision).returncode == 0
    # v6：源永在 → absorbed 同 hash 在场是常态；不得重进 pending，也不存在 residue 清单
    after = collect_manifest(tmp_path, root, source, tag="s07b")
    assert key_a not in pending_map(after), "S7: same-hash survivor must not re-enter pending"
    assert_manifest_v6(after, "S7")
    assert after["summary"]["pending"] == 1, (
        f"S7: only the undecided fact-b stays pending; got {after['summary']}"
    )
    assert (source / POOL_A / "memory" / "fact-a.md").exists(), (
        "S7: absorbed source must still be on disk (read-only collection)"
    )
    assert snapshot_tree(source) == tree_before, "S7: client tree must stay byte-identical"
    record = ledger_entries(root).get(key_a)
    assert record and record["state"] == "absorbed", "S7: ledger keeps absorbed as terminal state"


def _row_s10(tmp_path):
    """S10：absorbed(h) + 扫描 present(h′) → pending(h′) 回流重审（源永在，内容变化即回流）。"""
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


def _row_s11(tmp_path):
    """S11：discarded(h) + 扫描 present(h) → 无动作、不冒回（弃用记账的意义）。"""
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
    assert second["summary"]["pending"] == 0, (
        f"S11: same-hash discarded entry stays suppressed on every collect; got {second['summary']}"
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
    """S13：任意条目文件解析失败 → unparsable（不入账本），只报错清单，文件保留。"""
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
    assert_manifest_v6(manifest, "S14")
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
    """S17：discarded(h) + 扫描 absent → discarded(h) 终态，不进任何清单。"""
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
    assert after["summary"]["pending"] == 0, (
        f"S17: entry appears in no manifest list (terminal); got {after['summary']}"
    )
    record = ledger_entries(root).get(key_b)
    assert record and record["state"] == "discarded", "S17: ledger keeps discarded as terminal state"


# v6/D-C28：S8/S9（cleanup 补删与 hash 不符跳过）随 cleanup 写路径整体移除，不再成行
ROW_HANDLERS = {
    1: _row_s01, 2: _row_s02, 3: _row_s03, 4: _row_s04, 5: _row_s05, 6: _row_s06,
    7: _row_s07, 10: _row_s10, 11: _row_s11, 12: _row_s12,
    13: _row_s13, 14: _row_s14, 15: _row_s15, 16: _row_s16, 17: _row_s17,
}


@pytest.mark.parametrize("row", [pytest.param(n, id=f"S{n:02d}") for n in
                                 [1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16, 17]])
def test_collect_state_matrix_row(row, tmp_path):
    """逐行执行 design 4.3 状态矩阵第 row 行（真实 CLI、真实目录树、v6 语义）。"""
    ROW_HANDLERS[row](tmp_path)


# ---------------------------------------------------------------------------
# E-C5：写序崩溃窗口（v6 故障注入点收敛为 after-raws / after-ledger）
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
    """W1（after-raws）：raw 已写、账本未记 → 条目回流 pending；复 apply 收敛（宁重复不丢失）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    tree_before = snapshot_tree(source)
    manifest = collect_manifest(tmp_path, root, source, tag="w1")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    res = apply_run(root, source, decision, env_extra=fault_env("after-raws"))
    _assert_crash(res, "after-raws")

    # 崩溃后磁盘状态：raw 在、账本无记录、客户端零改动、条目仍 pending
    assert len(raw_files(root)) == 1, "E-C5[W1]: raw must already be on disk"
    assert not (Path(root) / "collect").exists(), (
        "E-C5[W1]: ledger must not exist yet (raw first, ledger second)"
    )
    assert snapshot_tree(source) == tree_before, "E-C5[W1]: crash must leave the client tree untouched"
    after = collect_manifest(tmp_path, root, source, tag="w1b")
    assert key_a in pending_map(after), "E-C5[W1]: entry must stay pending after the crash (no silent loss)"

    # 恢复：普通 apply 重放同一决策 → 收敛；崩溃残留 raw 保留（重复候选可见，模型判重消化）
    recovery = apply_run(root, source, decision)
    assert recovery.returncode == 0, f"E-C5[W1]: recovery apply must exit 0; output: {out_of(recovery)}"
    assert len(raw_files(root)) == 2, (
        "E-C5[W1]: crash-residual raw plus recovery raw must both persist (duplicate over loss)"
    )
    record = ledger_entries(root).get(key_a)
    assert record and record["state"] == "absorbed", "E-C5[W1]: recovery must record absorbed"
    assert (Path(root) / record["raw"]).is_file(), "E-C5[W1]: ledger raw must point at a real file"
    assert snapshot_tree(source) == tree_before, "E-C5[W1]: recovery must leave the client tree untouched"
    final = collect_manifest(tmp_path, root, source, tag="w1c")
    assert key_a not in pending_map(final) and final["summary"]["pending"] == 1, (
        "E-C5[W1]: entry must converge; only the never-decided fact-b stays pending"
    )


def test_E_C5_W2_crash_after_ledger(tmp_path):
    """W2（after-ledger）：账本已记、（v6 无删源步骤）→ 一切终态正常收敛，重放=DUPLICATE。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    tree_before = snapshot_tree(source)
    manifest = collect_manifest(tmp_path, root, source, tag="w2")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    res = apply_run(root, source, decision, env_extra=fault_env("after-ledger"))
    _assert_crash(res, "after-ledger")

    # 崩溃后磁盘状态：账本已记 absorbed、raw 在、客户端零改动（v6：无删源窗口）
    record = ledger_entries(root).get(key_a)
    assert record and record["state"] == "absorbed", f"E-C5[W2]: ledger must hold absorbed; got {record}"
    assert "source" not in record, "E-C5[W2]: v6 ledger entries must not carry a source field"
    assert len(raw_files(root)) == 1, "E-C5[W2]: raw must be on disk"
    assert snapshot_tree(source) == tree_before, "E-C5[W2]: crash must leave the client tree untouched"

    # collect 即终态：不 pending、无任何残留清单（同 hash 在场=正常终态）
    after = collect_manifest(tmp_path, root, source, tag="w2b")
    assert key_a not in pending_map(after), "E-C5[W2]: recorded entry must not re-enter pending"
    assert_manifest_v6(after, "E-C5[W2]")
    assert after["summary"]["pending"] == 1, (
        f"E-C5[W2]: only the undecided fact-b stays pending; got {after['summary']}"
    )

    # 重放同一决策 = DUPLICATE（v6/W5：源永在，同 (key,hash) 已决即拒），不双写
    replay = apply_run(root, source, decision)
    assert replay.returncode == 1, f"E-C5[W2]: replay must exit 1; got {replay.returncode}; output: {out_of(replay)}"
    assert "APPLY_ENTRY_DUPLICATE" in out_of(replay), f"E-C5[W2]: DUPLICATE expected; got: {out_of(replay)}"
    assert len(raw_files(root)) == 1, "E-C5[W2]: replay must not write a second raw"
    assert snapshot_tree(source) == tree_before, "E-C5[W2]: replay must leave the client tree untouched"


# ---------------------------------------------------------------------------
# v6/D-C28：已移除的四个客户端写字段逐字段拒绝（写了即 fatal，零写入）
# ---------------------------------------------------------------------------

REMOVED_FIELD_PAYLOADS = {
    "delete_source": False,          # v3/D-C22 形态（布尔开关）
    "slim_index": True,              # v4/D-C23 形态（布尔开关）
    "cleanup": [{"key": "x/memory/x.md", "hash": "sha256:" + "0" * 64}],   # v2 形态（清单）
    "prune_empty_pools": ["some-pool-0000000000000aaa"],                   # v2 形态（清单）
}


@pytest.mark.parametrize("removed_field", ["delete_source", "slim_index", "cleanup", "prune_empty_pools"])
def test_v6_removed_write_fields_rejected(tmp_path, removed_field):
    """v6/D-C28：被移除字段出现在 decision 顶层 → [APPLY_DECISION_INVALID] exit 2、零写入、文案点名。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    tree_before = snapshot_tree(source)
    manifest = collect_manifest(tmp_path, root, source, tag="rmv")
    key_a = key_of(POOL_A, "fact-a.md")
    payload = {"schema_version": 1, "client": "zcode",
               removed_field: REMOVED_FIELD_PAYLOADS[removed_field],
               # 带一条完全合法的 absorb：即便如此也必须整批 fatal、零写入
               "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]}
    decision = write_decision(tmp_path, payload)
    res = apply_run(root, source, decision)
    assert res.returncode == 2, (
        f"D-C28[{removed_field}]: removed write field must fatal with exit 2; "
        f"got rc={res.returncode}; output: {out_of(res)}"
    )
    assert "[APPLY_DECISION_INVALID]" in res.stderr, (
        f"D-C28[{removed_field}]: APPLY_DECISION_INVALID expected on stderr; got: {res.stderr}"
    )
    assert "client-side write fields are removed" in res.stderr, (
        f"D-C28[{removed_field}]: v6 removal message expected; got: {res.stderr}"
    )
    assert removed_field in res.stderr, (
        f"D-C28[{removed_field}]: error must name the offending field; got: {res.stderr}"
    )
    # 零写入：无 raw、无账本、客户端目录树逐字节不变
    assert raw_files(root) == [], f"D-C28[{removed_field}]: no raw may be written"
    assert not (Path(root) / "collect").exists(), f"D-C28[{removed_field}]: no ledger may be created"
    assert snapshot_tree(source) == tree_before, (
        f"D-C28[{removed_field}]: client tree must stay byte-identical"
    )


# ---------------------------------------------------------------------------
# E-C7：端到端（v6：collect → 混合 decision → apply；客户端目录树逐字节不变）
# ---------------------------------------------------------------------------


def test_E_C7_end_to_end(tmp_path):
    """E-C7（v6）：absorb+discard 混合轮次；raw 全过 validate、账本正确（无 source 字段）、
    客户端目录树前后字节快照逐字节相同、重复索引行仍在（只读）、收敛 pending=0。"""
    root = make_kit(tmp_path)
    source = tmp_path / "projects"
    source.mkdir()
    make_pool(source, POOL_A, {"fact-a.md": FACT_A, "fact-b.md": FACT_B,
                               "fact-d.md": FACT_D, "broken.md": "plain body without frontmatter\n"},
              memory_md=MEMORY_MD_RICH_A)
    make_pool(source, POOL_G, {"fact-c.md": FACT_C}, memory_md=MEMORY_MD_RICH_G)
    make_pool(source, POOL_P, {}, memory_md="")  # 空壳池：仅 0 字节 MEMORY.md（只读报告）
    (source / "not-a-memory-project").mkdir()  # D-C27：无 memory/ 的普通目录不是池
    tree_before = snapshot_tree(source)

    manifest = collect_manifest(tmp_path, root, source, tag="ec7a")
    assert manifest["summary"]["pools"] == 3 and manifest["summary"]["pending"] == 4, (
        f"E-C7 premise: three pools with four pending entries; got {manifest['summary']}"
    )
    assert manifest["summary"]["unparsable"] == 1 and manifest["summary"]["empty_pools"] == 1, (
        f"E-C7 premise: one unparsable file and one empty pool expected; got {manifest['summary']}"
    )
    assert POOL_P in manifest["empty_pools"] and "not-a-memory-project" not in manifest["empty_pools"], (
        "E-C7/D-C27: only memory/-bearing directories count as pools"
    )

    pend = pending_map(manifest)
    key_a, key_b = key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-b.md")
    key_c, key_d = key_of(POOL_G, "fact-c.md"), key_of(POOL_A, "fact-d.md")
    decision = write_decision(tmp_path, {
        "schema_version": 1,
        "client": "zcode",
        "decisions": [
            absorb_decision(key_a, pend[key_a]["hash"]),                      # scope=project（在册）
            absorb_decision(key_c, pend[key_c]["hash"], scope="global",
                            project_id=None, topic="contract-topic-c"),       # scope=global
            discard_decision(key_b, pend[key_b]["hash"], reason="session noise"),
            discard_decision(key_d, pend[key_d]["hash"], reason="session noise too"),
        ],
    })
    res = apply_run(root, source, decision)
    assert res.returncode == 0, f"E-C7: mixed apply must exit 0; output: {out_of(res)}"
    assert res.stdout.count("absorbed:") == 2 and res.stdout.count("discarded:") == 2, (
        f"E-C7: two absorbs and two discards expected in the report; got: {res.stdout}"
    )
    assert "client side untouched" in res.stdout, f"E-C7: read-only marker expected; got: {res.stdout}"

    # raw 全部通过 hongzhao validate 语义（CLI 全 kit 校验）
    val = validate_run(root)
    assert val.returncode == 0, f"E-C7: validate must pass on absorbed raws; output: {out_of(val)}"
    assert "validation: degraded" not in val.stdout, f"E-C7: health must not degrade; got: {val.stdout}"
    assert "[RAW_" not in val.stdout, f"E-C7: no raw-schema issues expected; got: {val.stdout}"

    # 账本记账正确：absorbed 带 raw、discarded 带 reason；v6 无 source 字段
    entries = ledger_entries(root)
    assert entries[key_a]["state"] == "absorbed" and (Path(root) / entries[key_a]["raw"]).is_file()
    assert entries[key_c]["state"] == "absorbed" and (Path(root) / entries[key_c]["raw"]).is_file()
    assert entries[key_b]["state"] == "discarded" and entries[key_b]["reason"] == "session noise"
    assert entries[key_d]["state"] == "discarded" and entries[key_d]["reason"] == "session noise too"
    for key in (key_a, key_b, key_c, key_d):
        assert "source" not in entries[key], f"E-C7: v6/D-C28 ledger entry must not carry source: {key}"
    assert len(raw_files(root)) == 2, f"E-C7: exactly two raws expected; got {[p.name for p in raw_files(root)]}"
    raw_a = (Path(root) / entries[key_a]["raw"]).read_text(encoding="utf-8")
    assert f"> 来源：ZCode auto-memory {key_a}（" in raw_a, "E-C7: raw must carry the provenance footnote"

    # v6/D-C28 最强断言：整棵客户端目录树（CRLF/混合行尾索引、重复行、悬空行、空池、
    # 普通目录）前后字节快照逐字节相同
    assert snapshot_tree(source) == tree_before, (
        "E-C7: the whole client projects tree must stay byte-identical after absorb+discard"
    )
    memory_a = (source / POOL_A / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert memory_a.count("(fact-a.md)") == 2, (
        "E-C7: duplicate index lines of an absorbed entry must STILL be present (read-only)"
    )
    assert (source / POOL_A / "memory" / "fact-a.md").exists(), "E-C7: absorbed source must stay on disk"
    assert (source / POOL_A / "memory" / "fact-b.md").exists(), "E-C7: discarded source must stay on disk"

    # 轮次收敛：全决策后同源再 collect → pending=0；只读报告（空池/悬空行/unparsable）原样在场
    final = collect_manifest(tmp_path, root, source, tag="ec7b")
    assert final["summary"]["pending"] == 0, f"E-C7: converged collect expected; got {final['summary']}"
    assert_manifest_v6(final, "E-C7")
    assert final["summary"]["unparsable"] == 1 and final["summary"]["empty_pools"] == 1, (
        f"E-C7: read-only reports must keep surfacing; got {final['summary']}"
    )
    assert {d["file"] for d in final["dangling_index"]} == {"gone.md"}, (
        f"E-C7: dangling index lines must still be reported; got {final['dangling_index']}"
    )


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
                # CI windows 维护注记：统一 as_posix 相对键（同引擎 F-16 教训）
                snapshot[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
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
# D-C27：双客户端（claude_code 端到端 + 未知客户端支持清单）
# ---------------------------------------------------------------------------


def test_D_C27_claude_code_end_to_end(tmp_path):
    """D-C27/v6：claude_code 采集端到端——raw source=claude-code、脚注标签 Claude Code、
    账本分目录、客户端零改动。"""
    root = make_kit(tmp_path)
    cc_source = tmp_path / "cc-projects"
    cc_source.mkdir()
    make_pool(cc_source, POOL_CC, {"fact-a.md": FACT_A},
              memory_md="# Memory Index\n- [Fact A](fact-a.md) — hook a\n")
    tree_before = snapshot_tree(cc_source)

    out_file = tmp_path / "cc-manifest.yaml"
    res = run_cli(["--root", root, "collect", "--client", "claude_code",
                   "--source-dir", cc_source, "--out", out_file], root)
    assert res.returncode == 0, f"D-C27: claude_code collect must exit 0; output: {out_of(res)}"
    manifest = yaml.safe_load(out_file.read_text(encoding="utf-8"))
    assert manifest["client"] == "claude_code", f"D-C27: manifest client must be claude_code; got {manifest['client']}"
    assert manifest["summary"]["pending"] == 1, f"D-C27: one pending entry expected; got {manifest['summary']}"
    key = f"{POOL_CC}/memory/fact-a.md"
    assert manifest["pending"][0]["key"] == key, (
        f"D-C27: CC pool slug key expected; got {manifest['pending'][0]['key']}"
    )

    decision = write_decision(tmp_path, {"schema_version": 1, "client": "claude_code",
                                         "decisions": [absorb_decision(key, manifest["pending"][0]["hash"],
                                                                       topic="cc-topic")]})
    res2 = run_cli(["--root", root, "collect", "--apply", decision,
                    "--client", "claude_code", "--source-dir", cc_source], root)
    assert res2.returncode == 0, f"D-C27: claude_code apply must exit 0; output: {out_of(res2)}"

    raws = raw_files(root)
    assert len(raws) == 1, f"D-C27: exactly one raw expected; got {[p.name for p in raws]}"
    text = raws[0].read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---")[1])
    assert meta["source"] == "claude-code", (
        f"D-C27: raw source must be claude-code (client underscore to hyphen); got {meta['source']!r}"
    )
    assert f"> 来源：Claude Code auto-memory {key}（" in text, (
        "D-C27: footnote must carry the Claude Code label"
    )
    ledger = yaml.safe_load(ledger_path(root, "claude_code").read_text(encoding="utf-8"))
    assert ledger["client"] == "claude_code" and ledger["entries"][key]["state"] == "absorbed", (
        f"D-C27: claude_code ledger must record absorbed; got {ledger}"
    )
    assert not (Path(root) / "collect" / "zcode").exists(), (
        "D-C27: ledger directories must be per-client; zcode ledger must not exist here"
    )
    assert snapshot_tree(cc_source) == tree_before, (
        "D-C27: claude_code collection must leave the client tree byte-identical"
    )


def test_D_C27_unknown_client_reports_supported_list(tmp_path):
    """D-C27：--client 传未知值 → [COLLECT_CLIENT_UNKNOWN] exit 2，错误列出受支持客户端清单。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    res = run_cli(["--root", root, "collect", "--client", "codex", "--source-dir", source], root)
    assert res.returncode == 2, (
        f"D-C27: unknown client must fatal with exit 2; got rc={res.returncode}; output: {out_of(res)}"
    )
    assert "[COLLECT_CLIENT_UNKNOWN]" in res.stderr, f"D-C27: error code expected; got: {res.stderr}"
    assert "zcode" in res.stderr and "claude_code" in res.stderr, (
        f"D-C27: supported client list must name both clients; got: {res.stderr}"
    )


# ---------------------------------------------------------------------------
# v6：复 apply 同决策 = DUPLICATE（源永在，不双写）
# ---------------------------------------------------------------------------


def test_v6_reapply_same_decision_is_duplicate(tmp_path):
    """v6/W5：同一 decision 重放 → 第二遍 APPLY_ENTRY_DUPLICATE exit 1；raw 不双写、客户端零改动。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    tree_before = snapshot_tree(source)
    manifest = collect_manifest(tmp_path, root, source, tag="rap")
    pend = pending_map(manifest)
    key_a, key_b = key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-b.md")
    absorb = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                       "decisions": [absorb_decision(key_a, pend[key_a]["hash"])]})
    discard = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                        "decisions": [discard_decision(key_b, pend[key_b]["hash"])]})

    assert apply_run(root, source, absorb).returncode == 0, "v6/W5 premise: first absorb apply exits 0"
    replay = apply_run(root, source, absorb)
    assert replay.returncode == 1, f"v6/W5: absorb replay must exit 1; got {replay.returncode}; output: {out_of(replay)}"
    assert "APPLY_ENTRY_DUPLICATE" in out_of(replay), f"v6/W5: DUPLICATE expected; got: {out_of(replay)}"
    assert len(raw_files(root)) == 1, "v6/W5: replay must not write a second raw"

    assert apply_run(root, source, discard).returncode == 0, "v6/W5 premise: first discard apply exits 0"
    replay2 = apply_run(root, source, discard)
    assert replay2.returncode == 1, f"v6/W5: discard replay must exit 1; got {replay2.returncode}; output: {out_of(replay2)}"
    assert "APPLY_ENTRY_DUPLICATE" in out_of(replay2), f"v6/W5: DUPLICATE expected; got: {out_of(replay2)}"

    entries = ledger_entries(root)
    assert entries[key_a]["state"] == "absorbed" and entries[key_b]["state"] == "discarded", (
        "v6/W5: ledger must hold exactly one record per decided key"
    )
    assert len(raw_files(root)) == 1, "v6/W5: still exactly one raw after all replays"
    assert snapshot_tree(source) == tree_before, "v6/W5: replays must leave the client tree byte-identical"


# ---------------------------------------------------------------------------
# D-C25：--pool 过滤 + 子命令级 --dry-run（v4 起保留不变）
# ---------------------------------------------------------------------------


def test_D_C25_pool_filter_manifest_and_summary(tmp_path):
    """D-C25 --pool 面：manifest 仅含所列池、summary 计数同步（pending/unparsable/
    dangling/empty_pools 随池过滤；旗标可重复；未匹配池=空结果不报错）；
    附 D-C27 锚点：无 memory/ 的普通目录整目录忽略。"""
    root = make_kit(tmp_path)
    source = tmp_path / "projects"
    source.mkdir()
    make_pool(source, POOL_A, {"fact-a.md": FACT_A, "fact-b.md": FACT_B}, memory_md=MEMORY_MD_A)
    make_pool(source, POOL_B, {"fact-b.md": FACT_B}, memory_md="- [Fact B](fact-b.md) — hook b\n")
    make_pool(source, POOL_G, {"broken.md": "plain body without frontmatter\n"},
              memory_md="- [Broken](broken.md) — hook g\n")
    (source / POOL_P / "memory").mkdir(parents=True)  # 空池（带 memory/ 无事实文件）
    (source / "not-a-memory-project").mkdir()  # 无 memory/ 的普通目录：必须被忽略

    def filtered(pools, tag):
        out_file = tmp_path / f"manifest-{tag}-{uuid.uuid4().hex[:6]}.yaml"
        args = ["--root", root, "collect", "--source-dir", source]
        for pool in pools:
            args += ["--pool", pool]
        args += ["--out", out_file]
        res = run_cli(args, root)
        assert res.returncode == 0, f"D-C25: filtered collect must exit 0; output: {out_of(res)}"
        return yaml.safe_load(out_file.read_text(encoding="utf-8"))

    # 基线（无过滤）：全部 4 池可见；普通目录不进任何清单
    full = filtered([], tag="d25full")
    assert full["summary"]["pools"] == 4 and full["summary"]["pending"] == 3, (
        f"D-C25 premise: unfiltered manifest sees all pools; got {full['summary']}"
    )
    assert full["summary"]["unparsable"] == 1 and full["summary"]["empty_pools"] == 1
    assert_manifest_v6(full, "D-C25")
    assert "not-a-memory-project" not in full["empty_pools"] and all(
        k.split("/", 1)[0] != "not-a-memory-project" for k in pending_map(full)), (
        "D-C27: a directory without memory/ must be ignored entirely"
    )

    # 单池：仅 POOL_A 条目与该池悬空行；其他池的 pending/unparsable/空池全部排除
    only_a = filtered([POOL_A], tag="d25a")
    assert only_a["summary"]["pools"] == 1 and only_a["summary"]["files"] == 2, (
        f"D-C25: single-pool summary must sync; got {only_a['summary']}"
    )
    assert only_a["summary"]["pending"] == 2
    assert only_a["summary"]["unparsable"] == 0 and only_a["summary"]["empty_pools"] == 0
    assert sorted(pending_map(only_a)) == sorted([key_of(POOL_A, "fact-a.md"),
                                                  key_of(POOL_A, "fact-b.md")]), (
        f"D-C25: pending must contain exactly pool A entries; got {sorted(pending_map(only_a))}"
    )
    assert {d["pool"] for d in only_a["dangling_index"]} == {POOL_A}, (
        f"D-C25: dangling_index must be filtered to the requested pool; got {only_a['dangling_index']}"
    )

    # 双池（旗标可重复）：两池合并计数
    both = filtered([POOL_A, POOL_B], tag="d25ab")
    assert both["summary"]["pools"] == 2 and both["summary"]["pending"] == 3, (
        f"D-C25: repeatable --pool must union the pools; got {both['summary']}"
    )
    assert all(k.split("/", 1)[0] in {POOL_A, POOL_B} for k in pending_map(both)), (
        "D-C25: no entry from outside the requested pools may appear"
    )

    # 未匹配任何池：空结果正常退出（不 fatal）
    none_matched = filtered(["no-such-pool"], tag="d25none")
    assert none_matched["summary"]["pools"] == 0 and none_matched["summary"]["pending"] == 0, (
        f"D-C25: unknown pool must yield an empty (not failing) manifest; got {none_matched['summary']}"
    )


def test_D_C25_subcommand_dry_run_equivalent_to_global(tmp_path):
    """D-C25 子命令级 --dry-run：旗标在子命令后与全局位置行为等价（零写入、计划输出一致）；
    附 collect --dry-run 面：只读提示 + 照常输出清单。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    tree_before = snapshot_tree(source)
    manifest = collect_manifest(tmp_path, root, source, tag="d25d")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})

    # 写法 A：--dry-run 放在子命令之后
    sub_flag = run_cli(["--root", root, "collect", "--apply", decision,
                        "--source-dir", source, "--dry-run"], root)
    assert sub_flag.returncode == 0, (
        f"D-C25: subcommand-level --dry-run must exit 0; got rc={sub_flag.returncode}; output: {out_of(sub_flag)}"
    )
    assert raw_files(root) == [] and not (Path(root) / "collect").exists(), (
        "D-C25: subcommand-level --dry-run must write nothing (no raw, no ledger)"
    )
    # 写法 B：--dry-run 在全局位置（子命令之前）
    global_flag = run_cli(["--root", root, "--dry-run", "collect", "--apply", decision,
                           "--source-dir", source], root)
    assert global_flag.returncode == 0, (
        f"D-C25: global --dry-run must exit 0; got rc={global_flag.returncode}; output: {out_of(global_flag)}"
    )
    # 等价性：同一决策、同一状态 → 计划输出逐字节一致
    assert sub_flag.stdout == global_flag.stdout, (
        f"D-C25: subcommand and global --dry-run must print identical plans; "
        f"sub={sub_flag.stdout!r}; global={global_flag.stdout!r}"
    )
    for marker in ("would absorb", "client side untouched", "dry-run: no writes performed"):
        assert marker in sub_flag.stdout, f"D-C25: plan marker {marker!r} expected; got: {sub_flag.stdout}"
    # 双跑之后仍零写入、客户端目录树不动
    assert raw_files(root) == [], "D-C25: both dry runs together must write no raw"
    assert not (Path(root) / "collect").exists(), "D-C25: both dry runs must not create the ledger"
    assert snapshot_tree(source) == tree_before, "D-C25: dry runs must leave the client tree byte-identical"

    # collect --dry-run：collect 本身只读，提示等效并照常输出清单（design 5.1）
    dry = run_cli(["--root", root, "collect", "--source-dir", source, "--dry-run"], root)
    assert dry.returncode == 0, f"D-C25: collect --dry-run must exit 0; output: {out_of(dry)}"
    assert "collect is read-only" in dry.stderr, f"D-C25: read-only note expected; got: {dry.stderr}"
    parsed = yaml.safe_load(dry.stdout)
    assert parsed["summary"]["pending"] == 2, f"D-C25: manifest must still be printed; got {parsed['summary']}"


# ---------------------------------------------------------------------------
# D-C24：mentioned_in 字面提示（判重线索，不代决策）
# ---------------------------------------------------------------------------


def test_D_C24_mentioned_in_literal_match_and_empty(tmp_path):
    """D-C24 基础面：pending 条目带 mentioned_in（raw 正文字面命中的文件名清单）；
    未命中为 []；`_` 前缀 raw 不参与提示。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    hit_raw = root / "raw" / "2026-11-01_seed-topic-aabb0011.md"
    write_file(hit_raw, "Merged-source note: covers fact-a tooling preferences.\n")
    draft_raw = root / "raw" / "_draft-fact-a.md"  # _ 前缀 raw：提示必须跳过
    write_file(draft_raw, "draft also mentions fact-a but must be skipped\n")
    manifest = collect_manifest(tmp_path, root, source, tag="d24a")
    pend = pending_map(manifest)
    key_a, key_b = key_of(POOL_A, "fact-a.md"), key_of(POOL_A, "fact-b.md")
    assert pend[key_a]["mentioned_in"] == [hit_raw.name], (
        f"D-C24: literal body hit must list exactly the matching raw file name; "
        f"got {pend[key_a]['mentioned_in']}"
    )
    assert pend[key_b]["mentioned_in"] == [], (
        f"D-C24: unmatched entry must carry an empty list; got {pend[key_b]['mentioned_in']}"
    )


def test_D_C24_reflow_candidate_points_at_absorbed_raw(tmp_path):
    """D-C24 判重线索语义：吸收后内容变化回流的新候选 → mentioned_in 点名该 raw
    （命中来源=引擎生成的来源脚注中的原始 key；v6 源永在，回流是常态路径）。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = collect_manifest(tmp_path, root, source, tag="d24b")
    key_a = key_of(POOL_A, "fact-a.md")
    decision = write_decision(tmp_path, {"schema_version": 1, "client": "zcode",
                                         "decisions": [absorb_decision(key_a, pending_map(manifest)[key_a]["hash"])]})
    assert apply_run(root, source, decision).returncode == 0
    absorbed_raw = ledger_entries(root)[key_a]["raw"].split("/")[-1]
    raw_text = (Path(root) / "raw" / absorbed_raw).read_text(encoding="utf-8")
    # 前提：决策改写正文不含 fact-a，raw 中该 name 的唯一出现处=脚注里的原始 key
    assert key_a in raw_text and raw_text.count("fact-a") == 1, (
        "D-C24 premise: the only fact-a occurrence in the raw must be inside the footnote key"
    )
    # v6：源永在 → 直接改同池文件内容即形成回流候选（新 hash）
    write_file(source / POOL_A / "memory" / "fact-a.md", FACT_A2)
    reflow = collect_manifest(tmp_path, root, source, tag="d24c")
    pend = pending_map(reflow)
    assert key_a in pend, "D-C24 premise: changed content must reflow as pending"
    assert absorbed_raw in pend[key_a]["mentioned_in"], (
        f"D-C24: reflowed candidate must be pointed at the absorbed raw "
        f"(footnote key hit, dedup-clue semantics); got {pend[key_a]['mentioned_in']}"
    )


# ---------------------------------------------------------------------------
# CLI UTF-8 回归（重定向管道 locale 编码下打印中文清单不得崩）
# ---------------------------------------------------------------------------


def test_cli_utf8_stdout_under_locale_pipe(tmp_path):
    """UTF-8 回归：PYTHONIOENCODING=cp1252 的重定向管道下，中文清单照常输出（CLI 强制 UTF-8）。"""
    root = make_kit(tmp_path)
    source = tmp_path / "projects"
    source.mkdir()
    make_pool(source, POOL_G, {"f.md": FACT_A},
              memory_md="- [中文标题](f.md) — 中文钩子\n")
    res = run_cli(["--root", root, "collect", "--source-dir", source], root,
                  env_extra={"PYTHONIOENCODING": "cp1252"})
    assert res.returncode == 0, (
        f"UTF-8: must not crash under a locale-encoded pipe; got rc={res.returncode}; stderr: {res.stderr[-300:]}"
    )
    assert "中文标题" in res.stdout, "UTF-8: Chinese titles must survive the pipe intact"


# ---------------------------------------------------------------------------
# D-C18：apply 成功后的 auto-commit（git.auto_commit 缺省开启）
# ---------------------------------------------------------------------------


def _git(root: Path, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)


def test_D_C18_apply_auto_commits_kit(tmp_path):
    """D-C18（v6）：真实 git kit apply 含 absorb+discard → 提交信息
    `hongzhao collect apply … absorbed=N discarded=M`（无 cleaned），账本与 raw 入库。"""
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
    assert "absorbed=1 discarded=1" in subject, (
        f"D-C18: subject must carry absorbed/discarded counts; got: {subject!r}"
    )
    assert "cleaned" not in subject, (
        f"D-C18: v6 subject must not carry a cleaned count (write paths removed); got: {subject!r}"
    )
    tracked = set(_git(root, "ls-files").stdout.split())
    ledger_record = ledger_entries(root)[key_a]
    assert "collect/zcode/ledger.yaml" in tracked, f"D-C18: ledger must be committed; tracked={sorted(tracked)}"
    assert ledger_record["raw"] in tracked, f"D-C18: raw must be committed; expected {ledger_record['raw']}"
    status = _git(root, "status", "--porcelain")
    assert status.returncode == 0 and status.stdout.strip() == "", (
        f"D-C18: working tree must be clean after auto-commit; got: {status.stdout!r}"
    )
