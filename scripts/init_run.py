#!/usr/bin/env python3
"""Initialize one auditable daily-quote art-direction run."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Run date in YYYY-MM-DD")
    parser.add_argument("--slug", required=True, help="Lowercase short identifier")
    parser.add_argument("--out-dir", required=True, help="New run directory")
    parser.add_argument("--rendering-mode", choices=("integrated_image_text", "local_typesetting"), default="integrated_image_text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        run_date = date.fromisoformat(args.date)
    except ValueError:
        print("ERROR: --date must be a valid YYYY-MM-DD date", file=sys.stderr)
        return 2

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.slug):
        print("ERROR: --slug must use lowercase letters, digits, and hyphens", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir).expanduser().resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        print(f"ERROR: output directory is not empty: {out_dir}", file=sys.stderr)
        return 2

    template = Path(__file__).resolve().parent.parent / "assets" / "design-record.template.json"
    if not template.is_file():
        print(f"ERROR: missing template: {template}", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("sources", "backgrounds", "layout", "previews"):
        (out_dir / name).mkdir()

    record_path = out_dir / "design-record.json"
    shutil.copyfile(template, record_path)

    data = json.loads(record_path.read_text(encoding="utf-8"))
    data["run"]["date"] = args.date
    data["run"]["rendering_mode"] = args.rendering_mode
    data["run"]["meaning_grounding_required"] = True
    data["run"]["weekday"] = (
        "星期一",
        "星期二",
        "星期三",
        "星期四",
        "星期五",
        "星期六",
        "星期日",
    )[run_date.weekday()]
    data["run"]["slug"] = args.slug
    data["run"]["initialized_at"] = datetime.now(
        ZoneInfo(data["run"]["timezone"])
    ).isoformat(timespec="seconds")
    data["layout"]["date_text"] = args.date
    record_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(record_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
