"""契约生命周期////。

三层发现集：A=central（`projects/*/project-view.md`，空目录不算）；B=已登记项目根契约；
C=参数路径契约。写入不变式 – 在判定前统一校验，失败零写入。判定 J1→J6 按优先级
命中即停（16 行状态对照表见设计 ）。两阶段：锁外只读预判（K 计算、必填收集、字段
校验）；锁内重新判定并执行（flock 绑定记忆根 `<root>/.hongzhao.lock`，交互/字段收集
在锁外）。写序 registry → 契约：崩溃重试命中 J3 沿用 registry 的 id 补建。
故障注入：HONGZHAO_TEST=1 且 HONGZHAO_FAULT=<point> 双条件生效。
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

from hongzhao.core import load_config, load_registry, resolve_knowledge_root, write_atomic
from hongzhao.locking import exclusive_lock
from hongzhao import fields as _fields

PROJECT_VIEW = "project-view.md"
ID_SHAPE = re.compile(r"^proj-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
REQUIRED_NEW = ("purpose", "current_state", "next_action")
FAULTS = {"after-registry-write", "mid-contract-write", "contract-write", "after-registry-delete"}


class ContractError(Exception):
    """业务失败：code 进输出，exit_code 随 code。零写入由调用方保证（失败路径不落盘）。"""

    def __init__(self, code: str, message: str, exit_code: int = 1):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


def _today() -> str:
    return dt.date.today().isoformat()


def _fault_active(point: str) -> bool:
    return os.environ.get("HONGZHAO_TEST") == "1" and os.environ.get("HONGZHAO_FAULT") == point


def _crash(point: str) -> None:
    """硬崩溃注入点：模拟进程终止（锁由 OS 释放；磁盘保持崩溃时点的状态）。"""
    print(f"fault-injection: crashing at {point}", file=sys.stderr)
    sys.stderr.flush()
    os._exit(70)


# ---------------------------------------------------------------------------
# 锁（绑定记忆根；判定 + 读改写 + 写入同临界区）
# ---------------------------------------------------------------------------


@contextmanager
def registry_lock(root: Path, timeout: float = 10.0):
    # W1：锁实现移交 locking.exclusive_lock（平台分支 + 完整失败语义），本包装保持调用点签名不变
    with exclusive_lock(root / ".hongzhao.lock", timeout):
        yield


# ---------------------------------------------------------------------------
# registry 读写（落盘 schema 2 冻结；write_atomic）
# ---------------------------------------------------------------------------


def read_entries(root: Path) -> list[dict[str, Any]]:
    data, _issues = load_registry(root)
    return list((data or {}).get("projects", []) or [])


def write_entries(root: Path, entries: list[dict[str, Any]]) -> None:
    payload = {"schema_version": 2, "projects": entries}
    write_atomic(root / "registry" / "project-registry.yaml", yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))


def entry_location_path(root: Path, entry: dict[str, Any]) -> Path:
    loc = entry.get("location", {})
    kind, value = loc.get("kind"), loc.get("path", "")
    if kind == "external":
        return Path(os.path.expanduser(str(value))).resolve()
    return (root / str(value)).resolve()


def _entry_for(entries: list[dict[str, Any]], root: Path, target: Path) -> dict[str, Any] | None:
    for entry in entries:
        if entry_location_path(root, entry) == target.resolve():
            return entry
    return None


# ---------------------------------------------------------------------------
# 三层发现集
# ---------------------------------------------------------------------------


def _read_meta(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    try:
        meta = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError:
        return None
    return meta if isinstance(meta, dict) else None


def central_contracts(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """集 A：`projects/*/project-view.md`（空目录自然不命中——空目录不算集 A）。"""
    result = []
    for path in sorted((root / "projects").glob(f"*/{PROJECT_VIEW}")):
        meta = _read_meta(path)
        if meta is not None:
            result.append((path, meta))
    return result


def registered_root_contracts(root: Path, entries: list[dict[str, Any]]) -> list[tuple[Path, dict[str, Any], dict[str, Any]]]:
    """集 B：已登记项目的项目根契约（(路径, meta, registry条目)）。"""
    result = []
    for entry in entries:
        location = entry_location_path(root, entry) / PROJECT_VIEW
        if location.is_file():
            meta = _read_meta(location)
            if meta is not None:
                result.append((location, meta, entry))
    return result


def slugify(name: str) -> str | None:
    """目录名 → project_key 候选；非 ASCII 全被剥离后为空 → None（需显式 --key）。"""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or None


def compute_k(key_flag: str | None, param_dir: Path) -> str | None:
    if key_flag:
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", key_flag):
            raise ContractError("FIELD_INVALID", f"--key must be lowercase letters/digits/hyphens: {key_flag}")
        return key_flag
    return slugify(param_dir.name)


def check_field_values(values: dict[str, str]) -> None:
    for name, value in values.items():
        for message, code in _fields.check_fields({name: value}, (name,), "register"):
            raise ContractError(code, message)


# ---------------------------------------------------------------------------
# J 判定（纯读；锁内锁外共用）
# ---------------------------------------------------------------------------


class Judgment:
    def __init__(self, name: str, **facts: Any):
        self.name = name
        self.facts = facts


def judge(root: Path, param: Path, key_flag: str | None) -> tuple[Judgment, dict[str, Any]]:
    """返回 (判定, 共享事实)。失败以 ContractError 抛出（零写入）。"""
    entries = read_entries(root)
    param = param.resolve()
    contract_path = param / PROJECT_VIEW
    contract_meta = _read_meta(contract_path) if contract_path.is_file() else None

    registered_ids = {str(e.get("project_id")) for e in entries}
    entry_for_param = _entry_for(entries, root, param)
    centrals = central_contracts(root)
    central_by_id = {str(m.get("project_id")): (p, m) for p, m in centrals}
    central_by_key: dict[str, tuple[Path, dict[str, Any]]] = {}
    for p, m in centrals:
        central_by_key.setdefault(str(m.get("project_key")), (p, m))
    b_contracts = registered_root_contracts(root, entries)

    facts: dict[str, Any] = {
        "entries": entries,
        "entry_for_param": entry_for_param,
        "contract_meta": contract_meta,
        "centrals": centrals,
        "central_by_id": central_by_id,
        "central_by_key": central_by_key,
        "b_contracts": b_contracts,
    }

    def b_key_owner(key: str, exclude_path: Path | None = None) -> dict[str, Any] | None:
        for _p, m, e in b_contracts:
            if exclude_path is not None and entry_location_path(root, e) == exclude_path:
                continue
            if str(m.get("project_key")) == key:
                return e
        return None

    # J1：参数路径下有契约（集 C）
    if contract_meta is not None:
        x_id = str(contract_meta.get("project_id"))
        x_key = str(contract_meta.get("project_key"))
        if not ID_SHAPE.fullmatch(x_id or ""):
            raise ContractError("FIELD_INVALID", f"contract project_id malformed at param path: {x_id}")
        # d) 身份冲突：路径已登记为另一 id，或 X 已登记在另一路径
        if entry_for_param is not None and str(entry_for_param.get("project_id")) != x_id:
            raise ContractError("CONTRACT_DUPLICATE", f"path already registered to another id ({entry_for_param.get('project_id')})")
        for e in entries:
            if str(e.get("project_id")) == x_id and entry_location_path(root, e) != param:
                raise ContractError("CONTRACT_DUPLICATE", f"id {x_id} is already registered at another path (copied directory?)")
        # i) 集 A 已有同 id 的 central（同 id 两处）
        if x_id in central_by_id:
            raise ContractError("CONTRACT_DUPLICATE", f"id {x_id} also exists as a central contract ({central_by_id[x_id][0]})")
        # n) 另一已登记项目的项目根契约同 key 不同 id（集 B 扫描）
        owner = b_key_owner(x_key, exclude_path=param)
        if owner is not None and str(owner.get("project_id")) != x_id:
            raise ContractError("CONTRACT_KEY_DUPLICATE", f"key '{x_key}' already used by registered project {owner.get('project_id')}")
        # c) 集 A 中存在同 key 的 central 契约（id≠X）
        if x_key in central_by_key and str(central_by_key[x_key][1].get("project_id")) != x_id:
            raise ContractError("CONTRACT_KEY_DUPLICATE", f"key '{x_key}' already used by central {central_by_key[x_key][0].relative_to(root)}")
        # b) 传入 --key ≠ X.key
        if key_flag is not None and key_flag != x_key:
            raise ContractError("KEY_CONFLICT", f"--key '{key_flag}' does not match the contract key '{x_key}'")
        # a) 沿用 X 的身份登记/刷新
        return Judgment("J1", x_id=x_id, x_key=x_key, contract_path=contract_path), facts

    # J2/J3：无 C；该路径已登记
    if entry_for_param is not None:
        rid = str(entry_for_param.get("project_id"))
        if rid in central_by_id:
            central_path, central_meta = central_by_id[rid]
            central_key = str(central_meta.get("project_key"))
            if key_flag is not None and key_flag != central_key:
                raise ContractError("KEY_CONFLICT", f"--key '{key_flag}' does not match the central key '{central_key}'")
            return Judgment("J2", rid=rid, central_path=central_path, central_meta=central_meta), facts
        k = compute_k(key_flag, param)
        if k is None:
            raise ContractError("FIELD_INVALID", f"cannot derive a project key from directory name '{param.name}'; pass --key")
        # J3 占用检查：central K 已被他人（id≠I），或集 B 已用 K
        if k in central_by_key and str(central_by_key[k][1].get("project_id")) != rid:
            raise ContractError("KEY_CONFLICT", f"key '{k}' is taken by central {central_by_key[k][0].relative_to(root)}")
        owner = b_key_owner(k, exclude_path=param)
        if owner is not None and str(owner.get("project_id")) != rid:
            raise ContractError("KEY_CONFLICT", f"key '{k}' is taken by registered project {owner.get('project_id')}")
        return Judgment("J3", rid=rid, k=k), facts

    # J4/J5：无 C、未登记；集 A 有 key=K 的 central
    k = compute_k(key_flag, param)
    if k is not None and k in central_by_key:
        central_path, central_meta = central_by_key[k]
        orphan_id = str(central_meta.get("project_id"))
        if orphan_id in registered_ids:
            raise ContractError(
                "KEY_CONFLICT",
                f"key '{k}' belongs to central {central_path.relative_to(root)} whose id {orphan_id} is registered elsewhere",
            )
        # J4 认领：需 --key 且 --yes
        if key_flag is None:
            raise ContractError(
                "KEY_CONFLICT",
                f"an orphan central exists at key '{k}'; claim it with: project-register <path> --key {k} --yes",
            )
        owner = b_key_owner(k)
        if owner is not None:
            raise ContractError("KEY_CONFLICT", f"key '{k}' is taken by registered project {owner.get('project_id')}")
        return Judgment("J4", k=k, central_path=central_path, orphan_id=orphan_id), facts

    # J6：新建
    k = compute_k(key_flag, param)
    if k is None:
        raise ContractError("FIELD_INVALID", f"cannot derive a project key from directory name '{param.name}'; pass --key")
    owner = b_key_owner(k)
    if owner is not None:
        raise ContractError("KEY_CONFLICT", f"key '{k}' is taken by registered project {owner.get('project_id')}")
    return Judgment("J6", k=k), facts


# ---------------------------------------------------------------------------
# 契约写（central；frontmatter 字段来源表）
# ---------------------------------------------------------------------------


def _dump_contract(meta: dict[str, Any], body: str) -> str:
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + body


def _clean_residual(directory: Path) -> None:
    """接管残留：清掉 `.project-view.md.*` 临时文件（R7 P1）。"""
    if directory.is_dir():
        for stale in directory.glob(f".{PROJECT_VIEW}.*"):
            stale.unlink()


def _write_central(root: Path, k: str, meta: dict[str, Any], *, mid_crash_point: bool) -> None:
    directory = root / "projects" / k
    directory.mkdir(parents=True, exist_ok=True)
    if mid_crash_point and _fault_active("mid-contract-write"):
        _crash("mid-contract-write")  # mkdir 之后、replace 之前（R7 P1 注入点）
    target = directory / PROJECT_VIEW
    body = f"# {meta.get('project_name', k)}\n\nProject contract maintained by hongzhao.\n"
    if _fault_active("contract-write"):
        raise OSError("injected contract-write failure")
    write_atomic(target, _dump_contract(meta, body))


def _new_meta(project_id: str, k: str, args: dict[str, Any], param: Path) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "project_id": project_id,
        "project_key": k,
        "project_name": args.get("name") or param.name,
        "purpose": args["purpose"],
        "current_state": args["current_state"],
        "next_action": args["next_action"],
        "status": args.get("status") or "active",
        "activation": args.get("activation") or "on-demand",
        "entrypoints": list(args.get("entrypoints") or []),
        "updated_at": _today(),
    }


def _registry_entry(project_id: str, root: Path, param: Path) -> dict[str, Any]:
    from hongzhao.core import registry_kind_for

    kind, path_value = registry_kind_for(param, root)
    return {
        "project_id": project_id,
        "location": {"kind": kind, "path": path_value},
        "registered_at": _today(),
        "last_checked_at": _today(),
    }


def _refresh_last_checked(entry: dict[str, Any]) -> None:
    entry["last_checked_at"] = _today()


# ---------------------------------------------------------------------------
# project-register（新签名 +  旧签名别名）
# ---------------------------------------------------------------------------


def cmd_register(root: Path, target: str, args: dict[str, Any], dry_run: bool = False) -> int:
    try:
        # 旧签名别名：proj-<UUID> 形态位置参数 + --kind/--path
        if ID_SHAPE.fullmatch(target) and (args.get("kind") or args.get("path")):
            return _register_legacy(root, target, args)
        if args.get("kind") or args.get("path"):
            raise ContractError("FIELD_INVALID", "--kind/--path only apply to the legacy proj-<UUID> signature")

        param = Path(target).expanduser()
        if not param.is_dir():
            raise ContractError("PATH_INVALID", f"not a directory: {param}")
        param = param.resolve()
        provided = {k: args[k] for k in ("name", "purpose", "current_state", "next_action") if args.get(k)}
        check_field_values(provided)

        # 锁外只读预判：唯一职责=确定是否需要三必填（J3/J6）。预判读到撕裂状态
        # （注册表与中央契约非同一时刻——并发注册时可见「有契约无条目」的瞬时孤儿态）
        # 或瞬时冲突时，以锁内判定为权威：吸收异常、按需要三必填保守处理；
        # 真实冲突仍由锁内 judge 抛出（合同矩阵单进程行为不变）。
        try:
            pre, _facts = judge(root, param, args.get("key"))
            needs_fields = pre.name in {"J3", "J6"}
        except ContractError:
            pre = None
            needs_fields = True

        # 锁内：重新判定并执行）
        with registry_lock(root):
            decision, facts = judge(root, param, args.get("key"))
            if pre is not None and decision.name != pre.name and decision.name in {"J3", "J6"} and not needs_fields:
                print("[STATE_CHANGED] registry state changed while waiting; rerun with the required fields")
                return 1
            if decision.name in {"J3", "J6"}:
                missing = [f for f in REQUIRED_NEW if not args.get(f)]
                if missing:
                    raise ContractError("FIELD_INVALID", f"missing required fields for {decision.name}: {', '.join(missing)}")
            if dry_run:
                # 预览：预判已读、零写入（registry/契约/中央目录都不动）
                print(f"dry-run: {decision.name} for {param} (key={decision.facts.get('k')}); no files written")
                return 0

            entries: list[dict[str, Any]] = facts["entries"]

            if decision.name == "J1":
                entry = facts["entry_for_param"]
                if entry is None:
                    entries.append(_registry_entry(decision.facts["x_id"], root, param))
                    print(f"registered: {decision.facts['x_id']} (reused contract id, J1-a)")
                else:
                    _refresh_last_checked(entry)
                    print(f"registered: {decision.facts['x_id']} (last_checked_at refreshed, J1-a)")
                write_entries(root, entries)
                print("note: project-root contract untouched (maintained by memory-project-context)")
                return 0

            if decision.name == "J2":
                entry = facts["entry_for_param"]
                _refresh_last_checked(entry)
                write_entries(root, entries)  # registry 先写
                meta = dict(decision.facts["central_meta"])
                for field in ("name", "purpose", "current_state", "next_action", "status", "activation"):
                    if args.get(field):
                        meta["project_name" if field == "name" else field] = args[field]
                meta["updated_at"] = _today()
                try:
                    _write_central(
                        root,
                        str(meta.get("project_key")),
                        meta,
                        mid_crash_point=False,
                    )
                except OSError as exc:
                    print(f"[CONTRACT_WRITE_FAILED] {exc}; registry kept (last_checked_at only), contract unchanged", file=sys.stderr)
                    return 2
                print(f"updated central: {decision.facts['central_path'].relative_to(root)} (J2)")
                return 0

            if decision.name == "J3":
                entry = facts["entry_for_param"]
                _refresh_last_checked(entry)
                write_entries(root, entries)  # registry 先写；崩溃语义=停在「已登记、契约缺失」
                if _fault_active("after-registry-write"):
                    _crash("after-registry-write")
                meta = _new_meta(str(entry.get("project_id")), decision.facts["k"], args, param)
                _clean_residual(root / "projects" / decision.facts["k"])
                try:
                    _write_central(root, decision.facts["k"], meta, mid_crash_point=True)
                except OSError as exc:
                    print(f"[CONTRACT_WRITE_FAILED] {exc}; registry kept, retry will rebuild (J3)", file=sys.stderr)
                    return 2
                source = "--key" if args.get("key") else "directory slug"
                print(f"rebuilt central: projects/{decision.facts['k']} (id {entry.get('project_id')} reused, J3; key from {source})")
                return 0

            if decision.name == "J4":
                entries.append(_registry_entry(decision.facts["orphan_id"], root, param))
                write_entries(root, entries)
                print(f"claimed orphan central: {decision.facts['central_path'].relative_to(root)} (id {decision.facts['orphan_id']}, J4)")
                return 0

            # J6：先写 registry，再写契约
            new_id = f"proj-{uuid.uuid4()}"
            entry = _registry_entry(new_id, root, param)
            entries.append(entry)
            write_entries(root, entries)
            if _fault_active("after-registry-write"):
                _crash("after-registry-write")
            meta = _new_meta(new_id, decision.facts["k"], args, param)
            _clean_residual(root / "projects" / decision.facts["k"])
            try:
                _write_central(root, decision.facts["k"], meta, mid_crash_point=True)
            except OSError:
                # 回滚：删除刚加的 registry 条目 + 清理目录与临时文件（不留空目录）
                entries.pop()
                write_entries(root, entries)
                directory = root / "projects" / decision.facts["k"]
                for stale in list(directory.glob(f".{PROJECT_VIEW}.*")) + list(directory.glob(PROJECT_VIEW)):
                    stale.unlink()
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()
                print("[CONTRACT_WRITE_FAILED] contract write failed; registry entry rolled back, no residue", file=sys.stderr)
                return 2
            source = "--key" if args.get("key") else "directory slug"
            print(f"registered new project: {new_id} at projects/{decision.facts['k']} (J6; key from {source})")
            return 0
    except ContractError as exc:
        print(f"[{exc.code}] {exc.message}", file=sys.stderr)
        return exc.exit_code


def _register_legacy(root: Path, project_id: str, args: dict[str, Any]) -> int:
    """ 旧签名：registry-only upsert；不写不改契约； 同样执行（R6 M1）。"""
    kind = args.get("kind")
    path_value = args.get("path")
    if kind not in {"vault", "external"}:
        print(f"[FIELD_INVALID] --kind must be vault or external, got: {kind}", file=sys.stderr)
        return 1
    if not path_value:
        print("[FIELD_INVALID] legacy signature requires --path", file=sys.stderr)
        return 1
    if kind == "external" and not Path(os.path.expanduser(path_value)).is_absolute():
        print("[FIELD_INVALID] external --path must be absolute", file=sys.stderr)
        return 1
    with registry_lock(root):
        entries = read_entries(root)
        resolved = entry_location_path(root, {"location": {"kind": kind, "path": path_value}})
        for entry in entries:
            if entry_location_path(root, entry) == resolved and str(entry.get("project_id")) != project_id:
                print(f"[CONTRACT_DUPLICATE] path already registered to {entry.get('project_id')}", file=sys.stderr)
                return 1
        existing = next((e for e in entries if str(e.get("project_id")) == project_id), None)
        if existing is None:
            entries.append({
                "project_id": project_id,
                "location": {"kind": kind, "path": path_value},
                "registered_at": _today(),
                "last_checked_at": _today(),
            })
        else:
            _refresh_last_checked(existing)
        write_entries(root, entries)
    print(f"deprecated: use the new signature — hongzhao project-register <project-root> [--key k]")
    print(f"registry upsert done for {project_id} ({kind}); no contract files were read or written")
    return 0


# ---------------------------------------------------------------------------
# project-unregister（ 七例）
# ---------------------------------------------------------------------------


def _find_entry(root: Path, entries: list[dict[str, Any]], target: str) -> tuple[dict[str, Any] | None, Path | None, str]:
    """target 为路径 / proj-id / key 三态。返回 (条目, central路径, 形态)。"""
    candidate = Path(target).expanduser()
    if ID_SHAPE.fullmatch(target):
        for entry in entries:
            if str(entry.get("project_id")) == target:
                return entry, None, "id"
        return None, None, "id"
    if candidate.is_dir():
        return _entry_for(entries, root, candidate), None, "path"
    # key：central 目录名
    central = root / "projects" / target / PROJECT_VIEW
    if central.is_file():
        return None, central, "key"
    if candidate.exists():
        return _entry_for(entries, root, candidate), None, "path"
    return None, None, "unknown"


def cmd_unregister(root: Path, target: str, yes: bool, keep_contract: bool, delete_project_contract: bool) -> int:
    if keep_contract and delete_project_contract:
        print("[INVALID_FLAG_COMBINATION] --keep-contract and --delete-project-contract are mutually exclusive", file=sys.stderr)
        return 1
    try:
        with registry_lock(root):
            entries = read_entries(root)
            entry, central_by_key, form = _find_entry(root, entries, target)

            if form == "unknown":
                print(f"[PATH_INVALID] cannot resolve target: {target}", file=sys.stderr)
                return 1

            # key 形态：orphan（无 registry 条目）→ 仅 registry 侧语义，打印 orphan 路径
            if entry is None and central_by_key is not None:
                if not yes:
                    print(f"dry-run: would report orphan central {central_by_key.resolve()} (registry-side only)")
                    return 0
                print(f"orphan central remains: {central_by_key.resolve()}")
                print("cleanup: hongzhao project-unregister <key> removes nothing on the registry side; central kept")
                return 0
            if entry is None:
                print(f"[PATH_INVALID] no registry entry for: {target}", file=sys.stderr)
                return 1

            location = entry_location_path(root, entry)
            project_root_contract = location / PROJECT_VIEW
            entry_id = str(entry.get("project_id"))
            central_for_entry: Path | None = None
            for path, meta in central_contracts(root):
                if str(meta.get("project_id")) == entry_id:
                    central_for_entry = path
                    break

            if not yes:
                plan = [f"delete registry entry {entry_id}"]
                if keep_contract:
                    plan.append("keep central contract (will become CONTRACT_ORPHAN)")
                elif central_for_entry is not None:
                    plan.append(f"delete central {central_for_entry.relative_to(root)}")
                if delete_project_contract:
                    plan.append(f"delete project-root contract {project_root_contract}")
                print("dry-run (pass --yes to execute):")
                for line in plan:
                    print(f"  {line}")
                return 0

            # 写序：先删 registry 条目、再删 central（v3.4 与  同向）
            entries = [e for e in entries if e is not entry]
            write_entries(root, entries)
            if _fault_active("after-registry-delete"):
                _crash("after-registry-delete")

            if keep_contract and central_for_entry is not None:
                print(f"registry entry {entry_id} deleted; central kept")
                print(f"[CONTRACT_ORPHAN] upcoming: {central_for_entry.relative_to(root)}")
                print(f"cleanup: hongzhao project-unregister {central_for_entry.parent.name}  (or claim via project-register <path> --key {central_for_entry.parent.name} --yes)")
                return 0

            if delete_project_contract:
                if project_root_contract.is_file():
                    project_root_contract.unlink()
                    print(f"project-root contract deleted: {project_root_contract.resolve()}")
                print(f"registry entry {entry_id} deleted")
                return 0

            if central_for_entry is not None:
                central_for_entry.unlink()
                if central_for_entry.parent.is_dir() and not any(central_for_entry.parent.iterdir()):
                    central_for_entry.parent.rmdir()
                print(f"registry entry {entry_id} deleted; central deleted: {central_for_entry.relative_to(root)}")
                return 0

            # 项目根形态：契约永不删除，打印残留路径
            if project_root_contract.is_file():
                print(f"registry entry {entry_id} deleted")
                print(f"residual project-root contract (never deleted by default): {project_root_contract.resolve()}")
            else:
                print(f"registry entry {entry_id} deleted")
            return 0
    except ContractError as exc:
        print(f"[{exc.code}] {exc.message}", file=sys.stderr)
        return exc.exit_code


# ---------------------------------------------------------------------------
# project-check（查找序 central → 项目根）
# ---------------------------------------------------------------------------


def cmd_project_check(root: Path, target: str) -> int:
    entries = read_entries(root)
    entry, central_by_key, form = _find_entry(root, entries, target)
    if form == "key" and central_by_key is not None:
        meta = _read_meta(central_by_key)
        print(f"contract: {central_by_key.resolve()} (central, key form)")
        print(f"project_id: {meta.get('project_id') if meta else '?'}")
        return 0
    if entry is None:
        print(f"[PATH_INVALID] no registered project for: {target}", file=sys.stderr)
        return 1
    entry_id = str(entry.get("project_id"))
    for path, meta in central_contracts(root):
        if str(meta.get("project_id")) == entry_id:
            print(f"contract: {path.resolve()} (central)")
            print(f"project_id: {entry_id}; key: {meta.get('project_key')}")
            return 0
    location = entry_location_path(root, entry) / PROJECT_VIEW
    if location.is_file():
        print(f"contract: {location.resolve()} (project root)")
        print(f"project_id: {entry_id}")
        return 0
    print(f"[CONTRACT_MISSING] no contract found for {entry_id}; fix: hongzhao project-register <project-root>", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# knowledge-register（基=knowledge_root；成功后编译并经统一入口刷新 inline 客户端）
# ---------------------------------------------------------------------------


def cmd_knowledge_register(root: Path, path_value: str, title: str, topics: list[str], summary: str) -> int:
    try:
        base = resolve_knowledge_root(root)
        rel = Path(path_value)
        if rel.is_absolute() or ".." in rel.parts:
            raise ContractError("KNOWLEDGE_SCHEMA", f"path must be relative to the knowledge root without '..': {path_value}")
        target = (base / rel).resolve()
        if not target.is_relative_to(base):
            raise ContractError("KNOWLEDGE_SCHEMA", f"path escapes the knowledge root: {path_value}")
        if not target.exists():
            raise ContractError("KNOWLEDGE_SCHEMA", f"knowledge path does not exist: {target}")
        entry = {"path": rel.as_posix(), "title": title, "topics": list(topics), "summary": summary,
                 "registered_at": _today(), "last_checked_at": _today()}
        for message, code in _fields.check_knowledge_entry(entry, "knowledge-register"):
            raise ContractError(code, message)
        with registry_lock(root):
            registry_path = root / "registry" / "knowledge-registry.yaml"
            data = {}
            if registry_path.is_file():
                data = __import__("hongzhao.core", fromlist=["load_yaml"]).load_yaml(registry_path) or {}
            knowledge = [e for e in (data.get("knowledge") or []) if isinstance(e, dict) and e.get("path") != entry["path"]]
            knowledge.append(entry)
            write_atomic(registry_path, yaml.safe_dump({"schema_version": 2, "knowledge": knowledge}, sort_keys=False, allow_unicode=True))
        print(f"knowledge registered: {entry['path']} ({len(knowledge)} entries)")
        # 自动重建派生文件，再经统一入口刷新启用的 inline 客户端）
        from hongzhao.render import compile_all

        compile_all(root)
        config = load_config(root)
        from hongzhao import bridge

        for name, settings in config.get("clients", {}).items():
            if settings.get("enabled") and settings.get("mode") == "inline":
                bridge.install_bridge_checked(root, name, settings, explicit=False)
        print("note: derived outputs rebuilt; inline clients refreshed via bridge-install")
        return 0
    except ContractError as exc:
        print(f"[{exc.code}] {exc.message}", file=sys.stderr)
        return exc.exit_code


# ---------------------------------------------------------------------------
# 读取侧扫描（供 doctor/validate 使用的契约状态诊断）
# ---------------------------------------------------------------------------


def contract_state_issues(root: Path, registry: dict[str, Any]) -> list[tuple[str, str, str]]:
    """返回 [(code, message, path)]：CONTRACT_MISSING / CONTRACT_ORPHAN /
    CONTRACT_DUPLICATE / CONTRACT_KEY_DUPLICATE / CONTRACT_KEY_MISMATCH。"""
    entries = list((registry or {}).get("projects", []) or [])
    issues: list[tuple[str, str, str]] = []
    registered_ids = {str(e.get("project_id")) for e in entries}
    centrals = central_contracts(root)
    central_by_id: dict[str, Path] = {}
    seen_key_owner: dict[str, tuple[str, Path]] = {}
    for path, meta in centrals:
        cid = str(meta.get("project_id"))
        ckey = str(meta.get("project_key"))
        if cid in central_by_id:
            issues.append(("CONTRACT_DUPLICATE", f"central id {cid} appears more than once", str(path)))
        else:
            central_by_id[cid] = path
        if path.parent.name != ckey:
            issues.append(("CONTRACT_KEY_MISMATCH", f"directory name {path.parent.name} != project_key {ckey}", str(path)))
        if ckey in seen_key_owner and seen_key_owner[ckey][0] != cid:
            issues.append(("CONTRACT_KEY_DUPLICATE", f"key '{ckey}' used by ids {seen_key_owner[ckey][0]} and {cid}", str(path)))
        else:
            seen_key_owner[ckey] = (cid, path)
    for path, meta in centrals:
        cid = str(meta.get("project_id"))
        if cid not in registered_ids:
            issues.append(("CONTRACT_ORPHAN", f"central {path.relative_to(root)} has no registry entry", str(path)))
    root_keys: dict[str, str] = {}
    for path, meta, entry in registered_root_contracts(root, entries):
        rid = str(entry.get("project_id"))
        cid = str(meta.get("project_id"))
        if cid != rid:
            issues.append(("CONTRACT_DUPLICATE", f"registered {rid} but project-root contract says {cid}", str(path)))
        rkey = str(meta.get("project_key"))
        if rkey in root_keys and root_keys[rkey] != rid:
            issues.append(("CONTRACT_KEY_DUPLICATE", f"key '{rkey}' used by registered ids {root_keys[rkey]} and {rid}", str(path)))
        root_keys[rkey] = rid
        if rid in central_by_id:
            issues.append(("CONTRACT_DUPLICATE", f"id {rid} exists both as central and project-root contract", str(path)))
    for entry in entries:
        eid = str(entry.get("project_id"))
        location = entry_location_path(root, entry) / PROJECT_VIEW
        if eid not in central_by_id and not location.is_file():
            issues.append(("CONTRACT_MISSING", f"registered {eid} has no contract (J3 can rebuild)", str(location)))
    return issues
