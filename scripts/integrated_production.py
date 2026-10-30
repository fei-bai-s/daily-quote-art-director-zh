"""Mode-specific evidence for jointly generated art and exact Chinese copy.

These checks bind files and independent observations; they do not perform OCR,
prove aesthetic quality, or turn a context-isolated review into a quote-blind one.
"""
from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path

from record_utils import get, nonempty, now_for_record, rendering_mode, source_meaning_review_input
from production_integrity import (
    TYPOGRAPHY_REVIEW, attempt_errors, canonical_hash, checked_asset,
    designer_contexts, evidence_dir, find_attempt, image_asset, layout_text_errors,
    ordered_times, preserve_legacy_typography_contract, read_json, require_lock, snapshot_file, snapshot_json,
    text_data, typography_result_errors,
)
from expression_contract import REVIEW_BOUNDARY, expression_result_errors

GROUPS = ("quote", "source", "yi", "ji", "date", "weekday")
GUIDANCE = "以编辑设计与字体排印的专业方法，把文字与图像作为同一件作品设计。根据这张卡的需要，运用格式塔的接近、相似和图底关系，以及视觉重量、光学对齐和中文排印的阅读节奏；不必使用全部原则，也不要把术语印在图中。所有文字由专门设计的留白托住，与图像主体、可辨细节和明显纹理保持视觉间隔，不直接压在图像上；不是在照片里找一块字能看清的背景加字幕。留白的位置、形态和底色由你设计，并参与整体构图。让句子自然连续读完，不因换行、字距或强调而割裂词组；辅助信息清楚但不争夺注意力；文字的声音、疏密与画面的体量和气氛相互支持。字体、字号、位置、换行、字重、字色和具体构成全部由你自主决定。"


def exact_copy(data: dict) -> dict:
    texts = text_data(data)
    return {"quote": texts["quote_text"], "source": texts["source_label"],
            "yi": texts["yi_text"], "ji": texts["ji_text"],
            "date": texts["date_text"], "weekday": str(get(data, "run.weekday") or "")}


def compact(value: str) -> str:
    # Line wrapping is free, but punctuation and wording are not rewritten.
    return re.sub(r"\s+", "", value)


def prompt_errors(data: dict, prompt: str) -> list[str]:
    if rendering_mode(data) != "integrated_image_text":
        return [f"prompt must include '{token}'" for token in ("no text", "no watermark") if token not in prompt.lower()]
    errors = []
    if not prompt.strip():
        errors.append("integrated prompt must be non-empty")
    if re.search(r"\bno text\b|\btext[- ]free\b|不要(?:生成|出现|任何)?文字|完全无字|无文字底图", prompt, re.I):
        errors.append("integrated prompt conflicts with requested copy: remove the no-text instruction")
    if "no watermark" not in prompt.lower() and "无水印" not in prompt:
        errors.append("integrated prompt must forbid watermarks")
    for group, value in exact_copy(data).items():
        if not value or compact(value) not in compact(prompt):
            errors.append(f"integrated prompt must contain complete exact {group} copy")
    return errors


def require_integrated(data: dict) -> None:
    require_lock(data)
    if rendering_mode(data) != "integrated_image_text":
        raise ValueError("this command requires integrated_image_text")


def record_integrated_execution(data: dict, record_path: Path, result_path: Path) -> None:
    require_integrated(data)
    asset = get(data, "production.assets.background")
    errors = checked_asset(asset, "generated_card", True, True)
    result = read_json(result_path)
    for field in ("key_action_or_state_realized", "concept_fidelity"):
        if not nonempty(result.get(field)):
            errors.append(f"execution output requires {field}")
    if result.get("decision") not in {"pass", "regenerate_same_concept"}:
        errors.append("invalid execution decision")
    if result.get("background_text_free") is True:
        errors.append("integrated card must not be recorded as text-free")
    if result.get("decision") == "pass" and result.get("text_safe_area_usable") is not True:
        errors.append("execution pass requires usable text/image coexistence")
    if errors:
        raise ValueError("; ".join(errors))
    directory = evidence_dir(record_path, "execution")
    data["execution_validation"] = {**result, "checked_at": now_for_record(data),
        "background_sha256": asset["sha256"], "raw_output": snapshot_file(result_path, directory, "review.json")}
    data.setdefault("qa", {})["execution_gate_checked"] = result["decision"] == "pass"
    data["post_generation"]["planned_relationships_realized"] = [result["key_action_or_state_realized"]]
    data["post_generation"]["regeneration_or_fix_decision"] = result["decision"]


