"""根发现（ 四源）与 `root` 诊断命令。

顺序：①`--root` ②`$HONGZHAO_ROOT` ③cwd 向上最多 5 层——候选判据=config.yaml 的
`paths` 是映射且同时含 `raw` 与 `memory_index`；候选但校验失败=`CONFIG_INVALID`
停止且不回落（R5 N4：否则拼写错误会静默落到托管块指向的生产根）④托管块反查——
预置 bridge_path 常量表；import 模式从 `@` 路径向上找 config 并校验 `paths.bootstrap`
一致，inline 模式取快照 frontmatter `memory_root`；多个客户端命中不同根=
`ROOT_AMBIGUOUS`。cwd 优先于托管块的原因见设计 （影子副本/demo 的裸命令不得
写进生产库）。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from hongzhao.core import load_yaml

# 预置客户端默认 bridge_path 常量（包内定义，不依赖运行期已找到的 config）
PRESET_BRIDGE_PATHS = (
    "~/.claude/CLAUDE.md",
    "~/.codex/AGENTS.md",
    "~/.zcode/AGENTS.md",
)
MANAGED_MARKERS = ("<!-- hongzhao:start -->", "<!-- agent-memory:start -->")
CWD_MAX_LEVELS = 5


class RootError(Exception):
    """根发现失败；code ∈ {ROOT_NOT_FOUND, CONFIG_INVALID, ROOT_AMBIGUOUS}。"""

    def __init__(self, code: str, message: str, candidates: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.candidates = candidates or []


def _is_memory_root_candidate(config_path: Path) -> bool:
    """候选谓词（与 schema_version 取值无关，故新版本 config 会报 CONFIG_INVALID 而非被跳过）。"""
    try:
        data = load_yaml(config_path)
    except (OSError, yaml.YAMLError, ValueError):
        return False
    paths = data.get("paths") if isinstance(data, dict) else None
    return isinstance(paths, dict) and "raw" in paths and "memory_index" in paths


def _validate_config(root: Path) -> dict[str, Any]:
    from hongzhao.core import load_config  # 延迟导入，保持模块依赖单向

    return load_config(root)  # 校验失败抛 ValueError → 由调用方转 CONFIG_INVALID


def _from_explicit(value: str, label: str) -> tuple[Path, str]:
    root = Path(os.path.expanduser(value)).resolve()
    if not root.is_dir() or not (root / "config.yaml").is_file():
        raise RootError(
            "ROOT_NOT_FOUND", f"{label} is not a memory root (missing dir or config.yaml):{root}"
        )
    try:
        _validate_config(root)
    except (ValueError, yaml.YAMLError) as exc:
        raise RootError("CONFIG_INVALID", f"{label} config.yaml validation failed:{exc}")
    return root, label


def _from_cwd(start: Path) -> tuple[Path, str] | None:
    current = start.resolve()
    for _ in range(CWD_MAX_LEVELS):
        config_path = current / "config.yaml"
        if config_path.is_file():
            if not _is_memory_root_candidate(config_path):
                current = current.parent  # 无特征键：不是记忆根，继续上溯
                if current == current.parent:
                    break
                continue
            try:
                _validate_config(current)
            except (ValueError, yaml.YAMLError) as exc:
                # 有特征键但校验失败：就是记忆根却写错了——停止且绝不回落
                raise RootError(
                    "CONFIG_INVALID", f"candidate memory root {current}: config.yaml validation failed:{exc}"
                )
            return current, "cwd"
        if current == current.parent:
            break
        current = current.parent
    return None


def _managed_root_from_bridge_file(path: Path) -> Path | None:
    """托管块反查：import 模式校验 paths.bootstrap 一致；inline 模式取快照 memory_root。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not any(marker in text for marker in MANAGED_MARKERS):
        return None
    imported = re.search(r"^@(\S+)$", text, re.M)
    if imported:
        bootstrap = Path(os.path.expanduser(imported.group(1)))
        for candidate in bootstrap.parents:
            config_path = candidate / "config.yaml"
            if config_path.is_file():
                try:
                    config = load_yaml(config_path)
                except (OSError, yaml.YAMLError, ValueError):
                    return None
                declared = (
                    config.get("paths", {}).get("bootstrap")
                    if isinstance(config, dict)
                    else None
                )
                if isinstance(declared, str) and (candidate / declared).resolve() == bootstrap.resolve():
                    return candidate.resolve()
                return None
        return None
    frontmatter = re.search(r"^---\s*\n(.*?)\n---", text, re.S | re.M)
    if frontmatter:
        try:
            meta = yaml.safe_load(frontmatter.group(1)) or {}
        except yaml.YAMLError:
            return None
        memory_root = meta.get("memory_root") if isinstance(meta, dict) else None
        if isinstance(memory_root, str):
            root = Path(os.path.expanduser(memory_root))
            if (root / "config.yaml").is_file():
                return root.resolve()
    return None


def _from_managed_blocks() -> list[tuple[Path, Path]]:
    hits: list[tuple[Path, Path]] = []
    for raw_path in PRESET_BRIDGE_PATHS:
        path = Path(os.path.expanduser(raw_path))
        if not path.is_file():
            continue
        root = _managed_root_from_bridge_file(path)
        if root is not None:
            hits.append((root, path))
    return hits


def discover_root(
    explicit: str | None = None, env: dict[str, str] | None = None
) -> tuple[Path, str]:
    """四源发现：返回 (root, source)；失败抛 RootError。source ∈ {--root, $HONGZHAO_ROOT, cwd, bridge}。"""
    environ = os.environ if env is None else env
    if explicit:
        return _from_explicit(explicit, "--root")
    env_root = environ.get("HONGZHAO_ROOT")
    if env_root:
        return _from_explicit(env_root, "env")
    hit = _from_cwd(Path.cwd())
    if hit:
        return hit
    hits = _from_managed_blocks()
    distinct = sorted({str(root) for root, _ in hits})
    if len(distinct) > 1:
        # 设计要求列出「候选根与来源」：root (via <客户端文件>)
        sourced = sorted({f"{root} (via {path})" for root, path in hits})
        raise RootError(
            "ROOT_AMBIGUOUS", "multiple client managed blocks point to different memory roots; refusing to pick one silently", sourced
        )
    if distinct:
        return Path(distinct[0]), "bridge"
    raise RootError(
        "ROOT_NOT_FOUND", "all four sources missed; run hongzhao init, or pass --root / $HONGZHAO_ROOT"
    )


def cmd_root(json_output: bool, explicit: str | None = None) -> int:
    """`hongzhao root [--json]`：命中 exit 0；未命中或 ROOT_AMBIGUOUS exit 1。"""
    try:
        root, source = discover_root(explicit)
    except RootError as exc:
        if json_output:
            print(
                json.dumps(
                    {"root": None, "source": None, "error": exc.code, "candidates": exc.candidates},
                    ensure_ascii=False,
                )
            )
        else:
            print(f"[{exc.code}] {exc}", file=__import__("sys").stderr)
            for candidate in exc.candidates:
                print(f"  candidate: {candidate}", file=__import__("sys").stderr)
        return 1
    payload = {"root": str(root), "source": source, "config": str(root / "config.yaml")}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"root: {payload['root']} (source: {source})")
        print(f"config: {payload['config']}")
    return 0
