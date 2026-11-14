"""CI 失败摘要：解析 pytest junitxml，把失败用例与栈顶写入 run summary。

背景：公开仓的 Actions 日志下载需要鉴权，Windows 腿失败时排障靠盲猜；
run summary 对公开仓匿名可读，把失败清单放那里可自取。
用法：python scripts/ci_failure_summary.py report.xml（输出 Markdown 到 stdout）。
"""
from __future__ import annotations

import platform
import sys
import xml.etree.ElementTree as ET


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
    if len(sys.argv) != 2:
        print("usage: ci_failure_summary.py <junit.xml>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