def register_integrated(data: dict, record_path: Path, final: Path) -> dict:
    require_integrated(data)
    production = data["production"]
    assets = production["assets"]
    raw = assets.get("background")
    errors = checked_asset(raw, "generated_card", True, True) + layout_text_errors(data)
    execution = data.get("execution_validation", {})
    if execution.get("decision") != "pass" or execution.get("background_sha256") != (raw or {}).get("sha256"):
        errors.append("register-integrated requires execution approval of the current generated card")
    errors += checked_asset(execution.get("raw_output"), "execution.raw_output")
    if assets.get("final"):
        errors.append("final already registered; register a new generation revision before replacing it")
    if errors:
        raise ValueError("; ".join(errors))
    final = final.expanduser().resolve()
    if final.exists():
        raise ValueError("refusing to overwrite final; use a fresh output filename")
    if (raw["width"], raw["height"]) != (get(data, "layout.canvas_width"), get(data, "layout.canvas_height")):
        raise ValueError("generated card size must match the locked production canvas; do not crop the typography")
    final.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(raw["path"], final)  # No resizing, overlay, cleanup, or typography rewrite.
    directory = evidence_dir(record_path, "integrated")
    from PIL import Image
    with Image.open(final) as image:
        image.convert("RGB").resize((360, round(image.height * 360 / image.width)), Image.Resampling.LANCZOS).save(directory / "final-360.png")
    assets.update(final=image_asset(final, True), final_mobile=image_asset(directory / "final-360.png", True))
    production["layout_text_snapshot"] = exact_copy(data)
    production["layout_text_sha256"] = canonical_hash(exact_copy(data))
    production["integrated_registered_at"] = now_for_record(data)
    data["layout"].update(final_image_path=str(final), render_source_path="", rendered_at=production["integrated_registered_at"])
    data["qa"].update(final_text_rendered_deterministically=False, generated_text_checked=False)
    data["run"]["status"] = "integrated_registered"
    return {"final": assets["final"], "mobile": assets["final_mobile"]}


def hashes(data: dict) -> dict:
    return {key: get(data, f"production.assets.{key}.sha256") for key in ("background", "final", "final_mobile")}


def review_input(data: dict, images: dict) -> dict:
    result = {"protocol": "integrated_context_isolated", "text_visible": True, "quote_blind": False,
        "images": {"full_resolution": images["final"], "mobile": images["final_mobile"]},
        "exact_copy": exact_copy(data), "author": get(data, "content.author"), "work": get(data, "content.work"),
        "original_context": get(data, "content.chapter_or_context"),
        "series_boundary": REVIEW_BOUNDARY.replace("揭句后", "结合原句后"),
        "expression_policy": data["expression_policy"], "typography_review": copy.deepcopy(TYPOGRAPHY_REVIEW),
        "questions": [
            "这是带字成图，不能声称无字盲读。分别记录实际可见的画面状态/关系与结合文案后的推断；指出第一眼注意力和主导误读，不补造不可见的时间或因果。",
            "根据原句与必要语境自己说明句意，再判断图文关联natural/forced/conflicting/unrelated；独立填写expression_review，不能用自然相关抵消表达方式失败。",
            "逐组抄读quote/source/yi/ji/date/weekday，填写copy_check.observed_text和matches；空白与换行可变，字词、标点不能改，另给extra_text_absent。",
            "每组六项填写readability的full_resolution(pass/fail)与具体evidence。",
        ]}
    source_material = source_meaning_review_input(data)
    if source_material:
        result["meaning_grounding"] = source_material
    return result


def start_integrated_review(data: dict, record_path: Path, reviewer_id: str, context_id: str) -> dict:
    require_integrated(data)
    if not nonempty(reviewer_id) or not nonempty(context_id) or context_id in designer_contexts(data):
        raise ValueError("review requires an independent identity and context")
    if get(data, "semantic_cold_review.integrated_input"):
        raise ValueError("review exists; preserve it and register a new image revision")
    if context_id in {row.get("reviewer_context_id") for row in get(data, "production.review_contexts") or []}:
        raise ValueError("changed card requires a fresh reviewer context")
    directory = evidence_dir(record_path, "integrated-review")
    images = {}
    for key in ("final", "final_mobile"):
        asset = get(data, f"production.assets.{key}")
        errors = checked_asset(asset, key, True, True)
        if errors:
            raise ValueError("; ".join(errors))
        images[key] = snapshot_file(Path(asset["path"]), directory, f"{key}.png")
    review = {"protocol": "integrated_context_isolated", "text_visible": True, "quote_blind": False,
        "reviewer_id": reviewer_id, "reviewer_context_id": context_id, "started_at": now_for_record(data),
        "asset_hashes": hashes(data), "images": images, "decision": "pending"}
    review["integrated_input"] = snapshot_json(review_input(data, images), directory, "input.json")
    data["semantic_cold_review"] = review
    data["production"].setdefault("review_contexts", []).append({"reviewer_context_id": context_id, "started_at": review["started_at"]})
    return {"next_stage": "integrated", "input": review["integrated_input"]}


