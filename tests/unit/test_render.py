"""渲染层测试（ 链接矩阵 /  语言分层 /  契约链接 /  键集冻结）。

合成数据；链接断言按设计  的解析方式实现（markdown=从产物所在目录 resolve）。
"""
from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path

import yaml

from hongzhao.core import parse_frontmatter
from hongzhao.render import compile_all, markdown_link

FIX = Path(__file__).resolve().parents[1] / "fixtures"
BASE = (FIX / "containment" / "config_base.yaml").read_text(encoding="utf-8")
OPTIONAL_WIKILINK = (FIX / "containment" / "config_optional_ok.yaml").read_text(encoding="utf-8")
EXPECTED_FRONTMATTER = yaml.safe_load((FIX / "expected_frontmatter.yaml").read_text(encoding="utf-8"))

RECORD_A = """---
schema_version: 2
id: mem-1b0e6a2c-9f3d-4a51-8c2e-7a6b5d4e3f20
created: 2026-10-29
source: claude-code
topic: demo
kind: memory
scope: global
activation: on-demand
record_type: source
summary: Alpha source record.
compile_status: done
---

Alpha body.
"""

RECORD_B = """---
schema_version: 2
id: mem-2c1f7b3d-0e4f-4b62-9d3f-8b7c6e5f4a31
created: 2026-10-29
source: zcode
topic: demo
kind: memory
scope: global
activation: on-demand
record_type: synthesis
summary: Beta synthesis with special-char filename.
compile_status: done
derived_from:
  - mem-1b0e6a2c-9f3d-4a51-8c2e-7a6b5d4e3f20
---

Beta body.
"""


ID_A = "mem-1b0e6a2c-9f3d-4a51-8c2e-7a6b5d4e3f20"
ID_B = "mem-2c1f7b3d-0e4f-4b62-9d3f-8b7c6e5f4a31"


def make_kit(base: Path, config_text: str = BASE) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.yaml").write_text(config_text, encoding="utf-8")
    (base / "raw").mkdir(exist_ok=True)
    (base / "registry").mkdir(exist_ok=True)
    (base / "registry" / "project-registry.yaml").write_text("schema_version: 2\nprojects: []\n", encoding="utf-8")
    (base / "registry" / "knowledge-registry.yaml").write_text("schema_version: 2\nknowledge: []\n", encoding="utf-8")
    return base


def add_records(kit: Path) -> None:
    (kit / "raw" / "alpha.md").write_text(RECORD_A, encoding="utf-8")
    # 特殊字符文件名：空格、括号、#—— 的坏链高发面
    (kit / "raw" / "note #1 (beta).md").write_text(RECORD_B, encoding="utf-8")


MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(<([^>]+)>\)")


def _resolved_targets(text: str, product_dir: Path) -> list[Path]:
    targets = []
    for _label, target in MARKDOWN_LINK.findall(text):
        unquoted = urllib.parse.unquote(target)
        targets.append((product_dir / unquoted).resolve())
    return targets


def test_compile_markdown_links_resolve_with_special_chars(tmp_path):
    kit = make_kit(tmp_path / "kit")
    add_records(kit)
    code, issues = compile_all(kit)
    assert code == 0, [i.format() for i in issues]
    product_dir = kit / "compiled" / "effective-memory"
    text = (product_dir / "global.md").read_text(encoding="utf-8")
    targets = _resolved_targets(text, product_dir)
    assert targets and all(t.exists() for t in targets), targets
    names = {t.name for t in targets}
    assert "alpha.md" in names and "note #1 (beta).md" in names
    # 路由页链接同样可解析
    idx_text = (product_dir / "index.md").read_text(encoding="utf-8")
    for t in _resolved_targets(idx_text, product_dir):
        assert t.exists(), t


