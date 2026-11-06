"""客户端桥接生命周期：托管块安装/迁移/卸载、doctor 分级、skills 同步与软链。

要点：`hongzhao:` 新代标记 + 兼容检测旧 `agent-memory:` 标记（LEGACY_MARKER）；
`install_bridge_checked()` 为统一刷新入口（bridge-install / knowledge-register 自动
刷新 / uninstall 共用），内置三选二安装判定与 legacy 检测；migrate-bridge 按七行决策
表；doctor 按 severity 分级表输出 `<severity> <code> <client|-> <path> <message>`；
skills-install 两段式（manifest 三态同步 → 软链），只替换 resolve 后位于
`<root>/skills` 内的软链（外来软链 SKILL_CONFLICT 跳过、--force 覆盖）；uninstall
默认 dry-run；建链失败按自然异常退出、不静默退化。
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any

from hongzhao import __version__
from hongzhao.core import load_config, load_contracts, load_registry, write_atomic
from hongzhao.scaffold import PRESET_CLIENTS, detect_custom, detect_preset

MANAGED_START = "<!-- hongzhao:start -->"
MANAGED_END = "<!-- hongzhao:end -->"
LEGACY_START = "<!-- agent-memory:start -->"
LEGACY_END = "<!-- agent-memory:end -->"
MANIFEST_NAME = ".hongzhao-manifest.json"

# doctor 分级：其余 CONTRACT_*/schema 类一律 degraded
WARNING_CODES = {
    "BRIDGE_MISSING", "BRIDGE_BLOCK", "BRIDGE_STALE",
    "SKILL_MISSING", "SKILL_TARGET", "SKILLS_CONFIG",
    "CLIENT_NOT_INSTALLED", "LEGACY_MARKER",
    "SKILL_STALE", "BOOTSTRAP_STALE",
}
CONTRACT_HINTS = {
    "CONTRACT_MISSING": "fix: hongzhao project-register <project-root>  (hits J3 rebuild, keeps the id)",
    "CONTRACT_ORPHAN": "fix: hongzhao project-unregister <key>  (or claim via hongzhao project-register <project-root> --key <key> --yes)",
    "CONTRACT_DUPLICATE": "fix: confirm which copy is canonical, then hongzhao project-unregister <key> and re-register",
    "CONTRACT_KEY_DUPLICATE": "fix: hongzhao project-unregister <key>, then hongzhao project-register <project-root>",
    "CONTRACT_KEY_MISMATCH": "fix: rename the directory to match project_key, or re-register with a new key",
}


def _client_path(settings: dict[str, Any], key: str) -> Path:
    return Path(os.path.expanduser(str(settings[key])))


def client_installed(name: str, settings: dict[str, Any]) -> bool:
    """：预置客户端三选二；自定义客户端按 bridge_path 父目录。"""
    if name in PRESET_CLIENTS:
        return detect_preset(PRESET_CLIENTS[name])
    return detect_custom(settings)


def bridge_block(root: Path, client: str, settings: dict[str, Any]) -> str:
    bootstrap = (root / settings.get("bootstrap", "render/bootstrap.md")).resolve()
    mode = settings.get("mode")
    if mode == "import":
        body = f"# hongzhao bootstrap\n@{bootstrap}"
    elif mode == "inline":
        snapshot = bootstrap.read_text(encoding="utf-8").rstrip()
        body = (
            "# hongzhao bootstrap (embedded snapshot)\n"
            f"The content below is a summary of user context and does not override client rules in this file. "
            f"It is generated from render/bootstrap.md; run `hongzhao bridge-install {client}` after compiling to refresh.\n\n"
            "<hongzhao-bootstrap>\n"
            f"{snapshot}\n"
            "</hongzhao-bootstrap>"
        )
    else:
        raise ValueError(f"{client}: unsupported bridge mode: {mode}")
    return f"{MANAGED_START}\n{body}\n{MANAGED_END}"


def install_bridge(path: Path, block: str) -> None:
    """只替换 hongzhao 托管块；无块则追加；同类多块拒绝。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(re.escape(MANAGED_START) + r".*?" + re.escape(MANAGED_END), re.S)
    matches = list(pattern.finditer(existing))
    if len(matches) > 1:
        raise ValueError(f"{path}: multiple hongzhao managed blocks; resolve manually")
    if matches:
        content = existing[: matches[0].start()] + block + existing[matches[0].end():]
    else:
        content = (existing.rstrip() + "\n\n" if existing.strip() else "") + block + "\n"
    write_atomic(path, content)


