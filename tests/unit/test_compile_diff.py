"""编译差异报告测试：首次/增量/无变化三态与计数表。"""
from __future__ import annotations

from pathlib import Path

from hongzhao.render import COMPILE_DIFF_PATH, compile_all

FIX = Path(__file__).resolve().parents[1] / "fixtures"
BASE = (FIX / "containment" / "config_base.yaml").read_text(encoding="utf-8")

DONE_TMPL = """---
schema_version: 2
id: mem-aa11bb22-0000-4000-8000-{seq:012d}
created: 2026-11-02
source: user
topic: diff-demo
kind: memory
scope: global
activation: on-demand
record_type: source
summary: Record {seq} done.
compile_status: done
---

Body {seq}.
"""

NEW_TMPL = DONE_TMPL.replace("compile_status: done", "compile_status: new").replace(
    "summary: Record {seq} done.", "summary: Record {seq} pending."
)


def make_kit(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.yaml").write_text(BASE, encoding="utf-8")
    (base / "raw").mkdir(exist_ok=True)
    (base / "registry").mkdir(exist_ok=True)
    (base / "registry" / "project-registry.yaml").write_text("schema_version: 2\nprojects: []\n", encoding="utf-8")
    (base / "registry" / "knowledge-registry.yaml").write_text("schema_version: 2\nknowledge: []\n", encoding="utf-8")
    return base


def write_raw(kit: Path, name: str, template: str, seq: int) -> None:
    (kit / "raw" / name).write_text(template.format(seq=seq), encoding="utf-8")


def diff_text(kit: Path) -> str:
    return (kit / COMPILE_DIFF_PATH).read_text(encoding="utf-8")


def test_first_compile_diff_has_no_baseline_note(tmp_path):
    kit = make_kit(tmp_path / "kit")
    write_raw(kit, "a.md", DONE_TMPL, 1)
    code, issues = compile_all(kit)
    assert code == 0, [i.format() for i in issues]
    text = diff_text(kit)
    assert "no baseline" in text
    assert "First compile against this baseline" in text
    assert "| effective | - | 1 | - |" in text
    assert "health_after: ok" in text


def test_delta_diff_lists_newly_effective_pending_and_removal(tmp_path):
    kit = make_kit(tmp_path / "kit")
    write_raw(kit, "keep.md", DONE_TMPL, 1)
    write_raw(kit, "gone.md", DONE_TMPL, 2)
    code, _ = compile_all(kit)
    assert code == 0

    # 变更：gone 改 rejected、keep 保留、新增一条 done 与一条 new 候选
    (kit / "raw" / "gone.md").write_text(
        (kit / "raw" / "gone.md").read_text(encoding="utf-8").replace(
            "compile_status: done", "compile_status: rejected\nreview_note: obsolete\nreviewed_at: 2026-11-02"
        ),
        encoding="utf-8",
    )
    write_raw(kit, "add.md", DONE_TMPL, 3)
    write_raw(kit, "cand.md", NEW_TMPL, 4)
    code, _ = compile_all(kit)
    assert code == 0

    text = diff_text(kit)
    assert "## Newly effective (1)" in text
    assert "mem-aa11bb22-0000-4000-8000-000000000003" in text
    assert "## No longer effective (1)" in text
    assert "reason: rejected" in text
    assert "## Newly pending (1)" in text
    assert "Record 4 pending" in text
    # 计数行：effective 2 -> 2（加一减一）；rejected 0 -> 1
    assert "| effective | 2 | 2 | 0 |" in text
    assert "| rejected | 0 | 1 | +1 |" in text
    # 健康从 ok 变 review-needed（有新候选）
    assert "health_before: ok" in text
    assert "health_after: review-needed" in text
    assert "`ok` -> `review-needed`" in text


def test_no_change_diff_says_so(tmp_path):
    kit = make_kit(tmp_path / "kit")
    write_raw(kit, "a.md", DONE_TMPL, 1)
    compile_all(kit)
    code, _ = compile_all(kit)
    assert code == 0
    text = diff_text(kit)
    assert "No changes since baseline." in text
    assert "Newly effective" not in text
    assert "(unchanged)" in text


def test_deleted_effective_raw_reports_removal(tmp_path):
    kit = make_kit(tmp_path / "kit")
    write_raw(kit, "a.md", DONE_TMPL, 1)
    compile_all(kit)
    (kit / "raw" / "a.md").unlink()
    code, _ = compile_all(kit)
    assert code == 0
    text = diff_text(kit)
    assert "(record removed)" in text
    assert "| effective | 1 | 0 | -1 |" in text


def test_corrupt_baseline_does_not_block_compile(tmp_path):
    kit = make_kit(tmp_path / "kit")
    write_raw(kit, "a.md", DONE_TMPL, 1)
    compile_all(kit)
    (kit / "compiled" / "memory-index.yaml").write_text("::: not yaml [", encoding="utf-8")
    code, issues = compile_all(kit)
    assert code == 0, [i.format() for i in issues]
    # 不可解析基线按缺失处理（unreadable/malformed 分支皆可），编译不阻断
    assert "treated as first compile" in diff_text(kit)
