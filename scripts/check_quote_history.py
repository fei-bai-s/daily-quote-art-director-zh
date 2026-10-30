#!/usr/bin/env python3
"""Check all candidates and the selected quote against a series history index."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from record_utils import (
    atomic_write_json, candidate_input_sha256, file_sha256,
    history_index_freshness_errors, normalize_quote, now_for_record,
)


NEAR_DUPLICATE_THRESHOLDS = {
    "8_to_9_chars": 0.90,
    "10_to_13_chars": 0.82,
    "14_plus_chars": 0.72,
}
AUTHOR_COOLDOWN_DAYS = 21
WORK_COOLDOWN_DAYS = 60
CANDIDATE_EXPOSURE_WINDOW_DAYS = 60
CANDIDATE_EXPOSURE_REVIEW_COUNT = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", help="Path to design-record.json")
    parser.add_argument("--history-index", required=True, help="Path to series-index.json")
    return parser.parse_args()


def nonempty(value: Any) -> str:
    return str(value or "").strip()


def days_before(current: str, previous: str) -> int | None:
    try:
        return (date.fromisoformat(current) - date.fromisoformat(previous)).days
    except ValueError:
        return None


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def near_threshold(minimum_length: int) -> float:
    if minimum_length >= 14:
        return NEAR_DUPLICATE_THRESHOLDS["14_plus_chars"]
    if minimum_length >= 10:
        return NEAR_DUPLICATE_THRESHOLDS["10_to_13_chars"]
    return NEAR_DUPLICATE_THRESHOLDS["8_to_9_chars"]


def save_history_snapshot(index: dict[str, Any], record_path: Path, source_index: Path) -> Path:
    """Store a content-addressed per-run snapshot; never overwrite an old snapshot."""
    snapshot = dict(index)
    snapshot["source_manifest"] = [
        row for row in index["source_manifest"]
        if str(Path(row["path"]).resolve()) != str(record_path)
    ]
    snapshot["snapshot_for_record"] = str(record_path)
    snapshot["source_manifest_excluded_record"] = str(record_path)
    snapshot["snapshot_source_index_sha256"] = file_sha256(source_index)
    raw = (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    path = record_path.parent / "history" / f"history-index-{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if file_sha256(path) != digest:
            raise ValueError(f"immutable history snapshot was modified: {path}")
    else:
        atomic_write_json(path, snapshot)
    return path


def main() -> int:
    args = parse_args()
    record_path = Path(args.record).expanduser().resolve()
    index_path = Path(args.history_index).expanduser().resolve()
    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read record or history index: {exc}", file=sys.stderr)
        return 2

    if data.get("schema_version") not in {"1.2", "1.3", "1.4", "1.5"}:
        print("ERROR: history checking requires design-record schema 1.2, 1.3, 1.4 or 1.5", file=sys.stderr)
        return 2
    delivered = index.get("delivered_cards")
    exposures = index.get("candidate_exposures")
    if not isinstance(delivered, list) or not isinstance(exposures, list):
        print("ERROR: invalid history index structure", file=sys.stderr)
        return 2

    if data.get("schema_version") in {"1.4", "1.5"}:
        freshness_errors = history_index_freshness_errors(index, record_path)
        if freshness_errors:
            for error in freshness_errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1

    run_date = nonempty(data.get("run", {}).get("date"))
    try:
        date.fromisoformat(run_date)
    except ValueError:
        print("ERROR: run.date must be an ISO date", file=sys.stderr)
        return 2
    candidates = data.get("content_selection", {}).get("candidates")
    selected_id = nonempty(data.get("content_selection", {}).get("selected_candidate_id"))
    if not isinstance(candidates, list) or not candidates:
        print("ERROR: record has no candidates", file=sys.stderr)
        return 2

    selected_result: dict[str, Any] | None = None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_id = nonempty(candidate.get("candidate_id"))
        text = nonempty(candidate.get("text"))
        author = nonempty(candidate.get("author"))
        work = nonempty(candidate.get("work"))
        normalized = normalize_quote(text)
        exact_matches: list[dict[str, Any]] = []
        near_matches: list[dict[str, Any]] = []
        author_dates: list[str] = []
        work_dates: list[str] = []

        for card in delivered:
            if not isinstance(card, dict):
                continue
            if str(record_path) in card.get("record_paths", []):
                continue
            previous_normalized = nonempty(card.get("normalized_text"))
            match_summary = {
                "date": nonempty(card.get("date")),
                "author": nonempty(card.get("author")),
                "work": nonempty(card.get("work")),
                "text": nonempty(card.get("text")),
                "record_paths": card.get("record_paths", []),
            }
            if normalized and normalized == previous_normalized:
                exact_matches.append(match_summary)
            elif min(len(normalized), len(previous_normalized)) >= 8:
                score = similarity(normalized, previous_normalized)
                threshold = near_threshold(min(len(normalized), len(previous_normalized)))
                if score >= threshold:
                    match_summary["similarity"] = round(score, 4)
                    match_summary["threshold"] = threshold
                    near_matches.append(match_summary)
            past_gap = days_before(run_date, nonempty(card.get("date")))
            is_past = past_gap is not None and past_gap >= 0
            if is_past and author and author == nonempty(card.get("author")):
                author_dates.append(nonempty(card.get("date")))
            if is_past and work and author == nonempty(card.get("author")) and work == nonempty(card.get("work")):
                work_dates.append(nonempty(card.get("date")))

        exposure_dates = sorted(
            {
                nonempty(row.get("date"))
                for row in exposures
                if isinstance(row, dict)
                and normalized
                and normalized == nonempty(row.get("normalized_text"))
                and author == nonempty(row.get("author"))
                and nonempty(row.get("date"))
                and any(str(path) != str(record_path) for path in row.get("record_paths", []))
            }
        )
        recent_exposure_dates = [
            value
            for value in exposure_dates
            if (gap := days_before(run_date, value)) is not None
            and 0 <= gap < CANDIDATE_EXPOSURE_WINDOW_DAYS
        ]
        author_dates = sorted(value for value in set(author_dates) if value)
        work_dates = sorted(value for value in set(work_dates) if value)
        author_last_used = author_dates[-1] if author_dates else ""
        work_last_used = work_dates[-1] if work_dates else ""
        author_gap = days_before(run_date, author_last_used) if author_last_used else None
        work_gap = days_before(run_date, work_last_used) if work_last_used else None
        result = {
            "input_sha256": candidate_input_sha256(candidate),
            "normalized_text": normalized,
            "exact_matches": exact_matches,
            "near_matches": near_matches,
            "candidate_exposure_dates": exposure_dates,
            "candidate_exposure_count": len(exposure_dates),
            "recent_candidate_exposure_dates": recent_exposure_dates,
            "recent_candidate_exposure_count": len(recent_exposure_dates),
            "author_last_used": author_last_used,
            "author_days_since_last_use": author_gap,
            "work_last_used": work_last_used,
            "work_days_since_last_use": work_gap,
            "author_in_cooldown": author_gap is not None and 0 <= author_gap < AUTHOR_COOLDOWN_DAYS,
            "work_in_cooldown": work_gap is not None and 0 <= work_gap < WORK_COOLDOWN_DAYS,
        }
        candidate["history_check"] = result
        if candidate_id == selected_id:
            selected_result = result

    if selected_result is None:
        print("ERROR: selected candidate was not found", file=sys.stderr)
        return 2

    history = data.setdefault("history_dedup", {})
    reuse_authorized = history.get("reuse_authorized") is True
    reuse_reason = nonempty(history.get("reuse_authorization_reason"))
    cooldown_decision = nonempty(history.get("cooldown_decision"))
    cooldown_rationale = nonempty(history.get("cooldown_rationale"))
    exposure_decision = nonempty(history.get("candidate_exposure_decision"))
    exposure_rationale = nonempty(history.get("candidate_exposure_rationale"))
    mode = nonempty(data.get("content_selection", {}).get("selection_mode"))
    has_duplicate = bool(selected_result["exact_matches"] or selected_result["near_matches"])
    has_cooldown = bool(
        selected_result["author_in_cooldown"] or selected_result["work_in_cooldown"]
    )
    repeated_candidate = (
        selected_result["recent_candidate_exposure_count"]
        >= CANDIDATE_EXPOSURE_REVIEW_COUNT
    )

    decision = "passed"
    reasons: list[str] = []
    if has_duplicate:
        if mode in {"user_supplied", "revision"} and reuse_authorized and reuse_reason:
            decision = "passed_with_user_override"
        else:
            decision = "failed"
            reasons.append("selected quote matches delivered history")
    elif reuse_authorized:
        reasons.append("reuse_authorized is true but no historical duplicate was found")

    if decision != "failed" and has_cooldown and mode == "open_search":
        if cooldown_decision == "justified" and cooldown_rationale:
            pass
        else:
            decision = "review_required"
            reasons.append("selected author or work is inside the editorial cooldown")
    if decision != "failed" and repeated_candidate and mode == "open_search":
        if exposure_decision == "justified" and exposure_rationale:
            pass
        else:
            decision = "review_required"
            reasons.append("selected quote has repeatedly appeared in recent candidate pools")

    source_index_path = index_path
    if data.get("schema_version") in {"1.4", "1.5"}:
        try:
            index_path = save_history_snapshot(index, record_path, source_index_path)
        except (OSError, ValueError) as exc:
            print(f"ERROR: cannot create history snapshot: {exc}", file=sys.stderr)
            return 1
        history["snapshot_immutable"] = True
        history["source_index_path"] = str(source_index_path)
        history["checked_run_date"] = run_date
    history.update(
        {
            "history_index_path": str(index_path),
            "history_index_sha256": file_sha256(index_path),
            "checked_at": now_for_record(data),
            "records_scanned": int(index.get("delivered_card_count", 0)),
            "near_duplicate_policy": NEAR_DUPLICATE_THRESHOLDS,
            "author_cooldown_days": AUTHOR_COOLDOWN_DAYS,
            "work_cooldown_days": WORK_COOLDOWN_DAYS,
            "candidate_exposure_window_days": CANDIDATE_EXPOSURE_WINDOW_DAYS,
            "candidate_exposure_review_count": CANDIDATE_EXPOSURE_REVIEW_COUNT,
            "selected_candidate_id": selected_id,
            "selected_history_check": selected_result,
            "reuse_authorized": reuse_authorized,
            "reuse_authorization_reason": reuse_reason,
            "cooldown_decision": cooldown_decision,
            "cooldown_rationale": cooldown_rationale,
            "candidate_exposure_decision": exposure_decision,
            "candidate_exposure_rationale": exposure_rationale,
            "decision": decision,
            "decision_reasons": reasons,
        }
    )
    series_context = data.setdefault("series_context", {})
    series_context.update(
        {
            "history_index_path": str(index_path),
            "history_index_built_at": nonempty(index.get("built_at")),
            "history_records_scanned": int(index.get("delivered_card_count", 0)),
        }
    )
    atomic_write_json(record_path, data)
    print(
        json.dumps(
            {
                "ok": decision in {"passed", "passed_with_user_override"},
                "decision": decision,
                "selected_candidate_id": selected_id,
                "exact_match_count": len(selected_result["exact_matches"]),
                "near_match_count": len(selected_result["near_matches"]),
                "author_in_cooldown": selected_result["author_in_cooldown"],
                "work_in_cooldown": selected_result["work_in_cooldown"],
                "reasons": reasons,
            },
            ensure_ascii=False,
        )
    )
    return 0 if decision in {"passed", "passed_with_user_override"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
