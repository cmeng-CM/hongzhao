"""CI 失败摘要：解析 pytest junitxml，把失败用例与栈顶写入 run summary。

背景：公开仓的 Actions 日志下载需要鉴权，Windows 腿失败时排障靠盲猜；
两条匿名可读通道：①run summary（网页）②`--annotations` 模式输出 workflow
`::error` 命令 → check-run annotations（API 公开，最可靠的自取路径）。
用法：
  python scripts/ci_failure_summary.py report.xml            # Markdown 到 stdout
  python scripts/ci_failure_summary.py --annotations report.xml  # ::error 命令到 stdout
"""
from __future__ import annotations

import platform
import sys
import xml.etree.ElementTree as ET


def _iter_failures(root: ET.Element):
    for case in root.iter("testcase"):
        for kind in ("failure", "error"):
            node = case.find(kind)
            if node is not None:
                yield case.get("classname", "?"), case.get("name", "?"), kind, node
                break


def _annotations(root: ET.Element) -> int:
    """workflow 命令模式：每条失败一枚 ::error 注解（title=用例，message=栈顶摘要）。"""
    count = 0
    for classname, name, kind, node in _iter_failures(root):
        if count >= 10:  # GitHub 每步注解上限 10，超量截断
            print("::error title=more-failures::(annotations truncated; see summary)")
            break
        text = (node.text or node.get("message") or "").strip().splitlines()
        meaningful = [ln.strip() for ln in text if ln.strip()]
        head = " | ".join(meaningful[:4])[:400]
        title = f"{classname}::{name}".replace("::", "»")  # :: 是命令分隔符，替换
        message = head.replace("\r", " ").replace("\n", " ")
        print(f"::error title={kind} {title}::{message}")
        count += 1
    return 0


def main(path: str) -> int:
    tree = ET.parse(path)
    root = tree.getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    print(f"## CI 失败摘要（{platform.system()} / Python {platform.python_version()}）")
    print(f"\n- locale preferred encoding: `{sys.getdefaultencoding()}` / fs: `{sys.getfilesystemencoding()}`")
    if suite is not None:
        print(f"- totals: {suite.get('tests')} tests, {suite.get('failures')} failures, "
              f"{suite.get('errors')} errors, {suite.get('skipped')} skipped, {suite.get('time')}s")
    cases = root.iter("testcase")
    failures = []
    for case in cases:
        for kind in ("failure", "error"):
            node = case.find(kind)
            if node is not None:
                failures.append((case.get("classname", "?"), case.get("name", "?"), kind, node))
                break
    if not failures:
        print("\n（junitxml 中无失败条目）")
        return 0
    print(f"\n共 {len(failures)} 个失败/错误用例：\n")
    for classname, name, kind, node in failures:
        print(f"### {kind}: `{classname}::{name}`\n")
        text = (node.text or node.get("message", "")).strip()
        lines = [line for line in text.splitlines() if line.strip()]
        head = lines[:12]
        print("```\n" + "\n".join(head) + ("\n…（截断）" if len(lines) > 12 else "") + "\n```\n")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    annotations = "--annotations" in sys.argv
    if len(args) != 1:
        print("usage: ci_failure_summary.py [--annotations] <junit.xml>", file=sys.stderr)
        raise SystemExit(2)
    # 自曝：任何崩溃都转成 ::error 注解（本脚本曾作为排障通道自身失败且不可见）
    import os

    try:
        root = ET.parse(args[0]).getroot()
    except Exception as exc:  # noqa: BLE001 —— 诊断脚本要活过一切
        exists = os.path.exists(args[0])
        size = os.path.getsize(args[0]) if exists else -1
        msg = f"{type(exc).__name__}: {exc} | cwd={os.getcwd()} | file={args[0]} exists={exists} size={size}"
        print(f"::error title=summary-script-crashed::{msg[:400]}")
        raise SystemExit(0)
    if annotations:
        raise SystemExit(_annotations(root))
    raise SystemExit(main(args[0]))
