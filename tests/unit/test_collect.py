"""collect 单元测试（实现者侧；S 矩阵合同面由独立作者在 tests/contracts 覆盖）。

覆盖 design 8 章 E-C1（解析）/E-C2（增量完整轮次）/E-C3（回流）/E-C4（映射校验）/
E-C9（冷启动与账本损坏）/E-C10（CLI 面）及 W5、S3、脚注、账本 schema、空池、索引行级改写。
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
import yaml

from hongzhao import cli
from hongzhao.collect import CollectError, build_manifest, cmd_apply, cmd_collect, scan_source

PROJECT_ID = f"proj-{uuid.uuid4()}"


def make_kit(tmp_path: Path) -> Path:
    root = tmp_path / "kit"
    (root / "raw").mkdir(parents=True)
    (root / "registry").mkdir()
    (root / "compiled").mkdir()
    (root / "render").mkdir()
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
        "skills": ["memory-write", "memory-collect"],
        "clients": {
            "zcode": {
                "enabled": True,
                "bridge_path": "~/nonexistent-zcode-AGENTS.md",
                "skills_root": str(tmp_path / "skills"),
                "mode": "inline",
            }
        },
        "git": {"auto_commit": False},
    }
    (root / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    registry = {
        "schema_version": 2,
        "projects": [
            {"project_id": PROJECT_ID, "location": {"kind": "external", "path": str(tmp_path)},
             "registered_at": "2026-11-13", "last_checked_at": None}
        ],
    }
    (root / "registry" / "project-registry.yaml").write_text(
        yaml.safe_dump(registry, allow_unicode=True), encoding="utf-8")
    return root


def write_file(path: Path, text: str) -> None:
    # Path.write_text(newline=) 是 3.10+ API；显式 open 保 3.9 兼容与行尾控制
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def make_pool(source: Path, pool: str, facts: dict[str, str], memory_md: str | None = None) -> None:
    memory = source / pool / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    for name, text in facts.items():
        write_file(memory / name, text)
    if memory_md is not None:
        write_file(memory / "MEMORY.md", memory_md)


FACT_A = """---
name: fact-a
description: 事实 A 的描述
metadata:
  node_type: memory
  type: project
---

事实 A 正文。
"""

FACT_B = """---
name: fact-b
description: 事实 B 的描述
metadata:
  type: feedback
---

