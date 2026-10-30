#!/usr/bin/env python3
"""Lock semantic and art-direction decisions before image generation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from record_utils import (
    ALLOWED_TEXT_TYPES,
    atomic_write_json,
    compute_lock_hash,
    content_selection_errors,
    get,
    nonempty,
    now_for_record,
    pre_generation_required_fields,
    v13_art_direction_errors,
    v12_selection_system_errors,
    history_freshness_errors,
    rendering_mode, rendering_mode_errors,
)

PLANNED_LAYOUT_FIELDS = (
    "layout.date_text",
    "layout.source_label",
    "layout.yi_text",
    "layout.ji_text",
    "layout.font_rationale",
    "layout.line_break_rationale",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", help="Path to design-record.json")
    parser.add_argument(
        "--invalidate-background",
        action="store_true",
        help="Explicitly discard registered background and downstream QA state",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.record).expanduser().resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read record: {exc}", file=sys.stderr)
        return 2

    has_registered_background = nonempty(
        get(data, "post_generation.background_path")
    ) or nonempty(get(data, "post_generation.generated_at"))
    if has_registered_background and not args.invalidate_background:
        print(
            "LOCK FAILED\n"
            "- a background is already registered; use --invalidate-background "
            "only after deciding to discard it",
            file=sys.stderr,
        )
        return 1

    errors: list[str] = []
    errors.extend(rendering_mode_errors(data))
    errors.extend(content_selection_errors(data))
    errors.extend(v12_selection_system_errors(data, path))
    errors.extend(history_freshness_errors(data, path))
    if data.get("schema_version") not in {"1.0", "1.1", "1.2", "1.3", "1.4", "1.5"}:
        errors.append("schema_version must be '1.0', '1.1', '1.2', '1.3', '1.4', or '1.5'")
    if (
        get(data, "content_selection.selection_mode") == "open_search"
        and data.get("schema_version") not in {"1.2", "1.3", "1.4", "1.5"}
    ):
        errors.append("new open_search runs must use schema_version 1.2, 1.3, 1.4, or 1.5")
    errors.extend(v13_art_direction_errors(data))

    run_date = get(data, "run.date")
    try:
        parsed_date = date.fromisoformat(run_date)
    except (TypeError, ValueError):
        errors.append("run.date must be a valid YYYY-MM-DD date")
        parsed_date = None
    if parsed_date is not None:
        expected_weekday = (
            "星期一",
            "星期二",
            "星期三",
            "星期四",
            "星期五",
            "星期六",
            "星期日",
        )[parsed_date.weekday()]
        if get(data, "run.weekday") != expected_weekday:
            errors.append(f"run.weekday must be {expected_weekday}")

    for field in ("run.slug", "run.timezone", "run.initialized_at"):
        if not nonempty(get(data, field)):
            errors.append(f"required non-empty field: {field}")

    for field in pre_generation_required_fields(data):
        if not nonempty(get(data, field)):
            errors.append(f"required non-empty field: {field}")
    for field in PLANNED_LAYOUT_FIELDS:
        if rendering_mode(data) == "integrated_image_text" and field in {"layout.font_rationale", "layout.line_break_rationale"}:
            continue
        if not nonempty(get(data, field)):
            errors.append(f"required non-empty field before locking: {field}")
    for field in ("layout.canvas_width", "layout.canvas_height"):
        value = get(data, field)
        if not isinstance(value, int) or value <= 0:
            errors.append(f"{field} must be a positive integer before locking")

    text_type = get(data, "content.text_type")
    if text_type not in ALLOWED_TEXT_TYPES:
        errors.append(
            "content.text_type must use a machine value: "
            + ", ".join(sorted(ALLOWED_TEXT_TYPES))
        )
    if text_type != "editorial_summary" and not nonempty(get(data, "content.work")):
        errors.append("content.work is required for quoted source material")
    if text_type == "translated_quote" and not nonempty(get(data, "content.translator")):
        errors.append("content.translator is required for translated_quote")

    source_label = str(get(data, "layout.source_label") or "")
    author = str(get(data, "content.author") or "")
    work = str(get(data, "content.work") or "")
    if text_type in {"exact_quote", "translated_quote"}:
        if author not in source_label or f"《{work}" not in source_label:
            errors.append("quoted source_label must include the author and 《work》")
    if text_type == "translated_quote" and "译者：" not in source_label:
        errors.append("translated_quote source_label must include 译者：")
    if text_type == "editorial_summary" and "取意" not in source_label:
        errors.append("editorial_summary source_label must clearly use 取意")
    if text_type == "author_about_work" and "谈《" not in source_label:
        errors.append("author_about_work source_label must use 作者｜谈《作品》")

    forbidden_path = (
        "plain_brief.forbidden_literal_elements"
        if data.get("schema_version") == "1.3"
        else "semantic_card.forbidden_literal_elements"
    )
    forbidden = get(data, forbidden_path)
    if data.get("schema_version") not in {"1.4", "1.5"} and (not isinstance(forbidden, list) or not forbidden):
        errors.append(f"{forbidden_path} must be a non-empty list")
    avoid_cliches = get(data, "pre_generation.avoid_cliches")
    if not isinstance(avoid_cliches, list) or not avoid_cliches:
        errors.append("pre_generation.avoid_cliches must be a non-empty list")

    if get(data, "content.verified") is not True:
        errors.append("content.verified must be true before locking")

    from integrated_production import prompt_errors
    errors.extend(prompt_errors(data, str(get(data, "pre_generation.prompt") or "")))

    if data.get("schema_version") in {"1.4", "1.5"}:
        from production_integrity import layout_text_errors, ordered_times
        errors.extend(layout_text_errors(data))
        try:
            if not ordered_times(get(data, "run.initialized_at"), now_for_record(data)):
                errors.append("run.initialized_at must not be after locking")
        except (ValueError, TypeError) as exc:
            errors.append(f"invalid initialization timestamp: {exc}")

    if errors:
        print("LOCK FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    if args.invalidate_background:
        if data.get("schema_version") in {"1.4", "1.5"}:
            from production_integrity import invalidate_downstream
            invalidate_downstream(data, path, "generation plan re-locked", background=True)
        data["post_generation"].update(
            {
                "background_path": "",
                "generated_at": "",
                "planned_relationships_realized": [],
                "emergent_discoveries": [],
                "deviations": [],
                "regeneration_or_fix_decision": "",
                "generic_background_test": "",
                "literalness_test": "",
            }
        )
        data["layout"]["render_source_path"] = ""
        data["layout"]["final_image_path"] = ""
        if "rendered_at" in data["layout"]:
            data["layout"]["rendered_at"] = ""
        if isinstance(data.get("perceptual_validation"), dict):
            data["perceptual_validation"].update(
                {
                    "intended_relationship": "",
                    "blind_reading_recorded_at": "",
                    "blind_visual_reading": "",
                    "comparison_recorded_at": "",
                    "dominant_misreading": "",
                    "relationship_match": "pending",
                    "quote_reveal_fit": "pending",
                    "unrelated_text_test": "",
                    "full_resolution_checked": False,
                    "mobile_checked": False,
                    "decision": "pending",
                }
            )
        if isinstance(data.get("execution_validation"), dict):
            data["execution_validation"].update(
                {
                    "checked_at": "",
                    "key_action_or_state_realized": "",
                    "concept_fidelity": "",
                    "text_safe_area_usable": False,
                    "decision": "pending",
                }
            )
        if isinstance(data.get("semantic_cold_review"), dict):
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
        if isinstance(data.get("design_concept"), dict):
            for key in data["design_concept"]:
                data["design_concept"][key] = ""
        for key, value in data["qa"].items():
            if isinstance(value, bool):
                data["qa"][key] = False
            elif isinstance(value, int):
                data["qa"][key] = 0
        data["qa"]["final_status"] = "pending"

    data["pre_generation"]["locked_before_generation"] = True
    data["pre_generation"]["locked_at"] = now_for_record(data)
    data["pre_generation"]["lock_hash"] = ""
    data["pre_generation"]["lock_hash"] = compute_lock_hash(data)
    data["run"]["status"] = "pre_generation_locked"
    if data.get("schema_version") in {"1.4", "1.5"}:
        for flag in ("pre_generation_record_existed", "history_dedup_checked", "selection_breadth_checked", "concept_competition_checked", "date_and_weekday_correct"):
            data.setdefault("qa", {})[flag] = True
    atomic_write_json(path, data)
    print(data["pre_generation"]["lock_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
