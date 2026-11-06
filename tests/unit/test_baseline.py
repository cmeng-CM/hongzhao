# -*- coding: utf-8 -*-
"""scripts/baseline/verify_baseline.py 单测：一致→0；篡改 health/删产物/改 claim 集/改键集→非零。"""
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "baseline" / "verify_baseline.py"


def _write_root(root: Path) -> None:
    mem = root
    (mem / "compiled" / "effective-memory").mkdir(parents=True, exist_ok=True)
    (mem / "render").mkdir(parents=True, exist_ok=True)
    index = {
        "health": "review-needed",
        "records": [
            {"id": "mem-a", "effective": True},
            {"id": "mem-b", "effective": True},
            {"id": "mem-c", "effective": False},
        ],
    }
    (mem / "compiled" / "memory-index.yaml").write_text(
        yaml.safe_dump(index, allow_unicode=True, sort_keys=False), encoding="utf-8")
    fm = "---\nschema_version: 2\nhealth: review-needed\n---\n# Title\n\n## Section One\n\ntext mem-a\n"
    (mem / "compiled" / "effective-memory" / "global.md").write_text(fm, encoding="utf-8")
    (mem / "render" / "bootstrap.md").write_text(
        "---\nschema_version: 2\nmemory_root: .\n---\n# Bootstrap\n\n## Routing\n\ntext\n", encoding="utf-8")


def _snapshot(root: Path, base: Path) -> None:
    import shutil
    shutil.copytree(root, base, dirs_exist_ok=True)
    import hashlib
    sha, keys, sections = {}, {}, {}
    for p in sorted(list((base / "compiled").rglob("*.md")) + list((base / "render").rglob("*.md"))):
        rel = p.relative_to(base).as_posix()
        sha[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        text = p.read_text(encoding="utf-8")
        keys[rel] = [l.split(":", 1)[0] for l in text.splitlines() if l and not l.startswith((" ", "-", "#")) and ":" in l] if text.startswith("---") else []
        sections[rel] = [l.strip() for l in text.splitlines() if l.startswith("#")]
    sha["compiled/memory-index.yaml"] = hashlib.sha256((base / "compiled" / "memory-index.yaml").read_bytes()).hexdigest()
    (base / "sha256.yaml").write_text(yaml.safe_dump(sha, sort_keys=True), encoding="utf-8")
    (base / "frontmatter-keys.yaml").write_text(yaml.safe_dump(keys, sort_keys=True), encoding="utf-8")
    (base / "sections.yaml").write_text(yaml.safe_dump(sections, sort_keys=True), encoding="utf-8")


def _run(base: Path, root: Path) -> int:
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--baseline", str(base), "--root", str(root)],
        capture_output=True, text=True).returncode


def test_verify_passes_on_identical_root(tmp_path):
    root, base = tmp_path / "root", tmp_path / "baseline"
    _write_root(root)
    _snapshot(root, base)
    assert _run(base, root) == 0


def test_claim_extraction_covers_dict_shaped_records(tmp_path):
    """生产 memory-index 的 records 为 dict（id 是键名，行内无 id）——claim 集合检查不得空转。"""
    root, base = tmp_path / "root", tmp_path / "baseline"
    _write_root(root)
    _snapshot(root, base)
    # 把 root 与基线同步改成 dict 形态（mem-a 生效、mem-b 生效、mem-c 不生效）
    def to_dict(p):
        idx = p / "compiled" / "memory-index.yaml"
        data = yaml.safe_load(idx.read_text(encoding="utf-8"))
        data["records"] = {r["id"]: {k: v for k, v in r.items() if k != "id"} for r in data["records"]}
        idx.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    to_dict(root)
    to_dict(base)
    # 改写后刷新基线清单（sha256 键集覆盖 memory-index；sections/frontmatter 不涉 index）
    import hashlib
    sha = yaml.safe_load((base / "sha256.yaml").read_text(encoding="utf-8"))
    sha["compiled/memory-index.yaml"] = hashlib.sha256((base / "compiled" / "memory-index.yaml").read_bytes()).hexdigest()
    (base / "sha256.yaml").write_text(yaml.safe_dump(sha, sort_keys=True), encoding="utf-8")
    out = subprocess.run([sys.executable, "-B", str(SCRIPT), "--baseline", str(base), "--root", str(root)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
    assert "effective claims=2" in out.stdout, out.stdout  # 提取到真实集合而非 0
    # 基线侧 mem-b 失效后集合不等 → 必须失败（证明断言非空转）
    idx = base / "compiled" / "memory-index.yaml"
    data = yaml.safe_load(idx.read_text(encoding="utf-8"))
    data["records"]["mem-b"]["effective"] = False
    idx.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    assert _run(base, root) != 0


def test_verify_fails_when_health_degrades(tmp_path):
    root, base = tmp_path / "root", tmp_path / "baseline"
    _write_root(root)
    _snapshot(root, base)
    idx = root / "compiled" / "memory-index.yaml"
    data = yaml.safe_load(idx.read_text(encoding="utf-8"))
    data["health"] = "degraded"
    idx.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert _run(base, root) != 0


def test_verify_fails_on_claim_set_change(tmp_path):
    root, base = tmp_path / "root", tmp_path / "baseline"
    _write_root(root)
    _snapshot(root, base)
    idx = root / "compiled" / "memory-index.yaml"
    data = yaml.safe_load(idx.read_text(encoding="utf-8"))
    data["records"][0]["effective"] = False
    idx.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert _run(base, root) != 0


def test_verify_fails_on_missing_artifact_and_key_drift(tmp_path):
    root, base = tmp_path / "root", tmp_path / "baseline"
    _write_root(root)
    _snapshot(root, base)
    (root / "render" / "bootstrap.md").unlink()
    assert _run(base, root) != 0
    # 键集漂移：frontmatter 增键
    _write_root(root)
    g = root / "compiled" / "effective-memory" / "global.md"
    g.write_text(g.read_text(encoding="utf-8").replace("health: review-needed", "health: review-needed\nextra: 1"), encoding="utf-8")
    assert _run(base, root) != 0


def test_verify_fails_on_snapshot_tamper(tmp_path):
    root, base = tmp_path / "root", tmp_path / "baseline"
    _write_root(root)
    _snapshot(root, base)
    g = base / "compiled" / "effective-memory" / "global.md"
    g.write_text(g.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
    assert _run(base, root) != 0