def test_knowledge_map_markdown_links_cross_root(tmp_path):
    # knowledge_root=".."（条目在 memory root 外、knowledge_root 内）——恒 markdown、可解析
    kit = make_kit(tmp_path / "memory", OPTIONAL_WIKILINK)
    add_records(kit)
    notes = tmp_path / "31-知识" / "笔记.md"  # Unicode 路径：percent-encode 后仍需可解析
    notes.parent.mkdir(parents=True)
    notes.write_text("knowledge", encoding="utf-8")
    (kit / "registry" / "knowledge-registry.yaml").write_text(
        "schema_version: 2\nknowledge:\n  - path: 31-知识/笔记.md\n    title: Notes\n    topics: [a]\n    summary: s\n",
        encoding="utf-8",
    )
    code, issues = compile_all(kit)
    assert code == 0, [i.format() for i in issues]
    text = (kit / "compiled" / "knowledge-map.md").read_text(encoding="utf-8")
    assert "[[" not in text  # 知识条目链接恒 markdown，不受 wikilink 模式影响
    targets = _resolved_targets(text, kit / "compiled")
    assert targets and all(t.exists() for t in targets), targets


def test_wikilink_mode_uses_prefix_and_semantic_paths(tmp_path):
    kit = make_kit(tmp_path / "kit", OPTIONAL_WIKILINK)
    add_records(kit)
    code, issues = compile_all(kit)
    assert code == 0
    text = (kit / "compiled" / "effective-memory" / "global.md").read_text(encoding="utf-8")
    assert "[[60-Agent-Memory/raw/alpha.md|mem-1b0e6a2c-9f3d-4a51-8c2e-7a6b5d4e3f20]]" in text
    idx = (kit / "compiled" / "effective-memory" / "index.md").read_text(encoding="utf-8")
    assert "[[60-Agent-Memory/compiled/current-state.md|Current State]]" in idx


CJK = re.compile(r"[\u4e00-\u9fff]")


def test_outputs_contain_no_chinese_template_text(tmp_path):
    # ：模板/标题/协议全部英文化（本 kit 用户数据全英文，故整个产物应零 CJK）
    kit = make_kit(tmp_path / "kit")
    add_records(kit)
    compile_all(kit)
    outputs = [
        kit / "render" / "bootstrap.md",
        kit / "compiled" / "current-state.md",
        kit / "compiled" / "corrections.md",
        kit / "compiled" / "knowledge-map.md",
        kit / "compiled" / "effective-memory" / "index.md",
        kit / "compiled" / "effective-memory" / "global.md",
        kit / "compiled" / "effective-memory" / "non-project.md",
    ]
    for path in outputs:
        assert path.is_file(), path
        assert not CJK.search(path.read_text(encoding="utf-8")), f"CJK found in {path}"


def test_frontmatter_key_sets_frozen(tmp_path):
    # ：键集与基线完全一致（值可因语言/路径变化，键不可增删改名）
    kit = make_kit(tmp_path / "kit")
    add_records(kit)
    compile_all(kit)

    def keys(path: Path) -> set[str]:
        meta, _ = parse_frontmatter(path)
        return set(meta)

    base = kit
    checks = {
        "effective_file": base / "compiled/effective-memory/global.md",
        "effective_index": base / "compiled/effective-memory/index.md",
        "knowledge_map": base / "compiled/knowledge-map.md",
        "current_state": base / "compiled/current-state.md",
        "corrections": base / "compiled/corrections.md",
        "bootstrap": base / "render/bootstrap.md",
    }
    for name, path in checks.items():
        assert keys(path) == set(EXPECTED_FRONTMATTER[name]), f"{name} key set drifted: {path}"
    # bootstrap 专属键（ inline 反查依赖 memory_root）
    meta, _ = parse_frontmatter(base / "render/bootstrap.md")
    assert meta["memory_root"]


def test_markdown_link_contract_relative_to_product_dir(tmp_path):
    #  单元级：链接一律相对「产物所在目录」解析（不是语义基）
    target = tmp_path / "proj" / "deep" / "entry.md"
    product_dir = tmp_path / "root" / "projects" / "mykey"
    link = markdown_link(target, product_dir, "entry")
    assert link.startswith("[entry](<") and link.endswith(">)")
    relative = urllib.parse.unquote(link[len("[entry](<"):-2])
    assert (product_dir / relative).resolve() == target.resolve()
    # 编码覆盖：空格/括号/#/Unicode
    tricky = tmp_path / "a b (c) #d 中文.md"
    link2 = markdown_link(tricky, tmp_path, "t")
    assert " " not in link2 and "(" not in link2.split("](<")[1]
    restored = tmp_path / urllib.parse.unquote(link2[len("[t](<"):-2])
    assert restored.resolve() == tricky.resolve()
