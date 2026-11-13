"""CLI 入口：validate/compile/render/root + 全局旗标（--root/--dry-run/--json/--verbose）。

根解析走 root.discover_root 四源；普通命令下 ROOT_NOT_FOUND/CONFIG_INVALID/
ROOT_AMBIGUOUS 均按环境错误 exit 2（`root` 子命令自身按设计用 0/1 报告命中与否）。
加载器异常统一 fatal 前缀 + exit 2（对齐旧引擎语义，reviews/002 -M1）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from hongzhao import __version__
from hongzhao import bridge as bridgemod
from hongzhao import contracts as contractsmod
from hongzhao import root as rootmod
from hongzhao.core import (
    load_config,
    load_contracts,
    load_knowledge_registry,
    load_registry,
    load_yaml,
    project_keys_by_id,
    validate_knowledge_paths,
)
from hongzhao.index import build_memory_index, health_for
from hongzhao.render import COMPILE_DIFF_PATH, compile_all


def resolve_root(explicit: str | None) -> Path:
    try:
        root, _source = rootmod.discover_root(explicit)
    except rootmod.RootError as exc:
        print(f"[{exc.code}] {exc}", file=sys.stderr)
        raise SystemExit(2)
    return root


def cmd_validate(root: Path, verbose: bool = False) -> int:
    registry, registry_issues = load_registry(root)
    knowledge, knowledge_issues = load_knowledge_registry(root)
    knowledge_issues.extend(validate_knowledge_paths(root, knowledge))
    contracts, contract_issues = load_contracts(root, registry)
    memory_index, issues, _ = build_memory_index(root, project_keys_by_id(contracts))
    issues.extend(registry_issues)
    issues.extend(contract_issues)
    issues.extend(knowledge_issues)
    health = health_for(issues, memory_index.get("counts", {}))
    for issue in issues:
        print(issue.format())
    if verbose:
        print(f"# records={memory_index.get('counts', {}).get('total', '?')} health={health}")
    print(f"validation: {health}")
    return 1 if health == "degraded" else 0


def cmd_compile(root: Path, dry_run: bool = False) -> int:
    config = load_config(root)
    if dry_run:
        # 只读预演：打印将重建的产物清单，不做任何写入（语言变换不落盘）
        print("dry-run: would rebuild:")
        for key in ("memory_index", "current_state", "corrections", "bootstrap", "knowledge_map"):
            print(f"  {root / config['paths'][key]}")
        print(f"  {root / COMPILE_DIFF_PATH}")
        print(f"  {root / 'compiled' / 'effective-memory'}" + "/")
        return 0
    code, issues = compile_all(root)
    generated = load_yaml(root / config["paths"]["memory_index"])
    print(f"compiled: {generated.get('health', 'degraded')}")
    for issue in issues:
        print(issue.format())
    return code


def cmd_render(root: Path, dry_run: bool = False) -> int:
    return cmd_compile(root, dry_run=dry_run)


def cmd_upgrade(root: Path) -> int:
    """升级序列（docs/UPGRADE.md）：validate → skills-install → compile → bridge-install → doctor。

    每步复用既有命令的退出码语义；任一步非零即停（不硬闯），修复后重跑本命令即可续走。
    """
    steps = [
        ("validate", lambda: cmd_validate(root)),
        ("skills-install all", lambda: bridgemod.cmd_skills_install(root, "all")),
        ("compile", lambda: cmd_compile(root)),
        ("bridge-install all", lambda: bridgemod.cmd_bridge_install(root, "all")),
        ("doctor", lambda: bridgemod.cmd_doctor(root)),
    ]
    for i, (name, run) in enumerate(steps, 1):
        print(f"upgrade [{i}/{len(steps)}] {name}")
        code = run()
        if code != 0:
            print(f"upgrade: stopped at step {i} ({name}), exit {code}; "
                  "fix the issue above, then re-run `hongzhao upgrade`", file=sys.stderr)
            return code
    print(f"upgrade: ok (engine {__version__})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hongzhao",
        description="A file-based, human-gated memory ledger for AI coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--root", default=None, help="memory root (default: four-source discovery, see `hongzhao root`)")
    parser.add_argument("--dry-run", action="store_true", help="read-only preview: print planned actions, write nothing")
    parser.add_argument("--json", action="store_true", help="machine-readable output (root)")
    parser.add_argument("--verbose", action="store_true", help="print each step")
    sub = parser.add_subparsers(dest="command")
    init_cmd = sub.add_parser("init", help="scaffold a new memory kit")
    init_cmd.add_argument("path", nargs="?", default=None, help="target path (default ~/hongzhao)")
    init_cmd.add_argument("--client", action="append", dest="clients", help="client to enable if detected (repeatable)")
    init_cmd.add_argument("--example", action="store_true", help="seed a green demo kit")
    init_cmd.add_argument("--force", action="store_true", help="only fill missing files in an existing hongzhao root")
    sub.add_parser("validate", help="validate the memory kit")
    sub.add_parser("compile", help="rebuild derived outputs")
    sub.add_parser("render", help="alias of compile")
    root_cmd = sub.add_parser("root", help="show the discovered memory root and its source")
    root_cmd.add_argument("--json", dest="root_json", action="store_true", help="machine-readable output")
    bridge_cmd = sub.add_parser("bridge-install", help="install/refresh managed blocks")
    bridge_cmd.add_argument("client", help="client name or all")
    sub.add_parser("migrate-bridge", help="migrate legacy agent-memory blocks (all clients)")
    skills_cmd = sub.add_parser("skills-install", help="sync package skills/templates then link to clients")
    skills_cmd.add_argument("client", help="client name or all")
    skills_cmd.add_argument("--force", action="store_true", help="overwrite conflicts")
    skills_cmd.add_argument("--manifest-only", dest="manifest_only", action="store_true", help="write manifest only; no skill overwrite, no symlinks")
    uninstall_cmd = sub.add_parser("uninstall", help="remove managed blocks and root/skills symlinks (dry-run by default)")
    uninstall_cmd.add_argument("--yes", dest="uninstall_yes", action="store_true", help="execute the plan")
    sub.add_parser("doctor", help="health check with severity levels")
    sub.add_parser("upgrade", help="full upgrade sequence: validate, skills-install, compile, bridge-install, doctor")
    collect_cmd = sub.add_parser(
        "collect", help="collect client auto-memory: read-only pending manifest; --apply executes a decision file")
    collect_cmd.add_argument("--apply", dest="apply_file", metavar="DECISION_FILE",
                             help="apply a decision file: write raw + ledger + conditional source delete")
    collect_cmd.add_argument("--client", default="zcode", help="client source (v1: zcode)")
    collect_cmd.add_argument("--source-dir", dest="source_dir", help="override client source root path")
    collect_cmd.add_argument("--out", help="write the manifest to this path (default: stdout)")
    collect_cmd.add_argument("--pool", action="append", dest="pool",
                             help="filter the manifest to this pool directory (repeatable)")
    collect_cmd.add_argument("--dry-run", dest="collect_dry_run", action="store_true",
                             help="read-only preview (same as the global --dry-run; accepted after the subcommand)")
    reg_cmd = sub.add_parser("project-register", help="register a project (contract lifecycle J1-J6; legacy proj-<UUID> alias supported)")
    reg_cmd.add_argument("target", help="project root path, or legacy proj-<UUID> with --kind/--path")
    reg_cmd.add_argument("--key")
    reg_cmd.add_argument("--name")
    reg_cmd.add_argument("--purpose")
    reg_cmd.add_argument("--current-state", dest="current_state")
    reg_cmd.add_argument("--next-action", dest="next_action")
    reg_cmd.add_argument("--status")
    reg_cmd.add_argument("--activation")
    reg_cmd.add_argument("--entrypoint", action="append", dest="entrypoints")
    reg_cmd.add_argument("--yes", action="store_true", help="confirm orphan claim (J4)")
    reg_cmd.add_argument("--kind", choices=["vault", "external"], help="legacy signature only")
    reg_cmd.add_argument("--path", help="legacy signature only")
    unreg_cmd = sub.add_parser("project-unregister", help="remove registry entry (+central unless kept); dry-run by default")
    unreg_cmd.add_argument("target", help="project path | proj-id | key")
    unreg_cmd.add_argument("--yes", action="store_true")
    unreg_cmd.add_argument("--keep-contract", dest="keep_contract", action="store_true")
    unreg_cmd.add_argument("--delete-project-contract", dest="delete_project_contract", action="store_true")
    check_cmd = sub.add_parser("project-check", help="locate a project contract (central first, then project root)")
    check_cmd.add_argument("target", help="proj-id | key | path")
    know_cmd = sub.add_parser("knowledge-register", help="register a knowledge entry (base = knowledge_root)")
    know_cmd.add_argument("path", help="path relative to the knowledge root")
    know_cmd.add_argument("--title", required=True)
    know_cmd.add_argument("--topic", action="append", dest="topics", required=True)
    know_cmd.add_argument("--summary", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows 重定向管道默认 locale 编码（cp1252）编不了 CJK；collect 清单首次把用户内容
    # （标题/正文）打到 stdout，CI windows 腿即崩（charmap codec）。CLI 统一强制 UTF-8。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    args = build_parser().parse_args(argv)
    if not args.command:
        build_parser().print_help()
        return 0
    if args.command == "root":
        sub_json = getattr(args, "root_json", False) or args.json
        return rootmod.cmd_root(json_output=sub_json, explicit=args.root)
    if args.command == "init":
        from hongzhao import scaffold
        return scaffold.cmd_init(args.path, args.clients or [], args.example, args.force)
    if args.command in ("project-register", "project-unregister", "project-check", "knowledge-register"):
        try:
            root = resolve_root(args.root)
            if args.command == "project-register":
                payload = {k: getattr(args, k, None) for k in
                           ("key", "name", "purpose", "current_state", "next_action", "status",
                            "activation", "entrypoints", "yes", "kind", "path")}
                return contractsmod.cmd_register(root, args.target, payload, dry_run=getattr(args, "dry_run", False))
            if args.command == "project-unregister":
                return contractsmod.cmd_unregister(root, args.target, yes=args.yes,
                                                   keep_contract=args.keep_contract,
                                                   delete_project_contract=args.delete_project_contract)
            if args.command == "project-check":
                return contractsmod.cmd_project_check(root, args.target)
            return contractsmod.cmd_knowledge_register(root, args.path, args.title, args.topics or [], args.summary)
        except (ValueError, yaml.YAMLError, FileNotFoundError, OSError) as exc:
            print(f"fatal: {exc}", file=sys.stderr)
            return 2
    if args.command in ("bridge-install", "migrate-bridge", "skills-install", "uninstall", "doctor", "upgrade"):
        try:
            root = resolve_root(args.root)
            if args.command == "upgrade":
                return cmd_upgrade(root)
            if args.command == "bridge-install":
                return bridgemod.cmd_bridge_install(root, args.client)
            if args.command == "migrate-bridge":
                return bridgemod.cmd_migrate_bridge(root)
            if args.command == "skills-install":
                return bridgemod.cmd_skills_install(root, args.client, force=args.force, manifest_only=args.manifest_only)
            if args.command == "uninstall":
                return bridgemod.cmd_uninstall(root, yes=args.uninstall_yes)
            return bridgemod.cmd_doctor(root)
        except (ValueError, FileNotFoundError, OSError) as exc:
            print(f"fatal: {exc}", file=sys.stderr)
            return 2
    try:
        root = resolve_root(args.root)
        if args.command == "collect":
            from hongzhao import collect as collectmod
            from hongzhao.collect import CollectError
            dry = args.dry_run or getattr(args, "collect_dry_run", False)
            try:
                if args.apply_file:
                    return collectmod.cmd_apply(root, args.apply_file, client=args.client,
                                                source_dir=args.source_dir, dry_run=dry)
                return collectmod.cmd_collect(root, client=args.client, source_dir=args.source_dir,
                                              out_path=args.out, dry_run=dry, pools=args.pool)
            except CollectError as exc:
                print(f"[{exc.code}] {exc.message}", file=sys.stderr)
                return exc.exit_code
        if args.command == "validate":
            return cmd_validate(root, verbose=args.verbose)
        if args.command in ("compile", "render"):
            return cmd_compile(root, dry_run=args.dry_run)
    except (ValueError, yaml.YAMLError, FileNotFoundError, OSError) as exc:
        # 与旧引擎一致的 fatal 兜底：坏 config/坏数据不吐 traceback，exit 2
        print(f"fatal: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
