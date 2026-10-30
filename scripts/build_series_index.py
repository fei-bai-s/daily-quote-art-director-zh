#!/usr/bin/env python3
"""Build a deterministic history index from delivered daily-quote records."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from record_utils import atomic_write_json, history_source_sha256, normalize_quote


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", required=True, help="Directory containing run folders")
    parser.add_argument("--out", required=True, help="Output series-index.json path")
    return parser.parse_args()


def read_record(path: Path) -> tuple[dict[str, Any], str] | None:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: unreadable history record {path}: {exc}", file=sys.stderr)
        return None
    return (value, history_source_sha256(value)) if isinstance(value, dict) else None


def nonempty(value: Any) -> str:
    return str(value or "").strip()


def main() -> int:
    args = parse_args()
    runs_dir = Path(args.runs_dir).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    if not runs_dir.is_dir():
        print(f"ERROR: runs directory not found: {runs_dir}", file=sys.stderr)
        return 2

    delivered_groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    exposure_groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    records_read = 0
    history_errors: list[str] = []
    source_manifest: list[dict[str, str]] = []

    for record_path in sorted(runs_dir.glob("*/design-record.json")):
        loaded = read_record(record_path)
        if loaded is None:
            history_errors.append(f"unreadable record: {record_path}")
            continue
        data, source_hash = loaded
        source_manifest.append({"path": str(record_path), "sha256": source_hash})
        records_read += 1
        run = data.get("run") if isinstance(data.get("run"), dict) else {}
        content = data.get("content") if isinstance(data.get("content"), dict) else {}
        selection = (
            data.get("content_selection")
            if isinstance(data.get("content_selection"), dict)
            else {}
        )
        run_date = nonempty(run.get("date"))
        selected_candidate: dict[str, Any] = {}

        candidates = selection.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                text = nonempty(candidate.get("text"))
                author = nonempty(candidate.get("author"))
                if not run_date or not text or not author:
                    continue
                key = (run_date, normalize_quote(text), author)
                row = exposure_groups.setdefault(
                    key,
                    {
                        "date": run_date,
                        "normalized_text": key[1],
                        "text": text,
                        "author": author,
                        "work": nonempty(candidate.get("work")),
                        "decisions": set(),
                        "record_paths": set(),
                    },
                )
                row["decisions"].add(nonempty(candidate.get("decision")))
                row["record_paths"].add(str(record_path))
                if candidate.get("candidate_id") == selection.get("selected_candidate_id"):
                    selected_candidate = candidate

        if data.get("qa", {}).get("final_status") != "passed":
            continue
        text = nonempty(content.get("text"))
        author = nonempty(content.get("author"))
        work = nonempty(content.get("work"))
        if not run_date or not text or not author:
            history_errors.append(
                f"passed record lacks date, quote, or author: {record_path}"
            )
            continue
        normalized = normalize_quote(text)
        key = (run_date, normalized, author, work)
        row = delivered_groups.setdefault(
            key,
            {
                "date": run_date,
                "normalized_text": normalized,
                "text": text,
                "author": author,
                "work": work,
                "text_type": nonempty(content.get("text_type")),
                "translator": nonempty(content.get("translator")),
                "source_url": nonempty(content.get("source_url")),
                "source_type": nonempty(selected_candidate.get("source_type")),
                "cultural_context": nonempty(selected_candidate.get("cultural_context")),
                "period": nonempty(selected_candidate.get("period")),
                "semantic_signature": selected_candidate.get("semantic_signature", {}),
                "desired_effect": nonempty(selection.get("desired_effect")),
                "core_tension": nonempty(
                    data.get("plain_brief", {}).get("selected_emphasis")
                    or data.get("semantic_card", {}).get("core_tension")
                ),
                "source_of_strength": nonempty(
                    data.get("plain_brief", {}).get("source_of_strength")
                    or data.get("semantic_card", {}).get("source_of_strength")
                ),
                "emotional_temperature": nonempty(
                    data.get("plain_brief", {}).get("emotional_temperature")
                    or data.get("semantic_card", {}).get("emotional_temperature")
                ),
                "expression_mechanism": nonempty(
                    next(
                        (
                            concept.get("representation_mode")
                            for concept in data.get("concept_competition", {}).get("concepts", [])
                            if isinstance(concept, dict) and concept.get("decision") == "selected"
                        ),
                        "",
                    )
                ),
                "record_paths": set(),
                "final_image_paths": set(),
            },
        )
        row["record_paths"].add(str(record_path))
        final_path = nonempty(data.get("layout", {}).get("final_image_path"))
        if final_path:
            row["final_image_paths"].add(final_path)

    if history_errors:
        print("ERROR: history index was not written because source history is incomplete", file=sys.stderr)
        for error in history_errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    delivered_cards: list[dict[str, Any]] = []
    for row in delivered_groups.values():
        row["record_paths"] = sorted(row["record_paths"])
        row["final_image_paths"] = sorted(row["final_image_paths"])
        row["variant_count"] = len(row["record_paths"])
        delivered_cards.append(row)
    delivered_cards.sort(key=lambda item: (item["date"], item["author"], item["work"]))

    candidate_exposures: list[dict[str, Any]] = []
    for row in exposure_groups.values():
        row["decisions"] = sorted(value for value in row["decisions"] if value)
        row["record_paths"] = sorted(row["record_paths"])
        candidate_exposures.append(row)
    candidate_exposures.sort(
        key=lambda item: (item["date"], item["author"], item["normalized_text"])
    )

    author_counts = Counter(card["author"] for card in delivered_cards)
    work_counts = Counter(
        f"{card['author']}｜{card['work']}" for card in delivered_cards if card["work"]
    )
    desired_effect_counts = Counter(
        card["desired_effect"] for card in delivered_cards if card["desired_effect"]
    )
    source_type_counts = Counter(
        card["source_type"] for card in delivered_cards if card["source_type"]
    )
    cultural_context_counts = Counter(
        card["cultural_context"]
        for card in delivered_cards
        if card["cultural_context"]
    )
    period_counts = Counter(card["period"] for card in delivered_cards if card["period"])
    expression_mechanism_counts = Counter(
        card["expression_mechanism"]
        for card in delivered_cards
        if card.get("expression_mechanism")
    )
    quote_groups: dict[str, list[dict[str, Any]]] = {}
    for card in delivered_cards:
        quote_groups.setdefault(card["normalized_text"], []).append(
            {
                "date": card["date"],
                "author": card["author"],
                "work": card["work"],
                "text": card["text"],
                "record_paths": card["record_paths"],
            }
        )
    historical_duplicate_groups = [
        {"normalized_text": normalized, "deliveries": rows}
        for normalized, rows in quote_groups.items()
        if len({row["date"] for row in rows}) > 1
    ]
    historical_duplicate_groups.sort(key=lambda row: row["normalized_text"])
    index = {
        "schema_version": "1.1",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_runs_dir": str(runs_dir),
        "source_manifest": source_manifest,
        "source_manifest_hash_kind": "index_inputs_v1",
        "records_read": records_read,
        "delivered_card_count": len(delivered_cards),
        "candidate_exposure_count": len(candidate_exposures),
        "delivered_cards": delivered_cards,
        "candidate_exposures": candidate_exposures,
        "historical_duplicate_groups": historical_duplicate_groups,
        "stats": {
            "author_counts": dict(author_counts.most_common()),
            "work_counts": dict(work_counts.most_common()),
            "desired_effect_counts": dict(desired_effect_counts.most_common()),
            "source_type_counts": dict(source_type_counts.most_common()),
            "cultural_context_counts": dict(cultural_context_counts.most_common()),
            "period_counts": dict(period_counts.most_common()),
            "expression_mechanism_counts": dict(
                expression_mechanism_counts.most_common()
            ),
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_path, index)
    print(
        json.dumps(
            {
                "ok": True,
                "out": str(out_path),
                "records_read": records_read,
                "delivered_card_count": len(delivered_cards),
                "candidate_exposure_count": len(candidate_exposures),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
