#!/usr/bin/env python3
"""从场景定义导出 expected.yaml 到运行目录（record_asserts 类断言由专项脚本核对）。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_layer(layer: str):
    spec = importlib.util.spec_from_file_location(f"defs_{layer}", REPO / "eval" / "scenarios" / layer / "definitions.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return [getattr(mod, name) for name in dir(mod) if name[0] in "SE" and isinstance(getattr(mod, name), dict) and "id" in getattr(mod, name)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    for sc in load_layer(args.layer):
        if sc["id"] == args.scenario:
            Path(args.out).write_text(yaml_dump(sc["expected"]), encoding="utf-8")
            print(json.dumps({"exported": args.scenario, "out": args.out}))
            return 0
    print(json.dumps({"error": f"scenario {args.scenario} not found in {args.layer}"}))
    return 1


def yaml_dump(data) -> str:
    import yaml
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


if __name__ == "__main__":
    sys.exit(main())
