"""字段约束与渲染转义：=300 依据批准记录）。

写入入口拒绝（不截断）：单行、≤300 字符、无控制字符——覆盖进入渲染的字段
（summary / project_name / purpose / current_state / next_action 与知识条目
title / summary / topics）。渲染层只做标记与行首 @ 转义，绝不截断。
"""
from __future__ import annotations

import re
from typing import Any, Iterable

FIELD_LIMIT = 300
# 进入渲染的 raw/契约字段与知识字段（其余字段不进渲染文本）
RENDER_FIELDS = ("summary",)
CONTRACT_RENDER_FIELDS = ("project_name", "purpose", "current_state", "next_action")
KNOWLEDGE_RENDER_FIELDS = ("title", "summary", "topics")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MANAGED_MARKER = "hongzhao:"


def _check_value(value: Any, field: str, path: str) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    if not isinstance(value, str) or not value:
        return issues
    if "\n" in value or "\r" in value:
        issues.append((f"{path}: {field} must be a single line", "FIELD_NOT_SINGLE_LINE"))
    if _CONTROL.search(value):
        issues.append((f"{path}: {field} must not contain control characters", "FIELD_CONTROL_CHAR"))
    if len(value) > FIELD_LIMIT:
        issues.append((f"{path}: {field} exceeds {FIELD_LIMIT} characters ({len(value)})", "FIELD_TOO_LONG"))
    return issues


def check_fields(metadata: dict[str, Any], fields: Iterable[str], path: str) -> list[tuple[str, str]]:
    """写入/校验入口统一调用：返回 [(消息, 错误码)]，拒绝不截断。"""
    issues: list[tuple[str, str]] = []
    for field in fields:
        issues.extend(_check_value(metadata.get(field), field, path))
    return issues


def check_knowledge_entry(entry: dict[str, Any], path: str) -> list[tuple[str, str]]:
    issues = check_fields(entry, ("title", "summary"), path)
    topics = entry.get("topics")
    if isinstance(topics, list):
        for i, topic in enumerate(topics):
            if isinstance(topic, str):
                issues.extend(_check_value(topic, f"topics[{i}]", path))
    return issues


def escape_render_text(text: str) -> str:
    """渲染层转义（不截断）：行首 @ 防注入 import 指令；托管标记防提前截断。"""
    lines = []
    for line in text.split("\n"):
        if line.lstrip().startswith("@"):
            line = "\u200b" + line  # 零宽间隔打断行首 @ 的指令语义
        line = line.replace(MANAGED_MARKER, "hongzhao\u200b:")
        line = line.replace("</hongzhao-bootstrap>", "</hongzhao\u200b-bootstrap>")
        line = line.replace("<hongzhao-bootstrap>", "<hongzhao\u200b-bootstrap>")
        lines.append(line)
    return "\n".join(lines)
