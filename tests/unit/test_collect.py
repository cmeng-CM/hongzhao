"""collect 单元测试（实现者侧；S 矩阵合同面由独立作者在 tests/contracts 覆盖）。

v6/D-C28 语义基线：严格只读采集——apply 只写 hongzhao（raw/账本/auto-commit），
客户端事实文件与 MEMORY.md 在任何决策组合下都一字不动；无 residue/cleanup/prune 概念。
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

from hongzhao import cli
from hongzhao.collect import CLIENT_SOURCE_DEFAULTS, CollectError, build_manifest, cmd_apply, cmd_collect, scan_source

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
    (source / "empty-pool-0000000000000fff" / "memory").mkdir(parents=True)  # 空壳池（带 memory/ 无文件）
    (source / "not-a-pool-just-a-dir").mkdir()  # v5：无 memory/ 的目录不是池
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


POOL = "pool-a1b2c3d4e5f60718"


# ---------------------------------------------------------------------------
# E-C1 解析
# ---------------------------------------------------------------------------


def test_scan_parses_and_flags(tmp_path):
    root = make_kit(tmp_path)
    source = make_source(tmp_path)
    make_pool(source, "bad-pool-1111111111111aaa", {
        "no-frontmatter.md": "就是一段正文",
        "missing-fields.md": "---\nkind: memory\n---\n\n正文\n",
    })
    scan = scan_source(source)
    entries = scan["entries"]
    assert set(entries) == {f"{POOL}/memory/fact-a.md", f"{POOL}/memory/fact-b.md"}
    a = entries[f"{POOL}/memory/fact-a.md"]
    assert a["title"] == "事实A" and a["hook"] == "钩子A" and a["type"] == "project"
    assert a["index_missing"] is False
    b = entries[f"{POOL}/memory/fact-b.md"]
    assert b["index_missing"] is True and b["title"].startswith("事实 B")
    assert {u["key"].split("/")[-1] for u in scan["unparsable"]} == {"no-frontmatter.md", "missing-fields.md"}
    assert scan["dangling_index"] == [{"pool": POOL, "file": "gone.md",
                                        "line": "- [悬空](gone.md) — 不存在的文件"}]
    assert scan["empty_pools"] == ["empty-pool-0000000000000fff"]
    assert "not-a-pool-just-a-dir" not in scan["pool_files"]


def test_scan_crlf_and_headerless_index(tmp_path):
    source = tmp_path / "projects"
    source.mkdir()
    memory_md = "# Memory Index\r\n- [T](f.md) — H\r\n"
    make_pool(source, "crlf-pool-2222222222222bbb", {"f.md": FACT_A}, memory_md=memory_md)
    scan = scan_source(source)
    entry = scan["entries"]["crlf-pool-2222222222222bbb/memory/f.md"]
    assert entry["title"] == "T" and entry["hook"] == "H"


# ---------------------------------------------------------------------------
# E-C2/E-C3 增量（v6：全程只读，无 residue 字段）
# ---------------------------------------------------------------------------


def test_increment_full_round_readonly(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    memory_md_before = (source / POOL / "memory/MEMORY.md").read_bytes()

    manifest = manifest_of(root, source)
    assert manifest["summary"] == {"pools": 2, "files": 2, "pending": 2, "unparsable": 0,
                                   "empty_pools": 1}
    entries = {e["key"]: e for e in manifest["pending"]}
    decision = decision_file(tmp_path, {"schema_version": 1, "client": "zcode", "decisions": [
        absorb_decision(entries[f"{POOL}/memory/fact-a.md"]),
        {"key": f"{POOL}/memory/fact-b.md",
         "hash": entries[f"{POOL}/memory/fact-b.md"]["hash"],
         "action": "discard", "reason": "过程记录"},
    ]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 0
    capsys.readouterr()

    second = manifest_of(root, source)
    assert second["summary"]["pending"] == 0 and "residue" not in second["summary"]
    # v6/D-C28 核心断言：收编+弃用之后，客户端一个字节都不变
    assert (source / POOL / "memory/fact-a.md").exists()
    assert (source / POOL / "memory/fact-b.md").exists()
    assert (source / POOL / "memory/MEMORY.md").read_bytes() == memory_md_before

    third = manifest_of(root, source)
    second.pop("generated_at"), third.pop("generated_at")
    assert second == third  # 幂等：剥离 generated_at 后逐字节一致


def test_content_change_reflows(tmp_path):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entry = next(e for e in manifest["pending"] if e["key"].endswith("fact-a.md"))
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": [absorb_decision(entry)]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 0
    assert manifest_of(root, source)["summary"]["pending"] == 1  # 仅剩未决的 fact-b

    write_file(source / POOL / "memory/fact-a.md", FACT_A + "\n新增一行改变了 hash。\n")
    assert manifest_of(root, source)["summary"]["pending"] == 2  # 回流（源永在，内容变化即重审）


def test_reapply_semantics(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entries = {e["key"]: e for e in manifest["pending"]}
    absorb = decision_file(tmp_path, {"schema_version": 1, "decisions": [
        absorb_decision(entries[f"{POOL}/memory/fact-a.md"])]})
    assert cmd_apply(root, str(absorb), client="zcode", source_dir=str(source)) == 0
    capsys.readouterr()
    # v6：源永在 → 复 apply 同决策 = 同 (key,hash) 已决 → DUPLICATE（W5），不双写
    assert cmd_apply(root, str(absorb), client="zcode", source_dir=str(source)) == 1
    assert "APPLY_ENTRY_DUPLICATE" in capsys.readouterr().out
    assert len(list((root / "raw").glob("*.md"))) == 1

    discard = decision_file(tmp_path, {"schema_version": 1, "decisions": [
        {"key": f"{POOL}/memory/fact-b.md",
         "hash": entries[f"{POOL}/memory/fact-b.md"]["hash"],
         "action": "discard", "reason": "r"}]})
    assert cmd_apply(root, str(discard), client="zcode", source_dir=str(source)) == 0
    capsys.readouterr()
    assert cmd_apply(root, str(discard), client="zcode", source_dir=str(source)) == 1
    assert "APPLY_ENTRY_DUPLICATE" in capsys.readouterr().out


def test_stale_when_file_changes_after_decision(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entry = manifest["pending"][0]
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": [absorb_decision(entry)]})
    write_file(source / POOL / "memory/fact-a.md", FACT_A + "\n决策后并发修改。\n")  # hash 漂移
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 1
    assert "APPLY_ENTRY_STALE" in capsys.readouterr().out
    assert list((root / "raw").glob("*.md")) == []


# ---------------------------------------------------------------------------
# E-C4 映射校验 / 字段校验 / 已移除字段
# ---------------------------------------------------------------------------


def test_unknown_project_fails_entry_only(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entries = {e["key"]: e for e in manifest["pending"]}
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": [
        absorb_decision(entries[f"{POOL}/memory/fact-a.md"], project_id="proj-00000000-0000-0000-0000-000000000000"),
        {"key": f"{POOL}/memory/fact-b.md",
         "hash": entries[f"{POOL}/memory/fact-b.md"]["hash"],
         "action": "discard", "reason": "ok"},
    ]})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 1
    out = capsys.readouterr().out
    assert "APPLY_PROJECT_UNKNOWN" in out and "discarded" in out
    assert list((root / "raw").glob("*.md")) == []


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


@pytest.mark.parametrize("removed_field", ["delete_source", "slim_index", "cleanup", "prune_empty_pools"])
def test_removed_write_fields_rejected(tmp_path, removed_field):
    """v6/D-C28：客户端写字段整体移除——decision 里出现即 fatal 拒绝，零写入。"""
    root, source = make_kit(tmp_path), make_source(tmp_path)
    payload = {"schema_version": 1, "decisions": [], removed_field: True}
    decision = decision_file(tmp_path, payload)
    assert cli.main(["--root", str(root), "collect", "--apply", str(decision),
                     "--source-dir", str(source)]) == 2
    assert not (root / "collect").exists() and list((root / "raw").glob("*.md")) == []


# ---------------------------------------------------------------------------
# raw/账本产物（v6：账本无 source 字段；footnote 按客户端取标签）
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
    record = ledger["entries"][f"{POOL}/memory/fact-a.md"]
    assert record["state"] == "absorbed" and record["hash"].startswith("sha256:") \
        and record["raw"].startswith("raw/") and record["decided_at"]
    assert "source" not in record  # v6/D-C28：字段已移除


def test_claude_code_source_label(tmp_path):
    """v6：claude_code 采集的 raw source=claude-code（枚举合法），footnote 用 Claude Code 标签。"""
    root = make_kit(tmp_path)
    cc_source = tmp_path / "cc-projects"
    cc_source.mkdir()
    make_pool(cc_source, "-Users-cm-workspace-demo-app",
              {"f.md": FACT_A}, memory_md="# Memory Index\n- [T](f.md) — H\n")
    manifest = build_manifest(root, "claude_code", cc_source)
    entry = manifest["pending"][0]
    decision = decision_file(tmp_path, {"schema_version": 1, "client": "claude_code",
                                        "decisions": [absorb_decision(entry, topic="cc-topic")]})
    assert cmd_apply(root, str(decision), client="claude_code", source_dir=str(cc_source)) == 0
    raw_file = next((root / "raw").glob("*.md"))
    meta = yaml.safe_load(raw_file.read_text(encoding="utf-8").split("---")[1])
    assert meta["source"] == "claude-code"
    assert "> 来源：Claude Code auto-memory -Users-cm-workspace-demo-app/memory/f.md（" in raw_file.read_text(encoding="utf-8")


def test_empty_decision_is_ok(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    decision = decision_file(tmp_path, {"schema_version": 1, "decisions": []})
    assert cmd_apply(root, str(decision), client="zcode", source_dir=str(source)) == 0
    assert "nothing to do" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# E-C9/E-C10 与 v5 CLI 面
# ---------------------------------------------------------------------------


def test_client_binding_and_pool_discovery(tmp_path, capsys):
    assert set(CLIENT_SOURCE_DEFAULTS) == {"zcode", "claude_code"}
    assert CLIENT_SOURCE_DEFAULTS["claude_code"] == "~/.claude/projects"

    root, source = make_kit(tmp_path), make_source(tmp_path)
    assert cli.main(["--root", str(root), "collect", "--client", "codex",
                     "--source-dir", str(source)]) == 2
    err = capsys.readouterr().err
    assert "COLLECT_CLIENT_UNKNOWN" in err and "claude_code" in err and "zcode" in err

    cc_source = tmp_path / "cc-projects"
    cc_source.mkdir()
    make_pool(cc_source, "-Users-cm-workspace-demo-app",
              {"fact-a.md": FACT_A}, memory_md="# Memory Index\n- [T](fact-a.md) — H\n")
    assert cli.main(["--root", str(root), "collect", "--client", "claude_code",
                     "--source-dir", str(cc_source)]) == 0
    manifest = yaml.safe_load(capsys.readouterr().out)
    assert manifest["summary"] == {"pools": 1, "files": 1, "pending": 1, "unparsable": 0,
                                   "empty_pools": 0}
    assert manifest["pending"][0]["key"] == "-Users-cm-workspace-demo-app/memory/fact-a.md"


def test_pool_filter_and_mentions(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    manifest = manifest_of(root, source)
    entry = manifest["pending"][0]
    absorb = decision_file(tmp_path, {"schema_version": 1,
                                      "decisions": [absorb_decision(entry)]})
    assert cmd_apply(root, str(absorb), client="zcode", source_dir=str(source)) == 0
    # 新池加一条同名 name 的候选 → mentioned_in 应点名刚才的 raw
    make_pool(source, "other-4444444444444ddd", {"fact-a.md": FACT_A + "\n改。\n"},
              memory_md="- [T](fact-a.md) — H\n")
    m = build_manifest(root, "zcode", source, pools=["other-4444444444444ddd"])
    assert m["summary"]["pools"] == 1 and m["summary"]["pending"] == 1
    pending = m["pending"][0]
    assert pending["name"] == "fact-a"
    ledger = yaml.safe_load((root / "collect/zcode/ledger.yaml").read_text(encoding="utf-8"))
    absorbed_raw = ledger["entries"][entry["key"]]["raw"].split("/")[-1]  # 正文脚注含 name → 应被点名
    assert absorbed_raw in pending["mentioned_in"]
    assert all(e["key"].startswith("other-4444") for e in m["pending"])


def test_cli_collect_stdout_yaml_and_out(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    assert cli.main(["--root", str(root), "collect", "--source-dir", str(source)]) == 0
    manifest = yaml.safe_load(capsys.readouterr().out)
    assert manifest["summary"]["pending"] == 2 and "residue" not in manifest

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
    assert "would absorb" in out and "client side untouched" in out and "no writes performed" in out
    assert list((root / "raw").glob("*.md")) == []
    assert not (root / "collect").exists()
    assert (source / POOL / "memory/fact-a.md").exists()


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


def test_stdout_utf8_under_locale_pipe(tmp_path):
    """回归（CI windows 腿实故障）：重定向管道 locale 编码（cp1252）下打印中文清单不得崩。"""
    root = make_kit(tmp_path)
    source = tmp_path / "projects"
    source.mkdir()
    make_pool(source, "demo-pool-5555555555555eee", {"f.md": FACT_A},
              memory_md="- [中文标题](f.md) — 中文钩子\n")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    res = subprocess.run(
        [sys.executable, "-m", "hongzhao", "--root", str(root),
         "collect", "--source-dir", str(source)],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=60,
    )
    assert res.returncode == 0, f"must not crash under a locale-encoded pipe: {res.stderr[-300:]}"
    assert "中文标题" in res.stdout


def test_corrupt_ledger_fatal(tmp_path, capsys):
    root, source = make_kit(tmp_path), make_source(tmp_path)
    (root / "collect/zcode").mkdir(parents=True)
    (root / "collect/zcode/ledger.yaml").write_text("not: [valid\n", encoding="utf-8")
    with pytest.raises(CollectError) as excinfo:
        cmd_collect(root, client="zcode", source_dir=str(source))
    assert excinfo.value.code == "COLLECT_LEDGER_INVALID" and excinfo.value.exit_code == 2
    assert cli.main(["--root", str(root), "collect", "--source-dir", str(source)]) == 2
    assert "COLLECT_LEDGER_INVALID" in capsys.readouterr().err
