#!/usr/bin/env python3
"""Register the generated background after a valid pre-generation lock."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from record_utils import (
    atomic_write_json,
    compute_lock_hash,
    get,
    now_for_record,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", help="Path to design-record.json")
    parser.add_argument("--background", required=True, help="Generated background file")
    parser.add_argument("--attempt-id", help="Completed generation attempt ID (required for schema 1.4)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    record_path = Path(args.record).expanduser().resolve()
    background_path = Path(args.background).expanduser().resolve()

    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read record: {exc}", file=sys.stderr)
        return 2

    if not background_path.is_file():
        print(f"ERROR: background not found: {background_path}", file=sys.stderr)
        return 2

    if data.get("schema_version") in {"1.4", "1.5"}:
        from production_integrity import register_background_v14
        try:
            register_background_v14(data, record_path, background_path, args.attempt_id or "")
            atomic_write_json(record_path, data)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(background_path)
        return 0

    saved_hash = str(get(data, "pre_generation.lock_hash") or "")
    if not saved_hash or saved_hash != compute_lock_hash(data):
        print(
            "ERROR: pre-generation record is unlocked or changed after locking",
            file=sys.stderr,
        )
        return 1

    data["post_generation"]["background_path"] = str(background_path)
    data["post_generation"]["generated_at"] = now_for_record(data)
    if data.get("schema_version") == "1.3":
        data["execution_validation"].update(
            {
                "checked_at": "",
                "key_action_or_state_realized": "",
                "concept_fidelity": "",
                "text_safe_area_usable": False,
                "decision": "pending",
            }
        )
        data["semantic_cold_review"].update(
            {
                "review_input_isolated": False,
                "image_only_reviewed_at": "",
                "image_only_first_read": "",
                "dominant_misreading": "",
                "quote_revealed_at": "",
                "shared_relationship": "",
                "missing_link": "pending",
                "missing_link_note": "",
                "explanation_required": True,
                "optional_genericity_test": "",
                "full_resolution_checked": False,
                "mobile_checked": False,
                "decision": "pending",
            }
        )
    data["run"]["status"] = "background_registered"
    atomic_write_json(record_path, data)
    print(background_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
