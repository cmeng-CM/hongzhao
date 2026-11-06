"""索引层：memory-index 构建、健康度、可见记录筛选（ 原样迁移）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from hongzhao.core import *  # 迁移期整组引用（数据类/加载器/常量）， 收敛为显式清单

def _ids(value: Any) -> list[str]:
    return value if isinstance(value, list) else []


def _record_entry(record: RawRecord, root: Path) -> dict[str, Any]:
    metadata = record.metadata
    return {
        "path": str(record.path.relative_to(root)),
        "kind": metadata.get("kind"),
        "scope": metadata.get("scope"),
        "project_id": metadata.get("project_id"),
        "topic": metadata.get("topic"),
        "created": metadata.get("created"),
        "summary": metadata.get("summary"),
        "compile_status": metadata.get("compile_status"),
        "record_type": metadata.get("record_type"),
        "activation": metadata.get("activation"),
        "derived_from": _ids(metadata.get("derived_from")),
        "source_chain": [],
        "covers": _ids(metadata.get("covers")),
        "covered_by": [],
        "supersedes": _ids(metadata.get("supersedes")),
        "superseded_by": [],
        "conflicts_with": _ids(metadata.get("conflicts_with")),
        "resolved_by": metadata.get("resolved_by"),
        "effective": False,
        "bootstrap_eligible": False,
        "exclusion_reason": "pending" if metadata.get("compile_status") == "new" else None,
        "output": None,
    }


def _same_scope(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a.get("scope") == b.get("scope") and a.get("project_id") == b.get("project_id")


def build_memory_index(root: Path, project_keys: dict[str, str] | None = None) -> tuple[dict[str, Any], list[Issue], list[RawRecord]]:
    project_keys = project_keys or {}
    records, issues = load_raw(root)
    by_id: dict[str, RawRecord] = {}
    invalid_ids: set[str] = set()
    invalid_paths = {issue.path for issue in issues if issue.path and issue.path.startswith("raw/")}
    index: dict[str, Any] = {
        "schema_version": RAW_SCHEMA,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "health": "ok",
        "counts": {},
        "records": {},
    }
    for record in records:
        record_id = record.metadata.get("id")
        if record_id in by_id:
            issues.append(Issue("RAW_DUPLICATE_ID", f"duplicate id: {record_id}", str(record.path.relative_to(root))))
            continue
        by_id[record_id] = record
        index["records"][record_id] = _record_entry(record, root)
        if str(record.path.relative_to(root)) in invalid_paths:
            invalid_ids.add(record_id)
            index["records"][record_id]["exclusion_reason"] = "invalid"

    def add_issue(code: str, message: str, record: RawRecord | None = None, severity: str = "degraded") -> None:
        path = str(record.path.relative_to(root)) if record else None
        issues.append(Issue(code, message, path, severity))
        if record is not None:
            invalid_ids.add(record.metadata.get("id"))

    # Validate references and type/scope constraints.
    relation_fields = ("derived_from", "covers", "supersedes", "conflicts_with")
    for record in records:
        rid = record.metadata.get("id")
        entry = index["records"].get(rid)
        if not entry:
            continue
        for field in relation_fields:
            for target in entry[field]:
                if target not in by_id:
                    add_issue("RELATION_TARGET", f"{field} target not found: {target}", record)
        resolved = entry.get("resolved_by")
        if resolved and resolved not in by_id:
            add_issue("RESOLUTION_TARGET", f"resolved_by target not found: {resolved}", record)
        if entry["record_type"] == "source" and entry["derived_from"]:
            add_issue("RELATION_TYPE", "source must not set derived_from", record)
        if entry["record_type"] == "synthesis" and not entry["derived_from"]:
            add_issue("RELATION_TYPE", "synthesis requires non-empty derived_from", record)
        if entry["record_type"] != "synthesis" and entry["covers"]:
            add_issue("RELATION_TYPE", "only synthesis may set covers", record)
        if set(entry["covers"]) - set(entry["derived_from"]):
            add_issue("COVER_TARGET", "covers must be a subset of direct derived_from sources", record)
        if resolved and resolved in by_id:
            resolved_entry = index["records"][resolved]
            if resolved_entry["record_type"] != "synthesis":
                add_issue("RESOLUTION_TYPE", "resolved_by must point to a synthesis", record)
            elif resolved_entry["compile_status"] != "done":
                add_issue("RESOLUTION_STATUS", "resolved_by must point to a done synthesis", record)
        for field in ("covers", "supersedes"):
            for target in entry[field]:
                if target in index["records"] and not _same_scope(entry, index["records"][target]):
                    add_issue("SCOPE_RELATION", f"{field} must not cross scope or project_id", record)
        for target in entry["conflicts_with"]:
            if target == rid:
                add_issue("CONFLICT_SELF", "conflicts_with must not point to itself", record)

    def detect_cycles(field: str, code: str) -> None:
        graph = {
            rid: [target for target in entry[field] if target in index["records"]]
            for rid, entry in index["records"].items()
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                issues.append(Issue(code, f"{field} relation cycle at: {node}"))
                invalid_ids.add(node)
                return
            if node in visited:
                return
            visiting.add(node)
            for child in graph.get(node, []):
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)

    detect_cycles("derived_from", "DERIVED_CYCLE")
    detect_cycles("covers", "COVER_CYCLE")
    detect_cycles("supersedes", "SUPERSEDES_CYCLE")

    # Compute recursive provenance, excluding the current record itself.
    def source_chain(rid: str, stack: set[str] | None = None) -> list[str]:
        stack = set() if stack is None else stack
        if rid in stack:
            return []
        stack.add(rid)
        result: list[str] = []
        for target in index["records"].get(rid, {}).get("derived_from", []):
            if target not in result:
                result.append(target)
            for ancestor in source_chain(target, stack):
                if ancestor not in result:
                    result.append(ancestor)
        stack.remove(rid)
        return result

    for rid, entry in index["records"].items():
        entry["source_chain"] = source_chain(rid)

    # Supersession is an explicit, same-scope replacement relation.
    for rid, entry in index["records"].items():
        if rid in invalid_ids:
            entry["effective"] = False
            entry["exclusion_reason"] = "invalid"
            continue
        if entry["compile_status"] != "done":
            continue
        for target in entry["supersedes"]:
            if target in index["records"]:
                index["records"][target]["superseded_by"].append(rid)
    for rid, entry in index["records"].items():
        if rid in invalid_ids:
            continue
        if len(entry["superseded_by"]) > 1:
            issues.append(Issue("SUPERSEDES_FORK", f"record superseded by multiple done claims: {rid}"))
        if entry["superseded_by"]:
            entry["effective"] = False
            entry["exclusion_reason"] = "superseded"

    # Treat conflicts as undirected even if only one side stores the relation.
    conflict_pairs: set[tuple[str, str]] = set()
    for rid, entry in index["records"].items():
        if rid in invalid_ids:
            continue
        for target in entry["conflicts_with"]:
            if target in index["records"] and target not in invalid_ids:
                conflict_pairs.add(tuple(sorted((rid, target))))

    def conflict_resolved(a: str, b: str) -> bool:
        ea, eb = index["records"][a], index["records"][b]
        if ea["compile_status"] == "rejected" or eb["compile_status"] == "rejected":
            return True
        for candidate in (ea.get("resolved_by"), eb.get("resolved_by")):
            if not candidate or candidate not in index["records"]:
                continue
            resolution = index["records"][candidate]
            if resolution["record_type"] == "synthesis" and resolution["compile_status"] == "done" and {a, b}.issubset(set(resolution["source_chain"]) | {candidate}):
                return True
        return False

    unresolved_conflicts: list[tuple[str, str]] = []
    pending_conflicts: list[tuple[str, str]] = []
    done_conflicts: list[tuple[str, str]] = []
    for a, b in sorted(conflict_pairs):
        if conflict_resolved(a, b):
            continue
        unresolved_conflicts.append((a, b))
        ea, eb = index["records"][a], index["records"][b]
        if ea["compile_status"] == "done" and eb["compile_status"] == "done":
            done_conflicts.append((a, b))
            ea["effective"] = eb["effective"] = False
            ea["exclusion_reason"] = eb["exclusion_reason"] = "unresolved-conflict"
            add_issue("DONE_CONFLICT", f"confirmed done-done conflict unresolved: {a} vs {b}")
        else:
            pending_conflicts.append((a, b))
            for item in (ea, eb):
                if item["compile_status"] == "new":
                    item["effective"] = False
                    item["exclusion_reason"] = "pending-conflict"

    # Done records that are not superseded or blocked by a confirmed conflict.
    for rid, entry in index["records"].items():
        if rid in invalid_ids:
            continue
        if entry["compile_status"] == "rejected":
            entry["effective"] = False
            entry["exclusion_reason"] = "rejected"
        elif entry["compile_status"] == "new":
            entry["effective"] = False
            entry["exclusion_reason"] = entry["exclusion_reason"] or "pending"
        elif entry["exclusion_reason"] is None:
            entry["effective"] = True

    # Only top-level effective syntheses apply covers; nested covers propagate.
    active_synthesis = {
        rid for rid, entry in index["records"].items()
        if rid not in invalid_ids and entry["record_type"] == "synthesis" and entry["effective"]
    }
    direct_cover_targets = {
        target
        for rid in active_synthesis
        for target in index["records"][rid]["covers"]
    }
    cover_roots = sorted(active_synthesis - direct_cover_targets)
    cover_owner: dict[str, str] = {}

    def apply_covers(owner: str, target: str, visiting: set[str] | None = None) -> None:
        visiting = set() if visiting is None else visiting
        if target in visiting:
            return
        visiting.add(target)
        previous = cover_owner.get(target)
        if previous and previous != owner:
            issues.append(Issue("COVER_FORK", f"record covered by multiple syntheses: {target}"))
        else:
            cover_owner[target] = owner
        target_entry = index["records"].get(target)
        if target_entry and target_entry["record_type"] == "synthesis":
            for nested in target_entry["covers"]:
                apply_covers(owner, nested, visiting)
        visiting.remove(target)

    for owner in cover_roots:
        for target in index["records"][owner]["covers"]:
            apply_covers(owner, target)
    for target, owner in cover_owner.items():
        entry = index["records"].get(target)
        if entry and entry["effective"]:
            entry["effective"] = False
            entry["exclusion_reason"] = "covered-by-synthesis"
            entry["covered_by"] = [owner]

    def output_for(entry: dict[str, Any]) -> str | None:
        if entry["scope"] == "global":
            return "compiled/effective-memory/global.md"
        if entry["scope"] == "non-project":
            return "compiled/effective-memory/non-project.md"
        if entry["scope"] == "project":
            project_id = entry["project_id"]
            return f"compiled/effective-memory/projects/{project_keys.get(project_id, project_id)}.md"
        return None

    for entry in index["records"].values():
        if entry["effective"]:
            entry["output"] = output_for(entry)
            if entry["scope"] in {"global", "non-project"} and entry["activation"] == "bootstrap":
                entry["bootstrap_eligible"] = True
        elif entry["exclusion_reason"] is None:
            entry["exclusion_reason"] = "not-selected"

    counts = {
        "total": len(index["records"]),
        "effective": sum(bool(e["effective"]) for e in index["records"].values()),
        "pending": sum(e["compile_status"] == "new" for e in index["records"].values()),
        "rejected": sum(e["compile_status"] == "rejected" for e in index["records"].values()),
        "superseded": sum(e["exclusion_reason"] == "superseded" for e in index["records"].values()),
        "covered": sum(e["exclusion_reason"] == "covered-by-synthesis" for e in index["records"].values()),
        "unresolved_conflicts": len(done_conflicts),
        "pending_conflicts": len(pending_conflicts),
        "bootstrap": sum(bool(e["bootstrap_eligible"]) for e in index["records"].values()),
    }
    index["counts"] = counts
    index["health"] = health_for(issues, counts)
    return index, issues, records


def health_for(issues: list[Issue], counts: dict[str, Any]) -> str:
    if any(issue.severity == "degraded" for issue in issues) or counts.get("unresolved_conflicts", 0):
        return "degraded"
    if counts.get("pending", 0) or counts.get("pending_conflicts", 0):
        return "review-needed"
    return "ok"


def eligible_records(index: dict[str, Any], records: Iterable[RawRecord], *, scope: str | None = None, project_id: str | None = None) -> list[RawRecord]:
    by_id = index.get("records", {})
    result: list[RawRecord] = []
    for record in records:
        item = by_id.get(record.metadata.get("id"), {})
        if not item.get("effective"):
            continue
        if scope and record.metadata.get("scope") != scope:
            continue
        if project_id and record.metadata.get("project_id") != project_id:
            continue
        result.append(record)
    return sorted(result, key=lambda r: (str(r.metadata.get("kind")), str(r.metadata.get("topic")), str(r.metadata.get("created")), str(r.metadata.get("id"))))


def bootstrap_records(index: dict[str, Any], records: Iterable[RawRecord], scope: str, kinds: set[str] | None = None) -> list[RawRecord]:
    by_id = index.get("records", {})
    result = []
    for record in records:
        entry = by_id.get(record.metadata.get("id"), {})
        if entry.get("bootstrap_eligible") and record.metadata.get("scope") == scope and (not kinds or record.metadata.get("kind") in kinds):
            result.append(record)
    return sorted(result, key=lambda r: (str(r.metadata.get("kind")), str(r.metadata.get("topic")), str(r.metadata.get("created")), str(r.metadata.get("id"))))


