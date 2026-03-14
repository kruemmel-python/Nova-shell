from __future__ import annotations

import argparse
import json
from pathlib import Path

from nova.compiler import NovaGraphBuilder, NovaValidator
from nova.parser import NovaParser
from nova.runtime import RuntimeExecutor


def _load_program(ns_file: str) -> tuple[str, object]:
    source = Path(ns_file).read_text(encoding="utf-8")
    parser = NovaParser()
    program = parser.parse(source)
    return source, program


def cmd_build(ns_file: str) -> int:
    _source, program = _load_program(ns_file)
    validator = NovaValidator()
    validation = validator.validate(program)
    if not validation.valid:
        print(json.dumps({"valid": False, "errors": validation.errors}, indent=2))
        return 1

    builder = NovaGraphBuilder()
    _, plan = builder.build(program)
    print(json.dumps({"valid": True, "graph": plan.to_dict()}, indent=2))
    return 0


def cmd_graph(ns_file: str) -> int:
    _source, program = _load_program(ns_file)
    builder = NovaGraphBuilder()
    _, plan = builder.build(program)
    print("digraph nova {")
    for node in plan.nodes:
        print(f'  "{node["id"]}" [label="{node["kind"]}:{node["id"].split(":", 1)[1]}"];')
    for edge in plan.edges:
        print(f'  "{edge["source"]}" -> "{edge["target"]}" [label="{edge["relation"]}"];')
    print("}")
    return 0


def cmd_plan(ns_file: str) -> int:
    _source, program = _load_program(ns_file)
    validator = NovaValidator()
    validation = validator.validate(program)
    if not validation.valid:
        print("Validation errors:")
        for err in validation.errors:
            print(f"- {err}")
        return 1
    builder = NovaGraphBuilder()
    for line in builder.render_plan(program):
        print(line)
    return 0


def cmd_run(ns_file: str) -> int:
    source, program = _load_program(ns_file)
    validator = NovaValidator()
    validation = validator.validate(program)
    if not validation.valid:
        print(json.dumps({"valid": False, "errors": validation.errors}, indent=2))
        return 1

    executor = RuntimeExecutor()
    result = executor.execute(source)
    print(json.dumps({"schedule": result.schedule, "results": result.flow_results}, indent=2))
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nova", description="Nova language compiler and runtime CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("build", "run", "graph", "plan"):
        cmd = sub.add_parser(name)
        cmd.add_argument("file", help="Path to .ns program")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    match args.command:
        case "build":
            return cmd_build(args.file)
        case "run":
            return cmd_run(args.file)
        case "graph":
            return cmd_graph(args.file)
        case "plan":
            return cmd_plan(args.file)
        case _:
            parser.error("unknown command")
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
