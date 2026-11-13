"""init 脚手架：`hongzhao init [路径] [--client a,b] [--example] [--force]`。

规则：未指定路径→默认 `~/hongzhao` 且输出必须明示；非空目录拒绝；`--force` 只补缺失、
绝不覆盖 config/raw；`--client` 仅对**检测到**的客户端置 enabled:true，未检测到
→false+警告，init 自身不调用 skills-install/bridge-install；win32 fail-fast。
产物清单（manifest 除外缺一即 validate degraded；manifest 为可选校验物 ，但 init
必须写它——）：config（3 预置全 false）+ raw/_template + 双 registry 空骨架 +
skills/（包内拷贝）+ templates/ + .gitignore（含 .hongzhao.lock）+ .hongzhao-manifest.json。
检测：预置=which+配置目录+版本命令三选二；自定义=bridge_path 父目录存在。
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from hongzhao import __version__

DEFAULT_ROOT = "~/hongzhao"
# 预置客户端检测输入（ 三选二）：可执行名、配置目录、版本命令
PRESET_CLIENTS: dict[str, dict[str, Any]] = {
    "claude_code": {
        "executable": "claude",
        "config_dir": "~/.claude",
        "version_cmd": ["claude", "--version"],
        "bridge_path": "~/.claude/CLAUDE.md",
        "skills_root": "~/.claude/skills",
        "mode": "import",
    },
    "codex": {
        "executable": "codex",
        "config_dir": "~/.codex",
        "version_cmd": ["codex", "--version"],
        "bridge_path": "~/.codex/AGENTS.md",
        "skills_root": "~/.codex/skills",
        "mode": "inline",
    },
    "zcode": {
        "executable": "zcode",
        "config_dir": "~/.zcode",
        "version_cmd": ["zcode", "--version"],
        "bridge_path": "~/.zcode/AGENTS.md",
        "skills_root": "~/.zcode/skills",
        "mode": "inline",
    },
    "pi": {
        # pi（earendil-works/pi-coding-agent）：全局指令 ~/.pi/agent/AGENTS.md；
        # 技能原生读 ~/.agents/skills（pi 自身 CHANGELOG 明载），与共享位约定天然一致
        "executable": "pi",
        "config_dir": "~/.pi",
        "version_cmd": ["pi", "--version"],
        "bridge_path": "~/.pi/agent/AGENTS.md",
        "skills_root": "~/.agents/skills",
        "mode": "inline",
    },
    "dsh": {
        # dsh（DeepSeek Harness）：指令文件与配置目录都在 ~/.dsh
        "executable": "dsh",
        "config_dir": "~/.dsh",
        "version_cmd": ["dsh", "--version"],
        "bridge_path": "~/.dsh/AGENTS.md",
        "skills_root": "~/.agents/skills",
        "mode": "inline",
    },
    "opencode": {
        # opencode（sst/opencode）：全局指令 ~/.config/opencode/AGENTS.md；
        # 技能原生目录 ~/.config/opencode/skills（非共享位，与 pi/dsh 不同）
        "executable": "opencode",
        "config_dir": "~/.config/opencode",
        "version_cmd": ["opencode", "--version"],
        "bridge_path": "~/.config/opencode/AGENTS.md",
        "skills_root": "~/.config/opencode/skills",
        "mode": "inline",
    },
}
SKILL_NAMES = ["memory-write", "memory-compile", "memory-project-context", "work-closeout", "memory-collect"]

RAW_TEMPLATE = """---
schema_version: 2
id: mem-<uuid>
created: YYYY-MM-DD
source: claude-code|codex|zcode|user|migration|other
topic: <topic>
kind: profile|preference|memory
scope: global|project|non-project
activation: bootstrap|on-demand
record_type: source|synthesis
summary: one-line summary (single line, <=300 chars)
compile_status: new
---

