"""客户端记忆采集（design：.delivery/2026-11-13-客户端记忆采集/design.md v2，已批准）。

collect                只读：解析客户端 auto-memory 池 → 账本 diff → 增量清单（manifest）
collect --apply <f>    决策落盘：校验 decision file → 写 raw → 记账 → hash 条件删源 → auto-commit

引擎纪律（D-C04/D-C11/D-C12/D-C14）：
- 纯确定性，零语义判断（判重/重要性归 skill 的模型环节，终审归人）；
- 写序 raw → 账本 → 条件删源 → auto-commit：宁重复候选，不静默丢失；
- 删源按内容 hash 条件删除 + MEMORY.md 行级原字节改写（删全部精确匹配行）；
- apply 校验序与写序同临界区（.hongzhao.lock，与注册互斥）。
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

# v1 客户端源（D-C03/D-C15）：默认路径随客户端预设内建；--source-dir 可指任意同构目录
CLIENT_SOURCE_DEFAULTS = {"zcode": "~/.zcode/cli/memories/projects"}
LEDGER_SCHEMA = 1
TOPIC_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
INDEX_LINE = re.compile(r"^- \[(?P<title>.*)\]\((?P<file>[^\)]+)\) — (?P<hook>.*)$")
# 故障注入点（对齐 contracts 双条件先例；合同测试走子进程触发）
FAULTS = {"after-raws", "after-ledger", "mid-deletes", "after-deletes"}


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


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """字节级原子写（MEMORY.md 行级保留需要按字节落盘，write_atomic 只收 str）。"""
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


# ---------------------------------------------------------------------------
# 源解析（D-C17：解析失败只报不猜）
# ---------------------------------------------------------------------------


def _parse_memory_index(text: str) -> dict[str, tuple[str, str]]:
    """索引行 file → (title, hook)。同文件重复行取首行（重复行的全量删除在删源步骤）。"""
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
    """扫描源根：{entries, index_map, dangling_index, unparsable, empty_pools, pool_files}。

    entries: key("<pool>/memory/<file>") → 条目 dict（hash=name/title/hook/type/description/body/…）
    pool_files: pool → [事实文件名]（删源与空池判定复用）
    """
    entries: dict[str, dict[str, Any]] = {}
    index_map: dict[str, dict[str, tuple[str, str]]] = {}  # pool → file → (title, hook)
    dangling: list[dict[str, str]] = []
    unparsable: list[dict[str, str]] = []
    empty_pools: list[str] = []
    pool_files: dict[str, list[str]] = {}

    for pool_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
        pool = pool_dir.name
        memory = pool_dir / "memory"
        if not memory.is_dir():
            empty_pools.append(pool)
            pool_files[pool] = []
            index_map[pool] = {}
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
# 三态账本（D-C09/D-C10：只记已决条目；<root>/collect/<client>/ledger.yaml）
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
        source = record.get("source")
        if source is not None and source not in {"deleted", "kept"}:
            issues.append(f"entry {key}: source must be deleted or kept")
    return issues


def load_ledger(root: Path, client: str) -> dict[str, dict[str, Any]]:
    """缺失=冷启动空账本（S14）；损坏抛 COLLECT_LEDGER_INVALID（S15，判定口径见 design 5.1）。"""
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
        raise CollectError("COLLECT_CLIENT_UNKNOWN", f"client '{client}' is not supported (v1: zcode)")
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
    residue: list[dict[str, Any]] = []
    for key in sorted(scan["entries"]):
        entry = dict(scan["entries"][key])
        record = ledger.get(key)
        if record is not None and record.get("hash") == entry["hash"]:
            if record.get("state") == "absorbed" and record.get("source") != "kept":
                # v3/D-C22：kept 条目同 hash 在场=正常终态，不算 residue
                residue.append({"key": key, "hash": entry["hash"], "raw": record.get("raw", "")})
            # discarded 同 hash：不冒回（S11）；kept 同 hash：保留源终态
            continue
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
            "residue": len(residue),
            "unparsable": len(scan["unparsable"]),
            "empty_pools": len(scan["empty_pools"]),
        },
        "pending": pending,
        "residue": residue,
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
              f"residue={summary['residue']} unparsable={summary['unparsable']} empty_pools={summary['empty_pools']}")
        print(f"manifest: {os.path.expanduser(out_path)}")
    else:
        sys.stdout.write(text)
    return 0


# ---------------------------------------------------------------------------
# apply：校验 → raw → 账本 → 条件删源 → auto-commit（D-C11/D-C12/D-C13）
# ---------------------------------------------------------------------------


def _entry_fail(report: list[tuple[str, str]], key: str, code: str, message: str) -> None:
    print(f"[{code}] {key}: {message}")
    report.append((key, code))


def _absorb_metadata(decision: dict[str, Any], today: str) -> tuple[dict[str, Any], str]:
    """组装 raw metadata+正文（引擎生成身份与来源脚注，D-C13）；字段问题抛 ValueError。"""
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
        "source": "zcode",
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


def _footnote(key: str, digest: str, evidence: dict[str, Any]) -> str:
    similar = evidence["similar"]
    return (
        f"> 来源：ZCode auto-memory {key}（{digest[:8]}，{_today()} collect 采集）\n"
        f"> 采集依据：值得留——{evidence['why']}；最相似——{similar['ref']}，差异：{similar['diff']}"
    )


def _delete_source(source_dir: Path, key: str, expect_hash: str,
                   deleted: dict[str, set[str]]) -> str:
    """hash 条件删除 + 记录待清索引行；返回 deleted | absent | mismatch。"""
    path = source_dir / key
    if not path.is_file():
        return "absent"
    if _sha256(path.read_bytes()) != expect_hash:
        return "mismatch"
    path.unlink()
    pool, _, name = key.partition("/memory/")
    deleted.setdefault(pool, set()).add(name)
    return "deleted"


def _prune_index_lines(source_dir: Path, pool: str, filenames: set[str]) -> str:
    """MEMORY.md 删除全部精确匹配行（行级原字节拼接；不用主导行尾策略）。"""
    memory_md = source_dir / pool / "memory" / "MEMORY.md"
    if not memory_md.is_file():
        return "missing"
    try:
        raw = memory_md.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return "unreadable"
    kept: list[str] = []
    removed = 0
    for line in text.splitlines(keepends=True):
        matched = INDEX_LINE.match(line.strip())
        if matched and matched.group("file") in filenames:
            removed += 1
            continue
        kept.append(line)
    if not removed:
        return "no-match"
    _atomic_write_bytes(memory_md, "".join(kept).encode("utf-8"))
    return f"removed-{removed}"


def _prune_empty_pool(source_dir: Path, pool: str) -> str:
    """空池修剪（保守口径）：memory/ 无事实文件且无内容（仅允许 0 字节 MEMORY.md）才整目录删除；
    有索引内容的池=客户端数据，报 not-empty 跳过（人工清理路径）。"""
    pool_dir = source_dir / pool
    if not pool_dir.is_dir():
        return "absent"
    memory = pool_dir / "memory"
    if memory.is_dir():
        children = list(memory.iterdir())
        for child in children:
            if child.name == "MEMORY.md" and child.is_file() and child.stat().st_size == 0:
                continue
            return "not-empty"
        for child in children:
            child.unlink()
        memory.rmdir()
    if any(pool_dir.iterdir()):
        return "not-empty"
    pool_dir.rmdir()
    return "pruned"


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
    for field in ("cleanup", "prune_empty_pools"):
        value = data.get(field)
        if value is not None and not isinstance(value, list):
            raise CollectError("APPLY_DECISION_INVALID", f"{path}: {field} must be a list")
    if data.get("delete_source") is not None and not isinstance(data.get("delete_source"), bool):
        raise CollectError("APPLY_DECISION_INVALID", f"{path}: delete_source must be a boolean")
    if data.get("slim_index") is not None and not isinstance(data.get("slim_index"), bool):
        raise CollectError("APPLY_DECISION_INVALID", f"{path}: slim_index must be a boolean")
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
                _absorb_metadata(decision, _today())
            except ValueError as exc:
                print(f"[APPLY_RAW_INVALID] {key}: {exc}")
                code = 1
                continue
            keep_note = "" if data.get("delete_source", True) else " (keep source)"
            print(f"would absorb{keep_note} {key} -> {raw_dir}/<today>_{decision.get('topic')}_<uuid8>.md")
        elif action == "discard":
            if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
                print(f"[APPLY_DECISION_INVALID] {key}: discard requires reason")
                code = 1
                continue
            print(f"would discard {key}")
        else:
            print(f"[APPLY_DECISION_INVALID] {key}: action must be absorb or discard")
            code = 1
    for item in data.get("cleanup") or []:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            print(f"[APPLY_DECISION_INVALID] cleanup entries must be {{key, hash}}: {item}")
            code = 1
            continue
        key = item["key"]
        record = ledger.get(key)
        if not isinstance(record, dict) or record.get("state") != "absorbed" \
                or record.get("hash") != item.get("hash"):
            print(f"[APPLY_ENTRY_STALE] cleanup {key}: ledger premise mismatch")
            code = 1
            continue
        print(f"would delete source {key} (conditional on hash)")
    for pool in data.get("prune_empty_pools") or []:
        print(f"would prune empty pool {pool} (re-verified at apply time)")
    if data.get("slim_index"):
        print("would slim MEMORY.md index lines for decided entries (files untouched)")
    if code == 0 and not data["decisions"] and not data.get("cleanup") and not data.get("prune_empty_pools"):
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

    if not data["decisions"] and not data.get("cleanup") and not data.get("prune_empty_pools"):
        print("apply: nothing to do")
        return 0

    # 步骤 1-3：逐条校验并写 raw（先 validate 后写；不合格该条目失败，零部分文件）
    absorbed_keys: list[str] = []
    decided_keys: list[str] = []  # 本批全部成功决策（absorbed+discarded，slim_index 用）
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
            decided_keys.append(key)
            print(f"discarded: {key}")
            continue
        if action != "absorb":
            _entry_fail(report, key, "APPLY_DECISION_INVALID", "action must be absorb or discard")
            continue
        if decision.get("scope") == "project" and decision.get("project_id") not in known_projects:
            _entry_fail(report, key, "APPLY_PROJECT_UNKNOWN", f"project_id {decision.get('project_id')} not in registry")
            continue
        try:
            metadata, ident = _absorb_metadata(decision, today)
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
        body = decision["body"].rstrip("\n") + "\n\n" + _footnote(key, digest, decision["evidence"]) + "\n"
        write_atomic(raw_dir / filename, dump_frontmatter(metadata, body))
        ledger[key] = {"hash": decision["hash"], "state": "absorbed",
                       "raw": f"{config['paths']['raw']}/{filename}", "decided_at": today,
                       "source": "kept" if not data.get("delete_source", True) else "deleted"}
        absorbed_keys.append(key)
        decided_keys.append(key)
        absorbed_n += 1
        keep_note = "" if data.get("delete_source", True) else " (source kept)"
        print(f"absorbed{keep_note}: {key} -> {config['paths']['raw']}/{filename}")
    if _fault_active("after-raws"):
        _crash("after-raws")

    # 步骤 4：账本原子更新（raw 已全部落盘后才记账——宁重复，不丢失）
    save_ledger(root, client, ledger)
    if _fault_active("after-ledger"):
        _crash("after-ledger")

    # 步骤 5：条件删源（重读文件 hash 必须等于决策依据 hash；MEMORY.md 删全部精确匹配行）。
    # v3/D-C22：delete_source=false 时本次 absorbed 不删源（cleanup 仍按显式清单执行）。
    deleted: dict[str, set[str]] = {}
    to_delete: list[tuple[str, str]] = []
    if data.get("delete_source", True):
        to_delete.extend((key, ledger[key]["hash"]) for key in absorbed_keys)
    for item in data.get("cleanup") or []:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            _entry_fail(report, str(item), "APPLY_DECISION_INVALID", "cleanup entries must be {key, hash}")
            continue
        key = item["key"]
        record = ledger.get(key)
        if not isinstance(record, dict) or record.get("state") != "absorbed" \
                or record.get("hash") != item.get("hash"):
            _entry_fail(report, key, "APPLY_ENTRY_STALE", "cleanup premise mismatch (ledger)")
            continue
        to_delete.append((key, record["hash"]))
    for key, expect_hash in to_delete:
        outcome = _delete_source(resolved, key, expect_hash, deleted)
        if outcome == "mismatch":
            _entry_fail(report, key, "APPLY_DELETE_MISMATCH", "source changed since decision; kept (residue)")
        elif outcome == "deleted":
            print(f"deleted source: {key}")
        if _fault_active("mid-deletes"):
            _crash("mid-deletes")
    for pool, names in sorted(deleted.items()):
        result = _prune_index_lines(resolved, pool, names)
        if result.startswith("removed-"):
            print(f"index pruned: {pool}/MEMORY.md ({result})")
        elif result == "unreadable":
            _entry_fail(report, f"{pool}/MEMORY.md", "APPLY_DELETE_MISMATCH", "index rewrite skipped: unreadable")
        else:
            print(f"index note: {pool}/MEMORY.md {result}")
    if _fault_active("after-deletes"):
        _crash("after-deletes")

    # 步骤 5b：瘦身索引（v4/D-C23，缺省关闭）——本批已决条目只删 MEMORY.md 索引行，
    # 事实文件与其内容一字不动；与删源正交（文件刚被删的条目已随之清行，此处天然 no-match 跳过）。
    if data.get("slim_index"):
        slim_by_pool: dict[str, set[str]] = {}
        for key in decided_keys:
            pool, _, name = key.partition("/memory/")
            slim_by_pool.setdefault(pool, set()).add(name)
        for pool, names in sorted(slim_by_pool.items()):
            result = _prune_index_lines(resolved, pool, names - deleted.get(pool, set()))
            if result.startswith("removed-"):
                print(f"index slimmed: {pool}/MEMORY.md ({result}; files untouched)")
            elif result == "unreadable":
                _entry_fail(report, f"{pool}/MEMORY.md", "APPLY_DELETE_MISMATCH", "slim skipped: unreadable")
            else:
                print(f"index note: {pool}/MEMORY.md {result} (slim)")

    # 步骤 6：空池修剪（现场复核）
    for pool in data.get("prune_empty_pools") or []:
        if not isinstance(pool, str):
            _entry_fail(report, str(pool), "APPLY_DECISION_INVALID", "prune_empty_pools entries must be pool names")
            continue
        result = _prune_empty_pool(resolved, pool)
        if result == "pruned":
            print(f"pruned empty pool: {pool}")
        elif result == "not-empty":
            _entry_fail(report, pool, "APPLY_DECISION_INVALID", "pool is not empty; skipped")
        else:
            print(f"prune note: {pool} {result}")

    # 步骤 7：auto-commit（同 git.auto_commit 配置与守卫；失败降级 warning 不阻断）
    cleaned = sum(len(names) for names in deleted.values())
    auto_commit_with_message(root, config,
                             f"hongzhao collect apply {dt.datetime.now().isoformat(timespec='seconds')} "
                             f"absorbed={absorbed_n} discarded={discarded_n} cleaned={cleaned}")
    failures = len(report)
    print(f"apply: done ({'ok' if not failures else f'{failures} entry-level issue(s)'})")
    return 1 if failures else 0
