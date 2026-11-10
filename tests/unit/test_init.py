"""init 脚手架测试（ 默认路径明示 / 非空拒绝 / --force 只补缺 /
--client 检测门控 / --example 绿场景 / manifest / .gitignore 含锁 / win32 fail-fast）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from hongzhao.core import load_config
from hongzhao.render import compile_all
from hongzhao import scaffold


def test_default_path_notice_and_creation(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows expanduser 走 USERPROFILE
    code = scaffold.cmd_init(None, None, False, False)
    assert code == 0
    out = capsys.readouterr().out
    assert "~/hongzhao" in out  # ：默认路径必须明示
    kit = tmp_path / "hongzhao"
    assert (kit / "config.yaml").is_file()
    assert (kit / "raw" / "_template.md").is_file()
    assert (kit / ".gitignore").read_text(encoding="utf-8").find(".hongzhao.lock") >= 0  # 
    assert (kit / ".hongzhao-manifest.json").is_file()  # ：init 必须写 manifest
    # manifest 覆盖 skills/templates 全部文件（键=相对 POSIX 路径，值=sha256；`_` 前缀=版本元数据）
    manifest = yaml.safe_load((kit / ".hongzhao-manifest.json").read_text(encoding="utf-8"))
    assert manifest
    assert manifest["_synced_with"] == scaffold.__version__  # init 即写同步版本（出生不偏斜）
    for relative, digest in manifest.items():
        if relative.startswith("_"):
            continue
        content = (kit / relative).read_bytes()
        assert hashlib.sha256(content).hexdigest() == digest
    # config：6 预置全 enabled:false（不带 --client 不启用）
    config = load_config(kit)
    assert set(config["clients"]) == {"claude_code", "codex", "dsh", "opencode", "pi", "zcode"}
    assert all(not c["enabled"] for c in config["clients"].values())


def test_nonempty_refused_and_force_only_fills_missing(tmp_path, monkeypatch):
    kit = tmp_path / "kit"
    kit.mkdir()
    (kit / "unrelated.txt").write_text("x", encoding="utf-8")
    assert scaffold.cmd_init(str(kit), None, False, False) == 2  # 非空拒绝
    # --force 也拒绝「非空且无 config」的目录（不是 hongzhao 根）
    assert scaffold.cmd_init(str(kit), None, False, True) == 2
    (kit / "unrelated.txt").unlink()
    assert scaffold.cmd_init(str(kit), None, False, False) == 0
    # config 打上标记后 --force：只补缺失、不覆盖 config
    cfg = kit / "config.yaml"
    marked = cfg.read_text(encoding="utf-8") + "# marker\n"
    cfg.write_text(marked, encoding="utf-8")
    (kit / "registry" / "project-registry.yaml").unlink()
    assert scaffold.cmd_init(str(kit), None, False, True) == 0
    assert cfg.read_text(encoding="utf-8") == marked  # config 未被覆盖
    assert (kit / "registry" / "project-registry.yaml").is_file()  # 缺失被补


def test_client_flag_gated_by_detection(tmp_path, monkeypatch, capsys):
    kit = tmp_path / "kit"
    # zcode 检测为已装、claude_code 未装；另给一个非预置名
    monkeypatch.setattr(
        scaffold, "client_detected",
        lambda name, settings: name == "zcode",
    )
    code = scaffold.cmd_init(str(kit), ["zcode", "claude_code", "dsh", "cursor"], False, False)
    assert code == 0
    config = load_config(kit)
    assert config["clients"]["zcode"]["enabled"] is True
    assert config["clients"]["claude_code"]["enabled"] is False
    assert config["clients"]["dsh"]["enabled"] is False  # 预置但未检测 → 条目在、enabled=false（六预设全量入 config）
    out = capsys.readouterr().out
    assert "not detected" in out
    assert "not a preset client" in out  # 非预置名给指引，不写入
    assert "cursor" not in config["clients"]
    assert sorted(config["clients"]) == ["claude_code", "codex", "dsh", "opencode", "pi", "zcode"]


def test_preset_detection_two_of_three(tmp_path, monkeypatch):
    # 只命中配置目录一项 → 不装；目录+可执行两项 → 装
    monkeypatch.setattr(scaffold.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        scaffold.subprocess, "run",
        lambda cmd, **kw: type("R", (), {"returncode": 1})(),
    )
    spec = scaffold.PRESET_CLIENTS["zcode"]
    monkeypatch.setattr(Path, "is_dir", lambda self, _spec=spec: self.expanduser() == Path(_spec["config_dir"]).expanduser())
    assert not scaffold.detect_preset(spec)
    monkeypatch.setattr(scaffold.shutil, "which", lambda name: "/bin/zcode")
    assert scaffold.detect_preset(spec)


def test_custom_detection_by_bridge_parent(tmp_path):
    bridge = tmp_path / "cfgdir" / "AGENTS.md"
    bridge.parent.mkdir()
    assert scaffold.detect_custom({"bridge_path": str(bridge)})
    assert not scaffold.detect_custom({"bridge_path": str(tmp_path / "nope" / "AGENTS.md")})


def test_example_seed_compiles_green(tmp_path, monkeypatch):
    kit = tmp_path / "kit"
    assert scaffold.cmd_init(str(kit), None, True, False) == 0
    code, issues = compile_all(kit)
    assert code == 0, [i.format() for i in issues]
    # 冲突演示存在且以 supersedes 呈现（corrections 非空）
    corrections = (kit / "compiled" / "corrections.md").read_text(encoding="utf-8")
    assert "Correction demo" in corrections


def test_windows_platform_inits_normally(monkeypatch, tmp_path):
    # D-W7（取代 D-31）：win32 不再 fail-fast，init 正常落盘
    import sys as _sys

    monkeypatch.setattr(_sys, "platform", "win32")
    kit = tmp_path / "kit"
    assert scaffold.cmd_init(str(kit), None, False, False) == 0
    assert (kit / "config.yaml").is_file()
    assert (kit / ".gitattributes").is_file()  # W4：行尾治理下界随 init 落盘


def test_new_presets_shape_and_detection_inputs():
    # pi/dsh/opencode 预设：五键齐备、bridge/skills 路径与各自约定一致（见 scaffold 注释）
    expected = {
        "pi": ("~/.pi/agent/AGENTS.md", "~/.agents/skills"),
        "dsh": ("~/.dsh/AGENTS.md", "~/.agents/skills"),
        "opencode": ("~/.config/opencode/AGENTS.md", "~/.config/opencode/skills"),
    }
    for name, (bridge, skills) in expected.items():
        spec = scaffold.PRESET_CLIENTS[name]
        assert set(spec) == {"executable", "config_dir", "version_cmd", "bridge_path", "skills_root", "mode"}
        assert spec["bridge_path"] == bridge
        assert spec["skills_root"] == skills
        assert spec["mode"] == "inline"
        assert spec["executable"] == name and spec["config_dir"].startswith("~")
        assert isinstance(spec["version_cmd"], list) and name in spec["version_cmd"]
