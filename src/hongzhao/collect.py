"""客户端记忆采集（design：.delivery/2026-11-13-客户端记忆采集/design.md v6，已确认）。

collect                只读：解析客户端 auto-memory 池 → 账本 diff → 增量清单（manifest）
collect --apply <f>    决策落盘：校验 decision file → 写 raw → 记账 → auto-commit

引擎纪律（D-C04/D-C11/D-C28）：
- 纯确定性，零语义判断（判重/重要性归 skill 的模型环节，终审归人）；
- **严格只读采集：对客户端侧零写能力**——不删事实文件、不动 MEMORY.md、不剪目录，
  亦不存在任何开启这些行为的选项（D-C12/D-C16/D-C18 写侧/D-C22/D-C23 已被 D-C28 取代）；
- apply 写面只有：raw 文件、三态账本、kit auto-commit（均在 hongzhao 记忆根内）；
- 全程持 .hongzhao.lock（校验序与写序同临界区，D-C14）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import yaml

from hongzhao.core import (
    ACTIVATIONS,
    KINDS,
    dump_frontmatter,
    load_config,
    load_registry,
    parse_frontmatter,
    validate_raw,
    write_atomic,
)
from hongzhao.gitauto import auto_commit_with_message
from hongzhao.locking import exclusive_lock

# 客户端源表（v5/D-C27：采集与调用方绑定，先支持 zcode + claude_code；文件格式实测逐字段同构，
# 差异仅池根与池目录命名——CC 为项目路径 slug）；--source-dir 可覆盖该客户端默认源
CLIENT_SOURCE_DEFAULTS = {
    "zcode": "~/.zcode/cli/memories/projects",
    "claude_code": "~/.claude/projects",
}
LEDGER_SCHEMA = 1
TOPIC_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
INDEX_LINE = re.compile(r"^- \[(?P<title>.*)\]\((?P<file>[^\)]+)\) — (?P<hook>.*)$")
# v6/D-C28：删源类注入点随写路径一并移除，只剩 raw/账本两个落盘边界
FAULTS = {"after-raws", "after-ledger"}
# v6/D-C28：这些 decision 字段已被移除——出现即拒绝（零写能力不是选项）
REMOVED_DECISION_FIELDS = {"delete_source", "slim_index", "cleanup", "prune_empty_pools"}


class CollectError(Exception):
    """环境/致命错误：code 进输出，exit_code 随 code（条目级失败不抛，走返回报告）。"""

    def __init__(self, code: str, message: str, exit_code: int = 2):
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


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# 源解析（D-C17：解析失败只报不猜；D-C27：只认含 memory/ 的目录为记忆池）
# ---------------------------------------------------------------------------


def _parse_memory_index(text: str) -> dict[str, tuple[str, str]]:
    """索引行 file → (title, hook)。同文件重复行取首行（只读解析，不修改任何内容）。"""
    index: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        matched = INDEX_LINE.match(line.strip())
        if not matched:
            continue  # 容忍 # 标题头、空行与其他形态
        target = matched.group("file")
        if target not in index:
            index[target] = (matched.group("title"), matched.group("hook"))
    return index


def scan_source(source_dir: Path) -> dict[str, Any]:
    """扫描源根（纯读）：{entries, index_map, dangling_index, unparsable, empty_pools, pool_files}。

    entries: key("<pool>/memory/<file>") → 条目 dict（hash/name/title/hook/type/description/body/…）
    empty_pools / dangling_index：只读报告，本功能不治理（客户端侧零写，D-C28）。
    """
    entries: dict[str, dict[str, Any]] = {}
    index_map: dict[str, dict[str, tuple[str, str]]] = {}
    dangling: list[dict[str, str]] = []
    unparsable: list[dict[str, str]] = []
    empty_pools: list[str] = []
    pool_files: dict[str, list[str]] = {}

    for pool_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
        pool = pool_dir.name
        memory = pool_dir / "memory"
        if not memory.is_dir():
            # v5/D-C27：不含 memory/ 的一级目录不是记忆池（CC projects/ 下的普通项目目录），整目录忽略
            continue
        fact_paths = sorted(
            p for p in memory.glob("*.md")
            if p.name != "MEMORY.md" and not p.name.startswith((".", "_"))
        )
        pool_files[pool] = [p.name for p in fact_paths]
        index: dict[str, tuple[str, str]] = {}
        memory_md = memory / "MEMORY.md"
        if memory_md.is_file():
            try:
                index = _parse_memory_index(memory_md.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                index = {}
        index_map[pool] = index
        present = {p.name for p in fact_paths}
        for target, (title, hook) in index.items():
            if target not in present:
                dangling.append({"pool": pool, "file": target, "line": f"- [{title}]({target}) — {hook}"})
        if not fact_paths:
            empty_pools.append(pool)
            continue
        for path in fact_paths:
            key = f"{pool}/memory/{path.name}"
            try:
                data = path.read_bytes()
                metadata, body = parse_frontmatter(path)
            except (OSError, ValueError, yaml.YAMLError, UnicodeDecodeError) as exc:
                unparsable.append({"key": key, "error": str(exc).splitlines()[0] if str(exc) else repr(exc)})
                continue
            if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str) \
                    or not isinstance(metadata.get("description"), str):
                unparsable.append({"key": key, "error": "frontmatter must provide name and description strings"})
                continue
            meta_meta = metadata.get("metadata")
            entry_type = meta_meta.get("type") if isinstance(meta_meta, dict) else None
            title, hook = index.get(path.name, ("", ""))
            entries[key] = {
                "key": key,
                "hash": _sha256(data),
                "name": metadata["name"],
                "title": title or metadata["description"].splitlines()[0][:80],
                "hook": hook,
                "type": entry_type if isinstance(entry_type, str) else "",
                "description": metadata["description"],
                "index_missing": path.name not in index,
                "body_chars": len(body),
                "body": body,
            }
    return {
        "entries": entries,
        "index_map": index_map,
        "dangling_index": dangling,
        "unparsable": unparsable,
        "empty_pools": empty_pools,
        "pool_files": pool_files,
    }


# ---------------------------------------------------------------------------
# 三态账本（D-C09/D-C10/D-C28：只记已决条目；<root>/collect/<client>/ledger.yaml）
# ---------------------------------------------------------------------------


def ledger_path(root: Path, client: str) -> Path:
    return root / "collect" / client / "ledger.yaml"


def _ledger_issues(path: Path, data: Any) -> list[str]:
    issues: list[str] = []
    if not isinstance(data, dict) or data.get("schema_version") != LEDGER_SCHEMA:
        issues.append(f"schema_version must be {LEDGER_SCHEMA}")
        return issues
    entries = data.get("entries")
    if not isinstance(entries, dict):
        issues.append("entries must be a mapping")
        return issues
    for key, record in entries.items():
        if not isinstance(record, dict):
            issues.append(f"entry {key}: must be a mapping")
            continue
        state = record.get("state")
        if state not in {"absorbed", "discarded"}:
            issues.append(f"entry {key}: state must be absorbed or discarded")
        if not isinstance(record.get("hash"), str) or not record["hash"].startswith("sha256:"):
            issues.append(f"entry {key}: hash must be a sha256: string")
        if state == "absorbed" and not isinstance(record.get("raw"), str):
            issues.append(f"entry {key}: absorbed requires raw")
        if state == "discarded" and not isinstance(record.get("reason"), str):
            issues.append(f"entry {key}: discarded requires reason")
    return issues


def load_ledger(root: Path, client: str) -> dict[str, dict[str, Any]]:
    """缺失=冷启动空账本；损坏抛 COLLECT_LEDGER_INVALID（判定口径见 design 5.1）。"""
    path = ledger_path(root, client)
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
        raise CollectError("COLLECT_LEDGER_INVALID", f"{path}: {exc}") from exc
    issues = _ledger_issues(path, data)
    if issues:
        raise CollectError("COLLECT_LEDGER_INVALID", f"{path}: {'; '.join(issues[:5])}")
    return data["entries"]


def save_ledger(root: Path, client: str, entries: dict[str, dict[str, Any]]) -> None:
    payload = {
        "schema_version": LEDGER_SCHEMA,
        "client": client,
        "updated_at": _today(),
        "entries": dict(sorted(entries.items())),
    }
    write_atomic(ledger_path(root, client), yaml.safe_dump(
        payload, sort_keys=False, allow_unicode=True, default_flow_style=False))


def collect_ledger_issues(root: Path) -> list[tuple[str, str, str]]:
    """doctor 用（D-C21）：遍历在场账本，返回 (client, code, message)。"""
    results: list[tuple[str, str, str]] = []
    base = root / "collect"
    if not base.is_dir():
        return results
    for client_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        path = client_dir / "ledger.yaml"
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
            results.append((client_dir.name, "COLLECT_LEDGER_INVALID", f"{path}: {exc}"))
            continue
        for issue in _ledger_issues(path, data):
            results.append((client_dir.name, "COLLECT_LEDGER_INVALID", f"{path}: {issue}"))
    return results


# ---------------------------------------------------------------------------
# collect：只读增量清单（D-C10：pending = 扫描中 (key,hash) ∉ 账本）
# ---------------------------------------------------------------------------


def resolve_source_dir(client: str, source_dir: str | None) -> Path:
    if client not in CLIENT_SOURCE_DEFAULTS:
        supported = ", ".join(sorted(CLIENT_SOURCE_DEFAULTS))
        raise CollectError("COLLECT_CLIENT_UNKNOWN",
                           f"client '{client}' is not supported (supported: {supported})")
    base = source_dir or CLIENT_SOURCE_DEFAULTS[client]
    resolved = Path(os.path.expanduser(base)).resolve()
    if not resolved.is_dir():
        raise CollectError("COLLECT_SOURCE_MISSING", f"source directory missing: {resolved}")
    return resolved


def _filter_scan(scan: dict[str, Any], pools: list[str] | None) -> dict[str, Any]:
    """v4/D-C25：--pool 过滤（池目录名精确匹配；未匹配任何池时保持空结果）。"""
    if not pools:
        return scan
    wanted = set(pools)
    scan = dict(scan)
    scan["entries"] = {k: v for k, v in scan["entries"].items() if k.split("/", 1)[0] in wanted}
    scan["pool_files"] = {p: v for p, v in scan["pool_files"].items() if p in wanted}
    scan["unparsable"] = [u for u in scan["unparsable"] if u["key"].split("/", 1)[0] in wanted]
    scan["dangling_index"] = [d for d in scan["dangling_index"] if d["pool"] in wanted]
    scan["empty_pools"] = [p for p in scan["empty_pools"] if p in wanted]
    return scan


def _mentions(root: Path, names: list[str]) -> dict[str, list[str]]:
    """v4/D-C24：字面提示——条目 name 出现在哪些 raw 正文（判重线索，不代决策）。"""
    result = {name: [] for name in names}
    if not names:
        return result
    raw_dir = root / load_config(root)["paths"]["raw"]
    if not raw_dir.is_dir():
        return result
    for path in sorted(raw_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for name in result:
            if name in text:
                result[name].append(path.name)
    return result


def build_manifest(root: Path, client: str, source_dir: Path,
                   pools: list[str] | None = None) -> dict[str, Any]:
    ledger = load_ledger(root, client)
    scan = _filter_scan(scan_source(source_dir), pools)
    pending: list[dict[str, Any]] = []
    for key in sorted(scan["entries"]):
        entry = dict(scan["entries"][key])
        record = ledger.get(key)
        if record is not None and record.get("hash") == entry["hash"]:
            continue  # 已决同 hash（absorbed/discarded）＝正常终态，不冒回（D-C28：源永在，无 residue 概念）
        pending.append(entry)
    mentions = _mentions(root, [e["name"] for e in pending])
    for entry in pending:
        entry["mentioned_in"] = mentions.get(entry["name"], [])
    pool_names = sorted(scan["pool_files"])
    files = sum(len(v) for v in scan["pool_files"].values())
    return {
        "schema_version": 1,
        "client": client,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_dir": str(source_dir),
        "summary": {
            "pools": len(pool_names),
            "files": files,
            "pending": len(pending),
            "unparsable": len(scan["unparsable"]),
            "empty_pools": len(scan["empty_pools"]),
        },
        "pending": pending,
        "unparsable": scan["unparsable"],
        "dangling_index": scan["dangling_index"],
        "empty_pools": sorted(scan["empty_pools"]),
    }


def cmd_collect(root: Path, client: str = "zcode", source_dir: str | None = None,
                out_path: str | None = None, dry_run: bool = False,
                pools: list[str] | None = None) -> int:
    resolved = resolve_source_dir(client, source_dir)
    if dry_run:
        print("collect is read-only; --dry-run has no additional effect", file=sys.stderr)
    manifest = build_manifest(root, client, resolved, pools=pools)
    text = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, default_flow_style=False)
    if out_path:
        write_atomic(Path(os.path.expanduser(out_path)).resolve(), text)
        summary = manifest["summary"]
        print(f"collect: pools={summary['pools']} files={summary['files']} pending={summary['pending']} "
              f"unparsable={summary['unparsable']} empty_pools={summary['empty_pools']}")
        print(f"manifest: {os.path.expanduser(out_path)}")
    else:
        sys.stdout.write(text)
    return 0


# ---------------------------------------------------------------------------
# apply：校验 → raw → 账本 → auto-commit（D-C11/D-C28：只写 hongzhao 侧）
# ---------------------------------------------------------------------------


def _entry_fail(report: list[tuple[str, str]], key: str, code: str, message: str) -> None:
    print(f"[{code}] {key}: {message}")
    report.append((key, code))


def _absorb_metadata(decision: dict[str, Any], today: str, client: str) -> tuple[dict[str, Any], str]:
    """组装 raw metadata（引擎生成身份与来源脚注，D-C13）；字段问题抛 ValueError。"""
    required = ("scope", "topic", "kind", "activation", "summary", "body")
    for field in required:
        if not isinstance(decision.get(field), str) or not decision[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    evidence = decision.get("evidence")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("why"), str) or not evidence["why"].strip():
        raise ValueError("evidence.why must be a non-empty string")
    similar = evidence.get("similar")
    if not isinstance(similar, dict) or not isinstance(similar.get("ref"), str) or not similar["ref"].strip() \
            or not isinstance(similar.get("diff"), str) or not similar["diff"].strip():
        raise ValueError("evidence.similar must provide ref and diff strings")
    scope = decision["scope"]
    if scope not in {"global", "project", "non-project"}:
        raise ValueError("scope must be global | project | non-project")
    if decision["kind"] not in KINDS or decision["activation"] not in ACTIVATIONS:
        raise ValueError("kind/activation not in the allowed enum")
    if not TOPIC_PATTERN.fullmatch(decision["topic"]):
        raise ValueError("topic must be lowercase letters, digits and hyphens")
    if scope == "project":
        project_id = decision.get("project_id")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id is required when scope=project")
    ident = uuid.uuid4()
    metadata: dict[str, Any] = {
        "schema_version": 2,
        "id": f"mem-{ident}",
        "created": today,
        "source": client.replace("_", "-"),  # zcode | claude-code（core SOURCES 枚举既含两者）
        "topic": decision["topic"],
        "kind": decision["kind"],
        "scope": scope,
        "activation": decision["activation"],
        "record_type": "source",
        "summary": decision["summary"],
        "compile_status": "new",
        "supersedes": [],
    }
    if scope == "project":
        metadata["project_id"] = decision["project_id"]
    return metadata, str(ident)


def _raw_filename(root: Path, today: str, topic: str, ident: str) -> str:
    """文件名后缀 = record id 的 uuid 前 8 位（与既有 raw 命名约定一致）；撞名防御性重生成。"""
    raw_dir = root / load_config(root)["paths"]["raw"]
    short = ident.replace("-", "")[:8]
    name = f"{today}_{topic}_{short}.md"
    while (raw_dir / name).exists():
        name = f"{today}_{topic}_{uuid.uuid4().hex[:8]}.md"
    return name


def _footnote(key: str, digest: str, evidence: dict[str, Any], client: str) -> str:
    label = {"zcode": "ZCode", "claude_code": "Claude Code"}.get(client, client)
    similar = evidence["similar"]
    return (
        f"> 来源：{label} auto-memory {key}（{digest[:8]}，{_today()} collect 采集）\n"
        f"> 采集依据：值得留——{evidence['why']}；最相似——{similar['ref']}，差异：{similar['diff']}"
    )


def cmd_apply(root: Path, decision_file: str, client: str = "zcode", source_dir: str | None = None,
              dry_run: bool = False) -> int:
    if dry_run:
        return _apply_plan(root, decision_file, client, source_dir)
    with exclusive_lock(root / ".hongzhao.lock"):
        return _apply_locked(root, decision_file, client, source_dir)


def _load_decision(path_text: str) -> tuple[dict[str, Any], Path]:
    path = Path(os.path.expanduser(path_text))
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
        raise CollectError("APPLY_DECISION_INVALID", f"{path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 \
            or not isinstance(data.get("decisions"), list):
        raise CollectError("APPLY_DECISION_INVALID", f"{path}: schema_version must be 1 with a decisions list")
    removed = REMOVED_DECISION_FIELDS & set(data)
    if removed:
        raise CollectError(
            "APPLY_DECISION_INVALID",
            f"{path}: client-side write fields are removed under strict read-only collection "
            f"(design v6/D-C28): {', '.join(sorted(removed))}")
    return data, path


def _apply_plan(root: Path, decision_file: str, client: str, source_dir: str | None) -> int:
    """--dry-run：全量校验+打印计划，零写入（design 5.1）。"""
    data, _path = _load_decision(decision_file)
    resolved = resolve_source_dir(client, source_dir)
    ledger = load_ledger(root, client)
    scan = scan_source(resolved)
    config = load_config(root)
    raw_dir = root / config["paths"]["raw"]
    code = 0
    seen: set[str] = set()
    for decision in data["decisions"]:
        key = decision.get("key") if isinstance(decision, dict) else None
        if not isinstance(key, str):
            print("[APPLY_DECISION_INVALID] decision entry without key")
            code = 1
            continue
        if key in seen:
            print(f"[APPLY_ENTRY_DUPLICATE] {key}: duplicate key in decisions")
            code = 1
            continue
        seen.add(key)
        entry = scan["entries"].get(key)
        if entry is None or entry["hash"] != decision.get("hash"):
            print(f"[APPLY_ENTRY_STALE] {key}: not in pending set (changed or already decided)")
            code = 1
            continue
        if ledger.get(key, {}).get("hash") == decision.get("hash"):
            print(f"[APPLY_ENTRY_DUPLICATE] {key}: already decided at this hash")
            code = 1
            continue
        action = decision.get("action")
        if action == "absorb":
            try:
                _absorb_metadata(decision, _today(), client)
            except ValueError as exc:
                print(f"[APPLY_RAW_INVALID] {key}: {exc}")
                code = 1
                continue
            print(f"would absorb {key} (client side untouched) -> "
                  f"{raw_dir}/<today>_{decision.get('topic')}_<uuid8>.md")
        elif action == "discard":
            if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
                print(f"[APPLY_DECISION_INVALID] {key}: discard requires reason")
                code = 1
                continue
            print(f"would discard {key} (ledger only; client side untouched)")
        else:
            print(f"[APPLY_DECISION_INVALID] {key}: action must be absorb or discard")
            code = 1
    if code == 0 and not data["decisions"]:
        print("apply: nothing to do")
    print("dry-run: no writes performed")
    return code


def _apply_locked(root: Path, decision_file: str, client: str, source_dir: str | None) -> int:
    data, _path = _load_decision(decision_file)
    resolved = resolve_source_dir(client, source_dir)
    ledger = load_ledger(root, client)
    scan = scan_source(resolved)
    config = load_config(root)
    raw_dir = root / config["paths"]["raw"]
    registry, _issues = load_registry(root)
    known_projects = {str(e.get("project_id")) for e in registry.get("projects", []) if isinstance(e, dict)}
    today = _today()
    report: list[tuple[str, str]] = []
    seen: set[str] = set()

    if not data["decisions"]:
        print("apply: nothing to do")
        return 0

    # 步骤 1：逐条校验并写 raw（先 validate 后写；不合格该条目失败，零部分文件）
    absorbed_n = 0
    discarded_n = 0
    for decision in data["decisions"]:
        key = decision.get("key") if isinstance(decision, dict) else None
        if not isinstance(key, str):
            _entry_fail(report, "?", "APPLY_DECISION_INVALID", "decision entry without key")
            continue
        if key in seen:
            _entry_fail(report, key, "APPLY_ENTRY_DUPLICATE", "duplicate key in decisions")
            continue
        seen.add(key)
        entry = scan["entries"].get(key)
        if entry is None or entry["hash"] != decision.get("hash"):
            _entry_fail(report, key, "APPLY_ENTRY_STALE", "not in pending set (changed or already decided)")
            continue
        if ledger.get(key, {}).get("hash") == decision.get("hash"):
            _entry_fail(report, key, "APPLY_ENTRY_DUPLICATE", "already decided at this hash")
            continue
        action = decision.get("action")
        if action == "discard":
            reason = decision.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                _entry_fail(report, key, "APPLY_DECISION_INVALID", "discard requires reason")
                continue
            ledger[key] = {"hash": decision["hash"], "state": "discarded",
                           "reason": reason, "decided_at": today}
            discarded_n += 1
            print(f"discarded: {key} (ledger only; client side untouched)")
            continue
        if action != "absorb":
            _entry_fail(report, key, "APPLY_DECISION_INVALID", "action must be absorb or discard")
            continue
        if decision.get("scope") == "project" and decision.get("project_id") not in known_projects:
            _entry_fail(report, key, "APPLY_PROJECT_UNKNOWN", f"project_id {decision.get('project_id')} not in registry")
            continue
        try:
            metadata, ident = _absorb_metadata(decision, today, client)
        except ValueError as exc:
            _entry_fail(report, key, "APPLY_RAW_INVALID", str(exc))
            continue
        filename = _raw_filename(root, today, decision["topic"], ident)
        issues = validate_raw(metadata, filename)
        if issues:
            first = issues[0]
            _entry_fail(report, key, "APPLY_RAW_INVALID", f"{first.code}: {first.message}")
            continue
        digest = decision["hash"].removeprefix("sha256:")
        body = decision["body"].rstrip("\n") + "\n\n" + _footnote(key, digest, decision["evidence"], client) + "\n"
        write_atomic(raw_dir / filename, dump_frontmatter(metadata, body))
        ledger[key] = {"hash": decision["hash"], "state": "absorbed",
                       "raw": f"{config['paths']['raw']}/{filename}", "decided_at": today}
        absorbed_n += 1
        print(f"absorbed: {key} -> {config['paths']['raw']}/{filename} (client side untouched)")
    if _fault_active("after-raws"):
        _crash("after-raws")

    # 步骤 2：账本原子更新（raw 已全部落盘后才记账——宁重复，不丢失）
    save_ledger(root, client, ledger)
    if _fault_active("after-ledger"):
        _crash("after-ledger")

    # 步骤 3：auto-commit（同 git.auto_commit 配置与守卫；失败降级 warning 不阻断）
    auto_commit_with_message(root, config,
                             f"hongzhao collect apply {dt.datetime.now().isoformat(timespec='seconds')} "
                             f"absorbed={absorbed_n} discarded={discarded_n}")
    failures = len(report)
    print(f"apply: done ({'ok, client side untouched' if not failures else f'{failures} entry-level issue(s)'}); "
          "raw/ledger committed to the memory root only")
    return 1 if failures else 0
