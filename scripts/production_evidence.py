#!/usr/bin/env python3
"""Register schema 1.4 generation, layout, and staged independent review evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from record_utils import atomic_write_json
from production_integrity import complete_generation, prepare_layout, read_json, record_execution, register_background_v14, register_cold_stage1, register_cold_stage2, register_layout, start_cold_review, start_generation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("generation-start")
    start.add_argument("--attempt-id", required=True)
    start.add_argument("--prompt-file", type=Path, required=True)
    start.add_argument("--designer-context-id", required=True)
    start.add_argument("--change-note", default="")
    start.add_argument("--retry-authorization", default="", help="Actual explicit user instruction authorizing this additional integrated attempt, not model-written permission")
    complete = commands.add_parser("generation-complete")
    complete.add_argument("--attempt-id", required=True)
    complete.add_argument("--tool-result", type=Path, required=True)
    complete.add_argument("--tool-result-locator", required=True)
    complete.add_argument("--background", type=Path, required=True)
    complete.add_argument("--select", action="store_true", help="Also register this completed background; does not pass execution review")
    execution = commands.add_parser("execution")
    execution.add_argument("--result", type=Path, required=True)
    execution.add_argument("--prepare-layout", action="store_true", help="Prepare layout after a passing execution result")
    commands.add_parser("prepare-layout")
    layout = commands.add_parser("register-layout")
    layout.add_argument("--source", type=Path, required=True)
    layout.add_argument("--final", type=Path, required=True)
    layout.add_argument("--manifest", type=Path, required=True)
    integrated = commands.add_parser("register-integrated")
    integrated.add_argument("--final", type=Path, required=True)
    integrated_review = commands.add_parser("cold-integrated")
    integrated_review.add_argument("--result", type=Path, required=True)
    cold = commands.add_parser("cold-start")
    cold.add_argument("--reviewer-id", required=True)
    cold.add_argument("--reviewer-context-id", required=True)
    for name in ("cold-stage1", "cold-stage2"):
        command = commands.add_parser(name)
        command.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    record_path = Path(args.record).expanduser().resolve()
    try:
        data = read_json(record_path)
        result = None
        if args.command == "generation-start":
            result = start_generation(data, record_path, args.attempt_id, args.prompt_file, args.designer_context_id, args.change_note, args.retry_authorization)
        elif args.command == "generation-complete":
            result = complete_generation(data, record_path, args.attempt_id, args.tool_result, args.tool_result_locator, args.background)
            if args.select:
                register_background_v14(data, record_path, args.background, args.attempt_id)
        elif args.command == "execution":
            record_execution(data, record_path, args.result)
            if args.prepare_layout:
                result = prepare_layout(data, record_path)
        elif args.command == "prepare-layout":
            result = prepare_layout(data, record_path)
        elif args.command == "register-layout":
            register_layout(data, record_path, args.source, args.final, args.manifest)
        elif args.command == "register-integrated":
            from integrated_production import register_integrated
            result = register_integrated(data, record_path, args.final)
        elif args.command == "cold-integrated":
            from integrated_production import register_integrated_review
            register_integrated_review(data, record_path, args.result)
        elif args.command == "cold-start":
            result = start_cold_review(data, record_path, args.reviewer_id, args.reviewer_context_id)
        elif args.command == "cold-stage1":
            result = register_cold_stage1(data, record_path, args.result)
        elif args.command == "cold-stage2":
            register_cold_stage2(data, record_path, args.result)
        atomic_write_json(record_path, data)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"EVIDENCE REGISTRATION FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result or {"status": "registered", "command": args.command}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