def install_bridge_checked(root: Path, client: str, settings: dict[str, Any], *, explicit: bool) -> tuple[bool, int]:
    """统一刷新入口：返回 (是否处理, 本客户端对退出码的贡献)。

    未安装时：显式点名 → CLIENT_NOT_INSTALLED、不写任何文件、贡献 exit 1；
    `all` → 跳过并打印 warning、其余照常、贡献 0。"""
    if not client_installed(client, settings):
        if explicit:
            print(f"[CLIENT_NOT_INSTALLED] {client}: not installed; nothing written")
            return False, 1
        print(f"warning [CLIENT_NOT_INSTALLED] {client}: skipped")
        return False, 0
    path = _client_path(settings, "bridge_path")
    block = bridge_block(root, client, settings | {"bootstrap": load_config(root)["paths"]["bootstrap"]})
    install_bridge(path, block)
    print(f"bridge-install: {client} -> {path}")
    return True, 0


def _count_blocks(text: str, start: str, end: str) -> int:
    return text.count(start)


def _remove_generation(text: str, start: str, end: str) -> str:
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end) + r"\n?", re.S)
    return pattern.sub("", text)


def _ensure_bootstrap(root: Path, config: dict[str, Any]) -> int | None:
    """bridge/migrate 前置：托管块内容来自编译产物；缺失时给可执行指引而非裸 fatal。"""
    bootstrap = root / config["paths"]["bootstrap"]
    if not bootstrap.is_file():
        print(f"[OUTPUT_MISSING] {bootstrap} not found; run `hongzhao compile` first", file=sys.stderr)
        return 1
    return None


def cmd_bridge_install(root: Path, client: str) -> int:
    config = load_config(root)
    missing = _ensure_bootstrap(root, config)
    if missing is not None:
        return missing
    clients = config.get("clients", {})
    if client == "all":
        code = 0
        for name, settings in clients.items():
            if not settings.get("enabled"):
                continue
            _done, contribution = install_bridge_checked(root, name, settings, explicit=False)
            code = max(code, contribution)
        return code
    settings = clients.get(client)
    if not settings or not settings.get("enabled"):
        print(f"[BRIDGE_DISABLED] {client} is not enabled; nothing written")
        return 1
    _done, code = install_bridge_checked(root, client, settings, explicit=True)
    return code


def cmd_migrate_bridge(root: Path) -> int:
    """七行决策表：enabled×{旧/新/旧+新/同类多个} + disabled×{旧/新/旧+新}。"""
    config = load_config(root)
    code = 0
    for name, settings in config.get("clients", {}).items():
        path = _client_path(settings, "bridge_path")
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        old_count = _count_blocks(text, LEGACY_START, LEGACY_END)
        new_count = _count_blocks(text, MANAGED_START, MANAGED_END)
        if old_count > 1 or new_count > 1:
            print(f"error [MIGRATE_AMBIGUOUS] {name} {path}: multiple same-generation blocks; resolve manually")
            code = 1
            continue
        enabled = bool(settings.get("enabled"))
        if old_count == 0 and new_count == 0:
            continue
        if enabled:
            if old_count and not new_count:
                # 旧块 → 替换为新块
                block = bridge_block(root, name, settings | {"bootstrap": config["paths"]["bootstrap"]})
                text = _remove_generation(text, LEGACY_START, LEGACY_END)
                pattern = re.compile(re.escape(MANAGED_START) + r".*?" + re.escape(MANAGED_END), re.S)
                if pattern.search(text):
                    text = pattern.sub(block, text)
                else:
                    text = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
                write_atomic(path, text)
                print(f"migrate-bridge: {name} legacy block replaced")
            elif old_count and new_count:
                text = _remove_generation(text, LEGACY_START, LEGACY_END)
                write_atomic(path, text)
                print(f"migrate-bridge: {name} legacy block removed, new block kept")
            else:  # 只有新块：重新生成（刷新）
                block = bridge_block(root, name, settings | {"bootstrap": config["paths"]["bootstrap"]})
                pattern = re.compile(re.escape(MANAGED_START) + r".*?" + re.escape(MANAGED_END), re.S)
                write_atomic(path, pattern.sub(block, text))
                print(f"migrate-bridge: {name} new block refreshed")
        else:
            # disabled：旧块仍清理；既有新块保留不刷新
            if old_count:
                text = _remove_generation(text, LEGACY_START, LEGACY_END)
                write_atomic(path, text)
                print(f"migrate-bridge: {name} (disabled) legacy block removed")
            if new_count:
                print(f"migrate-bridge: {name} (disabled) new block kept untouched")
    return code


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_tree() -> list[tuple[Path, str]]:
    """包内 skills/ 与 templates/ 文件清单：[(包内绝对路径, 相对名)]。"""
    from importlib import resources

    package = resources.files("hongzhao")
    items: list[tuple[Path, str]] = []
    for subtree in ("skills", "templates"):
        base = Path(str(package / subtree))
        if not base.is_dir():
            continue
        for item in sorted(base.rglob("*")):
            if item.is_file():
                items.append((item, f"{subtree}/{item.relative_to(base).as_posix()}"))
    return items