Body (what was confirmed, by whom, evidence).
"""

GITIGNORE = """# hongzhao 运行期锁（绑定记忆根、持久存在；勿删）
.hongzhao.lock
# 常规忽略
.DS_Store
"""

# 行尾治理下界（design W4/F-08 硬约束）：检出形态必须与包内字节一致，
# 否则 skills-install 的字节比较会误判 SKILL_MODIFIED 并卡住 upgrade
GITATTRIBUTES = """* text=auto
skills/** text eol=lf
templates/** text eol=lf
compiled/** text eol=lf
render/** text eol=lf
registry/** text eol=lf
*.md text eol=lf
*.yaml text eol=lf
*.yml text eol=lf
.hongzhao-manifest.json text eol=lf
"""


def detect_preset(spec: dict[str, Any]) -> bool:
    """预置客户端检测：可执行 which / 配置目录存在 / 版本命令退出码——三选二。"""
    votes = 0
    if shutil.which(str(spec["executable"])):
        votes += 1
    if Path(str(spec["config_dir"])).expanduser().is_dir():
        votes += 1
    try:
        result = subprocess.run(
            list(spec["version_cmd"]), capture_output=True, timeout=10
        )
        if result.returncode == 0:
            votes += 1
    except (OSError, subprocess.TimeoutExpired):
        pass
    return votes >= 2


def detect_custom(settings: dict[str, Any]) -> bool:
    """自定义客户端（config 中任意名字）：bridge_path 父目录存在即视为安装。"""
    parent = Path(str(settings["bridge_path"])).expanduser().parent
    return parent.is_dir()


def client_detected(name: str, settings: dict[str, Any]) -> bool:
    if name in PRESET_CLIENTS:
        return detect_preset(PRESET_CLIENTS[name])
    return detect_custom(settings)


def build_config(enabled: dict[str, bool]) -> dict[str, Any]:
    # init 只创建预置客户端条目（六个）；自定义客户端由用户随后编辑 config 添加（ 检测在 ）
    clients: dict[str, dict[str, Any]] = {}
    for name, preset in PRESET_CLIENTS.items():
        clients[name] = {
            "enabled": enabled.get(name, False),
            "bridge_path": preset["bridge_path"],
            "skills_root": preset["skills_root"],
            "mode": preset["mode"],
        }
    return {
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
        "skills": list(SKILL_NAMES),
        "clients": clients,
        # 编译后自动提交：缺省开启；独立仓库守卫在 gitauto，显式 false 可关
        "git": {"auto_commit": True},
    }


def _write_text_lf(path: Path, content: str) -> None:
    """固定 LF 写出（Path.write_text 的 newline 参数为 3.10+，3.9 走 open）。"""
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_lf(path, content)  # W2：模板固定 LF（3.9 兼容）
    return True


def _copy_tree_if_missing(src: Path, dst: Path) -> list[Path]:
    written: list[Path] = []
    for item in sorted(src.rglob("*")):
        if item.is_dir():
            continue
        target = dst / item.relative_to(src)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        written.append(target)
    return written


def _manifest_entry(root: Path, path: Path) -> tuple[str, str]:
    relative = path.relative_to(root).as_posix()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return relative, digest


def seed_example(root: Path) -> None:
    """绿场景种子：一对用 resolved_by 闭合的冲突演示（compile 后 health ok）。"""
    raw = root / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    _write_text_lf(
        raw / "example-profile.md",
        "---\n"
        "schema_version: 2\n"
        "id: mem-11111111-1111-4111-8111-111111111111\n"
        "created: 2026-01-01\n"
        "source: user\n"
        "topic: getting-started\n"
        "kind: profile\n"
        "scope: global\n"
        "activation: on-demand\n"
        "record_type: source\n"
        "summary: Example profile claim for the green demo kit.\n"
        "compile_status: done\n"
        "---\n\nExample body.\n",
    )
    _write_text_lf(
        raw / "example-superseded.md",
        "---\n"
        "schema_version: 2\n"
        "id: mem-22222222-2222-4222-8222-222222222222\n"
        "created: 2026-01-01\n"
        "source: user\n"
        "topic: getting-started\n"
        "kind: memory\n"
        "scope: global\n"
        "activation: on-demand\n"
        "record_type: source\n"
        "summary: Old claim, superseded by the correction demo.\n"
        "compile_status: done\n"
        "supersedes: []\n"
        "---\n\nOld body.\n",
    )
    _write_text_lf(
        raw / "example-correction.md",
        "---\n"
        "schema_version: 2\n"
        "id: mem-33333333-3333-4333-8333-333333333333\n"
        "created: 2026-01-02\n"
        "source: user\n"
        "topic: getting-started\n"
        "kind: memory\n"
        "scope: global\n"
        "activation: on-demand\n"
        "record_type: source\n"
        "summary: Correction demo replacing the old claim.\n"
        "compile_status: done\n"
        "supersedes:\n"
        "  - mem-22222222-2222-4222-8222-222222222222\n"
        "---\n\nCorrected body.\n",
    )


def cmd_init(path: str | None, clients: list[str] | None, example: bool, force: bool) -> int:
    target = Path(path).expanduser() if path else Path(DEFAULT_ROOT).expanduser()
    if not path:
        # 未指定路径必须明示默认位置
        print(f"note: no path given, the memory kit will be created at {DEFAULT_ROOT}")
    if target.exists() and any(target.iterdir()):
        has_config = (target / "config.yaml").is_file()
        if not force or not has_config:
            print(
                f"error: {target} is not empty; --force only fills missing files in an "
                "existing hongzhao root and never overwrites config/raw",
                file=sys.stderr,
            )
            return 2
    target.mkdir(parents=True, exist_ok=True)

    # 检测与 enabled 决策（只对检测到的置 true）
    config = build_config({})
    enabled_map: dict[str, bool] = {}
    warnings: list[str] = []
    for name in clients or []:
        if name not in PRESET_CLIENTS:
            warnings.append(
                f"warning: '{name}' is not a preset client; custom clients are added by "
                "editing config.yaml (see docs/clients)"
            )
            continue
        detected = client_detected(name, PRESET_CLIENTS[name])
        enabled_map[name] = detected
        if not detected:
            warnings.append(f"warning: client '{name}' not detected; left enabled:false")
    config = build_config(enabled_map)

    wrote_config = _write_if_missing(target / "config.yaml", yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    (target / "raw").mkdir(exist_ok=True)
    _write_if_missing(target / "raw" / "_template.md", RAW_TEMPLATE)
    _write_if_missing(target / "registry" / "project-registry.yaml", "schema_version: 2\nprojects: []\n")
    _write_if_missing(target / "registry" / "knowledge-registry.yaml", "schema_version: 2\nknowledge: []\n")
    _write_if_missing(target / ".gitignore", GITIGNORE)
    _write_if_missing(target / ".gitattributes", GITATTRIBUTES)

    # 包内 skills/templates 拷贝（package data，importlib.resources）
    from importlib import resources

    package = resources.files("hongzhao")
    copied: list[Path] = []
    for subtree in ("skills", "templates"):
        src = Path(str(package / subtree))
        if src.is_dir():
            copied += _copy_tree_if_missing(src, target / subtree)
        else:
            (target / subtree).mkdir(exist_ok=True)

    if example:
        seed_example(target)

    # manifest（init 必须写；：可选校验物，不进「缺一即 degraded」）
    entries: dict[str, str] = {}
    for path in sorted((target / "skills").rglob("*")) + sorted((target / "templates").rglob("*")):
        if path.is_file():
            key, digest = _manifest_entry(target, path)
            entries[key] = digest
    entries["_synced_with"] = __version__  # 升级偏斜检测（doctor SKILL_STALE）
    _write_text_lf(
        target / ".hongzhao-manifest.json",
        yaml.safe_dump(entries, allow_unicode=True, sort_keys=True),
    )

    for line in warnings:
        print(line)
    print(f"initialized memory kit at {target}")
    print("next steps:")
    print("  hongzhao compile")
    print("  hongzhao skills-install all   # after enabling clients")
    print("  hongzhao bridge-install all")
    print("  hongzhao doctor")
    return 0