def result_errors(result: dict, data: dict, require_pass: bool = False) -> list[str]:
    errors = []
    for field in ("actual_image_observation", "first_attention", "dominant_misreading", "quote_meaning_in_own_words", "connection_reason"):
        if not nonempty(result.get(field)):
            errors.append(f"integrated review requires {field}")
    if result.get("connection_assessment") not in {"natural", "forced", "conflicting", "unrelated"}:
        errors.append("invalid connection_assessment")
    if result.get("decision") not in {"pass", "revise"}:
        errors.append("invalid integrated review decision")
    if type(result.get("extra_text_absent")) is not bool:
        errors.append("extra_text_absent must be boolean")
    copies = result.get("copy_check", {})
    readable = result.get("readability", {})
    for group, expected in exact_copy(data).items():
        row = copies.get(group) if isinstance(copies, dict) else None
        if not isinstance(row, dict) or not nonempty(row.get("observed_text")) or type(row.get("matches")) is not bool:
            errors.append(f"copy_check.{group} requires observed_text and boolean matches")
        elif row["matches"] != (compact(row["observed_text"]) == compact(expected)):
            errors.append(f"copy_check.{group}.matches contradicts observed_text")
        elif require_pass and not row["matches"]:
            errors.append(f"generated {group} copy is incorrect")
        row = readable.get(group) if isinstance(readable, dict) else None
        if not isinstance(row, dict) or not nonempty(row.get("evidence")):
            errors.append(f"readability.{group} requires concrete evidence")
            continue
        for size in ("full_resolution",):
            if row.get(size) not in {"pass", "fail"}:
                errors.append(f"readability.{group}.{size} must be pass/fail")
            elif require_pass and row[size] != "pass":
                errors.append(f"readability.{group}.{size} must pass")
    errors += expression_result_errors(result, data, require_pass)
    errors += typography_result_errors(result, {"typography_review": TYPOGRAPHY_REVIEW}, require_pass)
    if require_pass and (result.get("decision") != "pass" or result.get("connection_assessment") != "natural" or result.get("extra_text_absent") is not True):
        errors.append("integrated review must pass natural fit and absence of extra text")
    return errors


def register_integrated_review(data: dict, record_path: Path, result_path: Path) -> None:
    require_integrated(data)
    review = data.get("semantic_cold_review", {})
    errors = review_contract_errors(data, review)
    if review.get("integrated_output"):
        errors.append("review output already sealed; do not overwrite it")
    result = read_json(result_path)
    errors += result_errors(result, data)
    if errors:
        raise ValueError("; ".join(errors))
    directory = Path(review["integrated_input"]["path"]).parent
    review["integrated_output"] = snapshot_file(result_path, directory, "output.json")
    review["completed_at"] = now_for_record(data)
    passed = not result_errors(result, data, True)
    review.update(decision="pass" if passed else "revise", alignment_basis={
        "lock_hash": get(data, "pre_generation.lock_hash"), "integrated_output_sha256": review["integrated_output"]["sha256"]},
        plan_vs_observed="", missing_link="pending", missing_link_note="", explanation_required=True)
    qa = data.setdefault("qa", {})
    qa.update(readability=result["readability"], semantic_cold_review_checked=True,
        generated_text_checked=all(result["copy_check"][g]["matches"] for g in GROUPS) and result["extra_text_absent"],
        final_image_inspected_full_resolution=all(result["readability"][g]["full_resolution"] == "pass" for g in GROUPS),
        no_overlap_or_clipping=all(result["readability"][g]["full_resolution"] == "pass" for g in GROUPS))
    data["run"]["status"] = "review_passed" if passed else "revision_required"


def review_contract_errors(data: dict, review: dict) -> list[str]:
    errors = []
    if review.get("protocol") != "integrated_context_isolated" or review.get("text_visible") is not True or review.get("quote_blind") is not False:
        errors.append("integrated review must honestly record visible text, not quote-blind review")
    if any(key in review for key in ("stage1_input", "stage1_output", "image_only_reviewed_at", "quote_revealed_at")):
        errors.append("integrated review cannot claim staged text-free observation")
    if not nonempty(review.get("reviewer_id")) or not nonempty(review.get("reviewer_context_id")) or review.get("reviewer_context_id") in designer_contexts(data):
        errors.append("independent reviewer identity/context required")
    if review.get("asset_hashes") != hashes(data):
        errors.append("review belongs to another card revision")
    images = review.get("images", {})
    for key in ("final", "final_mobile"):
        errors += checked_asset(images.get(key), f"review.images.{key}")
        if images.get(key, {}).get("sha256") != get(data, f"production.assets.{key}.sha256"):
            errors.append(f"review image {key} differs from current card")
    errors += checked_asset(review.get("integrated_input"), "review.integrated_input")
    try:
        saved_input = read_json(Path(review["integrated_input"]["path"]))
        expected_input = preserve_legacy_typography_contract(review_input(data, images), saved_input)
        if saved_input != expected_input:
            errors.append("integrated review input differs from its isolated fixed contract")
    except (KeyError, OSError, ValueError, TypeError) as exc:
        errors.append(f"invalid integrated input: {exc}")
    return errors


