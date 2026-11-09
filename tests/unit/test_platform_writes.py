"""平台写出回归（W2/D-W8/D-W10/D-W11）：LF 固定、行尾保留、replace 重试分支、索引 POSIX 路径。"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from hongzhao import bridge
from hongzhao.core import write_atomic
from hongzhao.render import compile_all

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _make_kit(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((FIX / "containment" / "config_base.yaml").read_text(encoding="utf-8"))
    (base / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (base / "raw").mkdir(exist_ok=True)
    (base / "registry").mkdir(exist_ok=True)
    (base / "registry" / "project-registry.yaml").write_text("schema_version: 2\nprojects: []\n", encoding="utf-8")
    (base / "registry" / "knowledge-registry.yaml").write_text("schema_version: 2\nknowledge: []\n", encoding="utf-8")
    return base


def test_write_atomic_default_is_lf(tmp_path):
    # W2 规则 1：默认 LF——即使在 CRLF 主导平台上（Windows）也不翻译（E3 底座）
    write_atomic(tmp_path / "out.md", "a\nb\n")
    raw = (tmp_path / "out.md").read_bytes()
    assert b"\r" not in raw
    assert raw == b"a\nb\n"


def test_write_atomic_explicit_crlf(tmp_path):
    # D-W10 接口：newline 参数可保留 CRLF（用户文件路径）
    write_atomic(tmp_path / "out.md", "a\nb\n", newline="\r\n")
    assert (tmp_path / "out.md").read_bytes() == b"a\r\nb\r\n"


def test_write_preserving_eol_keeps_user_crlf(tmp_path):
    # D-W10/E11：CRLF 用户客户端文件经 bridge-install 后仍为 CRLF，块外内容逐字节不变
    target = tmp_path / "CLAUDE.md"
    target.write_bytes(b"user rule one\r\nuser rule two\r\n")
    block = "managed body line\nsecond line\n"
    bridge._write_preserving_eol(target, block)
    raw = target.read_bytes()
    assert raw == b"managed body line\r\nsecond line\r\n"  # 按原主导行尾写回


def test_write_preserving_eol_defaults_lf_for_new_file(tmp_path):
    target = tmp_path / "AGENTS.md"
    bridge._write_preserving_eol(target, "x\n")
    assert target.read_bytes() == b"x\n"


def test_replace_no_retry_on_posix(tmp_path, monkeypatch):
    # D-W11：POSIX 分支不重试——PermissionError 立即抛出（E10 的 POSIX 断言）
    if os.name == "nt":
        return  # Windows 上由 retry 分支用例覆盖
    import hongzhao.core as core

    real_replace = os.replace
    calls = []

    def flaky(src, dst):
        calls.append(1)
        raise PermissionError("locked")

    monkeypatch.setattr(core.os, "replace", flaky)
    try:
        write_atomic(tmp_path / "p.md", "x\n")
    except PermissionError:
        pass
    assert len(calls) == 1  # 立即失败，零重试
    monkeypatch.setattr(core.os, "replace", real_replace)


def test_replace_retries_on_windows_branch(tmp_path, monkeypatch):
    # E10：Windows 分支有界重试后成功（monkeypatch os.name + os.replace 首次占用）
    import hongzhao.core as core

    real_replace = os.replace
    state = {"n": 0}

    def flaky(src, dst):
        state["n"] += 1
        if state["n"] == 1:
            raise PermissionError("antivirus scan")
        return real_replace(src, dst)

    monkeypatch.setattr(core.os, "name", "nt")
    monkeypatch.setattr(core.os, "replace", flaky)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)  # 重试不真实等待
    write_atomic(tmp_path / "p.md", "x\n")
    assert state["n"] == 2
    assert (tmp_path / "p.md").read_bytes() == b"x\n"


def test_index_paths_are_posix(tmp_path):
    # D-W8/E12 底座：memory-index 的 records.*.path 恒为 / 分隔
    kit = _make_kit(tmp_path / "kit")
    raw = kit / "raw" / "2026-01-01_topic_ab12cd34.md"
    meta = (
        "---\n"
        "schema_version: 2\n"
        "id: mem-55555555-5555-4555-8555-555555555555\n"
        "created: 2026-01-01\n"
        "source: user\n"
        "topic: topic\n"
        "kind: memory\n"
        "scope: global\n"
        "activation: on-demand\n"
        "record_type: source\n"
        "compile_status: done\n"
        'summary: "one line"\n'
        "---\nbody\n"
    )
    raw.write_text(meta, encoding="utf-8")
    compile_all(kit)
    index = yaml.safe_load((kit / "compiled" / "memory-index.yaml").read_text(encoding="utf-8"))
    paths = [entry["path"] for entry in index["records"].values()]
    assert paths and all("\\" not in p and "/" in p for p in paths), paths
