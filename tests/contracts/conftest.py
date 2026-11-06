# -*- coding: utf-8 -*-
# 修改记录（RB-02a M1）：2026-10-29，修改人=t16-author；差异①CONFIG_PATHS 键 effective_memory → corrections ②knowledge registry 骨架容器键 records → knowledge；理由=对齐冻结 schema（仅改两处键名，不动断言与用例）。
"""合同测试公共设施////。

约定（design  /  /：
- 真实入口：一律经 subprocess 调用 CLI。优先已安装的 ``hongzhao`` 可执行文件；
  未安装时回退到包的公开入口 ``hongzhao.cli:main``（与 console-script 同一入口，
  不属于引擎内部模块）。测试进程内不 import 引擎实现、不 mock 引擎内部。
- 测试数据自建自清理：全部落在 pytest tmp_path 内的最小记忆库，绝不读写
  vault 生产库。
- 根注入：显式设置 ``$HONGZHAO_ROOT``（ 根发现序 ②，直读不回落），
  避免 cwd / 托管块反查带来的环境干扰。
- 注释中文、断言英文。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# CLI 调用（真实入口）
# ---------------------------------------------------------------------------

# CLI 未安装时的回退形式：经包公开入口 hongzhao.cli:main 调起（console-script 同源）
_CLI_FALLBACK = "import sys; from hongzhao.cli import main; raise SystemExit(main(sys.argv[1:]))"


def build_cmd(args):
    """构造真实 CLI 命令行：优先 hongzhao 可执行文件，其次 python -c 回退。"""
    args = [str(a) for a in args]
    exe = shutil.which("hongzhao")
    if exe is not None:
        return [exe] + args
    return [sys.executable, "-c", _CLI_FALLBACK] + args


def build_env(root, env_extra=None):
    """构造子进程环境：显式根（ 序 ②）+ 清除外部故障注入变量防串扰。"""
    env = os.environ.copy()
    env["HONGZHAO_ROOT"] = str(Path(root).resolve())
    # 默认清除故障注入变量；需要注入的用例显式传入（ 双条件）
    env.pop("HONGZHAO_TEST", None)
    env.pop("HONGZHAO_FAULT", None)
    if env_extra:
        env.update({k: str(v) for k, v in env_extra.items()})
    return env


def run_cli(args, root, cwd=None, env_extra=None, timeout=90):
    """同步执行一条真实 CLI 命令，返回 CompletedProcess。"""
    cmd = build_cmd(args)
    return subprocess.run(
        cmd,
        cwd=str(Path(cwd if cwd is not None else root).resolve()),
        env=build_env(root, env_extra),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def popen_cli(args, root, env_extra=None):
    """异步启动一条真实 CLI 命令（并发用例使用，真实多进程）。"""
    cmd = build_cmd(args)
    return subprocess.Popen(
        cmd,
        cwd=str(Path(root).resolve()),
        env=build_env(root, env_extra),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def out_of(res):
    """合并 stdout/stderr（错误码可能出现在任一流）。"""
    return (getattr(res, "stdout", "") or "") + (getattr(res, "stderr", "") or "")


#  双条件故障注入点（ 全部 4 点）
FAULT_AFTER_REGISTRY_WRITE = "after-registry-write"
FAULT_MID_CONTRACT_WRITE = "mid-contract-write"
FAULT_CONTRACT_WRITE = "contract-write"
FAULT_AFTER_REGISTRY_DELETE = "after-registry-delete"


def fault_env(point):
    """：HONGZHAO_TEST=1 且 HONGZHAO_FAULT=<point> 同时满足才生效。"""
    return {"HONGZHAO_TEST": "1", "HONGZHAO_FAULT": point}


# ---------------------------------------------------------------------------
# 最小记忆库构造（fixture 数据层，自建自清理）
# ---------------------------------------------------------------------------

# config.yaml 的 paths 8 必填键（design  键表）。
# 推断说明：按任务约定作者不读取 vault 生产库，键名依据 design 引用的实际文件名
# /：raw/、registry/project-registry.yaml、compiled/memory-index.yaml、
# compiled/effective-memory/、compiled/knowledge-map.md、compiled/current-state.md、
# render/bootstrap.md）与「paths 8 键、语义同现状」推出；知识 registry 文件名按同目录惯例。
# 若与冻结 schema 有出入，属 fixture 数据问题（RB-02 在  转绿前核对修正），不属断言放宽。
CONFIG_PATHS = {
    "raw": "raw",
    "project_registry": "registry/project-registry.yaml",
    "knowledge_registry": "registry/knowledge-registry.yaml",
    "memory_index": "compiled/memory-index.yaml",
    "corrections": "compiled/effective-memory",
    "knowledge_map": "compiled/knowledge-map.md",
    "current_state": "compiled/current-state.md",
    "bootstrap": "render/bootstrap.md",
}

# skills 4 内核名（design ：skills 为 4 内核名）
CONFIG_SKILLS = ["memory-write", "memory-compile", "memory-project-context", "work-closeout"]

# 客户端条目仍严格 4 键；测试全部 enabled:false，不触发任何客户端写入
CONFIG_CLIENTS = {
    "claude_code": {
        "enabled": False,
        "bridge_path": "~/.claude/CLAUDE.md",
        "skills_root": "~/.claude/skills",
        "mode": "import",
    },
    "codex": {
        "enabled": False,
        "bridge_path": "~/.codex/AGENTS.md",
        "skills_root": "~/.codex/skills",
        "mode": "import",
    },
    "zcode": {
        "enabled": False,
        "bridge_path": "~/.zcode/AGENTS.md",
        "skills_root": "~/.zcode/skills",
        "mode": "import",
    },
}

# registry 落盘形状（schema 2 冻结，）：
# 顶层 schema_version: 2 + 条目列表；条目 4 字段（project_id / location{kind,path} /
# registered_at / last_checked_at）。依据 design 「条目仅 4 字段、location.kind 取值
# {vault,external}」、「registry 不存 key」「刷新 last_checked_at」推出；
# 列表键名（projects）为推断项，同上由 RB-02 核对。
REGISTRY_FILE = "registry/project-registry.yaml"


def make_memory_root(base):
    """在 tmp 目录内构造最小记忆库（config.yaml 按  键表 + registry schema 2 空骨架）。"""
    root = Path(base) / "memory"
    for sub in ("raw", "registry", "compiled", "render", "projects", "skills", "templates"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 2,
        "paths": dict(CONFIG_PATHS),
        "skills": list(CONFIG_SKILLS),
        "clients": {name: dict(spec) for name, spec in CONFIG_CLIENTS.items()},
    }
    (root / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    set_registry_entries(root, [])
    # 知识 registry 空骨架（列表键为推断，测试内惰性使用）
    (root / "registry" / "knowledge-registry.yaml").write_text(
        yaml.safe_dump({"schema_version": 2, "knowledge": []}, sort_keys=False), encoding="utf-8"
    )
    return root


# ---------------------------------------------------------------------------
# registry / 契约数据读写（纯数据层，不经引擎）
# ---------------------------------------------------------------------------

def registry_entries(root):
    """读取 registry 条目列表（容忍列表键名差异：projects/entries/records 或顶层列表）。"""
    path = Path(root) / REGISTRY_FILE
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict):
        for key in ("projects", "entries", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return []
    if isinstance(data, list):
        return data
    return []


def set_registry_entries(root, entries):
    """整写 registry（fixture 层自建数据）。"""
    path = Path(root) / REGISTRY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 2, "projects": list(entries)}
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def add_registry_entry(root, project_id, target_dir, registered_at="2026-10-01",
                       last_checked_at="2026-10-01"):
    """按  写值规则追加一条 registry 条目（root 内 → vault+相对；root 外 → external+绝对）。"""
    root = Path(root)
    target = Path(target_dir).resolve()
    root_resolved = root.resolve()
    if target == root_resolved or root_resolved in target.parents:
        kind, path_value = "vault", os.path.relpath(target, root_resolved)
    else:
        kind, path_value = "external", str(target)
    entries = registry_entries(root)
    entry = {
        "project_id": project_id,
        "location": {"kind": kind, "path": path_value},
        "registered_at": registered_at,
        "last_checked_at": last_checked_at,
    }
    entries.append(entry)
    set_registry_entries(root, entries)
    return entry


def location_of(entry):
    """取条目 location 的 (kind, path)；容忍扁平形状（kind/path 平铺在条目上）。"""
    loc = entry.get("location")
    if isinstance(loc, dict):
        return loc.get("kind"), loc.get("path")
    return entry.get("kind"), entry.get("path")


def write_contract(directory, project_id, project_key, project_name=None,
                   purpose="Purpose of the project", current_state="Stable state",
                   next_action="Next action", status="active", activation="on-demand",
                   entrypoints=None, updated_at="2026-10-29"):
    """写一份契约（frontmatter 字段按 「契约 frontmatter 字段来源」表）。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "schema_version": 2,
        "project_id": project_id,
        "project_key": project_key,
        "project_name": project_name or project_key,
        "purpose": purpose,
        "current_state": current_state,
        "next_action": next_action,
        "status": status,
        "activation": activation,
        "entrypoints": list(entrypoints or []),
        "updated_at": updated_at,
    }
    body = (
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + f"# {project_key}\n\nProject contract body (fixture).\n"
    )
    contract = directory / "project-view.md"
    contract.write_text(body, encoding="utf-8")
    return contract


