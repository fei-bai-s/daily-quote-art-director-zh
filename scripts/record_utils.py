"""Shared deterministic helpers for design-record scripts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


ALLOWED_TEXT_TYPES = {
    "exact_quote",
    "translated_quote",
    "author_about_work",
    "editorial_summary",
}

ALLOWED_SELECTION_MODES = {
    "open_search",
    "user_supplied",
    "revision",
}

V14_SOURCE_TYPES = {
    "poetry", "prose", "fiction", "drama", "letter", "diary", "preface",
    "interview", "speech", "literary_criticism", "other",
}
V14_ROUTE_TYPES = {"semantic", "genre", "culture_period", "primary_work", "serendipity"}

LEGACY_PRE_GENERATION_REQUIRED_FIELDS = (
    "content_selection.user_direction",
    "content_selection.desired_effect",
    "content_selection.scope_note",
    "content_selection.range_check",
    "content_selection.pool_stop_reason",
    "content_selection.selected_candidate_id",
    "content_selection.selection_rationale",
    "content.text",
    "content.author",
    "content.verification_note",
    "semantic_card.surface_meaning",
    "semantic_card.core_tension",
    "semantic_card.emotional_temperature",
    "semantic_card.source_of_strength",
    "semantic_card.visualizable_relationship",
    "semantic_card.intended_aftertaste",
    "recent_inertia_check.decision",
    "pre_generation.core_visual_relationship",
    "pre_generation.medium",
    "pre_generation.style_language",
    "pre_generation.composition",
    "pre_generation.typography_direction",
    "pre_generation.color_functions",
    "pre_generation.negative_space_plan",
    "pre_generation.difference_from_recent",
    "pre_generation.prompt",
)

V13_PRE_GENERATION_REQUIRED_FIELDS = (
    "content_selection.user_direction",
    "content_selection.desired_effect",
    "content_selection.scope_note",
    "content_selection.range_check",
    "content_selection.pool_stop_reason",
    "content_selection.selected_candidate_id",
    "content_selection.selection_rationale",
    "content.text",
    "content.author",
    "content.verification_note",
    "plain_brief.core_meaning",
    "plain_brief.selected_emphasis",
    "plain_brief.common_misreading",
    "plain_brief.must_be_visible_relation",
    "plain_brief.emotional_temperature",
    "plain_brief.source_of_strength",
    "plain_brief.intended_aftertaste",
    "recent_inertia_check.repeated_theme_risk",
    "recent_inertia_check.repeated_expression_mechanism_risk",
    "recent_inertia_check.novelty_priority_check",
    "recent_inertia_check.decision",
    "concept_competition.selected_concept_id",
    "concept_competition.selection_rationale",
    "pre_generation.selected_concept_id",
    "pre_generation.core_visual_relationship",
    "pre_generation.medium",
    "pre_generation.style_language",
    "pre_generation.composition",
    "pre_generation.typography_direction",
    "pre_generation.color_functions",
    "pre_generation.negative_space_plan",
    "pre_generation.difference_from_recent",
    "pre_generation.prompt",
)

V12_EDITORIAL_BRIEF_FIELDS = (
    "today_need",
    "quality_guardrail",
    "selection_risk",
)

V12_SEMANTIC_SIGNATURE_FIELDS = (
    "desired_effect",
    "core_tension",
    "source_of_strength",
    "emotional_temperature",
)


def get(data: dict[str, Any], dotted: str) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def pre_generation_required_fields(data: dict[str, Any]) -> tuple[str, ...]:
    if data.get("schema_version") in {"1.4", "1.5"}:
        return tuple(
            "plain_brief.semantic_invariant" if field == "plain_brief.must_be_visible_relation" else field
            for field in V13_PRE_GENERATION_REQUIRED_FIELDS
        )
    if data.get("schema_version") == "1.3":
        return V13_PRE_GENERATION_REQUIRED_FIELDS
    return LEGACY_PRE_GENERATION_REQUIRED_FIELDS


def normalize_quote(value: Any) -> str:
    """Normalize a quote for matching without changing its displayed text."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(
        char
        for char in normalized
        if not unicodedata.category(char).startswith(("P", "S", "Z"))
        and not char.isspace()
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_input_sha256(candidate: dict[str, Any]) -> str:
    """Bind a history result to the exact quote identity, not only candidate ID."""
    payload = {field: candidate.get(field, "") for field in ("text", "author", "work")}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def source_locator_errors(value: Any, label: str, *, check_local_exists: bool = True) -> list[str]:
    """Validate a source pointer's shape; this does not assert its contents are true."""
    if not isinstance(value, dict):
        return [f"{label} must be an object containing url or local_path and location"]
    url = value.get("url", "")
    local = value.get("local_path", "")
    if bool(nonempty(url)) == bool(nonempty(local)):
        return [f"{label} requires exactly one of url or local_path"]
    if nonempty(url):
        try:
            parsed = urlparse(url)
        except ValueError:
            return [f"{label}.url must be an absolute HTTP(S) URL"]
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return [f"{label}.url must be an absolute HTTP(S) URL"]
    else:
        if not Path(local).is_absolute() or not nonempty(value.get("location")):
            return [f"{label} local source requires an absolute local_path and non-empty location"]
        if check_local_exists and not Path(local).is_file():
            return [f"{label}.local_path does not exist or is not a file: {local}"]
    return []


