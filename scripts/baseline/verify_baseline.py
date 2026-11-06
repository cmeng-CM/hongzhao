#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-20 基线校验器（design §10.3 机判维度的 T-20 种子；T-23 扩展链接/客户端/契约/coverage 维）。

用法：python3 -B verify_baseline.py --baseline <dir> --root <memory-root>
断言（全只读，exit 0=通过）：
① 快照完整性：baseline 内每产物存在且 sha256 与 sha256.yaml 一致；
② health：root 的 memory-index health 为 degraded=0 且不劣于基线（§10.3 health 维）；
③ claim 集合：root 与基线的 effective claim id 集合相等（§10.3 claim 维，不比对文本）；
④ frontmatter 键集：root 各产物键集与基线 frontmatter-keys.yaml 一致（§10.3 键冻结口径）。
"""
import argparse
import hashlib
import sys
from pathlib import Path

import yaml


def load_index(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def effective_ids(index: dict) -> set[str]:
    records = index.get("records", {})
    if isinstance(records, dict):
        # dict 形态：id 是键名，行内无 id 字段（生产 memory-index 即此形态）
        return {rid for rid, row in records.items() if isinstance(row, dict) and row.get("effective") is True}
    return {row["id"] for row in records if isinstance(row, dict) and row.get("effective") is True and row.get("id")}


def health_value(index: dict) -> str:
    return str(index.get("health", "?"))


def frontmatter_keys(text: str) -> list[str]:
    if not text.startswith("---"):
        return []
    try:
        end = text.index("\n---", 3)
    except ValueError:
        return []
    keys = []
    for line in text[4:end].splitlines():
        if line and not line.startswith((" ", "\t", "-")) and ":" in line:
            keys.append(line.split(":", 1)[0].strip())
    return keys


def rank(health: str) -> int:
    return {"ok": 0, "review-needed": 1}.get(health, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--root", required=True)
    args = ap.parse_args()
    base, root = Path(args.baseline), Path(args.root)
    problems = []

    # ① 快照完整性
    sha = yaml.safe_load((base / "sha256.yaml").read_text(encoding="utf-8")) or {}
    if not sha:
        print("baseline sha256.yaml missing or empty")
        return 1
    for rel, digest in sorted(sha.items()):
        p = base / rel
        if not p.is_file():
            problems.append(f"missing snapshot file: {rel}")
        elif hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            problems.append(f"snapshot hash mismatch: {rel}")

    # ② health
    b_idx, r_idx = load_index(base / "compiled" / "memory-index.yaml"), load_index(root / "compiled" / "memory-index.yaml")
    b_health, r_health = health_value(b_idx), health_value(r_idx)
    if r_health != "ok" and "degraded" in r_health:
        problems.append(f"root health degraded: {r_health}")
    if rank(r_health) > rank(b_health):
        problems.append(f"root health worse than baseline: root={r_health} baseline={b_health}")

    # ③ claim 集合
    b_ids, r_ids = effective_ids(b_idx), effective_ids(r_idx)
    if b_ids != r_ids:
        problems.append(f"effective claim set differs: only-baseline={sorted(b_ids - r_ids)} only-root={sorted(r_ids - b_ids)}")

    # ④ frontmatter 键集（基线清单内的产物在 root 必须在场且键集一致）
    keys = yaml.safe_load((base / "frontmatter-keys.yaml").read_text(encoding="utf-8")) or {}
    for rel, expected in sorted(keys.items()):
        p = root / rel
        if not p.is_file():
            problems.append(f"root artifact missing: {rel}")
            continue
        if frontmatter_keys(p.read_text(encoding="utf-8")) != expected:
            problems.append(f"frontmatter key set differs: {rel}")

    if problems:
        print("BASELINE VERIFY FAILED:")
        for p in problems:
            print("  " + p)
        return 1
    print(f"baseline verify OK: {len(sha)} snapshot files, health={r_health}, effective claims={len(r_ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