事实 B 正文。
"""


def make_source(tmp_path: Path) -> Path:
    source = tmp_path / "projects"
    source.mkdir()
    make_pool(
        source, "pool-a1b2c3d4e5f60718",
        {"fact-a.md": FACT_A, "fact-b.md": FACT_B},
        memory_md="- [事实A](fact-a.md) — 钩子A\n- [悬空](gone.md) — 不存在的文件\n",
    )
    (source / "empty-pool-0000000000000fff").mkdir()
    return source


def manifest_of(root: Path, source: Path) -> dict:
    return build_manifest(root, "zcode", source)


def absorb_decision(entry: dict, **override) -> dict:
    decision = {
        "key": entry["key"], "hash": entry["hash"], "action": "absorb",
        "scope": "project", "project_id": PROJECT_ID, "topic": "test-topic",
        "kind": "memory", "activation": "on-demand", "summary": "测试摘要",
        "body": "测试正文事实。",
        "evidence": {"why": "长期事实", "similar": {"ref": "none", "diff": "无相近条目"}},
    }
    decision.update(override)
    return decision


def decision_file(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / f"decision-{uuid.uuid4().hex[:6]}.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# E-C1 解析
# ---------------------------------------------------------------------------


def test_scan_parses_and_flags(tmp_path):
    root = make_kit(tmp_path)
    source = make_source(tmp_path)
    # 无 frontmatter 文件 → unparsable；缺 name/description → unparsable
    make_pool(source, "bad-pool-1111111111111aaa", {
        "no-frontmatter.md": "就是一段正文",
        "missing-fields.md": "---\nkind: memory\n---\n\n正文\n",
    })
    scan = scan_source(source)
    entries = scan["entries"]
    assert set(entries) == {
        "pool-a1b2c3d4e5f60718/memory/fact-a.md",
        "pool-a1b2c3d4e5f60718/memory/fact-b.md",
    }
    a = entries["pool-a1b2c3d4e5f60718/memory/fact-a.md"]
    assert a["title"] == "事实A" and a["hook"] == "钩子A" and a["type"] == "project"
    assert a["index_missing"] is False
    b = entries["pool-a1b2c3d4e5f60718/memory/fact-b.md"]
    assert b["index_missing"] is True and b["title"].startswith("事实 B")
    assert {u["key"].split("/")[-1] for u in scan["unparsable"]} == {"no-frontmatter.md", "missing-fields.md"}
    assert scan["dangling_index"] == [{"pool": "pool-a1b2c3d4e5f60718",
                                        "file": "gone.md", "line": "- [悬空](gone.md) — 不存在的文件"}]
    assert scan["empty_pools"] == ["empty-pool-0000000000000fff"]


def test_scan_crlf_and_headerless_index(tmp_path):
    source = tmp_path / "projects"
    source.mkdir()
    memory_md = "# Memory Index\r\n- [T](f.md) — H\r\n"
    make_pool(source, "crlf-pool-2222222222222bbb", {"f.md": FACT_A}, memory_md=memory_md)
    scan = scan_source(source)
    entry = scan["entries"]["crlf-pool-2222222222222bbb/memory/f.md"]
    assert entry["title"] == "T" and entry["hook"] == "H"


# ---------------------------------------------------------------------------
# E-C2/E-C3 增量
# ---------------------------------------------------------------------------


def test_increment_full_round(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    assert manifest["summary"]["pending"] == 2

    entries = {e["key"]: e for e in manifest["pending"]}
    decision = decision_file(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": [
        absorb_decision(entries["pool-a1b2c3d4e5f60718/memory/fact-a.md"]),
        {"key": "pool-a1b2c3d4e5f60718/memory/fact-b.md",
         "hash": entries["pool-a1b2c3d4e5f60718/memory/fact-b.md"]["hash"],
         "action": "discard", "reason": "过程记录"},
    ]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 0
    capsys.readouterr()

    second = manifest_of(root, source)
    assert second["summary"]["pending"] == 0
    assert second["summary"]["residue"] == 0  # absorb 后删源已完成
    # S3：discard 不删源
    assert (source / "pool-a1b2c3d4e5f60718/memory/fact-b.md").exists()
    assert not (source / "pool-a1b2c3d4e5f60718/memory/fact-a.md").exists()

    # 幂等：同源再 collect 输出剥离 generated_at 后一致
    third = manifest_of(root, source)
    second.pop("generated_at"), third.pop("generated_at")
    assert second == third


def test_content_change_reflows(tmp_path):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entry = next(e for e in manifest["pending"] if e["key"].endswith("fact-a.md"))
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": [absorb_decision(entry)]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 0
    assert manifest_of(root, source)["summary"]["pending"] == 1  # 仅剩未决的 fact-b

    # 内容变化 → 回流（S10）：fact-a 以新 hash 重新 pending
    write_file(source / "pool-a1b2c3d4e5f60718/memory/fact-a.md", FACT_A + "\n新增一行改变了 hash。\n")
    assert manifest_of(root, source)["summary"]["pending"] == 2


def test_residue_and_cleanup(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entries = {e["key"]: e for e in manifest["pending"]}
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": [
        absorb_decision(entries["pool-a1b2c3d4e5f60718/memory/fact-a.md"]),
        {"key": "pool-a1b2c3d4e5f60718/memory/fact-b.md",
         "hash": entries["pool-a1b2c3d4e5f60718/memory/fact-b.md"]["hash"],
         "action": "discard", "reason": "先收着"},
    ]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 0
    capsys.readouterr()

    # 模拟 W2 残留：删源未发生（重新放回同内容文件）
    write_file(source / "pool-a1b2c3d4e5f60718/memory/fact-a.md", FACT_A)
    manifest = manifest_of(root, source)
    assert manifest["summary"]["residue"] == 1 and manifest["summary"]["pending"] == 0
    residue = manifest["residue"][0]

    # cleanup 决策后源被并发修改（E-C6 删源窗口用例）→ DELETE_MISMATCH，文件保留
    write_file(source / "pool-a1b2c3d4e5f60718/memory/fact-a.md", FACT_A + "\n并发改动。\n")
    wrong = decision_file(tmp_path, {"schema_version": 1, "decisions": [], "cleanup": [
        {"key": residue["key"], "hash": residue["hash"]}]})
    assert cmd_apply(root, str(wrong), client="zcode", source_dir=str(source)) == 1
    assert "APPLY_DELETE_MISMATCH" in capsys.readouterr().out
    assert (source / "pool-a1b2c3d4e5f60718/memory/fact-a.md").exists()
    # 改动后的内容以新 hash 回流重审（S10）
    assert manifest_of(root, source)["summary"]["pending"] == 1

    # cleanup hash 相符 → 删除 + 索引行清除（先还原原内容，文件 hash 回到 residue hash）
    write_file(source / "pool-a1b2c3d4e5f60718/memory/fact-a.md", FACT_A)
    right = decision_file(tmp_path, {"schema_version": 1, "decisions": [], "cleanup": [
        {"key": residue["key"], "hash": residue["hash"]}]})
    assert cmd_apply(root, str(right), client="zcode", source_dir=str(source)) == 0
    assert not (source / "pool-a1b2c3d4e5f60718/memory/fact-a.md").exists()
    index_text = (source / "pool-a1b2c3d4e5f60718/memory/MEMORY.md").read_text(encoding="utf-8")
    assert "fact-a.md" not in index_text and "悬空" in index_text


# ---------------------------------------------------------------------------
# E-C4 映射校验 / 字段校验 / W5
# ---------------------------------------------------------------------------


def test_unknown_project_fails_entry_only(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entries = {e["key"]: e for e in manifest["pending"]}
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": [
        absorb_decision(entries["pool-a1b2c3d4e5f60718/memory/fact-a.md"], project_id="proj-00000000-0000-0000-0000-000000000000"),
        {"key": "pool-a1b2c3d4e5f60718/memory/fact-b.md",
         "hash": entries["pool-a1b2c3d4e5f60718/memory/fact-b.md"]["hash"],
         "action": "discard", "reason": "ok"},
    ]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 1
    out = capsys.readouterr().out
    assert "APPLY_PROJECT_UNKNOWN" in out and "discarded" in out
    assert list((root / "raw").glob("*.md")) == []  # 失败条目零部分文件


@pytest.mark.parametrize("override,code", [
    ({"summary": "长" * 301}, "APPLY_RAW_INVALID"),
    ({"topic": "Bad_Topic"}, "APPLY_RAW_INVALID"),
    ({"evidence": {"why": "", "similar": {"ref": "none", "diff": "x"}}}, "APPLY_RAW_INVALID"),
    ({"evidence": None}, "APPLY_RAW_INVALID"),
    ({"body": "  "}, "APPLY_RAW_INVALID"),
    ({"kind": "note"}, "APPLY_RAW_INVALID"),
    ({"scope": "project", "project_id": None}, "APPLY_PROJECT_UNKNOWN"),
])
def test_absorb_field_validation(tmp_path, capsys, override, code):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entry = manifest["pending"][0]
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": [absorb_decision(entry, **override)]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 1
    assert code in capsys.readouterr().out
    assert list((root / "raw").glob("*.md")) == []


def test_reapply_semantics(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entries = {e["key"]: e for e in manifest["pending"]}
    absorb = decision_file(tmp_path, {"schema_version": 1, "decisions": [
        absorb_decision(entries["pool-a1b2c3d4e5f60718/memory/fact-a.md"])]})
    assert cmd_apply(root, str(absorb), client="zcode", source_dir=str(source)) == 0
    capsys.readouterr()
    # absorb 已删源 → 复 apply 同决策：条目 absent → STALE（S16），不双写
    assert cmd_apply(root, str(absorb), client="zcode", source_dir=str(source)) == 1
    assert "APPLY_ENTRY_STALE" in capsys.readouterr().out
    assert len(list((root / "raw").glob("*.md"))) == 1

    # discard 保留源 → 复 apply 同决策：同 (key,hash) 已决 → DUPLICATE（W5）
    discard = decision_file(tmp_path, {"schema_version": 1, "decisions": [
        {"key": "pool-a1b2c3d4e5f60718/memory/fact-b.md",
         "hash": entries["pool-a1b2c3d4e5f60718/memory/fact-b.md"]["hash"],
         "action": "discard", "reason": "r"}]})
    assert cmd_apply(root, str(discard), client="zcode", source_dir=str(source)) == 0
    capsys.readouterr()
    assert cmd_apply(root, str(discard), client="zcode", source_dir=str(source)) == 1
    assert "APPLY_ENTRY_DUPLICATE" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# raw/账本产物
# ---------------------------------------------------------------------------


def test_raw_and_ledger_artifacts(tmp_path):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entry = next(e for e in manifest["pending"] if e["key"].endswith("fact-a.md"))
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": [absorb_decision(entry)]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 0

    raw_files = list((root / "raw").glob("*.md"))
    assert len(raw_files) == 1
    text = raw_files[0].read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---")[1])
    assert meta["source"] == "zcode" and meta["compile_status"] == "new" and meta["record_type"] == "source"
    assert meta["project_id"] == PROJECT_ID and meta["id"].startswith("mem-")
    assert raw_files[0].name.split("_")[2][:8] == meta["id"].removeprefix("mem-").replace("-", "")[:8]
    assert "> 来源：ZCode auto-memory pool-a1b2c3d4e5f60718/memory/fact-a.md（" in text
    assert "> 采集依据：值得留——长期事实；最相似——none，差异：无相近条目" in text

    ledger = yaml.safe_load((root / "collect/zcode/ledger.yaml").read_text(encoding="utf-8"))
    assert ledger["schema_version"] == 1 and ledger["client"] == "zcode"
    record = ledger["entries"]["pool-a1b2c3d4e5f60718/memory/fact-a.md"]
    assert record["state"] == "absorbed" and record["hash"].startswith("sha256:") \
        and record["raw"].startswith("raw/") and record["decided_at"]


def test_memory_md_surgical_delete_and_crlf(tmp_path):
    root = make_kit(tmp_path)
    source = tmp_path / "projects"
    source.mkdir()
    memory_md = "# Memory Index\r\n- [A](a.md) — one\r\n- [B](b.md) — keep\r\n- [A](a.md) — dup\r\n"
    make_pool(source, "surgical-3333333333333ccc", {"a.md": FACT_A, "b.md": FACT_B}, memory_md=memory_md)
    manifest = manifest_of(root, source)
    entry = next(e for e in manifest["pending"] if e["key"].endswith("a.md"))
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": [absorb_decision(entry)]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 0
    raw_bytes = (source / "surgical-3333333333333ccc/memory/MEMORY.md").read_bytes()
    text = raw_bytes.decode("utf-8")
    assert "a.md" not in text and "b.md" in text  # 删除全部精确匹配行（含重复行）
    assert raw_bytes.count(b"\r\n") >= 2 and b"\r\n" in raw_bytes  # 其余行行尾保留
    assert "# Memory Index" in text


def test_prune_empty_pool(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": [], "prune_empty_pools": [
        "empty-pool-0000000000000fff", "pool-a1b2c3d4e5f60718"]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 1
    out = capsys.readouterr().out
    assert "pruned empty pool: empty-pool-0000000000000fff" in out
    assert "pool is not empty; skipped" in out
    assert not (source / "empty-pool-0000000000000fff").exists()
    assert (source / "pool-a1b2c3d4e5f60718").exists()


def test_keep_source_mode(tmp_path, capsys):
    """v3/D-C22：delete_source=false 收编不删源、不动 MEMORY.md、账本记 kept、kept 不进 residue。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entries = {e["key"]: e for e in manifest["pending"]}
    memory_md_before = (source / "pool-a1b2c3d4e5f60718/memory/MEMORY.md").read_bytes()
    decision = decision_file(tmp_path, {
        "schema_version": 1, "delete_source": False, "decisions": [
            absorb_decision(entries["pool-a1b2c3d4e5f60718/memory/fact-a.md"]),
            {"key": "pool-a1b2c3d4e5f60718/memory/fact-b.md",
             "hash": entries["pool-a1b2c3d4e5f60718/memory/fact-b.md"]["hash"],
             "action": "discard", "reason": "过程记录"}]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 0
    out = capsys.readouterr().out
    assert "absorbed (source kept)" in out and "deleted source" not in out
    # 客户端原始记录全部保留（absorb 保留 + discard 本就不删），MEMORY.md 字节不动
    assert (source / "pool-a1b2c3d4e5f60718/memory/fact-a.md").exists()
    assert (source / "pool-a1b2c3d4e5f60718/memory/fact-b.md").exists()
    assert (source / "pool-a1b2c3d4e5f60718/memory/MEMORY.md").read_bytes() == memory_md_before
    # 账本记 source=kept
    ledger = yaml.safe_load((root / "collect/zcode/ledger.yaml").read_text(encoding="utf-8"))
    assert ledger["entries"]["pool-a1b2c3d4e5f60718/memory/fact-a.md"]["source"] == "kept"
    # kept 同 hash 在场不冒回也不进 residue（正常终态）
    m = manifest_of(root, source)
    assert m["summary"]["pending"] == 0 and m["summary"]["residue"] == 0
    # 内容变化仍回流重审（S10 不受 keep 影响）
    write_file(source / "pool-a1b2c3d4e5f60718/memory/fact-a.md", FACT_A + "\n改动。\n")
    assert manifest_of(root, source)["summary"]["pending"] == 1


def test_ledger_source_enum_validation(tmp_path):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    (root / "collect/zcode").mkdir(parents=True)
    (root / "collect/zcode/ledger.yaml").write_text(
        "schema_version: 1\nentries:\n  k: {hash: 'sha256:x', state: absorbed, raw: r.md, decided_at: '2026-11-13', source: vanished}\n",
        encoding="utf-8")
    with pytest.raises(CollectError) as excinfo:
        cmd_collect(root, client="zcode", source_dir=str(source))
    assert excinfo.value.code == "COLLECT_LEDGER_INVALID"


def test_slim_index_mode(tmp_path, capsys):
    """v4/D-C23：slim_index=true 只删 MEMORY.md 索引行，文件与内容一字不动。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entries = {e["key"]: e for e in manifest["pending"]}
    memory_md_before = (source / "pool-a1b2c3d4e5f60718/memory/MEMORY.md").read_bytes()
    decision = decision_file(tmp_path, {
        "schema_version": 1, "delete_source": False, "slim_index": True, "decisions": [
            absorb_decision(entries["pool-a1b2c3d4e5f60718/memory/fact-a.md"]),
            {"key": "pool-a1b2c3d4e5f60718/memory/fact-b.md",
             "hash": entries["pool-a1b2c3d4e5f60718/memory/fact-b.md"]["hash"],
             "action": "discard", "reason": "过程记录"}]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 0
    out = capsys.readouterr().out
    assert "index slimmed" in out
    # 事实文件与内容保留；索引行全部移除（含 fact-a 行与悬空行保留差异）
    assert (source / "pool-a1b2c3d4e5f60718/memory/fact-a.md").exists()
    assert (source / "pool-a1b2c3d4e5f60718/memory/fact-b.md").exists()
    index_text = (source / "pool-a1b2c3d4e5f60718/memory/MEMORY.md").read_text(encoding="utf-8")
    assert "fact-a.md" not in index_text and "fact-b" not in index_text
    assert "悬空" in index_text  # 未决条目的索引行不动
    assert memory_md_before != (source / "pool-a1b2c3d4e5f60718/memory/MEMORY.md").read_bytes()
    # 幂等：同决策复跑（DUPLICATE 条目级）不影响索引；重跑 slim no-match 不报错


def test_pool_filter_and_mentions(tmp_path, capsys):
    """v4/D-C24/D-C25：--pool 过滤 + mentioned_in 字面提示。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entry = manifest["pending"][0]
    absorb = decision_file(tmp_path, {"schema_version": 1, "delete_source": False,
                                      "decisions": [absorb_decision(entry)]})
    assert cmd_apply(root, str(absorb), client="zcode", source_dir=str(source)) == 0
    # 新池加一条同名 name 的候选 → mentioned_in 应点名刚才的 raw
    make_pool(source, "other-4444444444444ddd", {"fact-a.md": FACT_A + "\n改。\n"},
              memory_md="- [T](fact-a.md) — H\n")
    from hongzhao.collect import build_manifest
    m = build_manifest(root, "zcode", source, pools=["other-4444444444444ddd"])
    assert m["summary"]["pools"] == 1 and m["summary"]["pending"] == 1
    pending = m["pending"][0]
    assert pending["name"] == "fact-a"
    ledger = yaml.safe_load((root / "collect/zcode/ledger.yaml").read_text(encoding="utf-8"))
    absorbed_raw = ledger["entries"][entry["key"]]["raw"].split("/")[-1]  # 正文脚注含 name → 应被点名
    assert absorbed_raw in pending["mentioned_in"]
    # 过滤后其他池不出现
    assert all(e["key"].startswith("other-4444") for e in m["pending"])


def test_subcommand_dry_run_flag(tmp_path, capsys):
    """v4/D-C25：子命令级 --dry-run（放子命令后）与全局位置等价。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entry = manifest["pending"][0]
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": [absorb_decision(entry)]})
    assert cli.main(["--root", str(root), "collect", "--apply", str(decision),
                     "--source-dir", str(source), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would absorb" in out and "no writes performed" in out
    assert list((root / "raw").glob("*.md")) == []


def test_empty_decision_is_ok(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": []})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 0
    assert "nothing to do" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# E-C9/E-C10 CLI 面
# ---------------------------------------------------------------------------


def test_cli_collect_stdout_yaml_and_out(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    assert cli.main(["--root", str(root), "collect", "--source-dir", str(source)]) == 0
    manifest = yaml.safe_load(capsys.readouterr().out)
    assert manifest["summary"]["pending"] == 2

    out_file = tmp_path / "manifest.yaml"
    assert cli.main(["--root", str(root), "collect", "--source-dir", str(source),
                     "--out", str(out_file)]) == 0
    capsys.readouterr()
    assert yaml.safe_load(out_file.read_text(encoding="utf-8"))["summary"]["pending"] == 2


def test_cli_error_surface(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    assert cli.main(["--root", str(root), "collect", "--source-dir", str(tmp_path / "nope")]) == 2
    assert "COLLECT_SOURCE_MISSING" in capsys.readouterr().err
    assert cli.main(["--root", str(root), "collect", "--client", "codex"]) == 2
    assert "COLLECT_CLIENT_UNKNOWN" in capsys.readouterr().err

    bad = tmp_path / "bad.yaml"
    bad.write_text("schema_version: 9\n", encoding="utf-8")
    assert cli.main(["--root", str(root), "collect", "--apply", str(bad), "--source-dir", str(source)]) == 2
    assert "APPLY_DECISION_INVALID" in capsys.readouterr().err


def test_cli_apply_dry_run_zero_writes(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entry = manifest["pending"][0]
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": [absorb_decision(entry)]})
    assert cli.main(["--root", str(root), "--dry-run", "collect", "--apply", str(decision),
                     "--source-dir", str(source)]) == 0
    out = capsys.readouterr().out
    assert "would absorb" in out and "no writes performed" in out
    assert list((root / "raw").glob("*.md")) == []
    assert not (root / "collect").exists()
    assert (source / "pool-a1b2c3d4e5f60718/memory/fact-a.md").exists()


def test_corrupt_ledger_fatal(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    (root / "collect/zcode").mkdir(parents=True)
    (root / "collect/zcode/ledger.yaml").write_text("not: [valid\n", encoding="utf-8")
    with pytest.raises(CollectError) as excinfo:
        cmd_collect(root, client="zcode", source_dir=str(source))
    assert excinfo.value.code == "COLLECT_LEDGER_INVALID" and excinfo.value.exit_code == 2
    assert cli.main(["--root", str(root), "collect", "--source-dir", str(source)]) == 2
    assert "COLLECT_LEDGER_INVALID" in capsys.readouterr().err
