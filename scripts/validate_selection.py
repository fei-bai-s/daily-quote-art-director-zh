#!/usr/bin/env python3
"""Validate the schema 1.2+ content-selection gate before art direction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from record_utils import content_selection_errors, history_freshness_errors, v12_selection_system_errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", help="Path to design-record.json")
    parser.add_argument("--archive", action="store_true", help="Verify the saved snapshot only; not a production release gate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    record_path = Path(args.record).expanduser().resolve()
    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"ERROR: record not found: {record_path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON: {exc}", file=sys.stderr)
        return 2

    errors: list[str] = []
    if data.get("schema_version") not in {"1.2", "1.3", "1.4", "1.5"}:
        errors.append("selection validation requires schema_version 1.2, 1.3, 1.4 or 1.5")
    errors.extend(content_selection_errors(data, check_local_sources=not args.archive))
    errors.extend(v12_selection_system_errors(data, record_path, check_local_sources=not args.archive))
    if not args.archive:
        errors.extend(history_freshness_errors(data, record_path))
    if errors:
        print("SELECTION VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("ARCHIVE SELECTION VERIFICATION PASSED (not valid for new delivery)" if args.archive else "SELECTION VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