def history_source_sha256(data: dict[str, Any]) -> str:
    """Hash only inputs consumed by the history index, excluding receipts and QA notes."""
    def fields(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
        value = value if isinstance(value, dict) else {}
        return {key: value.get(key) for key in keys}

    selection = data.get("content_selection")
    selection = selection if isinstance(selection, dict) else {}
    candidates = selection.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    concepts = get(data, "concept_competition.concepts")
    concepts = concepts if isinstance(concepts, list) else []
    payload = {
        "date": get(data, "run.date"),
        "passed": get(data, "qa.final_status") == "passed",
        "content": fields(data.get("content"), ("text", "author", "work", "text_type", "translator", "source_url")),
        "selection": fields(selection, ("desired_effect", "selected_candidate_id")),
        "candidates": [fields(row, ("candidate_id", "text", "author", "work", "decision", "source_type", "cultural_context", "period", "semantic_signature")) for row in candidates if isinstance(row, dict)],
        "plain_brief": fields(data.get("plain_brief"), ("selected_emphasis", "source_of_strength", "emotional_temperature")),
        "semantic_card": fields(data.get("semantic_card"), ("core_tension", "source_of_strength", "emotional_temperature")),
        "concepts": [fields(row, ("decision", "representation_mode")) for row in concepts if isinstance(row, dict)],
        "final_image_path": get(data, "layout.final_image_path"),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def history_index_freshness_errors(index: dict[str, Any], record_path: Path) -> list[str]:
    """Compare live source inventory with a snapshot, excluding only this run."""
    manifest = index.get("source_manifest")
    raw_root = index.get("source_runs_dir")
    if not isinstance(manifest, list) or not nonempty(raw_root) or index.get("source_manifest_hash_kind") != "index_inputs_v1":
        return ["history source_manifest is missing; rebuild the series index"]
    root = Path(raw_root)
    if not root.is_absolute() or not root.is_dir():
        return ["history source_runs_dir must be an existing absolute directory"]
    excluded = str(record_path.resolve())
    expected: dict[str, str] = {}
    for row in manifest:
        if not isinstance(row, dict) or not nonempty(row.get("path")) or not nonempty(row.get("sha256")):
            return ["history source_manifest contains an invalid entry"]
        path = str(Path(row["path"]).resolve())
        if path != excluded:
            expected[path] = row["sha256"]
    try:
        current = {
            str(path.resolve()): history_source_sha256(json.loads(path.read_text(encoding="utf-8")))
            for path in root.glob("*/design-record.json")
            if str(path.resolve()) != excluded
        }
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        return [f"cannot verify history source freshness: {exc}"]
    if current != expected:
        return ["history source records changed since index build; rebuild and repeat history checking"]
    return []


def history_freshness_errors(data: dict[str, Any], record_path: Path) -> list[str]:
    """Production-only gate. Do not invoke during historical final verification."""
    if data.get("schema_version") not in {"1.4", "1.5"}:
        return []
    raw = get(data, "history_dedup.history_index_path")
    if not nonempty(raw):
        return ["history snapshot path is missing"]
    path = Path(raw)
    if not path.is_absolute():
        path = record_path.parent / path
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read history snapshot: {exc}"]
    if not isinstance(index, dict):
        return ["history snapshot must be an object"]
    return history_index_freshness_errors(index, record_path)


def now_for_record(data: dict[str, Any]) -> str:
    timezone = str(get(data, "run.timezone") or "Asia/Shanghai")
    return datetime.now(ZoneInfo(timezone)).isoformat(timespec="microseconds")


def rendering_mode(data: dict[str, Any]) -> str:
    # Absence means the historical local route, NOT the new default.
    return get(data, "run.rendering_mode") if "rendering_mode" in data.get("run", {}) else "local_typesetting"


def rendering_mode_errors(data: dict[str, Any]) -> list[str]:
    mode = rendering_mode(data)
    if mode not in {"integrated_image_text", "local_typesetting"}:
        return ["run.rendering_mode must be integrated_image_text or local_typesetting"]
    if mode == "integrated_image_text" and data.get("schema_version") != "1.5":
        return ["integrated_image_text requires schema_version 1.5"]
    return []


def lock_payload(data: dict[str, Any]) -> dict[str, Any]:
    pre_generation = dict(data.get("pre_generation", {}))
    pre_generation.pop("locked_at", None)
    pre_generation.pop("lock_hash", None)
    payload = {
        "content_selection": data.get("content_selection", {}),
        "content": data.get("content", {}),
        "recent_inertia_check": data.get("recent_inertia_check", {}),
        "pre_generation": pre_generation,
    }
    if data.get("schema_version") in {"1.3", "1.4", "1.5"}:
        payload.update(
            {
                "plain_brief": data.get("plain_brief", {}),
                "concept_competition": data.get("concept_competition", {}),
            }
        )
    else:
        payload["semantic_card"] = data.get("semantic_card", {})
    if data.get("schema_version") in {"1.2", "1.3", "1.4", "1.5"}:
        payload.update(
            {
                "series_context": data.get("series_context", {}),
                "editorial_brief": data.get("editorial_brief", {}),
                "discovery_routes": data.get("discovery_routes", []),
                "history_dedup": data.get("history_dedup", {}),
            }
        )
    if data.get("schema_version") in {"1.4", "1.5"}:
        # Refreshable evidence has its own input binding and immutable snapshot.
        # It must not invalidate otherwise unchanged art direction or backgrounds.
        payload.pop("history_dedup", None)
        payload.pop("series_context", None)
        selection = dict(payload["content_selection"])
        selection["candidates"] = [
            {key: value for key, value in row.items() if key != "history_check"}
            if isinstance(row, dict) else row
            for row in selection.get("candidates", [])
        ]
        payload["content_selection"] = selection
        payload["schema_version"] = data["schema_version"]
        payload["run_identity"] = {
            field: get(data, f"run.{field}") for field in ("date", "timezone", "initialized_at")
        }
    if data.get("schema_version") == "1.5":
        payload["expression_policy"] = data.get("expression_policy")
    if "meaning_grounding_required" in data.get("run", {}):
        payload["meaning_grounding_required"] = get(data, "run.meaning_grounding_required")
    if "rendering_mode" in data.get("run", {}):
        payload["rendering_mode"] = rendering_mode(data)
    if rendering_mode(data) == "integrated_image_text":
        # All copy is part of this generation, so it must be locked beforehand.
        payload["integrated_copy"] = {
            "quote": get(data, "content.text"), "weekday": get(data, "run.weekday"),
            **{field: get(data, f"layout.{field}") for field in ("date_text", "source_label", "yi_text", "ji_text")},
        }
        payload["integrated_canvas"] = {field: get(data, f"layout.{field}") for field in ("canvas_width", "canvas_height")}
    return payload


def compute_lock_hash(data: dict[str, Any]) -> str:
    canonical = json.dumps(
        lock_payload(data),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def author_review_errors(data: dict[str, Any]) -> list[str]:
    """Validate the new opt-in record contract, not an author's reputation."""
    review = get(data, "content_selection.author_review")
    if review is None and not get(data, "run.author_review_required"):
        return []  # Historical records are not retroactively certified.
    if not isinstance(review, dict):
        return ["content_selection.author_review must be an object"]
    errors: list[str] = []
    prefix = "content_selection.author_review"
    for field in ("candidate_id", "author", "checked_at", "identity_note", "rationale", "limitations"):
        if not nonempty(review.get(field)):
            errors.append(f"{prefix}.{field} must be non-empty")
    if review.get("candidate_id") != get(data, "content_selection.selected_candidate_id"):
        errors.append(f"{prefix}.candidate_id must match the selected candidate")
    if review.get("author") != get(data, "content.author"):
        errors.append(f"{prefix}.author must match content.author")
    if review.get("decision") != "pass":
        errors.append(f"{prefix}.decision must be pass before art direction or release")
    try:
        checked = datetime.fromisoformat(review.get("checked_at", ""))
        if checked.tzinfo is None:
            raise ValueError("missing timezone")
    except (ValueError, TypeError):
        errors.append(f"{prefix}.checked_at must be an ISO timestamp with timezone")
    queries = review.get("queries")
    if not isinstance(queries, list) or not queries or not all(isinstance(q, str) and q.strip() for q in queries):
        errors.append(f"{prefix}.queries must contain actual search queries")
    sources = review.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append(f"{prefix}.sources must contain inspected sources")
    else:
        for i, source in enumerate(sources):
            if not isinstance(source, dict) or any(not isinstance(source.get(k), str) or not source[k].strip() for k in ("url", "title", "note")):
                errors.append(f"{prefix}.sources[{i}] requires url, title and note")
                continue
            parsed = urlparse(source["url"])
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append(f"{prefix}.sources[{i}].url must be an HTTP(S) source")
    if not isinstance(review.get("findings"), list):
        errors.append(f"{prefix}.findings must be a list; empty is allowed when no material issue was found")
    return errors


def content_selection_errors(data: dict[str, Any], *, check_local_sources: bool = True) -> list[str]:
    errors: list[str] = []
    errors.extend(author_review_errors(data))
    mode = get(data, "content_selection.selection_mode")
    if mode not in ALLOWED_SELECTION_MODES:
        errors.append(
            "content_selection.selection_mode must be one of: "
            + ", ".join(sorted(ALLOWED_SELECTION_MODES))
        )

    candidates = get(data, "content_selection.candidates")
    if not isinstance(candidates, list) or not candidates:
        errors.append("content_selection.candidates must be a non-empty list")
        return errors
    schema_version = data.get("schema_version")
    if mode == "open_search" and schema_version in {"1.2", "1.3", "1.4", "1.5"} and len(candidates) < 5:
        errors.append(f"schema {schema_version} open_search requires at least 5 candidates")
    elif mode == "open_search" and len(candidates) < 3:
        errors.append("open_search requires at least 3 effective candidates")

    candidate_ids: list[str] = []
    selected_rows: list[dict[str, Any]] = []
    allowed_source_status = {"verified", "locatable", "unverified", "rejected"}
    allowed_decisions = {"selected", "reserve", "rejected"}
    required_candidate_fields = (
        "candidate_id",
        "text_type",
        "text",
        "author",
        "source_status",
        "relevance",
        "risk",
        "decision",
    )

    if schema_version in {"1.2", "1.3", "1.4", "1.5"}:
        required_candidate_fields += (
            "work",
            "source_type",
            "cultural_context",
            "period",
            "discovery_route_id",
            "novelty_note",
        )

    for index, candidate in enumerate(candidates):
        label = f"content_selection.candidates[{index}]"
        if not isinstance(candidate, dict):
            errors.append(f"{label} must be an object")
            continue
        for field in required_candidate_fields:
            if not nonempty(candidate.get(field)):
                errors.append(f"{label}.{field} must be non-empty")
        candidate_id = candidate.get("candidate_id")
        if nonempty(candidate_id):
            candidate_ids.append(candidate_id)
        if candidate.get("text_type") not in ALLOWED_TEXT_TYPES:
            errors.append(f"{label}.text_type is invalid")
        if candidate.get("source_status") not in allowed_source_status:
            errors.append(f"{label}.source_status is invalid")
        if candidate.get("decision") not in allowed_decisions:
            errors.append(f"{label}.decision is invalid")
        if candidate.get("decision") == "selected":
            selected_rows.append(candidate)

        if schema_version in {"1.4", "1.5"}:
            if candidate.get("source_type") not in V14_SOURCE_TYPES:
                errors.append(f"{label}.source_type must use a canonical v1.4 source type")
            if candidate.get("decision") in {"selected", "reserve"}:
                if candidate.get("source_status") not in {"locatable", "verified"}:
                    errors.append(f"{label} effective candidate source_status must be locatable or verified")
                errors.extend(source_locator_errors(candidate.get("source_locator"), f"{label}.source_locator", check_local_exists=check_local_sources))
                if not nonempty(candidate.get("source_note")):
                    errors.append(f"{label}.source_note must be non-empty")
                if candidate.get("text_type") == "translated_quote":
                    for field in ("translator", "edition"):
                        if not nonempty(candidate.get(field)):
                            errors.append(f"{label}.{field} is required for a translated candidate")

        if schema_version in {"1.2", "1.3", "1.4", "1.5"}:
            signature = candidate.get("semantic_signature")
            if not isinstance(signature, dict):
                errors.append(f"{label}.semantic_signature must be an object")
            else:
                for field in V12_SEMANTIC_SIGNATURE_FIELDS:
                    if not nonempty(signature.get(field)):
                        errors.append(
                            f"{label}.semantic_signature.{field} must be non-empty"
                        )
            history_check = candidate.get("history_check")
            if not isinstance(history_check, dict):
                errors.append(
                    f"{label}.history_check must be written by check_quote_history.py"
                )
            else:
                if schema_version in {"1.4", "1.5"} and history_check.get("input_sha256") != candidate_input_sha256(candidate):
                    errors.append(f"{label} history input changed; repeat history checking")
                if not nonempty(history_check.get("normalized_text")):
                    errors.append(f"{label}.history_check.normalized_text must be non-empty")
                for field in ("exact_matches", "near_matches"):
                    if not isinstance(history_check.get(field), list):
                        errors.append(f"{label}.history_check.{field} must be a list")
                if (
                    mode == "open_search"
                    and candidate.get("decision") in {"selected", "reserve"}
                    and (history_check.get("exact_matches") or history_check.get("near_matches"))
                ):
                    errors.append(
                        f"{label} cannot remain effective after a historical duplicate match"
                    )

    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("candidate_id values must be unique")

    if schema_version in {"1.2", "1.3", "1.4", "1.5"} and mode == "open_search":
        effective = [
            row
            for row in candidates
            if isinstance(row, dict) and row.get("decision") in {"selected", "reserve"}
        ]
        if len(effective) < 5:
            errors.append(f"schema {schema_version} open_search requires at least 5 effective candidates")
        effective_authors = [str(row.get("author") or "").strip() for row in effective]
        if len(effective_authors) != len(set(effective_authors)):
            errors.append("effective open_search candidates must use distinct authors")
        source_types = {
            str(row.get("source_type") or "").strip() for row in effective
        }
        source_types.discard("")
        if len(source_types) < 3:
            errors.append("effective open_search candidates require at least 3 source types")
        signatures = {
            (
                str(row.get("semantic_signature", {}).get("desired_effect") or "").strip(),
                str(row.get("semantic_signature", {}).get("core_tension") or "").strip(),
                str(row.get("semantic_signature", {}).get("source_of_strength") or "").strip(),
            )
            for row in effective
            if isinstance(row.get("semantic_signature"), dict)
        }
        if schema_version not in {"1.4", "1.5"} and len(signatures) < 3:
            errors.append(
                "effective open_search candidates require at least 3 distinct semantic signatures"
            )
        if schema_version in {"1.4", "1.5"}:
            review = get(data, "content_selection.semantic_diversity_review")
            if not isinstance(review, dict) or review.get("decision") != "pass" or not nonempty(review.get("note")):
                errors.append("v1.4 semantic_diversity_review requires an explicit human comparison decision=pass and note")
        finalists = get(data, "content_selection.finalist_comparison")
        if not isinstance(finalists, list) or len(finalists) < 2:
            errors.append("open_search requires at least 2 finalist comparisons")
        else:
            finalist_ids: list[str] = []
            for index, finalist in enumerate(finalists):
                label = f"content_selection.finalist_comparison[{index}]"
                if not isinstance(finalist, dict):
                    errors.append(f"{label} must be an object")
                    continue
                for field in (
                    "candidate_id",
                    "quality_case",
                    "core_relationship",
                    "comparison_to_winner",
                ):
                    if not nonempty(finalist.get(field)):
                        errors.append(f"{label}.{field} must be non-empty")
                finalist_ids.append(str(finalist.get("candidate_id") or "").strip())
            if len(finalist_ids) != len(set(finalist_ids)):
                errors.append("finalist candidate IDs must be unique")
            if any(value not in candidate_ids for value in finalist_ids):
                errors.append("finalist candidate IDs must match candidates")
            if get(data, "content_selection.selected_candidate_id") not in finalist_ids:
                errors.append("finalist comparison must include the selected candidate")
        for field, minimum in (
            ("content_selection.range_check", 30),
            ("content_selection.pool_stop_reason", 40),
            ("content_selection.selection_rationale", 50),
        ):
            value = str(get(data, field) or "").strip()
            if value and len(value) < minimum:
                errors.append(f"{field} must be at least {minimum} characters")

    selected_id = get(data, "content_selection.selected_candidate_id")
    if selected_id not in candidate_ids:
        errors.append("selected_candidate_id must match a candidate_id")
    if len(selected_rows) != 1:
        errors.append("exactly one candidate decision must be selected")
    elif selected_rows[0].get("candidate_id") != selected_id:
        errors.append(
            "selected candidate decision does not match selected_candidate_id"
        )
    else:
        selected = selected_rows[0]
        if selected.get("source_status") != "verified":
            errors.append("selected candidate source_status must be verified")
        for candidate_field, content_field in (
            ("text_type", "content.text_type"),
            ("text", "content.text"),
            ("author", "content.author"),
        ):
            if selected.get(candidate_field) != get(data, content_field):
                errors.append(
                    f"selected candidate {candidate_field} "
                    f"must match {content_field}"
                )
        if schema_version in {"1.2", "1.3", "1.4", "1.5"} and selected.get("work") != get(
            data, "content.work"
        ):
            errors.append("selected candidate work must match content.work")
        if schema_version in {"1.4", "1.5"}:
            if get(data, "content.verified") is not True:
                errors.append("content.verified must be true before v1.4 selection passes")
            if selected.get("text_type") == "translated_quote":
                for field in ("translator", "edition"):
                    if not nonempty(get(data, f"content.{field}")) or selected.get(field) != get(data, f"content.{field}"):
                        errors.append(f"selected translated candidate {field} must match content.{field}")

    return errors


def v12_selection_system_errors(
    data: dict[str, Any], record_path: Path | None = None, *, check_local_sources: bool = True
) -> list[str]:
    """Validate the executable selection system introduced in schema 1.2."""
    if data.get("schema_version") not in {"1.2", "1.3", "1.4", "1.5"}:
        return []
    errors: list[str] = []
    for section in ("series_context", "editorial_brief", "history_dedup"):
        if not isinstance(data.get(section), dict):
            errors.append(f"missing object section: {section}")

    brief = data.get("editorial_brief")
    if isinstance(brief, dict):
        for field in V12_EDITORIAL_BRIEF_FIELDS:
            if not nonempty(brief.get(field)):
                errors.append(f"editorial_brief.{field} must be non-empty")
        for field in (
            "recent_saturation",
            "underexplored_directions",
            "avoid_repeating",
            "exploration_priority",
        ):
            value = brief.get(field)
            if not isinstance(value, list):
                errors.append(f"editorial_brief.{field} must be a list")
            elif get(data, "content_selection.selection_mode") == "open_search" and not value:
                errors.append(f"editorial_brief.{field} must be non-empty for open_search")

    routes = data.get("discovery_routes")
    mode = get(data, "content_selection.selection_mode")
    if not isinstance(routes, list):
        errors.append("discovery_routes must be a list")
        routes = []
    if mode == "open_search":
        if len(routes) < 4:
            errors.append("open_search requires at least 4 discovery routes")
        route_ids: list[str] = []
        route_types: set[str] = set()
        route_effective_map: dict[str, set[str]] = {}
        raw_total = 0
        candidate_route_ids = {
            str(row.get("discovery_route_id") or "").strip()
            for row in get(data, "content_selection.candidates") or []
            if isinstance(row, dict)
        }
        for index, route in enumerate(routes):
            label = f"discovery_routes[{index}]"
            if not isinstance(route, dict):
                errors.append(f"{label} must be an object")
                continue
            for field in ("route_id", "route_type", "search_intent", "scope", "finding"):
                if not nonempty(route.get(field)):
                    errors.append(f"{label}.{field} must be non-empty")
            route_id = str(route.get("route_id") or "").strip()
            route_type = str(route.get("route_type") or "").strip()
            if route_id:
                route_ids.append(route_id)
            if route_type:
                route_types.add(route_type)
            raw_count = route.get("raw_count")
            if data.get("schema_version") in {"1.4", "1.5"}:
                if route_type not in V14_ROUTE_TYPES:
                    errors.append(f"{label}.route_type must use a canonical v1.4 route type")
                leads = route.get("leads")
                if not isinstance(leads, list):
                    errors.append(f"{label}.leads must be a list")
                else:
                    if raw_count != len(leads):
                        errors.append(f"{label}.raw_count must equal len(leads)")
                    for lead_index, lead in enumerate(leads):
                        lead_label = f"{label}.leads[{lead_index}]"
                        if not isinstance(lead, dict):
                            errors.append(f"{lead_label} must be an object")
                            continue
                        errors.extend(source_locator_errors(lead.get("locator"), f"{lead_label}.locator", check_local_exists=check_local_sources))
                        if not nonempty(lead.get("observation")):
                            errors.append(f"{lead_label}.observation must be non-empty")
            if not isinstance(raw_count, int) or raw_count <= 0:
                errors.append(f"{label}.raw_count must be a positive integer")
            else:
                raw_total += raw_count
            effective_ids = route.get("effective_candidate_ids")
            if not isinstance(effective_ids, list):
                errors.append(f"{label}.effective_candidate_ids must be a list")
            elif route_id:
                route_effective_map[route_id] = {
                    str(value).strip() for value in effective_ids if str(value).strip()
                }
        if len(route_ids) != len(set(route_ids)):
            errors.append("discovery route IDs must be unique")
        if len(route_types) < 3:
            errors.append("open_search requires at least 3 discovery route types")
        if raw_total < 12:
            errors.append("open_search discovery routes must examine at least 12 raw leads")
        unknown_routes = candidate_route_ids - set(route_ids)
        if unknown_routes:
            errors.append(
                "candidate discovery_route_id values must match discovery_routes: "
                + ", ".join(sorted(unknown_routes))
            )
        for candidate in get(data, "content_selection.candidates") or []:
            if not isinstance(candidate, dict) or candidate.get("decision") == "rejected":
                continue
            route_id = str(candidate.get("discovery_route_id") or "").strip()
            candidate_id = str(candidate.get("candidate_id") or "").strip()
            if candidate_id and candidate_id not in route_effective_map.get(route_id, set()):
                errors.append(
                    f"effective candidate {candidate_id} must be listed in route {route_id}"
                )

    history = data.get("history_dedup")
    if isinstance(history, dict):
        for field in (
            "history_index_path",
            "history_index_sha256",
            "checked_at",
            "selected_candidate_id",
            "decision",
        ):
            if not nonempty(history.get(field)):
                errors.append(f"history_dedup.{field} must be non-empty")
        if not isinstance(history.get("records_scanned"), int) or history.get(
            "records_scanned"
        ) < 0:
            errors.append("history_dedup.records_scanned must be a non-negative integer")
        decision = history.get("decision")
        if decision not in {"passed", "passed_with_user_override"}:
            errors.append(
                "history_dedup.decision must be passed or passed_with_user_override"
            )
        selected_check = history.get("selected_history_check")
        if not isinstance(selected_check, dict):
            errors.append("history_dedup.selected_history_check must be an object")
        else:
            exact = selected_check.get("exact_matches")
            near = selected_check.get("near_matches")
            if not isinstance(exact, list) or not isinstance(near, list):
                errors.append(
                    "history_dedup selected exact_matches and near_matches must be lists"
                )
            has_duplicate = bool(exact or near)
            if has_duplicate and decision != "passed_with_user_override":
                errors.append("historical duplicate requires passed_with_user_override")
            if has_duplicate:
                if get(data, "content_selection.selection_mode") not in {
                    "user_supplied",
                    "revision",
                }:
                    errors.append("open_search cannot override a historical duplicate")
                if history.get("reuse_authorized") is not True or not nonempty(
                    history.get("reuse_authorization_reason")
                ):
                    errors.append("historical duplicate override requires user authorization")
        if history.get("selected_candidate_id") != get(
            data, "content_selection.selected_candidate_id"
        ):
            errors.append(
                "history_dedup.selected_candidate_id must match content selection"
            )
        if data.get("schema_version") in {"1.4", "1.5"}:
            if history.get("checked_run_date") != get(data, "run.date"):
                errors.append("history run date changed; repeat history checking")
            selected = next((row for row in get(data, "content_selection.candidates") or []
                             if isinstance(row, dict) and row.get("candidate_id") == history.get("selected_candidate_id")), None)
            if selected is not None and selected_check != selected.get("history_check"):
                errors.append("selected history check must match the selected candidate history check")
            if history.get("snapshot_immutable") is not True:
                errors.append("v1.4 history requires an immutable per-run snapshot")

        raw_index_path = str(history.get("history_index_path") or "").strip()
        if raw_index_path:
            index_path = Path(raw_index_path).expanduser()
            if not index_path.is_absolute() and record_path is not None:
                index_path = record_path.parent / index_path
            if not index_path.is_file():
                errors.append(f"history index file does not exist: {index_path}")
            else:
                expected = str(history.get("history_index_sha256") or "")
                if expected and file_sha256(index_path) != expected:
                    errors.append("history index changed after the duplicate check")

    series = data.get("series_context")
    if isinstance(series, dict):
        for field in (
            "history_index_path",
            "history_index_built_at",
        ):
            if not nonempty(series.get(field)):
                errors.append(f"series_context.{field} must be non-empty")
        if not isinstance(series.get("history_records_scanned"), int):
            errors.append("series_context.history_records_scanned must be an integer")
    return errors


def meaning_grounding_errors(data: dict[str, Any]) -> list[str]:
    """Bind source evidence, not certify authors' intentions or interpretation."""
    flag = get(data, "run.meaning_grounding_required")
    if flag is None:
        return []  # Do not invent evidence for historical records.
    if flag is not True:
        return ["run.meaning_grounding_required cannot be disabled once declared"]
    basis = get(data, "plain_brief.meaning_basis")
    if not isinstance(basis, dict):
        return ["plain_brief.meaning_basis must be an object"]
    errors = []
    for field in ("source_locator", "supporting_text", "attribution_scope", "support_note", "limits"):
        if not isinstance(basis.get(field), str) or not nonempty(basis.get(field)):
            errors.append(f"plain_brief.meaning_basis.{field} must be a non-empty string")
    if not isinstance(get(data, "plain_brief.editorial_extension"), str):
        errors.append("plain_brief.editorial_extension must be a string (empty if absent)")
    def normalize(value: Any) -> str:
        return "".join(str(value or "").split())
    excerpt = normalize(basis.get("supporting_text"))
    context = normalize(get(data, "content.chapter_or_context"))
    quote = normalize(get(data, "content.text"))
    if not context or (excerpt and excerpt not in context):
        errors.append("meaning_basis.supporting_text must be a verbatim excerpt of content.chapter_or_context")
    if get(data, "content.text_type") in {"exact_quote", "translated_quote", "author_about_work"} and (not quote or quote not in excerpt):
        errors.append("meaning_basis.supporting_text must include the selected quote")
    return errors


def source_meaning_review_input(data: dict[str, Any]) -> dict[str, Any]:
    """Only raw source material; never expose the designer's interpretation."""
    if get(data, "run.meaning_grounding_required") is not True:
        return {}
    return {"source_locator": get(data, "plain_brief.meaning_basis.source_locator"),
            "supporting_text": get(data, "plain_brief.meaning_basis.supporting_text"),
            "question": "先仅根据原句和原始上下文，在quote_meaning_in_own_words中说明句意、具体原文依据及说话者/对象/限制；不把人物台词自动归为作者立场。再判断图文关系，不把卡片暗示的生活建议当原意；依据不足或关系被改义时revise。"}


def v13_art_direction_errors(data: dict[str, Any]) -> list[str]:
    """Validate the light, high-leverage art-direction decisions in schema 1.3."""
    if data.get("schema_version") not in {"1.3", "1.4", "1.5"}:
        return []
    from expression_contract import concept_expression_errors
    errors: list[str] = concept_expression_errors(data) + meaning_grounding_errors(data)

    brief = data.get("plain_brief")
    if not isinstance(brief, dict):
        return ["missing object section: plain_brief"]
    for field in (
        "core_meaning",
        "selected_emphasis",
        "common_misreading",
        "semantic_invariant" if data.get("schema_version") in {"1.4", "1.5"} else "must_be_visible_relation",
        "emotional_temperature",
        "source_of_strength",
        "intended_aftertaste",
    ):
        if not nonempty(brief.get(field)):
            errors.append(f"plain_brief.{field} must be non-empty")
    emphasis_options = brief.get("editorial_emphasis_options")
    if not isinstance(emphasis_options, list) or not emphasis_options:
        errors.append("plain_brief.editorial_emphasis_options must be a non-empty list")
    elif brief.get("selected_emphasis") not in emphasis_options:
        errors.append("plain_brief.selected_emphasis must match an editorial emphasis option")
    forbidden = brief.get("forbidden_literal_elements")
    if data.get("schema_version") not in {"1.4", "1.5"} and (not isinstance(forbidden, list) or not forbidden):
        errors.append("plain_brief.forbidden_literal_elements must be a non-empty list")

    inertia = data.get("recent_inertia_check")
    if not isinstance(inertia, dict):
        errors.append("missing object section: recent_inertia_check")
    else:
        if not isinstance(inertia.get("recent_cards_reviewed"), list):
            errors.append("recent_inertia_check.recent_cards_reviewed must be a list")
        if not isinstance(inertia.get("recent_expression_mechanisms"), list):
            errors.append("recent_inertia_check.recent_expression_mechanisms must be a list")

    competition = data.get("concept_competition")
    if not isinstance(competition, dict):
        return errors + ["missing object section: concept_competition"]
    mode = competition.get("mode")
    if mode not in {"standard", "directed"}:
        errors.append("concept_competition.mode must be standard or directed")
    if mode == "directed" and not nonempty(competition.get("directed_reason")):
        errors.append("directed concept competition requires directed_reason")
    concepts = competition.get("concepts")
    if not isinstance(concepts, list):
        errors.append("concept_competition.concepts must be a list")
        concepts = []
    minimum = 3 if mode == "standard" else 1
    if len(concepts) < minimum:
        errors.append(f"{mode or 'unknown'} concept competition requires at least {minimum} concept(s)")

    concept_ids: list[str] = []
    selected_rows: list[dict[str, Any]] = []
    representation_modes: set[str] = set()
    for index, concept in enumerate(concepts):
        label = f"concept_competition.concepts[{index}]"
        if not isinstance(concept, dict):
            errors.append(f"{label} must be an object")
            continue
        for field in (
            "concept_id",
            "core_visual_proposition",
            "first_read_relationship",
            "representation_mode",
            "implementation",
            "misreading_risk",
            "comparison_note",
            "decision",
        ):
            if not nonempty(concept.get(field)):
                errors.append(f"{label}.{field} must be non-empty")
        concept_id = str(concept.get("concept_id") or "").strip()
        if concept_id:
            concept_ids.append(concept_id)
        representation_mode = str(concept.get("representation_mode") or "").strip()
        if representation_mode:
            representation_modes.add(representation_mode)
        if concept.get("decision") not in {"selected", "reserve", "rejected"}:
            errors.append(f"{label}.decision is invalid")
        if concept.get("decision") == "selected":
            selected_rows.append(concept)
    if len(concept_ids) != len(set(concept_ids)):
        errors.append("concept_id values must be unique")
    if mode == "standard" and len(representation_modes) < 2:
        errors.append("standard concept competition requires at least 2 representation modes")
    selected_id = competition.get("selected_concept_id")
    if selected_id not in concept_ids:
        errors.append("selected_concept_id must match a concept_id")
    if len(selected_rows) != 1:
        errors.append("exactly one visual concept must be selected")
    elif selected_rows[0].get("concept_id") != selected_id:
        errors.append("selected visual concept does not match selected_concept_id")
    if not nonempty(competition.get("selection_rationale")):
        errors.append("concept_competition.selection_rationale must be non-empty")

    pre_selected = get(data, "pre_generation.selected_concept_id")
    if selected_id and pre_selected != selected_id:
        errors.append("pre_generation.selected_concept_id must match concept competition")
    if selected_rows:
        first_read = str(selected_rows[0].get("first_read_relationship") or "")
        planned = str(get(data, "pre_generation.core_visual_relationship") or "")
        if first_read.strip() and planned.strip() and first_read.strip() != planned.strip():
            errors.append(
                "pre_generation.core_visual_relationship must match the selected concept first_read_relationship"
            )
    return errors


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path = path.resolve()
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
