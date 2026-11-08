"""核心层：常量、数据结构、YAML/frontmatter、原子写、配置/注册表/契约加载校验。

 自 vault scripts/agent_memory.py 原样迁移（行号对照 p1-briefs ）。
行为改造分批进行：config 放宽/knowledge_root/containment 在 ，契约生命周期在 。
本任务内唯一行为变化：SOURCES 枚举补 zcode（校验放宽，落盘字段冻结）。
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

import yaml

RAW_SCHEMA = 2
CONFIG_SCHEMA = 2
REGISTRY_SCHEMA = 2
KNOWLEDGE_SCHEMA = 2
CONTRACT_SCHEMA = 2
PROJECT_CONTEXT_FILENAME = "project-view.md"
PROJECT_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROJECT_ARCHIVE_DIR_NAMES = {"archive", "99-archive"}
MANAGED_START = "<!-- agent-memory:start -->"
MANAGED_END = "<!-- agent-memory:end -->"
KINDS = {"profile", "preference", "memory"}
SCOPES = {"global", "project", "non-project"}
SOURCES = {"claude-code", "codex", "user", "migration", "other", "zcode"}
ACTIVATIONS = {"bootstrap", "on-demand"}
RECORD_TYPES = {"source", "synthesis"}
COMPILE_STATUSES = {"new", "done", "rejected"}
PROJECT_STATUSES = {"active", "blocked", "paused", "completed"}
RAW_REQUIRED = {
    "schema_version", "id", "created", "source", "topic", "kind", "scope",
    "activation", "record_type", "summary", "compile_status",
}
RAW_OPTIONAL = {
    "project_id", "derived_from", "covers", "supersedes", "conflicts_with",
    "resolved_by", "review_note", "reviewed_at",
}
@dataclass
class Issue:
    code: str
    message: str
    path: str | None = None
    severity: str = "degraded"

    def format(self) -> str:
        prefix = f"{self.path}: " if self.path else ""
        return f"[{self.code}] {prefix}{self.message}"


@dataclass
class RawRecord:
    path: Path
    metadata: dict[str, Any]
    body: str


@dataclass
class ProjectContract:
    path: Path
    metadata: dict[str, Any]


def project_keys_by_id(contracts: Iterable[ProjectContract]) -> dict[str, str]:
    """Return only unambiguous human-facing keys for project output paths."""
    grouped: dict[str, list[str]] = {}
    for contract in contracts:
        project_id = contract.metadata.get("project_id")
        project_key = contract.metadata.get("project_key")
        if isinstance(project_id, str) and isinstance(project_key, str):
            grouped.setdefault(project_key, []).append(project_id)
    return {
        project_id: project_key
        for project_key, project_ids in grouped.items()
        if len(project_ids) == 1
        for project_id in project_ids
    }


def parse_date_value(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle.read())


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing YAML frontmatter opening delimiter")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("missing YAML frontmatter closing delimiter")
    metadata = yaml.safe_load("".join(lines[1:end])) or {}
    if not isinstance(metadata, dict):
        raise ValueError("frontmatter must parse to a mapping")
    return metadata, "".join(lines[end + 1 :])


def dump_frontmatter(metadata: dict[str, Any], body: str) -> str:
    front = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    body = body if body.startswith("\n") or not body else "\n" + body
    return f"---\n{front}\n---{body}"


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


REQUIRED_TOP = {"schema_version", "paths", "skills", "clients"}
# ：已知可选键；未知键拒绝且错误信息列出违规键名
OPTIONAL_TOP = {"output", "knowledge_root", "git"}


def load_config(root: Path) -> dict[str, Any]:
    path = root / "config.yaml"
    data = load_yaml(path)
    if not isinstance(data, dict) or data.get("schema_version") != CONFIG_SCHEMA:
        raise ValueError(f"{path}: config schema required: {CONFIG_SCHEMA}")
    missing = REQUIRED_TOP - set(data)
    unknown = set(data) - REQUIRED_TOP - OPTIONAL_TOP
    if missing or unknown:
        parts = []
        if missing:
            parts.append(f"missing required fields: {', '.join(sorted(missing))}")
        if unknown:
            parts.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise ValueError(f"{path}: invalid top-level fields:{'；'.join(parts)}")
    required_paths = {"raw", "memory_index", "project_registry", "knowledge_registry", "current_state", "corrections", "bootstrap", "knowledge_map"}
    paths = data.get("paths")
    if not isinstance(paths, dict) or set(paths) != required_paths or not all(isinstance(value, str) and value.strip() for value in paths.values()):
        raise ValueError(f"{path}: paths incomplete or contains invalid entries")
    #  containment（写入/校验侧）：memory 内路径 resolve 后必须位于 memory root 内
    root_resolved = root.resolve()
    for key, value in paths.items():
        resolved = (root / value).resolve()
        if not resolved.is_relative_to(root_resolved):
            raise ValueError(f"{path}: paths.{key} escapes the memory root: {value}")
    output = data.get("output")
    if output is not None:
        if not isinstance(output, dict):
            raise ValueError(f"{path}: output must be a mapping")
        unknown_output = set(output) - {"link_style", "link_prefix"}
        if unknown_output:
            raise ValueError(f"{path}: output unknown fields: {', '.join(sorted(unknown_output))}")
        link_style = output.get("link_style")
        if link_style is not None and link_style not in {"markdown", "wikilink"}:
            raise ValueError(f"{path}: output.link_style must be markdown or wikilink")
        link_prefix = output.get("link_prefix")
        if link_prefix is not None and not isinstance(link_prefix, str):
            raise ValueError(f"{path}: output.link_prefix must be a string")
    knowledge_root_value = data.get("knowledge_root")
    if knowledge_root_value is not None and (not isinstance(knowledge_root_value, str) or not knowledge_root_value.strip()):
        raise ValueError(f"{path}: knowledge_root must be a non-empty relative path (default .)")
    git_conf = data.get("git")
    if git_conf is not None:
        # 编译后自动提交段：唯一键 auto_commit，必须显式布尔（缺省=关闭）
        if not isinstance(git_conf, dict):
            raise ValueError(f"{path}: git must be a mapping")
        unknown_git = set(git_conf) - {"auto_commit"}
        if unknown_git:
            raise ValueError(f"{path}: git unknown fields: {', '.join(sorted(unknown_git))}")
        if git_conf.get("auto_commit") is not None and not isinstance(git_conf.get("auto_commit"), bool):
            raise ValueError(f"{path}: git.auto_commit must be a boolean")
    skills = data.get("skills")
    if not isinstance(skills, list) or not skills or not all(isinstance(value, str) and value.strip() for value in skills):
        raise ValueError(f"{path}: skills must be a non-empty list of strings")
    clients = data.get("clients")
    if not isinstance(clients, dict) or not clients:
        raise ValueError(f"{path}: clients must be a non-empty mapping")
    required_client = {"enabled", "bridge_path", "skills_root", "mode"}
    for name, settings in clients.items():
        if not isinstance(settings, dict) or set(settings) != required_client:
            raise ValueError(f"{path}: client {name} fields incomplete")
        if not isinstance(settings.get("enabled"), bool):
            raise ValueError(f"{path}: client {name}.enabled must be a boolean")
        if settings.get("mode") not in {"import", "inline"}:
            raise ValueError(f"{path}: client {name}.mode must be import or inline")
        for field in ("bridge_path", "skills_root"):
            if not isinstance(settings.get(field), str) or not settings[field].strip():
                raise ValueError(f"{path}: client {name}.{field} must be a non-empty path")
    return data


def resolve_knowledge_root(root: Path, config: dict[str, Any] | None = None) -> Path:
    """知识条目路径基：默认 `.`（=memory root）；作者 `..`（=vault 根）零迁移。"""
    if config is None:
        config = load_config(root)
    value = config.get("knowledge_root") or "."
    return (root / value).resolve()


def registry_kind_for(project: Path, memory_root: Path) -> tuple[str, str]:
    """ kind 写值（两行唯一解）：root 内 → vault + POSIX 相对路径（`.` 表示根自身）；
    root 外 → external + 展开 ~ 并 resolve 的绝对路径。既有条目的 kind/path 永不改写，
    由写入口保证（ 的 register 接线）。"""
    resolved = Path(os.path.expanduser(str(project))).resolve()
    root = memory_root.resolve()
    if resolved == root or resolved.is_relative_to(root):
        rel = resolved.relative_to(root)
        return "vault", "." if str(rel) == "." else rel.as_posix()
    return "external", str(resolved)


def resolve_config_path(root: Path, value: str) -> Path:
    return root / value


def validate_uuid(value: Any, field: str, path: str) -> list[Issue]:
    if not isinstance(value, str):
        return [Issue("FIELD_TYPE", f"{field} must be a UUID string", path)]
    raw = value.removeprefix("mem-").removeprefix("proj-")
    try:
        UUID(raw)
    except (ValueError, AttributeError):
        return [Issue("FIELD_VALUE", f"{field} is not a valid UUID", path)]
    return []


def validate_id_list(value: Any, field: str, path: str) -> list[Issue]:
    if value in (None, [], ""):
        return []
    if not isinstance(value, list):
        return [Issue("FIELD_TYPE", f"{field} must be a list of memory IDs", path)]
    issues: list[Issue] = []
    for item in value:
        if not isinstance(item, str) or not item.startswith("mem-"):
            issues.append(Issue("FIELD_VALUE", f"{field} contains invalid memory id: {item}", path))
        else:
            issues.extend(validate_uuid(item, field, path))
    return issues


def validate_raw(metadata: dict[str, Any], path: Path | str) -> list[Issue]:
    path_text = str(path)
    issues: list[Issue] = []
    missing = sorted(RAW_REQUIRED - metadata.keys())
    if missing:
        return [Issue("RAW_SCHEMA", f"missing fields: {', '.join(missing)}", path_text)]
    unexpected = sorted(set(metadata) - RAW_REQUIRED - RAW_OPTIONAL)
    if unexpected:
        issues.append(Issue("RAW_SCHEMA", f"undefined fields present: {', '.join(unexpected)}", path_text))
    if metadata.get("schema_version") != RAW_SCHEMA:
        issues.append(Issue("RAW_SCHEMA", f"schema_version must be {RAW_SCHEMA}", path_text))
    issues.extend(validate_uuid(metadata.get("id"), "id", path_text))
    created_date = parse_date_value(metadata.get("created"))
    if not created_date:
        issues.append(Issue("FIELD_VALUE", "created must be YYYY-MM-DD", path_text))
    elif created_date > dt.date.today():
        # 未来日期不阻断（迁移数据可能有钟差），但如实提示核对（观测项 O1 → C4）
        issues.append(Issue("FIELD_VALUE", "created is in the future; verify the record date", path_text, severity="warning"))
    for field, values in (("kind", KINDS), ("scope", SCOPES), ("activation", ACTIVATIONS),
                          ("record_type", RECORD_TYPES), ("compile_status", COMPILE_STATUSES)):
        if metadata.get(field) not in values:
            issues.append(Issue("FIELD_VALUE", f"{field} not in the allowed enum", path_text))
    if metadata.get("source") not in SOURCES:
        issues.append(Issue("FIELD_VALUE", "source not in the allowed enum", path_text))
    if not isinstance(metadata.get("topic"), str) or not metadata["topic"].strip():
        issues.append(Issue("FIELD_VALUE", "topic must be a non-empty string", path_text))
    if not isinstance(metadata.get("summary"), str) or not metadata["summary"].strip():
        issues.append(Issue("FIELD_VALUE", "summary must be a non-empty string", path_text))
    scope = metadata.get("scope")
    project_id = metadata.get("project_id")
    if scope == "project":
        if not project_id:
            issues.append(Issue("FIELD_VALUE", "project_id is required when scope=project", path_text))
        else:
            issues.extend(validate_uuid(project_id, "project_id", path_text))
    elif project_id not in (None, ""):
        issues.append(Issue("FIELD_VALUE", "non-project scope must not set project_id", path_text))
    record_type = metadata.get("record_type")
    derived = metadata.get("derived_from")
    covers = metadata.get("covers")
    if record_type == "source" and derived not in (None, [], ""):
        issues.append(Issue("RELATION_TYPE", "source must not set derived_from", path_text))
    if record_type == "synthesis" and (not isinstance(derived, list) or not derived):
        issues.append(Issue("RELATION_TYPE", "synthesis requires non-empty derived_from", path_text))
    if record_type != "synthesis" and covers not in (None, [], ""):
        issues.append(Issue("RELATION_TYPE", "only synthesis may set covers", path_text))
    for field in ("derived_from", "covers", "supersedes", "conflicts_with"):
        issues.extend(validate_id_list(metadata.get(field), field, path_text))
    resolved_by = metadata.get("resolved_by")
    if resolved_by is not None and (not isinstance(resolved_by, str) or not resolved_by.startswith("mem-")):
        issues.append(Issue("FIELD_VALUE", "resolved_by must be a memory id", path_text))
    elif resolved_by is not None:
        issues.extend(validate_uuid(resolved_by, "resolved_by", path_text))
    reviewed_at = metadata.get("reviewed_at")
    if reviewed_at is not None and not parse_date_value(reviewed_at):
        issues.append(Issue("FIELD_VALUE", "reviewed_at must be YYYY-MM-DD", path_text))
    if metadata.get("compile_status") == "rejected":
        if not metadata.get("review_note") or not reviewed_at:
            issues.append(Issue("FIELD_VALUE", "rejected requires review_note and reviewed_at", path_text))
    issues.extend(_field_issues(metadata, path))
    return issues


from hongzhao import fields as _fields  # ：渲染字段约束（写入入口拒绝，validate 侧同样触发）


def _field_issues(metadata: dict[str, Any], path: Path | str) -> list[Issue]:
    """：进入渲染的字段约束（单行/≤300/无控制字符）——拒绝不截断。"""
    return [
        Issue(code, message, str(path))
        for message, code in _fields.check_fields(metadata, _fields.RENDER_FIELDS, str(path))
    ]


def load_raw(root: Path) -> tuple[list[RawRecord], list[Issue]]:
    config = load_config(root)
    raw_dir = resolve_config_path(root, config["paths"]["raw"])
    records: list[RawRecord] = []
    issues: list[Issue] = []
    if not raw_dir.is_dir():
        return [], [Issue("RAW_DIR_MISSING", "raw directory missing", str(raw_dir))]
    for path in sorted(raw_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            metadata, body = parse_frontmatter(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            issues.append(Issue("RAW_PARSE", str(exc), str(path.relative_to(root))))
            continue
        records.append(RawRecord(path, metadata, body))
        issues.extend(validate_raw(metadata, path.relative_to(root)))
    return records, issues


def load_registry(root: Path) -> tuple[dict[str, Any], list[Issue]]:
    config = load_config(root)
    path = resolve_config_path(root, config["paths"]["project_registry"])
    if not path.exists():
        return {"schema_version": REGISTRY_SCHEMA, "projects": []}, [Issue("REGISTRY_MISSING", "project registry missing", str(path))]
    issues: list[Issue] = []
    try:
        data = load_yaml(path)
    except (OSError, yaml.YAMLError) as exc:
        return {}, [Issue("REGISTRY_PARSE", str(exc), str(path.relative_to(root)))]
    if not isinstance(data, dict) or data.get("schema_version") != REGISTRY_SCHEMA:
        return {}, [Issue("REGISTRY_SCHEMA", f"schema_version must be {REGISTRY_SCHEMA}", str(path.relative_to(root)))]
    projects = data.get("projects", [])
    if not isinstance(projects, list):
        return {}, [Issue("REGISTRY_SCHEMA", "projects must be a list", str(path.relative_to(root)))]
    seen: set[str] = set()
    for entry in projects:
        if not isinstance(entry, dict):
            issues.append(Issue("REGISTRY_SCHEMA", "project entry must be an object", str(path.relative_to(root))))
            continue
        unexpected = sorted(set(entry) - {"project_id", "location", "registered_at", "last_checked_at"})
        if unexpected:
            issues.append(Issue("REGISTRY_SCHEMA", f"project entry has undefined fields: {', '.join(unexpected)}", str(path.relative_to(root))))
        project_id = entry.get("project_id")
        if project_id in seen:
            issues.append(Issue("REGISTRY_DUPLICATE", f"duplicate project_id: {project_id}", str(path.relative_to(root))))
        seen.add(project_id)
        issues.extend(validate_uuid(project_id, "project_id", str(path.relative_to(root))))
        location = entry.get("location")
        if not isinstance(location, dict) or location.get("kind") not in {"vault", "external"}:
            issues.append(Issue("REGISTRY_SCHEMA", "location.kind must be vault or external", str(path.relative_to(root))))
        elif not isinstance(location.get("path"), str) or not location["path"].strip():
            issues.append(Issue("REGISTRY_SCHEMA", "location.path must be a non-empty string", str(path.relative_to(root))))
        elif set(location) - {"kind", "path"}:
            issues.append(Issue("REGISTRY_SCHEMA", "location allows only kind and path", str(path.relative_to(root))))
        elif location.get("kind") == "external" and not Path(os.path.expanduser(location["path"])).is_absolute():
            issues.append(Issue("REGISTRY_SCHEMA", "external location.path must be an absolute path", str(path.relative_to(root))))
        for field in ("registered_at", "last_checked_at"):
            if entry.get(field) is not None and not parse_date_value(entry[field]):
                issues.append(Issue("REGISTRY_SCHEMA", f"{field} must be YYYY-MM-DD", str(path.relative_to(root))))
    return data, issues


def load_knowledge_registry(root: Path) -> tuple[dict[str, Any], list[Issue]]:
    config = load_config(root)
    path = resolve_config_path(root, config["paths"]["knowledge_registry"])
    if not path.exists():
        return {"schema_version": KNOWLEDGE_SCHEMA, "knowledge": []}, [Issue("KNOWLEDGE_REGISTRY_MISSING", "knowledge registry missing", str(path))]
    issues: list[Issue] = []
    try:
        data = load_yaml(path)
    except (OSError, yaml.YAMLError) as exc:
        return {}, [Issue("KNOWLEDGE_REGISTRY_PARSE", str(exc), str(path.relative_to(root)))]
    if not isinstance(data, dict) or data.get("schema_version") != KNOWLEDGE_SCHEMA:
        return {}, [Issue("KNOWLEDGE_SCHEMA", f"schema_version must be {KNOWLEDGE_SCHEMA}", str(path.relative_to(root)))]
    entries = data.get("knowledge", [])
    if not isinstance(entries, list):
        return {}, [Issue("KNOWLEDGE_SCHEMA", "knowledge must be a list", str(path.relative_to(root)))]
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            issues.append(Issue("KNOWLEDGE_SCHEMA", "knowledge entry must be an object", str(path.relative_to(root))))
            continue
        unexpected = sorted(set(entry) - {"path", "title", "topics", "summary", "registered_at", "last_checked_at"})
        if unexpected:
            issues.append(Issue("KNOWLEDGE_SCHEMA", f"knowledge entry has undefined fields: {', '.join(unexpected)}", str(path.relative_to(root))))
        entry_path = entry.get("path")
        if not isinstance(entry_path, str) or not entry_path.strip():
            issues.append(Issue("KNOWLEDGE_SCHEMA", "path must be a non-empty string", str(path.relative_to(root))))
        elif Path(entry_path).is_absolute() or ".." in Path(entry_path).parts or entry_path.endswith("/"):
            issues.append(Issue("KNOWLEDGE_SCHEMA", f"path must be relative without '..' and not ending in '/': {entry_path}", str(path.relative_to(root))))
        elif entry_path in seen:
            issues.append(Issue("KNOWLEDGE_DUPLICATE", f"duplicate path: {entry_path}", str(path.relative_to(root))))
        else:
            seen.add(entry_path)
        for field in ("title", "summary"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                issues.append(Issue("KNOWLEDGE_SCHEMA", f"{field} must be a non-empty string", str(path.relative_to(root))))
        topics = entry.get("topics")
        if not isinstance(topics, list) or not topics or not all(isinstance(t, str) and t.strip() for t in topics):
            issues.append(Issue("KNOWLEDGE_SCHEMA", "topics must be a non-empty list of strings", str(path.relative_to(root))))
        for field in ("registered_at", "last_checked_at"):
            if entry.get(field) is not None and not parse_date_value(entry[field]):
                issues.append(Issue("KNOWLEDGE_SCHEMA", f"{field} must be YYYY-MM-DD", str(path.relative_to(root))))
    return data, issues


def validate_knowledge_paths(root: Path, registry: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    for entry in registry.get("knowledge", []) or []:
        if not isinstance(entry, dict):
            continue
        entry_path = entry.get("path")
        if not isinstance(entry_path, str) or not entry_path.strip():
            continue
        if Path(entry_path).is_absolute() or ".." in Path(entry_path).parts:
            continue
        # ：基由隐含 root.parent 参数化为 knowledge_root（默认 .，作者 ..）；条目必须落在其内
        base = resolve_knowledge_root(root)
        target = (base / entry_path).resolve()
        if not target.is_relative_to(base):
            issues.append(Issue("KNOWLEDGE_SCHEMA", f"knowledge path escapes knowledge_root: {entry_path}", str(target)))
            continue
        if not target.exists():
            issues.append(Issue("KNOWLEDGE_PATH_MISSING", f"knowledge path missing: {entry_path}", str(target)))
    return issues


def project_root(root: Path, entry: dict[str, Any]) -> Path:
    location = entry["location"]
    if location["kind"] == "vault":
        return (root / location["path"]).resolve()
    return Path(os.path.expanduser(location["path"])).resolve()


def is_project_archive_path(path: str) -> bool:
    return any(part.casefold() in PROJECT_ARCHIVE_DIR_NAMES for part in Path(path).parts)


def validate_project_contract(metadata: dict[str, Any], path: Path | str, expected_id: str | None = None) -> list[Issue]:
    path_text = str(path)
    required = {"schema_version", "project_id", "project_key", "project_name", "updated_at", "status", "purpose", "current_state", "next_action", "entrypoints", "activation"}
    issues: list[Issue] = []
    missing = sorted(required - metadata.keys())
    if missing:
        return [Issue("CONTRACT_SCHEMA", f"missing fields: {', '.join(missing)}", path_text)]
    unexpected = sorted(set(metadata) - required)
    if unexpected:
        issues.append(Issue("CONTRACT_SCHEMA", f"undefined fields present: {', '.join(unexpected)}", path_text))
    if metadata.get("schema_version") != CONTRACT_SCHEMA:
        issues.append(Issue("CONTRACT_SCHEMA", f"schema_version must be {CONTRACT_SCHEMA}", path_text))
    issues.extend(validate_uuid(metadata.get("project_id"), "project_id", path_text))
    if expected_id and metadata.get("project_id") != expected_id:
        issues.append(Issue("CONTRACT_ID", f"project_id should be {expected_id}", path_text))
    project_key = metadata.get("project_key")
    if not isinstance(project_key, str) or not PROJECT_KEY_PATTERN.fullmatch(project_key):
        issues.append(Issue("CONTRACT_VALUE", "project_key must be a stable key of lowercase letters, digits and hyphens", path_text))
    if metadata.get("status") not in PROJECT_STATUSES:
        issues.append(Issue("CONTRACT_VALUE", "status not in the allowed enum", path_text))
    if metadata.get("activation") not in ACTIVATIONS:
        issues.append(Issue("CONTRACT_VALUE", "activation not in the allowed enum", path_text))
    for field in ("project_name", "purpose", "current_state", "next_action"):
        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
            issues.append(Issue("CONTRACT_VALUE", f"{field} must be a non-empty string", path_text))
    if not parse_date_value(metadata.get("updated_at")):
        issues.append(Issue("CONTRACT_VALUE", "updated_at must be YYYY-MM-DD", path_text))
    entrypoints = metadata.get("entrypoints")
    if not isinstance(entrypoints, list):
        issues.append(Issue("CONTRACT_VALUE", "entrypoints must be a list", path_text))
    else:
        for item in entrypoints:
            if not isinstance(item, str) or not item.strip():
                issues.append(Issue("CONTRACT_VALUE", "entrypoints each item must be a non-empty relative path string", path_text))
            elif Path(item).is_absolute() or ".." in Path(item).parts:
                issues.append(Issue("CONTRACT_VALUE", "entrypoints must be relative to the project root", path_text))
            elif is_project_archive_path(item):
                issues.append(Issue("CONTRACT_ARCHIVE_ENTRYPOINT", "entrypoints must not point into an Archive/99-Archive directory", path_text))
    return issues


def _central_contract_by_id(root: Path) -> dict[str, Path]:
    """集 A：`projects/*/project-view.md`（中央契约），按 project_id 索引。

    与 contracts.contract_state_issues 的发现口径一致（空目录自然不命中）；
    core 不得 import contracts（反向依赖），故内联实现。
    """
    by_id: dict[str, Path] = {}
    central_dir = root / "projects"
    if not central_dir.is_dir():
        return by_id
    for contract_path in sorted(central_dir.glob(f"*/{PROJECT_CONTEXT_FILENAME}")):
        try:
            metadata, _ = parse_frontmatter(contract_path)
        except (OSError, ValueError, yaml.YAMLError):
            continue
        pid = metadata.get("project_id")
        if isinstance(pid, str):
            by_id[pid] = contract_path
    return by_id


def load_contracts(root: Path, registry: dict[str, Any]) -> tuple[list[ProjectContract], list[Issue]]:
    contracts: list[ProjectContract] = []
    issues: list[Issue] = []
    seen_keys: dict[str, Path] = {}
    central_by_id = _central_contract_by_id(root)
    for entry in registry.get("projects", []):
        project_id = entry.get("project_id")
        location = entry.get("location")
        if not isinstance(location, dict) or location.get("kind") not in {"vault", "external"} or not isinstance(location.get("path"), str):
            continue
        project = project_root(root, entry)
        contract_path = project / PROJECT_CONTEXT_FILENAME
        if contract_path.exists():
            # 根契约与中央契约并存=重复（doctor 同口径）：仍按根契约解析，但如实报错，
            # 不让 compile/validate 比 doctor 更乐观（三命令一致性）。
            central = central_by_id.get(str(project_id)) if project_id is not None else None
            if central is not None:
                issues.append(Issue(
                    "CONTRACT_DUPLICATE",
                    f"id {project_id} exists both as central and project-root contract; "
                    "fix: confirm which copy is canonical, then remove the other",
                    str(central),
                ))
        else:
            # J6 新建的是中央契约（projects/<key>/project-view.md）——项目根没有契约时
            # 回退到中央契约解析，与 doctor 的 contract_state_issues 口径一致
            # （此前缺这条回退：register 成功后 compile 立即 CONTRACT_MISSING）。
            central = central_by_id.get(str(project_id)) if project_id is not None else None
            if central is not None:
                contract_path = central
            else:
                issues.append(Issue("CONTRACT_MISSING", "project contract missing", str(contract_path)))
                continue
        try:
            metadata, _ = parse_frontmatter(contract_path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            issues.append(Issue("CONTRACT_PARSE", str(exc), str(contract_path)))
            continue
        contract_issues = validate_project_contract(metadata, contract_path, project_id)
        issues.extend(contract_issues)
        if not contract_issues:
            project_key = metadata["project_key"]
            if project_key in seen_keys:
                issues.append(Issue("CONTRACT_KEY_DUPLICATE", f"duplicate project_key: {project_key}", str(contract_path)))
            else:
                seen_keys[project_key] = contract_path
            contracts.append(ProjectContract(contract_path, metadata))
    return contracts, issues