def integrated_production_errors(data: dict, record_path: Path, stage: str) -> list[str]:
    errors = layout_text_errors(data) + prompt_errors(data, str(get(data, "pre_generation.prompt") or ""))
    try:
        require_integrated(data)
    except (ValueError, TypeError) as exc:
        errors.append(str(exc))
    if stage != "final":
        return errors
    assets = get(data, "production.assets") or {}
    for key in ("background", "final", "final_mobile"):
        errors += checked_asset(assets.get(key), f"production.assets.{key}", True, True)
    if assets.get("background", {}).get("sha256") != assets.get("final", {}).get("sha256"):
        errors.append("final must preserve generated PNG bytes; local overlay/crop is not integrated generation")
    if any(assets.get(key) for key in ("text_free", "text_free_mobile", "render_source", "render_manifest")) or get(data, "layout.render_source_path"):
        errors.append("integrated route must not claim local/text-free render artifacts")
    if get(data, "qa.final_text_rendered_deterministically") is not False:
        errors.append("integrated route must not claim deterministic typography")
    for field, key in (("post_generation.background_path", "background"), ("layout.final_image_path", "final")):
        if get(data, field) != assets.get(key, {}).get("path"):
            errors.append(f"{field} is not the registered asset")
    if get(data, "production.layout_text_snapshot") != exact_copy(data) or get(data, "production.layout_text_sha256") != canonical_hash(exact_copy(data)):
        errors.append("integrated copy changed after registration")
    execution = data.get("execution_validation", {})
    errors += checked_asset(execution.get("raw_output"), "execution.raw_output")
    review = data.get("semantic_cold_review", {})
    errors += review_contract_errors(data, review)
    errors += checked_asset(review.get("integrated_output"), "review.integrated_output")
    try:
        attempt = find_attempt(data, get(data, "production.current_attempt_id") or "")
        errors += attempt_errors(data, attempt)
        if attempt.get("background", {}).get("sha256") != assets.get("background", {}).get("sha256") or get(data, "post_generation.generated_at") != attempt.get("completed_at"):
            errors.append("card must bind the actual generation result and completion time")
        raw_execution = read_json(Path(execution["raw_output"]["path"]))
        for field, value in raw_execution.items():
            if execution.get(field) != value:
                errors.append(f"execution.{field} differs from original output")
        if execution.get("decision") != "pass" or execution.get("text_safe_area_usable") is not True or execution.get("background_text_free") is True or execution.get("background_sha256") != assets["background"]["sha256"]:
            errors.append("current integrated card needs passing execution evidence")
        result = read_json(Path(review["integrated_output"]["path"]))
        errors += result_errors(result, data, True)
        if get(data, "qa.readability") != result.get("readability"):
            errors.append("QA readability differs from the original independent review")
        basis = {"lock_hash": get(data, "pre_generation.lock_hash"), "integrated_output_sha256": review["integrated_output"]["sha256"]}
        if review.get("alignment_basis") != basis:
            errors.append("creator alignment is stale")
        if not ordered_times(attempt["completed_at"], get(data, "post_generation.registered_at"), execution["checked_at"], get(data, "production.integrated_registered_at"), review["started_at"], review["completed_at"], get(data, "design_concept.written_at"), now_for_record(data)):
            errors.append("integrated production/review timeline is out of order")
        if get(data, "layout.rendered_at") != get(data, "production.integrated_registered_at"):
            errors.append("layout.rendered_at must record actual integrated registration")
        from PIL import Image
        with Image.open(assets["final"]["path"]) as final, Image.open(assets["final_mobile"]["path"]) as mobile:
            expected = final.convert("RGB").resize((360, round(final.height * 360 / final.width)), Image.Resampling.LANCZOS)
            if mobile.convert("RGB").size != expected.size or mobile.convert("RGB").tobytes() != expected.tobytes():
                errors.append("mobile preview is not the exact 360px derivative of final")
    except (KeyError, OSError, ValueError, TypeError) as exc:
        errors.append(f"invalid integrated production evidence: {exc}")
    if review.get("decision") != "pass" or review.get("missing_link") != "none" or review.get("explanation_required") is not False:
        errors.append("integrated review and full sentence-to-image alignment must pass")
    for field in ("plan_vs_observed", "missing_link_note"):
        if not nonempty(review.get(field)):
            errors.append(f"creator alignment requires {field}")
    return errors