def _load_manifest(root: Path) -> dict[str, str] | None:
    path = root / MANIFEST_NAME
    if not path.exists():
        return None
    import yaml as _yaml

    data = _yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _save_manifest(root: Path, entries: dict[str, str]) -> None:
    import yaml as _yaml

    write_atomic(root / MANIFEST_NAME, _yaml.safe_dump(entries, allow_unicode=True, sort_keys=True))


def sync_package_to_root(root: Path, force: bool = False) -> int:
    """ 三态同步（skills+templates）：一致→覆盖更新；用户改过→.new；manifest 缺失→全部 .new。"""
    manifest = _load_manifest(root)
    entries: dict[str, str] = dict(manifest or {})
    code = 0
    for source, relative in _package_tree():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() == source.read_bytes():
            entries[relative] = _sha256(target)
            continue
        if target.exists():
            changed_by_user = manifest is None or manifest.get(relative) != _sha256(target)
            if force or not changed_by_user:
                # --force 或内容仍等于 manifest 记录（包更新）→ 覆盖
                target.write_bytes(source.read_bytes())
                entries[relative] = _sha256(target)
                print(f"skills-install: updated {relative}")
            else:
                new_file = target.with_name(target.name + ".new")
                new_file.write_bytes(source.read_bytes())
                print(f"warning [SKILL_MODIFIED] {relative}: kept yours; candidate written to {new_file.name}")
                code = 1
        else:
            target.write_bytes(source.read_bytes())
            entries[relative] = _sha256(target)
            print(f"skills-install: installed {relative}")
    # 包内已删而根内仍存的文件：保留不删并报告（；`_` 前缀为版本元数据键，不算 deprecated）
    known = {relative for _source, relative in _package_tree()}
    if manifest:
        for relative in sorted(set(manifest) - known):
            if relative.startswith("_"):
                continue
            if (root / relative).exists():
                print(f"warning [SKILL_DEPRECATED] {relative}: no longer shipped; kept in your root")
    entries["_synced_with"] = __version__  # 升级偏斜检测（doctor SKILL_STALE）
    _save_manifest(root, entries)
    return code


def _link_skills(root: Path, config: dict[str, Any], client: str, force: bool) -> int:
    settings = config["clients"][client]
    skills_root = _client_path(settings, "skills_root")
    skills_root.mkdir(parents=True, exist_ok=True)
    code = 0
    for skill in config.get("skills", []):
        source = (root / "skills" / skill).resolve()
        target = skills_root / skill
        if target.exists() and not target.is_symlink():
            if not force:
                print(f"warning [SKILL_CONFLICT] {target}: exists and is not a symlink; skipped")
                code = 1
                continue
        if target.is_symlink():
            resolved = target.resolve()
            inside = str(resolved).startswith(str((root / "skills").resolve()) + os.sep)
            if not inside and not force:
                print(f"warning [SKILL_CONFLICT] {target}: foreign symlink; skipped")
                code = 1
                continue
            target.unlink()
        if not target.exists():
            target.symlink_to(source, target_is_directory=True)  # 建链失败按自然异常退出（ 关闭）
        print(f"skills-install: {client}/{skill}")
    return code


