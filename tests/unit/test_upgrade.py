"""升级机制测试（docs/UPGRADE.md）：偏斜检测（SKILL_STALE/BOOTSTRAP_STALE）、
`hongzhao upgrade` 五步编排（全绿闭环 / 失败即停）、老 manifest（无版本键）向下兼容。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from hongzhao import __version__, bridge, scaffold
from hongzhao.cli import cmd_upgrade


def _fresh_kit(tmp: Path) -> Path:
    kit = tmp / "memory"
    assert scaffold.cmd_init(str(kit), [], False, False) == 0
    return kit


def _doctor_output(kit: Path, capsys) -> tuple[int, str]:
    code = bridge.cmd_doctor(kit)
    return code, capsys.readouterr().out


def test_bootstrap_records_engine_version_and_stale_warning(tmp_path, capsys):
    # compile 后 bootstrap 带 engine_version=当前版本；伪造旧版本 → doctor 报 BOOTSTRAP_STALE（warning 级，exit 0）
    kit = _fresh_kit(tmp_path)
    from hongzhao.cli import cmd_compile

    assert cmd_compile(kit) == 0
    bootstrap = kit / "render" / "bootstrap.md"
    text = bootstrap.read_text(encoding="utf-8")
    assert f"engine_version: {__version__}" in text
    stale = text.replace(f"engine_version: {__version__}", "engine_version: 0.0.1-old")
    assert stale != text
    bootstrap.write_text(stale, encoding="utf-8")
    code, out = _doctor_output(kit, capsys)
    assert code == 0  # warning 不降级
    assert "BOOTSTRAP_STALE" in out
    assert "0.0.1-old" in out and __version__ in out
    # 旧引擎产物（无该行）同样报 stale 而非静默
    bootstrap.write_text(text.replace(f"engine_version: {__version__}\n", ""), encoding="utf-8")
    code, out = _doctor_output(kit, capsys)
    assert code == 0 and "BOOTSTRAP_STALE" in out and "older engine" in out


def test_skill_stale_on_version_mismatch_and_legacy_manifest(tmp_path, capsys):
    # ① _synced_with 落后 → 报两个版本号；② 老 manifest 无该键 → 报 predates；均 warning
    kit = _fresh_kit(tmp_path)
    from hongzhao.cli import cmd_compile

    assert cmd_compile(kit) == 0  # 先到健康基线：偏斜是唯一告警源
    manifest_path = kit / ".hongzhao-manifest.json"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["_synced_with"] == __version__  # init 即写版本（出生不偏斜）
    manifest["_synced_with"] = "0.0.1-old"
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    code, out = _doctor_output(kit, capsys)
    assert code == 0 and "SKILL_STALE" in out
    assert "0.0.1-old" in out and __version__ in out
    del manifest["_synced_with"]  # 版本追踪之前的老 kit
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    code, out = _doctor_output(kit, capsys)
    assert code == 0 and "predates version tracking" in out


def test_upgrade_full_sequence_clears_skew(tmp_path, capsys):
    # 制造双重偏斜（manifest 旧版本 + bootstrap 旧引擎）→ upgrade 五步全绿 → doctor 无偏斜
    kit = _fresh_kit(tmp_path)
    from hongzhao.cli import cmd_compile

    assert cmd_compile(kit) == 0
    manifest_path = kit / ".hongzhao-manifest.json"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["_synced_with"] = "0.0.1-old"
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    bootstrap = kit / "render" / "bootstrap.md"
    bootstrap.write_text(
        bootstrap.read_text(encoding="utf-8").replace(f"engine_version: {__version__}", "engine_version: 0.0.1-old"),
        encoding="utf-8",
    )
    assert cmd_upgrade(kit) == 0
    out = capsys.readouterr().out
    assert out.count("upgrade [") == 5 and f"upgrade: ok (engine {__version__})" in out
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["_synced_with"] == __version__
    assert f"engine_version: {__version__}" in bootstrap.read_text(encoding="utf-8")
    code, doctor_out = _doctor_output(kit, capsys)
    assert code == 0 and "SKILL_STALE" not in doctor_out and "BOOTSTRAP_STALE" not in doctor_out
    assert "doctor: ok" in doctor_out


def test_upgrade_stops_at_skills_modified(tmp_path, capsys):
    # kit skill 被手改（manifest 记录旧哈希）→ skills-install 落 .new 退出 1 → upgrade 停在第 2 步，不硬闯后续
    kit = _fresh_kit(tmp_path)
    target = kit / "skills" / "memory-write" / "SKILL.md"
    target.write_bytes(b"user customized\n")
    assert cmd_upgrade(kit) == 1
    captured = capsys.readouterr()
    assert captured.out.count("upgrade [") == 2  # validate + skills-install 后即停
    assert "stopped at step 2" in captured.err
    assert (kit / "skills" / "memory-write" / "SKILL.md.new").exists()  # 新版候选已落盘待人工合并
    assert target.read_bytes() == b"user customized\n"  # 用户改动原样保留


def test_downgrade_protection_hint_on_newer_bootstrap(tmp_path, capsys):
    # 降级场景：bootstrap 由更新引擎生成（版本号更高形态）→ doctor 报 stale 提示重编译，而非静默错读
    kit = _fresh_kit(tmp_path)
    from hongzhao.cli import cmd_compile

    assert cmd_compile(kit) == 0
    bootstrap = kit / "render" / "bootstrap.md"
    bootstrap.write_text(
        bootstrap.read_text(encoding="utf-8").replace(f"engine_version: {__version__}", "engine_version: 99.0.0"),
        encoding="utf-8",
    )
    code, out = _doctor_output(kit, capsys)
    assert code == 0 and "BOOTSTRAP_STALE" in out and "99.0.0" in out