def read_contract(path):
    """读取契约 frontmatter（纯 YAML 解析）。"""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", f"contract frontmatter missing: {path}"
    end_idx = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    return yaml.safe_load("\n".join(lines[1:end_idx])) or {}


def central_path(root, key):
    """central 契约路径（目录名 = project_key，「central 目录名权威」）。"""
    return Path(root) / "projects" / key / "project-view.md"


def find_centrals(root):
    """列出全部 central 契约（集 A）。"""
    projects = Path(root) / "projects"
    if not projects.is_dir():
        return []
    return sorted(p for p in projects.rglob("project-view.md") if p.is_file())


# ---------------------------------------------------------------------------
# 零写入断言（失败路径：registry 与契约逐字节不变）
# ---------------------------------------------------------------------------

def snapshot_state(root, extra_dirs=()):
    """收集 config / registry / 全部 central 契约 / 指定项目目录契约的逐字节快照。"""
    root = Path(root)
    files = {}

    def _put(path):
        path = Path(path)
        if path.is_file():
            files[str(path.resolve())] = path.read_bytes()

    _put(root / "config.yaml")
    _put(root / "registry" / "project-registry.yaml")
    _put(root / "registry" / "knowledge-registry.yaml")
    for p in find_centrals(root):
        _put(p)
    for d in extra_dirs:
        _put(Path(d) / "project-view.md")
    return files