def cmd_skills_install(root: Path, client: str, force: bool = False, manifest_only: bool = False) -> int:
    config = load_config(root)
    if manifest_only:
        # /：只生成/刷新 manifest——不覆盖任何 skill 文件、不写 .new、不动软链；
        # 对包内已知且根内在场的文件按「当前内容」记录哈希（存量根场景，如作者中文版）。
        manifest = _load_manifest(root) or {}
        entries = dict(manifest)
        for _source, relative in _package_tree():
            target = root / relative
            if target.exists():
                entries[relative] = _sha256(target)
        entries["_synced_with"] = __version__
        _save_manifest(root, entries)
        print("skills-install: manifest-only complete")
        return 0
    code = sync_package_to_root(root, force=force)
    clients = config.get("clients", {})
    selected = (
        [client] if client != "all" else [n for n, s in clients.items() if s.get("enabled")]
    )
    for name in selected:
        settings = clients.get(name)
        if not settings or not settings.get("enabled"):
            print(f"[BRIDGE_DISABLED] {name}")
            code = max(code, 1)
            continue
        if not client_installed(name, settings):
            if client == "all":
                print(f"warning [CLIENT_NOT_INSTALLED] {name}: skipped")
                continue
            print(f"[CLIENT_NOT_INSTALLED] {name}: not installed; nothing written")
            return 1
        code = max(code, _link_skills(root, config, name, force))
    return code


def _iter_symlinks_in_root_skills(root: Path) -> list[Path]:
    """resolve 后位于 <root>/skills 内的候选客户端软链（uninstall 只删这类）。"""
    result: list[Path] = []
    config = load_config(root)
    for settings in config.get("clients", {}).values():
        skills_root_value = settings.get("skills_root")
        if not isinstance(skills_root_value, str) or not skills_root_value.strip():
            continue
        skills_root = _client_path(settings, "skills_root")
        if not skills_root.is_dir():
            continue
        for skill in config.get("skills", []):
            link = skills_root / skill
            if link.is_symlink():
                resolved = link.resolve()
                if str(resolved).startswith(str((root / "skills").resolve()) + os.sep):
                    result.append(link)
    return result


def cmd_uninstall(root: Path, yes: bool) -> int:
    """：默认 dry-run；只删两代托管块与 root/skills 内软链；绝不 rmtree 非软链；不删记忆根。"""
    config = load_config(root)
    blocks: list[tuple[str, Path]] = []
    for name, settings in config.get("clients", {}).items():
        path = _client_path(settings, "bridge_path")
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if MANAGED_START in text or LEGACY_START in text:
            blocks.append((name, path))
    links = _iter_symlinks_in_root_skills(root)
    print("uninstall plan (dry-run; pass --yes to execute):")
    for name, path in blocks:
        print(f"  remove managed block: {name} {path}")
    for link in links:
        print(f"  remove symlink: {link}")
    print(f"  keep: memory root itself ({root})")
    if not yes:
        return 0
    for _name, path in blocks:
        text = path.read_text(encoding="utf-8")
        text = _remove_generation(text, MANAGED_START, MANAGED_END)
        text = _remove_generation(text, LEGACY_START, LEGACY_END)
        write_atomic(path, text.rstrip() + "\n")
        print(f"uninstall: block removed from {path}")
    for link in links:
        link.unlink()
        print(f"uninstall: symlink removed {link}")
    return 0


