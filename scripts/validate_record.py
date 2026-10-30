#!/usr/bin/env python3
"""Validate structural completeness of a daily-quote design record."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from record_utils import (
    ALLOWED_TEXT_TYPES,
    compute_lock_hash,
    content_selection_errors,
    pre_generation_required_fields,
    v13_art_direction_errors,
    v12_selection_system_errors,
    history_freshness_errors,
    rendering_mode, rendering_mode_errors,
)

BASE_REQUIRED_QA_TRUE = (
    "date_and_weekday_correct",
    "source_and_text_correct",
    "content_type_labeled_correctly",
    "pre_generation_record_existed",
    "planned_vs_emergent_separated",
    "final_text_rendered_deterministically",
    "no_overlap_or_clipping",
    "style_inertia_checked",
    "theme_inertia_checked",
    "final_image_inspected_full_resolution",
    "output_saved_to_user_directory",
)

V11_REQUIRED_QA_TRUE = (
    "perceptual_validity_checked",
    "design_concept_matches_record",
)

V12_REQUIRED_QA_TRUE = (
    "history_dedup_checked",
    "selection_breadth_checked",
)

V13_REQUIRED_QA_TRUE = (
    "history_dedup_checked",
    "selection_breadth_checked",
    "concept_competition_checked",
    "execution_gate_checked",
    "semantic_cold_review_checked",
    "design_concept_matches_record",
)

V11_DESIGN_CONCEPT_FIELDS = (
    "written_at",
    "quote_and_selection",
    "intended_expression",
    "visual_translation",
    "concrete_art_plan",
    "typography_and_layout",
    "generation_constraints",
    "post_generation_review",
    "full_text",
)

V11_DESIGN_CONCEPT_MIN_LENGTHS = {
    "quote_and_selection": 30,
    "intended_expression": 30,
    "visual_translation": 40,
    "concrete_art_plan": 60,
    "typography_and_layout": 40,
    "generation_constraints": 30,
    "post_generation_review": 60,
}

ALLOWED_RELATIONSHIP_MATCH = {"pending", "strong", "partial", "weak"}
ALLOWED_QUOTE_REVEAL_FIT = {
    "pending",
    "natural",
    "explanation_needed",
    "conflicting",
}
ALLOWED_PERCEPTUAL_DECISIONS = {"pending", "pass", "fix", "regenerate"}
ALLOWED_EXECUTION_DECISIONS = {"pending", "pass", "regenerate_same_concept"}
ALLOWED_COLD_REVIEW_DECISIONS = {
    "pending",
    "pass",
    "regenerate_same_concept",
    "return_to_concepts",
    "return_to_semantic_anchor",
}
ALLOWED_MISSING_LINKS = {
    "pending",
    "none",
    "key_action",
    "key_state",
    "causal_link",
    "relationship_conflict",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", help="Path to design-record.json")
    parser.add_argument(
        "--stage",
        choices=("pre", "final"),
        default="final",
        help="'pre' validates a locked generation plan; 'final' validates delivery",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Validate immutable historical snapshots only; not authorization for a new delivery",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Deprecated alias for --stage pre",
    )
    return parser.parse_args()


def get(data: dict[str, Any], dotted: str) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def png_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return None
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", header[16:24])


def normalized_text(value: Any) -> str:
    return "".join(str(value or "").split())


def validate_perceptual(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_text_fields = (
        "intended_relationship",
        "blind_reading_recorded_at",
        "blind_visual_reading",
        "comparison_recorded_at",
        "dominant_misreading",
        "unrelated_text_test",
    )
    for field in required_text_fields:
        value = get(data, f"perceptual_validation.{field}")
        if not nonempty(value):
            errors.append(
                f"required non-empty field: perceptual_validation.{field}"
            )

    perceptual_min_lengths = {
        "blind_visual_reading": 30,
        "dominant_misreading": 15,
        "unrelated_text_test": 30,
    }
    for field, minimum in perceptual_min_lengths.items():
        value = str(get(data, f"perceptual_validation.{field}") or "").strip()
        if value and len(value) < minimum:
            errors.append(
                f"perceptual_validation.{field} must be at least {minimum} characters"
            )

    intended = normalized_text(get(data, "perceptual_validation.intended_relationship"))
    planned = normalized_text(get(data, "pre_generation.core_visual_relationship"))
    if intended and planned and intended != planned:
        errors.append(
            "perceptual_validation.intended_relationship must match "
            "pre_generation.core_visual_relationship"
        )

    blind_at = get(data, "perceptual_validation.blind_reading_recorded_at")
    compared_at = get(data, "perceptual_validation.comparison_recorded_at")
    if nonempty(blind_at) and nonempty(compared_at):
        try:
            if datetime.fromisoformat(blind_at) > datetime.fromisoformat(compared_at):
                errors.append(
                    "blind_reading_recorded_at must not be after comparison_recorded_at"
                )
        except ValueError:
            errors.append("perceptual validation timestamps must be ISO-8601")

    relationship_match = get(data, "perceptual_validation.relationship_match")
    if relationship_match not in ALLOWED_RELATIONSHIP_MATCH:
        errors.append(
            "perceptual_validation.relationship_match must be one of: "
            + ", ".join(sorted(ALLOWED_RELATIONSHIP_MATCH))
        )
    elif relationship_match != "strong":
        errors.append("perceptual_validation.relationship_match must be 'strong'")

    quote_reveal_fit = get(data, "perceptual_validation.quote_reveal_fit")
    if quote_reveal_fit not in ALLOWED_QUOTE_REVEAL_FIT:
        errors.append(
            "perceptual_validation.quote_reveal_fit must be one of: "
            + ", ".join(sorted(ALLOWED_QUOTE_REVEAL_FIT))
        )
    elif quote_reveal_fit != "natural":
        errors.append("perceptual_validation.quote_reveal_fit must be 'natural'")

    decision = get(data, "perceptual_validation.decision")
    if decision not in ALLOWED_PERCEPTUAL_DECISIONS:
        errors.append(
            "perceptual_validation.decision must be one of: "
            + ", ".join(sorted(ALLOWED_PERCEPTUAL_DECISIONS))
        )
    elif decision != "pass":
        errors.append("perceptual_validation.decision must be 'pass'")

    for field in ("full_resolution_checked", "mobile_checked"):
        if get(data, f"perceptual_validation.{field}") is not True:
            errors.append(f"perceptual_validation.{field} must be true")
    return errors


def validate_execution_v13(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in (
        "checked_at",
        "key_action_or_state_realized",
        "concept_fidelity",
    ):
        if not nonempty(get(data, f"execution_validation.{field}")):
            errors.append(f"required non-empty field: execution_validation.{field}")
    if get(data, "execution_validation.text_safe_area_usable") is not True:
        errors.append("execution_validation.text_safe_area_usable must be true")
    decision = get(data, "execution_validation.decision")
    if decision not in ALLOWED_EXECUTION_DECISIONS:
        errors.append(
            "execution_validation.decision must be one of: "
            + ", ".join(sorted(ALLOWED_EXECUTION_DECISIONS))
        )
    elif decision != "pass":
        errors.append("execution_validation.decision must be 'pass'")
    return errors


def validate_cold_review_v13(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if get(data, "semantic_cold_review.review_input_isolated") is not True:
        errors.append("semantic_cold_review.review_input_isolated must be true")
    for field in (
        "image_only_reviewed_at",
        "image_only_first_read",
        "dominant_misreading",
        "quote_revealed_at",
        "shared_relationship",
        "missing_link_note",
    ):
        if not nonempty(get(data, f"semantic_cold_review.{field}")):
            errors.append(f"required non-empty field: semantic_cold_review.{field}")
    for field, minimum in (
        ("image_only_first_read", 20),
        ("dominant_misreading", 10),
        ("shared_relationship", 20),
    ):
        value = str(get(data, f"semantic_cold_review.{field}") or "").strip()
        if value and len(value) < minimum:
            errors.append(
                f"semantic_cold_review.{field} must be at least {minimum} characters"
            )

    image_only_at = get(data, "semantic_cold_review.image_only_reviewed_at")
    revealed_at = get(data, "semantic_cold_review.quote_revealed_at")
    if nonempty(image_only_at) and nonempty(revealed_at):
        try:
            if datetime.fromisoformat(image_only_at) > datetime.fromisoformat(revealed_at):
                errors.append("image-only review must occur before quote reveal")
        except ValueError:
            errors.append("semantic cold-review timestamps must be ISO-8601")

    missing_link = get(data, "semantic_cold_review.missing_link")
    if missing_link not in ALLOWED_MISSING_LINKS:
        errors.append(
            "semantic_cold_review.missing_link must be one of: "
            + ", ".join(sorted(ALLOWED_MISSING_LINKS))
        )
    elif missing_link != "none":
        errors.append("semantic_cold_review.missing_link must be 'none' for delivery")
    if get(data, "semantic_cold_review.explanation_required") is not False:
        errors.append("semantic_cold_review.explanation_required must be false")
    for field in ("full_resolution_checked", "mobile_checked"):
        if get(data, f"semantic_cold_review.{field}") is not True:
            errors.append(f"semantic_cold_review.{field} must be true")
    decision = get(data, "semantic_cold_review.decision")
    if decision not in ALLOWED_COLD_REVIEW_DECISIONS:
        errors.append(
            "semantic_cold_review.decision must be one of: "
            + ", ".join(sorted(ALLOWED_COLD_REVIEW_DECISIONS))
        )
    elif decision != "pass":
        errors.append("semantic_cold_review.decision must be 'pass'")
    return errors


def validate_design_concept(
    data: dict[str, Any], record_path: Path
) -> list[str]:
    errors: list[str] = []
    for field in V11_DESIGN_CONCEPT_FIELDS:
        value = get(data, f"design_concept.{field}")
        if not nonempty(value):
            errors.append(f"required non-empty field: design_concept.{field}")
    for field, minimum in V11_DESIGN_CONCEPT_MIN_LENGTHS.items():
        value = str(get(data, f"design_concept.{field}") or "").strip()
        if value and len(value) < minimum:
            errors.append(
                f"design_concept.{field} must be at least {minimum} characters"
            )

    full_text = str(get(data, "design_concept.full_text") or "").strip()
    if full_text and not 500 <= len(full_text) <= 900:
        errors.append("design_concept.full_text must be 500-900 characters")

    quote = normalized_text(get(data, "content.text"))
    if full_text and quote and quote not in normalized_text(full_text):
        errors.append("design_concept.full_text must include the exact daily quote")
    author = str(get(data, "content.author") or "").strip()
    work = str(get(data, "content.work") or "").strip()
    if full_text and author and author not in full_text:
        errors.append("design_concept.full_text must include the author")
    if full_text and work and f"《{work}》" not in full_text:
        errors.append("design_concept.full_text must include the work title")
    outbound_audit_tokens = (
        "盲读",
        "感知闸门",
        "无关文本测试",
        "提示词",
        "生成后的发现",
        "本轮无需要保留的生成后发现",
        "缩略图",
        "第一版",
        "第二版",
        "第三版",
        "360像素",
        "发送回执",
    )
    found_audit_tokens = [token for token in outbound_audit_tokens if token in full_text]
    if found_audit_tokens:
        errors.append(
            "design_concept.full_text must not expose internal production audit: "
            + ", ".join(found_audit_tokens)
        )

    raw_path = str(get(data, "design_concept.file_path") or "").strip()
    if not raw_path:
        errors.append("required non-empty field: design_concept.file_path")
        return errors
    concept_path = Path(raw_path).expanduser()
    if not concept_path.is_absolute():
        concept_path = record_path.parent / concept_path
    if not concept_path.is_file():
        errors.append(f"design concept file does not exist: {concept_path}")
        return errors
    try:
        sent_text = concept_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        errors.append(f"cannot read design concept file: {exc}")
        return errors
    if sent_text != full_text:
        errors.append(
            "design_concept.full_text must exactly match the design concept file"
        )
    return errors


def validate_design_concept_v13(
    data: dict[str, Any], record_path: Path
) -> list[str]:
    errors: list[str] = []
    required_fields = (
        "written_at",
        "selected_quote",
        "quote_meaning",
        "intended_picture_message",
        "visual_design",
        "full_text",
    )
    for field in required_fields:
        if not nonempty(get(data, f"design_concept.{field}")):
            errors.append(f"required non-empty field: design_concept.{field}")
    full_text = str(get(data, "design_concept.full_text") or "").strip()
    if full_text and not 200 <= len(full_text) <= 1000:
        errors.append("design_concept.full_text must be 200-1000 characters")
    quote = normalized_text(get(data, "content.text"))
    selected_quote = normalized_text(get(data, "design_concept.selected_quote"))
    if quote and selected_quote and quote not in selected_quote:
        errors.append("design_concept.selected_quote must include the exact daily quote")
    if full_text and quote and quote not in normalized_text(full_text):
        errors.append("design_concept.full_text must include the exact daily quote")
    author = str(get(data, "content.author") or "").strip()
    work = str(get(data, "content.work") or "").strip()
    if full_text and author and author not in full_text:
        errors.append("design_concept.full_text must include the author")
    if full_text and work and f"《{work}》" not in full_text:
        errors.append("design_concept.full_text must include the work title")

    outbound_audit_tokens = (
        "盲读",
        "感知闸门",
        "语义冷审",
        "无关文本测试",
        "提示词",
        "缩略图",
        "发送回执",
        "第一版",
        "第二版",
        "第三版",
    )
    found = [token for token in outbound_audit_tokens if token in full_text]
    if found:
        errors.append(
            "design_concept.full_text must not expose internal production audit: "
            + ", ".join(found)
        )

    raw_path = str(get(data, "design_concept.file_path") or "").strip()
    if not raw_path:
        errors.append("required non-empty field: design_concept.file_path")
        return errors
    concept_path = Path(raw_path).expanduser()
    if not concept_path.is_absolute():
        concept_path = record_path.parent / concept_path
    if not concept_path.is_file():
        errors.append(f"design concept file does not exist: {concept_path}")
        return errors
    try:
        sent_text = concept_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        errors.append(f"cannot read design concept file: {exc}")
        return errors
    if sent_text != full_text:
        errors.append("design_concept.full_text must exactly match the design concept file")
    return errors


def main() -> int:
    args = parse_args()
    stage = "pre" if args.allow_incomplete else args.stage
    record_path = Path(args.record).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []

    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"ERROR: record not found: {record_path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON: {exc}", file=sys.stderr)
        return 2

    schema_version = data.get("schema_version")
    if schema_version not in {"1.0", "1.1", "1.2", "1.3", "1.4", "1.5"}:
        errors.append("schema_version must be '1.0', '1.1', '1.2', '1.3', '1.4', or '1.5'")
    has_legacy_v11_features = schema_version in {"1.1", "1.2"}
    has_selection_system = schema_version in {"1.2", "1.3", "1.4", "1.5"}
    is_v13 = schema_version in {"1.3", "1.4", "1.5"}
    is_v14 = schema_version in {"1.4", "1.5"}

    required_sections = (
        "run",
        "content_selection",
        "content",
        "recent_inertia_check",
        "pre_generation",
        "post_generation",
        "layout",
        "qa",
    )
    if is_v13:
        required_sections += (
            "plain_brief",
            "concept_competition",
            "execution_validation",
            "semantic_cold_review",
            "design_concept",
        )
    else:
        required_sections += ("semantic_card",)
    if has_legacy_v11_features:
        required_sections += ("perceptual_validation", "design_concept")
    if has_selection_system:
        required_sections += (
            "series_context",
            "editorial_brief",
            "history_dedup",
        )
    for section in required_sections:
        if not isinstance(data.get(section), dict):
            errors.append(f"missing object section: {section}")

    errors.extend(content_selection_errors(data, check_local_sources=not args.archive))
    errors.extend(v12_selection_system_errors(data, record_path, check_local_sources=not args.archive))
    if not args.archive:
        errors.extend(history_freshness_errors(data, record_path))
    elif stage != "final":
        errors.append("--archive is only available for historical final-stage verification")
    errors.extend(v13_art_direction_errors(data))
    errors.extend(rendering_mode_errors(data))

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

    text_type = get(data, "content.text_type")
    if text_type not in ALLOWED_TEXT_TYPES:
        errors.append(
            "content.text_type must be one of: "
            + ", ".join(sorted(ALLOWED_TEXT_TYPES))
        )

    pre_required_text_fields = pre_generation_required_fields(data) + (
        "layout.date_text",
        "layout.source_label",
        "layout.yi_text",
        "layout.ji_text",
        "layout.font_rationale",
        "layout.line_break_rationale",
    )
    final_required_text_fields = (
        "post_generation.background_path",
        "post_generation.regeneration_or_fix_decision",
        "post_generation.literalness_test",
        "layout.render_source_path",
        "layout.final_image_path",
    )
    if is_v14:
        # Execution evidence + creator alignment replace duplicated legacy narration.
        final_required_text_fields = ("post_generation.background_path", "layout.render_source_path", "layout.final_image_path")
    if rendering_mode(data) == "integrated_image_text":
        pre_required_text_fields = tuple(field for field in pre_required_text_fields if field not in {"layout.font_rationale", "layout.line_break_rationale"})
        final_required_text_fields = tuple(field for field in final_required_text_fields if field != "layout.render_source_path")
    if not is_v13:
        final_required_text_fields += ("post_generation.generic_background_test",)
    required_text_fields = pre_required_text_fields
    if stage == "final":
        required_text_fields += final_required_text_fields
        if has_legacy_v11_features or is_v13:
            required_text_fields += ("layout.rendered_at",)
    for field in required_text_fields:
        if not nonempty(get(data, field)):
            errors.append(f"required non-empty field: {field}")

    for field in ("layout.canvas_width", "layout.canvas_height"):
        value = get(data, field)
        if not isinstance(value, int) or value <= 0:
            errors.append(f"{field} must be a positive integer")

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

    if not get(data, "content.verified"):
        errors.append("content.verified must be true")

    if not get(data, "pre_generation.locked_before_generation"):
        errors.append("pre_generation.locked_before_generation must be true")

    saved_hash = str(get(data, "pre_generation.lock_hash") or "")
    if not saved_hash:
        errors.append("pre_generation.lock_hash is required")
    elif saved_hash != compute_lock_hash(data):
        errors.append("pre-generation content changed after locking")

    locked_at = get(data, "pre_generation.locked_at")
    generated_at = get(data, "post_generation.generated_at")
    if not nonempty(locked_at):
        errors.append("pre_generation.locked_at is required")
    if stage == "final" and not nonempty(generated_at):
        errors.append("post_generation.generated_at is required")
    if stage == "final" and nonempty(locked_at) and nonempty(generated_at):
        try:
            if datetime.fromisoformat(locked_at) > datetime.fromisoformat(generated_at):
                errors.append("pre_generation.locked_at must not be after generated_at")
        except ValueError:
            errors.append("locked_at and generated_at must be ISO-8601 timestamps")

    if stage == "final" and not is_v14 and (has_legacy_v11_features or is_v13):
        rendered_at = get(data, "layout.rendered_at")
        if is_v13:
            blind_at = get(data, "semantic_cold_review.image_only_reviewed_at")
            compared_at = get(data, "semantic_cold_review.quote_revealed_at")
        else:
            blind_at = get(data, "perceptual_validation.blind_reading_recorded_at")
            compared_at = get(data, "perceptual_validation.comparison_recorded_at")
        written_at = get(data, "design_concept.written_at")
        if is_v13:
            execution_at = get(data, "execution_validation.checked_at")
            timeline_values = (
                generated_at,
                execution_at,
                rendered_at,
                blind_at,
                compared_at,
                written_at,
            )
            timeline_label = (
                "generated_at <= execution_checked_at <= rendered_at <= "
                "image_only_reviewed_at <= quote_revealed_at <= written_at"
            )
        else:
            timeline_values = (
                generated_at,
                rendered_at,
                blind_at,
                compared_at,
                written_at,
            )
            timeline_label = (
                "generated_at <= rendered_at <= blind_reading_recorded_at <= "
                "comparison_recorded_at <= written_at"
            )
        if all(nonempty(value) for value in timeline_values):
            try:
                timeline = tuple(
                    datetime.fromisoformat(value)
                    for value in timeline_values
                )
                if list(timeline) != sorted(timeline):
                    errors.append(f"timeline must be {timeline_label}")
            except ValueError:
                errors.append("production timestamps must be ISO-8601")

    forbidden_path = (
        "plain_brief.forbidden_literal_elements"
        if is_v13
        else "semantic_card.forbidden_literal_elements"
    )
    forbidden = get(data, forbidden_path)
    if not is_v14 and (not isinstance(forbidden, list) or not forbidden):
        errors.append(f"{forbidden_path} must be a non-empty list")
    avoid_cliches = get(data, "pre_generation.avoid_cliches")
    if not isinstance(avoid_cliches, list) or not avoid_cliches:
        errors.append("pre_generation.avoid_cliches must be a non-empty list")
    if stage == "final":
        realized = get(data, "post_generation.planned_relationships_realized")
        if not isinstance(realized, list) or not realized:
            errors.append(
                "post_generation.planned_relationships_realized "
                "must be a non-empty list"
            )

    from integrated_production import prompt_errors
    errors.extend(prompt_errors(data, str(get(data, "pre_generation.prompt") or "")))

    background_path = Path(str(get(data, "post_generation.background_path") or "")).expanduser()
    final_path = Path(str(get(data, "layout.final_image_path") or "")).expanduser()
    render_path = Path(str(get(data, "layout.render_source_path") or "")).expanduser()
    if stage == "final":
        for label, path in (
            ("background", background_path),
            ("render source", render_path),
            ("final image", final_path),
        ):
            if label == "render source" and rendering_mode(data) == "integrated_image_text":
                continue
            if not path.is_file():
                errors.append(f"{label} file does not exist: {path}")

        dimensions = png_dimensions(final_path)
        if dimensions is None:
            errors.append("final image must be a readable PNG")
        else:
            recorded_width = get(data, "layout.canvas_width")
            recorded_height = get(data, "layout.canvas_height")
            if dimensions != (recorded_width, recorded_height):
                errors.append(
                    "layout canvas size does not match final PNG: "
                    f"recorded={recorded_width}x{recorded_height}, "
                    f"actual={dimensions[0]}x{dimensions[1]}"
                )

        required_qa_true = BASE_REQUIRED_QA_TRUE
        if rendering_mode(data) == "integrated_image_text":
            required_qa_true = tuple(field for field in required_qa_true if field != "final_text_rendered_deterministically") + ("generated_text_checked",)
        if has_legacy_v11_features:
            required_qa_true += V11_REQUIRED_QA_TRUE
        if schema_version == "1.2":
            required_qa_true += V12_REQUIRED_QA_TRUE
        if is_v13:
            required_qa_true += V13_REQUIRED_QA_TRUE
        for field in required_qa_true:
            if get(data, f"qa.{field}") is not True:
                errors.append(f"qa.{field} must be true")

        if has_legacy_v11_features:
            errors.extend(validate_perceptual(data))
            errors.extend(validate_design_concept(data, record_path))
        if is_v13 and not is_v14:
            errors.extend(validate_execution_v13(data))
            errors.extend(validate_cold_review_v13(data))
            errors.extend(validate_design_concept_v13(data, record_path))
        if is_v14:
            errors.extend(validate_design_concept_v13(data, record_path))

        score_rules = [
            ("qa.content_score", 8, 10),
            ("qa.typography_score", 10, 12),
        ]
        if not is_v13:
            score_rules.insert(1, ("qa.art_direction_score", 11, 14))
        for field, minimum, maximum in ([] if is_v14 else score_rules):
            score = get(data, field)
            if not isinstance(score, int) or not minimum <= score <= maximum:
                errors.append(f"{field} must be an integer from {minimum} to {maximum}")

        if get(data, "qa.final_status") != "passed":
            errors.append("qa.final_status must be 'passed'")

    if is_v14:
        from production_integrity import production_errors
        errors.extend(production_errors(data, record_path, stage))

    if not nonempty(get(data, "content.source_url")):
        warnings.append("content.source_url is empty; use only when primary text is locally verified")

    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        for warning in warnings:
            print(f"WARNING: {warning}")
        return 1

    print("ARCHIVE VALIDATION PASSED (snapshot only; NOT VALID FOR NEW DELIVERY)" if args.archive else "VALIDATION PASSED")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