def cmd_doctor(root: Path) -> int:
    """分级体检：degraded→exit 1；仅 warning/info→exit 0。"""
    config = load_config(root)
    lines: list[tuple[str, str, str, str, str]] = []  # (severity, code, client, path, message)

    def add(severity: str, code: str, client: str, path: str, message: str) -> None:
        lines.append((severity, code, client, path, message))

    index_path = root / config["paths"]["memory_index"]
    memory_health = "missing"
    if index_path.exists():
        try:
            import yaml as _yaml

            memory_health = str((_yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}).get("health", "unknown"))
        except (OSError, _yaml.YAMLError) as exc:
            add("degraded", "INDEX_PARSE", "-", str(index_path), str(exc))
        if memory_health == "degraded":
            add("degraded", "MEMORY_HEALTH", "-", str(index_path), "memory-index health=degraded")

    # 契约诊断（degraded + 修复命令；/J3 提示）——central 感知扫描
    from hongzhao.contracts import contract_state_issues

    registry, registry_issues = load_registry(root)
    for issue in registry_issues:
        hint = CONTRACT_HINTS.get(issue.code, "")
        add("degraded", issue.code, "-", issue.path or "-", issue.message + (f"; {hint}" if hint else ""))
    for code, message, path in contract_state_issues(root, registry):
        hint = CONTRACT_HINTS.get(code, "")
        add("degraded", code, "-", path, message + (f"; {hint}" if hint else ""))

    # 升级偏斜检测：kit 同步版本 / bootstrap 生成版本落后于当前引擎 → 提示升级序列
    # （manifest 缺失键=版本追踪之前的老 kit；bootstrap 无 engine_version 行=旧引擎生成）
    manifest = _load_manifest(root)
    if manifest is not None:
        synced = manifest.get("_synced_with")
        if synced is None:
            add("warning", "SKILL_STALE", "-", str(root / MANIFEST_NAME),
                "manifest predates version tracking; run hongzhao skills-install all")
        elif synced != __version__:
            add("warning", "SKILL_STALE", "-", str(root / MANIFEST_NAME),
                f"skills/templates synced with {synced}, engine {__version__}; run hongzhao skills-install all")
    bootstrap_path = root / config["paths"]["bootstrap"]
    if bootstrap_path.is_file():
        engine_version = ""
        for line in bootstrap_path.read_text(encoding="utf-8").splitlines()[:20]:
            if line.startswith("engine_version:"):
                engine_version = line.split(":", 1)[1].strip()
                break
        if engine_version != __version__:
            add("warning", "BOOTSTRAP_STALE", "-", str(bootstrap_path),
                f"bootstrap generated by {engine_version or 'an older engine'}, engine {__version__}; "
                "run hongzhao compile (then bridge-install all)")

    for client, settings in config.get("clients", {}).items():
        path = _client_path(settings, "bridge_path")
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        # LEGACY_MARKER：全部客户端（含 disabled， 旧块仍清理）
        if LEGACY_START in text:
            add("warning", "LEGACY_MARKER", client, str(path), "legacy agent-memory block present; run hongzhao migrate-bridge (no arguments)")
        if not settings.get("enabled"):
            if MANAGED_START in text:
                add("info", "DISABLED_HAS_BLOCK", client, str(path), "disabled client keeps a hongzhao block; it will be refreshed once re-enabled")
            continue
        if not client_installed(client, settings):
            add("warning", "CLIENT_NOT_INSTALLED", client, str(path), "client not installed")
            continue
        if not path.exists():
            add("warning", "BRIDGE_MISSING", client, str(path), "bridge file missing")
        elif text.count(MANAGED_START) != 1 or text.count(MANAGED_END) != 1:
            add("warning", "BRIDGE_BLOCK", client, str(path), "managed block missing or duplicated")
        else:
            start = text.index(MANAGED_START)
            end = text.index(MANAGED_END, start) + len(MANAGED_END)
            actual = text[start:end]
            expected = bridge_block(root, client, settings | {"bootstrap": config["paths"]["bootstrap"]})
            if actual != expected:
                add("warning", "BRIDGE_STALE", client, str(path), "managed block drifted; run hongzhao bridge-install")
        skills_root_value = settings.get("skills_root")
        if not isinstance(skills_root_value, str) or not skills_root_value.strip():
            add("warning", "SKILLS_CONFIG", client, "-", "skills_root missing")
            continue
        for skill in config.get("skills", []):
            link = _client_path(settings, "skills_root") / skill
            expected = (root / "skills" / skill).resolve()
            if not link.is_symlink():
                add("warning", "SKILL_MISSING", client, str(link), f"skill symlink missing: {skill}")
            elif link.resolve() != expected:
                add("warning", "SKILL_TARGET", client, str(link), f"skill symlink target wrong: {skill}")

    for relative in (
        config["paths"]["memory_index"], config["paths"]["current_state"], config["paths"]["corrections"],
        config["paths"]["bootstrap"], config["paths"]["knowledge_map"],
        "compiled/effective-memory/index.md", "compiled/effective-memory/global.md",
        "compiled/effective-memory/non-project.md",
    ):
        if not (root / relative).exists():
            add("degraded", "OUTPUT_MISSING", "-", str(root / relative), "derived output missing; run hongzhao compile")

    for severity, code, client, path, message in lines:
        print(f"{severity} {code} {client} {path} {message}")
    print(f"memory-health: {memory_health}")
    degraded = any(s == "degraded" for s, *_ in lines)
    warning = any(s == "warning" for s, *_ in lines)
    print(f"doctor: {'degraded' if degraded else 'warning' if warning else 'ok'}")
    return 1 if degraded else 0
