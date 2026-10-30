"""Small, file-backed provenance checks for schema 1.4 production revisions.

These are stale-artifact guards, not an authentication or aesthetic scoring system.
All mutations are explicitly called by production_evidence.py or the lock/register CLIs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from record_utils import atomic_write_json, compute_lock_hash, file_sha256, get, nonempty, now_for_record, rendering_mode, rendering_mode_errors, source_meaning_review_input

TEXT_GROUPS = ("quote", "source", "yi", "ji")
STAGE1_QUESTIONS = [
    "只看两张无字图片：第一眼看到了什么？有哪些可直接观察的关系、状态或动作？",
    "哪些地方不能唯一理解？最可能的另一种阅读是什么？不要猜测配文或设计者意图。",
]
STAGE2_QUESTIONS = [
    "仅根据原句和原文上下文，用自己的话说明句意。",
    "图与句是否自然相关，还是需要强行解释、发生冲突或不相关？不要求逐字图解，也不补造因果和时间顺序。",
    "分别核对原尺寸成品中的正文、出处、宜、忌：逐字、对比度、裁切和可读性，逐组给出观察依据。",
]
TYPOGRAPHY_REVIEW_V1 = {
    "profile": "voice-layout-v1",
    "questions": {
        "reading_rhythm": "实际在哪里停顿、重读？指出具体词组或行；换行、间距或强调是否拆词、割裂原句、让普通词变口号？",
        "image_text_relationship": "指出文字块与图像哪条轴线、边界、体量、间隔或方向形成怎样的具体关系，是否相互支持。共用背景、不重叠和留白充足本身不足以证明整体性；简洁分区可以成立，不强求叠字。",
        "hierarchy_and_breathing": "第一眼落在哪里，之后怎样读？指出具体区域和主次。日期、出处、宜忌是否抢成第二标题块或被缩成不可读脚注？正文第一层级不等于全句最大最重。",
        "font_fit": "只根据原句、原文语境和成品，说出实际感到的文字声音及具体字形或字重依据；与原句语气是否冲突？文学感、字体清楚等类别标签不足以通过。",
    },
    "output_contract": "返回 typography_design_review 对象，逐项填写 reading_rhythm、image_text_relationship、hierarchy_and_breathing、font_fit 的具体观察，另给 decision=pass/revise。有实际语气偏移、错误停顿、主次抢夺或图文脱节时 revise；仅个人偏好不同不构成失败。不先看设计者的字体或小样理由，不新增审查轮次。",
}
TYPOGRAPHY_REVIEW = copy.deepcopy(TYPOGRAPHY_REVIEW_V1)
TYPOGRAPHY_REVIEW["profile"] = "voice-layout-v2-negative-space"
TYPOGRAPHY_REVIEW["questions"]["image_text_relationship"] = "先指出正文和全部辅助文字分别由哪处设计留白承托，和图像主体、可辨细节及明显纹理之间有怎样的视觉间隔；直接压在图像上、像摄影作品加字幕，即使可读也 revise。再指出文字块与图像的轴线、边界、体量、间隔或方向怎样相互支持。留白存在本身不足以证明整体性，简洁分区可以成立。"


def preserve_legacy_typography_contract(expected: dict, saved: dict) -> dict:
    # Preserve exact historical evidence, not a claim that it meets today's rule.
    if saved.get("typography_review") == TYPOGRAPHY_REVIEW_V1:
        expected["typography_review"] = copy.deepcopy(TYPOGRAPHY_REVIEW_V1)
    return expected


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def timestamp(value: Any) -> datetime:
    if not nonempty(value):
        raise ValueError("timestamp must be non-empty")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def ordered_times(*values: Any) -> bool:
    parsed = [timestamp(value) for value in values]
    return parsed == sorted(parsed)


def resolve_asset_path(value: str, record_path: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (record_path.parent / path).resolve()


def file_asset(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"file does not exist: {path}")
    return {"path": str(path), "sha256": file_sha256(path)}


def image_asset(path: Path, require_png: bool = False) -> dict[str, Any]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("Pillow is required for complete image decoding") from exc
    result = file_asset(path)
    try:
        with Image.open(result["path"]) as image:
            image.verify()
        with Image.open(result["path"]) as image:
            image.load()
            if require_png and image.format != "PNG":
                raise ValueError("final/review image must be PNG")
            result.update(width=image.width, height=image.height, format=image.format)
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError(f"image cannot be fully decoded: {path}: {exc}") from exc
    return result


def checked_asset(asset: Any, label: str, image: bool = False, png: bool = False) -> list[str]:
    if not isinstance(asset, dict) or not nonempty(asset.get("path")) or not nonempty(asset.get("sha256")):
        return [f"{label} requires path and sha256"]
    try:
        actual = image_asset(Path(asset["path"]), png) if image else file_asset(Path(asset["path"]))
    except (ValueError, OSError) as exc:
        return [f"{label}: {exc}"]
    errors = []
    for key in ("sha256", "width", "height") if image else ("sha256",):
        if actual.get(key) != asset.get(key):
            errors.append(f"{label}.{key} changed; register a new revision and repeat affected reviews")
    return errors


def text_data(data: dict) -> dict[str, str]:
    return {
        "quote_text": str(get(data, "content.text") or ""),
        "date_text": str(get(data, "layout.date_text") or ""),
        "source_label": str(get(data, "layout.source_label") or ""),
        "yi_text": str(get(data, "layout.yi_text") or ""),
        "ji_text": str(get(data, "layout.ji_text") or ""),
    }


def layout_text_errors(data: dict) -> list[str]:
    texts = text_data(data)
    errors = []
    if any(not nonempty(value) for value in texts.values()):
        errors.append("layout exact text fields must be non-empty")
    normalized_date = re.sub(r"[./年月]", "-", texts["date_text"]).rstrip("日-")
    try:
        if datetime.strptime(normalized_date, "%Y-%m-%d").date().isoformat() != get(data, "run.date"):
            errors.append("layout.date_text must match run.date")
    except ValueError:
        errors.append("layout.date_text must be a recognizable YYYY-MM-DD date")
    if not texts["yi_text"].startswith("宜｜") or not texts["ji_text"].startswith("忌｜"):
        errors.append("layout.yi_text / ji_text must use 宜｜ / 忌｜ respectively")
    author = str(get(data, "content.author") or "")
    work = str(get(data, "content.work") or "")
    if get(data, "content.text_type") in {"exact_quote", "translated_quote"}:
        if author not in texts["source_label"] or f"《{work}》" not in texts["source_label"]:
            errors.append("layout.source_label must contain the exact author and complete work title")
    if get(data, "content.text_type") == "translated_quote":
        translator = str(get(data, "content.translator") or "")
        if not translator or translator not in texts["source_label"]:
            errors.append("layout.source_label must contain the verified translator")
    return errors


def require_v14(data: dict) -> None:
    if data.get("schema_version") not in {"1.4", "1.5"}:
        raise ValueError("this command requires schema_version 1.4 or 1.5; do not migrate delivered records in place")


def require_lock(data: dict) -> None:
    require_v14(data)
    if rendering_mode_errors(data):
        raise ValueError("; ".join(rendering_mode_errors(data)))
    if get(data, "pre_generation.locked_before_generation") is not True or get(data, "pre_generation.lock_hash") != compute_lock_hash(data):
        raise ValueError("generation plan changed or is unlocked; return to the plan and invalidate old assets")
    if not ordered_times(get(data, "run.initialized_at"), get(data, "pre_generation.locked_at"), now_for_record(data)):
        raise ValueError("initialized_at <= locked_at <= now is required")


def evidence_dir(record_path: Path, kind: str) -> Path:
    path = record_path.parent / "evidence" / f"{kind}-{uuid.uuid4().hex[:12]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def snapshot_file(path: Path, directory: Path, name: str) -> dict:
    target = directory / name
    if target.exists():
        raise ValueError(f"refusing to overwrite evidence: {target}")
    shutil.copyfile(path, target)
    return file_asset(target)


def snapshot_json(value: Any, directory: Path, name: str) -> dict:
    path = directory / name
    if path.exists():
        raise ValueError(f"refusing to overwrite evidence: {path}")
    atomic_write_json(path, value)
    return file_asset(path)


def archive_revision(data: dict, record_path: Path, reason: str) -> None:
    production = data.setdefault("production", {})
    if production.get("assets") or data.get("delivery") or get(data, "layout.final_image_path"):
        directory = evidence_dir(record_path, "revision")
        archived = copy.deepcopy(data)
        # Keep old bytes even if the user later renders into the same output filename.
        for key, asset in archived.get("production", {}).get("assets", {}).items():
            if isinstance(asset, dict) and Path(str(asset.get("path") or "")).is_file():
                copied = snapshot_file(Path(asset["path"]), directory, f"{key}{Path(asset['path']).suffix}")
                asset["path"] = copied["path"]
        archived_assets = archived.get("production", {}).get("assets", {})
        for section, field, key in (("post_generation", "background_path", "background"), ("layout", "render_source_path", "render_source"), ("layout", "final_image_path", "final")):
            if key in archived_assets:
                archived[section][field] = archived_assets[key]["path"]
        for attempt in archived.get("production", {}).get("attempts", []):
            if attempt.get("attempt_id") == archived.get("production", {}).get("current_attempt_id") and "background" in archived_assets:
                attempt["background"] = copy.deepcopy(archived_assets["background"])
        concept_path = Path(str(get(archived, "design_concept.file_path") or ""))
        if not concept_path.is_absolute():
            concept_path = record_path.parent / concept_path
        if concept_path.is_file():
            archived["design_concept"]["file_path"] = snapshot_file(concept_path, directory, "design-concept.txt")["path"]
        # Not named design-record.json: series history scanners must not treat revisions as new cards.
        snapshot = snapshot_json(archived, directory, "record-snapshot.json")
        production.setdefault("revisions", []).append({"reason": reason, "archived_at": now_for_record(data), "record": snapshot})
    production["revision"] = int(production.get("revision") or 0) + 1


def invalidate_downstream(data: dict, record_path: Path, reason: str, background: bool = False) -> None:
    archive_revision(data, record_path, reason)
    production = data.setdefault("production", {})
    keep = {} if background else {"background": production.get("assets", {}).get("background")}
    production["assets"] = {key: value for key, value in keep.items() if value}
    production.pop("layout_text_snapshot", None)
    production.pop("layout_text_sha256", None)
    production.pop("layout_prepared_at", None)
    production.pop("stage1_candidate", None)
    if background:
        data["post_generation"] = {"background_path": "", "generated_at": "", "registered_at": "", "planned_relationships_realized": [], "emergent_discoveries": [], "deviations": [], "regeneration_or_fix_decision": "", "literalness_test": ""}
        data["execution_validation"] = {"decision": "pending"}
    data["semantic_cold_review"] = {"decision": "pending"}
    data["design_concept"] = {}
    data.pop("delivery", None)
    for key in ("delivered", "delivered_at", "receipt_path"):
        data.pop(key, None)
        data.get("run", {}).pop(key, None)
    data.setdefault("layout", {}).update(render_source_path="", final_image_path="", rendered_at="")
    downstream_flags = {"final_text_rendered_deterministically", "generated_text_checked", "no_overlap_or_clipping", "final_image_inspected_full_resolution", "perceptual_validity_checked", "semantic_cold_review_checked", "design_concept_matches_record", "output_saved_to_user_directory"}
    if background:
        downstream_flags.add("execution_gate_checked")
    for key in downstream_flags:
        if key in data.setdefault("qa", {}):
            data["qa"][key] = False
    data["qa"].pop("readability", None)
    data["qa"]["final_status"] = "pending"
    data["run"]["status"] = "revision_pending"


def find_attempt(data: dict, attempt_id: str) -> dict:
    rows = [row for row in get(data, "production.attempts") or [] if row.get("attempt_id") == attempt_id]
    if len(rows) != 1:
        raise ValueError("attempt_id must identify exactly one recorded generation attempt")
    return rows[0]


def start_generation(data: dict, record_path: Path, attempt_id: str, prompt_file: Path, context_id: str, change_note: str = "", retry_authorization: str = "") -> dict:
    require_lock(data)
    if not nonempty(attempt_id) or not nonempty(context_id):
        raise ValueError("attempt_id and designer_context_id are required")
    production = data.setdefault("production", {})
    if any(row.get("attempt_id") == attempt_id for row in production.get("attempts", [])):
        raise ValueError("attempt_id already exists; create a new attempt instead of overwriting evidence")
    if rendering_mode(data) == "integrated_image_text":
        prior = [row for row in production.get("attempts", []) if row.get("lock_hash") == get(data, "pre_generation.lock_hash") and row.get("concept_id") == get(data, "pre_generation.selected_concept_id")]
        if len(prior) >= 2 and not nonempty(retry_authorization):
            raise ValueError("integrated attempt limit reached (initial + one correction); stop and obtain explicit user direction before another call")
    actual_prompt = prompt_file.read_text(encoding="utf-8")
    from integrated_production import prompt_errors
    errors = prompt_errors(data, actual_prompt)
    if errors:
        raise ValueError("; ".join(errors))
    if actual_prompt.strip() != str(get(data, "pre_generation.prompt") or "").strip() and not nonempty(change_note):
        raise ValueError("changed prompt requires change_note; changed concept requires a new lock")
    directory = evidence_dir(record_path, "generation")
    attempt = {"attempt_id": attempt_id, "lock_hash": get(data, "pre_generation.lock_hash"), "concept_id": get(data, "pre_generation.selected_concept_id"), "actual_prompt": actual_prompt, "prompt": snapshot_file(prompt_file, directory, "actual-prompt.txt"), "change_note": change_note, "designer_context_id": context_id, "started_at": now_for_record(data), "completed_at": ""}
    if nonempty(retry_authorization):
        attempt["user_retry_authorization"] = retry_authorization
    production["designer_context_id"] = context_id
    production.setdefault("attempts", []).append(attempt)
    return attempt


def complete_generation(data: dict, record_path: Path, attempt_id: str, result_path: Path, locator: str, background: Path) -> dict:
    require_lock(data)
    attempt = find_attempt(data, attempt_id)
    if attempt.get("completed_at"):
        raise ValueError("attempt already completed; use a new attempt")
    if attempt.get("lock_hash") != get(data, "pre_generation.lock_hash"):
        raise ValueError("attempt belongs to another generation lock")
    if not nonempty(locator):
        raise ValueError("tool_result_locator must locate the actual tool response/request")
    if not result_path.is_file() or result_path.stat().st_size == 0:
        raise ValueError("actual tool result must be a non-empty file")
    asset = image_asset(background)
    directory = Path(attempt["prompt"]["path"]).parent
    attempt.update(tool_result=snapshot_file(result_path, directory, "tool-result.txt"), tool_result_locator=locator, background=asset, completed_at=now_for_record(data))
    if not ordered_times(get(data, "pre_generation.locked_at"), attempt["started_at"], attempt["completed_at"]):
        raise ValueError("generation call timestamps are out of order")
    return attempt


def register_background_v14(data: dict, record_path: Path, background: Path, attempt_id: str) -> None:
    require_lock(data)
    attempt = find_attempt(data, attempt_id)
    if not attempt.get("completed_at") or attempt.get("lock_hash") != get(data, "pre_generation.lock_hash"):
        raise ValueError("background requires a completed attempt under the current lock")
    actual = image_asset(background)
    if actual["sha256"] != attempt.get("background", {}).get("sha256"):
        raise ValueError("background does not match the generation result")
    errors = attempt_errors(data, attempt)
    if errors:
        raise ValueError("; ".join(errors))
    invalidate_downstream(data, record_path, "background re-registered", background=True)
    data["production"]["assets"]["background"] = actual
    data["production"]["current_attempt_id"] = attempt_id
    data["post_generation"].update(background_path=actual["path"], generated_at=attempt["completed_at"], registered_at=now_for_record(data))
    data["run"]["status"] = "background_registered"


def attempt_errors(data: dict, attempt: dict) -> list[str]:
    errors = []
    if rendering_mode(data) == "integrated_image_text":
        same_plan = [row for row in get(data, "production.attempts") or [] if row.get("lock_hash") == attempt.get("lock_hash") and row.get("concept_id") == attempt.get("concept_id")]
        position = next((i for i, row in enumerate(same_plan) if row.get("attempt_id") == attempt.get("attempt_id")), -1)
        if position >= 2 and not nonempty(attempt.get("user_retry_authorization")):
            errors.append("additional integrated attempt requires recorded explicit user authorization")
    from integrated_production import prompt_errors
    errors += prompt_errors(data, str(attempt.get("actual_prompt") or ""))
    if attempt.get("lock_hash") != get(data, "pre_generation.lock_hash") or attempt.get("concept_id") != get(data, "pre_generation.selected_concept_id"):
        errors.append("generation attempt must bind the current locked concept")
    errors += checked_asset(attempt.get("prompt"), "attempt.prompt")
    errors += checked_asset(attempt.get("tool_result"), "attempt.tool_result")
    errors += checked_asset(attempt.get("background"), "attempt.background", image=True)
    if not nonempty(attempt.get("tool_result_locator")):
        errors.append("attempt.tool_result_locator is required")
    try:
        if Path(attempt["prompt"]["path"]).read_text(encoding="utf-8") != attempt.get("actual_prompt"):
            errors.append("attempt.actual_prompt differs from the snapshotted request")
        if not ordered_times(get(data, "pre_generation.locked_at"), attempt.get("started_at"), attempt.get("completed_at"), now_for_record(data)):
            errors.append("attempt must start after locking and complete before registration")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        errors.append(f"invalid generation evidence: {exc}")
    if str(attempt.get("actual_prompt") or "").strip() != str(get(data, "pre_generation.prompt") or "").strip() and not nonempty(attempt.get("change_note")):
        errors.append("modified attempt prompt requires a change note")
    return errors


def read_json(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("evidence output must be a JSON object")
    return result


def record_execution(data: dict, record_path: Path, result_path: Path) -> None:
    require_lock(data)
    if rendering_mode(data) == "integrated_image_text":
        from integrated_production import record_integrated_execution
        return record_integrated_execution(data, record_path, result_path)
    background = get(data, "production.assets.background")
    errors = checked_asset(background, "background", image=True)
    if errors:
        raise ValueError("; ".join(errors))
    result = read_json(result_path)
    for field in ("key_action_or_state_realized", "concept_fidelity"):
        if not nonempty(result.get(field)):
            raise ValueError(f"execution output requires {field}")
    if result.get("decision") not in {"pass", "regenerate_same_concept"}:
        raise ValueError("invalid execution decision")
    if result["decision"] == "pass" and (result.get("text_safe_area_usable") is not True or result.get("background_text_free") is not True):
        raise ValueError("execution pass requires usable text area and text-free background")
    directory = evidence_dir(record_path, "execution")
    data["execution_validation"] = {**result, "checked_at": now_for_record(data), "background_sha256": background["sha256"], "raw_output": snapshot_file(result_path, directory, "review.json")}
    data.setdefault("qa", {})["execution_gate_checked"] = result["decision"] == "pass"
    data["post_generation"]["planned_relationships_realized"] = [result["key_action_or_state_realized"]]
    data["post_generation"]["regeneration_or_fix_decision"] = result["decision"]


def prepare_layout(data: dict, record_path: Path) -> dict:
    require_lock(data)
    if rendering_mode(data) != "local_typesetting":
        raise ValueError("prepare-layout is local_typesetting only; do not silently overlay an integrated card")
    errors = layout_text_errors(data)
    background = get(data, "production.assets.background")
    errors += checked_asset(background, "background", image=True)
    if get(data, "execution_validation.decision") != "pass" or get(data, "execution_validation.background_sha256") != (background or {}).get("sha256"):
        errors.append("prepare-layout requires execution approval of the current background")
    if errors:
        raise ValueError("; ".join(errors))
    from PIL import Image, ImageOps
    width, height = get(data, "layout.canvas_width"), get(data, "layout.canvas_height")
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        raise ValueError("canvas dimensions must be positive integers")
    old_review = copy.deepcopy(data.get("semantic_cold_review", {}))
    invalidate_downstream(data, record_path, "new layout revision")
    directory = evidence_dir(record_path, "layout")
    with Image.open(background["path"]) as image:
        base = ImageOps.fit(image.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS)
        base.save(directory / "text-free.png")
        base.resize((360, round(height * 360 / width)), Image.Resampling.LANCZOS).save(directory / "text-free-360.png")
    production = data["production"]
    production["assets"].update(text_free=image_asset(directory / "text-free.png", True), text_free_mobile=image_asset(directory / "text-free-360.png", True))
    production["layout_text_snapshot"] = text_data(data)
    production["layout_text_sha256"] = canonical_hash(text_data(data))
    production["layout_prepared_at"] = now_for_record(data)
    if old_review.get("stage1_output") and all(old_review.get("asset_hashes", {}).get(key) == production["assets"][key]["sha256"] for key in ("text_free", "text_free_mobile")):
        # Font/text-only revisions do not invalidate the earlier image-only observation.
        production["stage1_candidate"] = old_review
    request = {"base": production["assets"]["text_free"], "text_data": text_data(data), "layout_text_sha256": production["layout_text_sha256"], "canvas_width": width, "canvas_height": height}
    production["assets"]["layout_request"] = snapshot_json(request, directory, "layout-request.json")
    return request


def register_layout(data: dict, record_path: Path, source: Path, final: Path, manifest_path: Path) -> None:
    require_lock(data)
    if rendering_mode(data) != "local_typesetting":
        raise ValueError("register-layout is local_typesetting only; use register-integrated")
    production = data.get("production", {})
    assets = production.get("assets", {})
    errors = layout_text_errors(data)
    errors += checked_asset(assets.get("text_free"), "text_free", True, True)
    if production.get("layout_text_sha256") != canonical_hash(text_data(data)):
        errors.append("layout text changed; run prepare-layout for a new text revision")
    if errors:
        raise ValueError("; ".join(errors))
    manifest = read_json(manifest_path)
    final_asset = image_asset(final, True)
    source_asset = file_asset(source)
    if (final_asset["width"], final_asset["height"]) != (get(data, "layout.canvas_width"), get(data, "layout.canvas_height")):
        raise ValueError("final PNG dimensions do not match the canvas")
    expected = {"text_data": text_data(data), "base_sha256": assets["text_free"]["sha256"], "render_source_sha256": source_asset["sha256"], "final_sha256": final_asset["sha256"]}
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("render manifest must bind exact text_data, text-free base, render source, and final PNG")
    if assets.get("final"):
        raise ValueError("layout already registered; run prepare-layout to preserve the previous revision")
    directory = Path(assets["text_free"]["path"]).parent
    from PIL import Image
    with Image.open(final) as image:
        image.convert("RGB").resize((360, round(image.height * 360 / image.width)), Image.Resampling.LANCZOS).save(directory / "final-360.png")
    assets.update(render_source=source_asset, final=final_asset, final_mobile=image_asset(directory / "final-360.png", True), render_manifest=snapshot_file(manifest_path, directory, "render-manifest.json"))
    data["layout"].update(render_source_path=source_asset["path"], final_image_path=final_asset["path"], rendered_at=now_for_record(data))
    data.setdefault("qa", {})["final_text_rendered_deterministically"] = True
    data["qa"]["date_and_weekday_correct"] = True
    data["run"]["status"] = "layout_registered"


def review_assets(data: dict) -> dict[str, str]:
    return {key: str(get(data, f"production.assets.{key}.sha256") or "") for key in ("background", "text_free", "text_free_mobile", "final", "final_mobile", "render_source")}


def designer_contexts(data: dict) -> set[str]:
    return {str(get(data, "production.designer_context_id") or ""), *(str(row.get("designer_context_id") or "") for row in get(data, "production.attempts") or [])}


def start_cold_review(data: dict, record_path: Path, reviewer_id: str, reviewer_context_id: str) -> dict:
    require_lock(data)
    if rendering_mode(data) == "integrated_image_text":
        from integrated_production import start_integrated_review
        return start_integrated_review(data, record_path, reviewer_id, reviewer_context_id)
    production = data.get("production", {})
    if not nonempty(reviewer_id) or not nonempty(reviewer_context_id) or reviewer_context_id in designer_contexts(data):
        raise ValueError("cold review requires an independent reviewer identity and context")
    if get(data, "semantic_cold_review.stage1_input"):
        raise ValueError("review session already exists; preserve it and prepare a new layout revision")
    for key in ("text_free", "text_free_mobile"):
        errors = checked_asset(get(data, f"production.assets.{key}"), key, True, True)
        if errors:
            raise ValueError("; ".join(errors))
    candidate = production.get("stage1_candidate", {})
    can_reuse = candidate.get("reviewer_id") == reviewer_id and candidate.get("reviewer_context_id") == reviewer_context_id and candidate.get("stage1_output") and not checked_asset(candidate.get("stage1_output"), "inherited.stage1_output") and not checked_asset(candidate.get("stage1_input"), "inherited.stage1_input")
    exposed_contexts = {row.get("reviewer_context_id") for row in production.get("review_contexts", [])}
    if reviewer_context_id in exposed_contexts and not can_reuse:
        raise ValueError("this reviewer context already saw the quote; use a fresh context for changed image-only inputs")
    directory = evidence_dir(record_path, "cold-review")
    copied = {}
    for key in ("text_free", "text_free_mobile", "final", "final_mobile"):
        if production["assets"].get(key):
            copied[key] = snapshot_file(Path(production["assets"][key]["path"]), directory, f"{key}.png")
    first_input = stage1_input(data, copied)
    review = {"reviewer_id": reviewer_id, "reviewer_context_id": reviewer_context_id, "started_at": now_for_record(data), "asset_hashes": review_assets(data), "images": copied, "stage1_input": snapshot_json(first_input, directory, "stage1-input.json"), "decision": "pending"}
    if can_reuse:
        if not all(key in copied for key in ("final", "final_mobile")):
            raise ValueError("inherited review needs registered final layout; no new image-only review is necessary")
        for key in ("text_free", "text_free_mobile"):
            review["images"][key] = candidate["images"][key]
        for key in ("stage1_input", "stage1_output", "image_only_reviewed_at"):
            review[key] = candidate[key]
        review["stage1_reused_from"] = candidate["stage1_output"]["sha256"]
        second_input = stage2_input(data, review)
        review["stage2_input"] = snapshot_json(second_input, directory, "stage2-input.json")
        review["quote_revealed_at"] = now_for_record(data)
        production.setdefault("review_contexts", []).append({"reviewer_context_id": reviewer_context_id, "quote_revealed_at": review["quote_revealed_at"]})
    data["semantic_cold_review"] = review
    production.pop("stage1_candidate", None)
    return {"next_stage": "stage2" if review.get("stage1_output") else "stage1", "input": review.get("stage2_input") or review["stage1_input"]}


def stage1_input(data: dict, images: dict) -> dict:
    result = {"images": {"full_resolution": images["text_free"], "mobile": images["text_free_mobile"]}, "questions": STAGE1_QUESTIONS}
    if data.get("schema_version") == "1.5":
        from expression_contract import REVIEW_BOUNDARY
        result["series_boundary"] = REVIEW_BOUNDARY
    return result


def stage2_input(data: dict, review: dict, include_typography: bool | None = None) -> dict:
    result = {"quote": get(data, "content.text"), "author": get(data, "content.author"), "work": get(data, "content.work"), "original_context": get(data, "content.chapter_or_context"), "images": {"full_resolution": review["images"]["final"], "mobile": review["images"]["final_mobile"]}, "questions": STAGE2_QUESTIONS}
    if data.get("schema_version") == "1.5":
        from expression_contract import REVIEW_BOUNDARY
        result["series_boundary"] = REVIEW_BOUNDARY
        result["expression_policy"] = data["expression_policy"]
        result["expression_question"] = "独立于图文自然相关，画面是关系隐喻、直接演示、装饰还是不明？人物是主体、陪衬还是没有？以可见证据给 expression_review 的 mode、figure_role、decision(pass/fail)、evidence；不要用符合题意抵消表达方式失败。"
    if include_typography is None:
        include_typography = data.get("schema_version") == "1.5"
    if include_typography:
        result["typography_review"] = copy.deepcopy(TYPOGRAPHY_REVIEW)
    source_material = source_meaning_review_input(data)
    if source_material:
        result["meaning_grounding"] = source_material
    return result


def typography_result_errors(result: dict, review_input: dict, require_pass: bool = False) -> list[str]:
    # Old immutable inputs retain their original contract; never invent an old review.
    if "typography_review" not in review_input:
        return []
    if review_input["typography_review"] not in (TYPOGRAPHY_REVIEW, TYPOGRAPHY_REVIEW_V1):
        return ["unsupported or changed typography_review input contract"]
    row = result.get("typography_design_review")
    if not isinstance(row, dict):
        return ["stage2 output requires typography_design_review"]
    errors = []
    for field in TYPOGRAPHY_REVIEW["questions"]:
        if not nonempty(row.get(field)):
            errors.append(f"typography_design_review.{field} requires observation evidence")
    if row.get("decision") not in {"pass", "revise"}:
        errors.append("typography_design_review.decision must be pass or revise")
    if require_pass and row.get("decision") != "pass":
        errors.append("typography_design_review must pass; readability alone cannot approve design")
    return errors


def register_cold_stage1(data: dict, record_path: Path, result_path: Path) -> dict:
    require_lock(data)
    if rendering_mode(data) != "local_typesetting":
        raise ValueError("integrated card has visible text; use cold-integrated, not image-only blind review")
    review = data.get("semantic_cold_review", {})
    if not review.get("stage1_input") or review.get("stage1_output"):
        raise ValueError("stage1 must follow cold-start, exactly once")
    current = review_assets(data)
    if any(review.get("asset_hashes", {}).get(key) != current[key] for key in ("background", "text_free", "text_free_mobile")):
        raise ValueError("review assets changed; prepare a new revision")
    result = read_json(result_path)
    for field in ("image_only_first_read", "dominant_misreading", "uncertain_elements"):
        if not nonempty(result.get(field)):
            raise ValueError(f"stage1 reviewer output requires {field}")
    context = get(data, "content.chapter_or_context")
    if not nonempty(context):
        raise ValueError("stage2 needs original source context in content.chapter_or_context, not the designer's brief")
    directory = Path(review["stage1_input"]["path"]).parent
    # Rendering may finish while the isolated reviewer examines the no-text crop.
    # Reveal nothing until a registered final exists and the original crop is unchanged.
    for key in ("final", "final_mobile"):
        asset = get(data, f"production.assets.{key}")
        errors = checked_asset(asset, key, True, True)
        if errors:
            raise ValueError("; ".join(errors))
        if key in review["images"]:
            if review["images"][key]["sha256"] != asset["sha256"] or checked_asset(review["images"][key], key):
                raise ValueError("review final assets changed; prepare a new revision")
        else:
            review["images"][key] = snapshot_file(Path(asset["path"]), directory, f"{key}.png")
    review["asset_hashes"] = current
    review["stage1_output"] = snapshot_file(result_path, directory, "stage1-output.json")
    review["image_only_reviewed_at"] = now_for_record(data)
    second_input = stage2_input(data, review)
    review["stage2_input"] = snapshot_json(second_input, directory, "stage2-input.json")
    review["quote_revealed_at"] = now_for_record(data)
    data["production"].setdefault("review_contexts", []).append({"reviewer_context_id": review["reviewer_context_id"], "quote_revealed_at": review["quote_revealed_at"]})
    return review["stage2_input"]


def stage2_result_errors(result: dict) -> list[str]:
    errors = []
    for key in ("quote_meaning_in_own_words", "connection_reason"):
        if not nonempty(result.get(key)):
            errors.append(f"stage2 output requires {key}")
    if result.get("connection_assessment") not in {"natural", "forced", "conflicting", "unrelated"}:
        errors.append("connection_assessment must be natural, forced, conflicting, or unrelated")
    if result.get("decision") not in {"pass", "revise"}:
        errors.append("stage2 decision must be pass or revise")
    readability = result.get("readability")
    if not isinstance(readability, dict):
        errors.append("readability must be an object with quote/source/yi/ji groups")
        readability = {}
    for group in TEXT_GROUPS:
        row = readability.get(group, {})
        if not isinstance(row, dict):
            errors.append(f"readability.{group} must be an object")
            row = {}
        for size in ("full_resolution",):
            if row.get(size) not in {"pass", "fail"}:
                errors.append(f"readability.{group}.{size} must be pass or fail")
        if not nonempty(row.get("evidence")):
            errors.append(f"readability.{group}.evidence is required")
    return errors


def register_cold_stage2(data: dict, record_path: Path, result_path: Path) -> None:
    require_lock(data)
    if rendering_mode(data) != "local_typesetting":
        raise ValueError("use cold-integrated for integrated cards")
    review = data.get("semantic_cold_review", {})
    if not review.get("stage1_output") or not review.get("stage2_input") or review.get("stage2_output"):
        raise ValueError("stage2 must follow immutable stage1 registration, exactly once")
    if review.get("asset_hashes") != review_assets(data):
        raise ValueError("review assets changed; prepare a new revision")
    result = read_json(result_path)
    from expression_contract import expression_result_errors
    input_asset = review["stage2_input"]
    errors = checked_asset(input_asset, "cold_review.stage2_input")
    second_input = read_json(Path(input_asset["path"]))
    expected_input = stage2_input(data, review, include_typography="typography_review" in second_input)
    if second_input != preserve_legacy_typography_contract(expected_input, second_input):
        errors.append("cold review stage2 input differs from its fixed contract")
    errors += stage2_result_errors(result) + expression_result_errors(result, data) + typography_result_errors(result, second_input)
    if errors:
        raise ValueError("; ".join(errors))
    directory = Path(review["stage2_input"]["path"]).parent
    review["stage2_output"] = snapshot_file(result_path, directory, "stage2-output.json")
    review["completed_at"] = now_for_record(data)
    passed = result["decision"] == "pass" and result["connection_assessment"] == "natural" and all(result["readability"][group]["full_resolution"] == "pass" for group in TEXT_GROUPS)
    passed = passed and not expression_result_errors(result, data, require_pass=True)
    passed = passed and not typography_result_errors(result, second_input, require_pass=True)
    review["decision"] = "pass" if passed else "revise"
    review.update(alignment_basis={"lock_hash": get(data, "pre_generation.lock_hash"), "stage1_output_sha256": review["stage1_output"]["sha256"], "stage2_output_sha256": review["stage2_output"]["sha256"]}, plan_vs_observed="", missing_link="pending", missing_link_note="", explanation_required=True)
    data.setdefault("qa", {})["readability"] = result["readability"]
    data["qa"]["semantic_cold_review_checked"] = True
    data["qa"]["final_image_inspected_full_resolution"] = all(result["readability"][group]["full_resolution"] == "pass" for group in TEXT_GROUPS)
    data["qa"]["no_overlap_or_clipping"] = all(result["readability"][group]["full_resolution"] == "pass" for group in TEXT_GROUPS)
    data["run"]["status"] = "review_passed" if passed else "revision_required"


def production_errors(data: dict, record_path: Path, stage: str = "final") -> list[str]:
    if data.get("schema_version") not in {"1.4", "1.5"}:
        return []
    if rendering_mode(data) == "integrated_image_text":
        from integrated_production import integrated_production_errors
        return integrated_production_errors(data, record_path, stage)
    errors = layout_text_errors(data)
    try:
        require_lock(data)
    except (ValueError, TypeError) as exc:
        errors.append(str(exc))
    if stage != "final":
        return errors
    production = data.get("production", {})
    if not isinstance(production, dict):
        return errors + ["production must be an object"]
    assets = production.get("assets", {})
    if not isinstance(assets, dict):
        return errors + ["production.assets must be an object"]
    for key in ("background", "text_free", "text_free_mobile", "final", "final_mobile"):
        errors += checked_asset(assets.get(key), f"production.assets.{key}", True, key != "background")
    for key in ("render_source", "render_manifest", "layout_request"):
        errors += checked_asset(assets.get(key), f"production.assets.{key}")
    for record_field, key in (("post_generation.background_path", "background"), ("layout.render_source_path", "render_source"), ("layout.final_image_path", "final")):
        if get(data, record_field) != assets.get(key, {}).get("path"):
            errors.append(f"{record_field} is not the registered asset")
    if production.get("layout_text_snapshot") != text_data(data) or production.get("layout_text_sha256") != canonical_hash(text_data(data)):
        errors.append("exact layout text changed after preparing this layout revision")
    try:
        attempt = find_attempt(data, production.get("current_attempt_id", ""))
        errors += attempt_errors(data, attempt)
        if assets.get("background", {}).get("sha256") != attempt.get("background", {}).get("sha256"):
            errors.append("registered background differs from the actual generation output")
        if get(data, "post_generation.generated_at") != attempt.get("completed_at"):
            errors.append("generated_at must be the recorded generation completion, not registration time")
        review = data.get("semantic_cold_review", {})
        if not ordered_times(attempt.get("completed_at"), get(data, "post_generation.registered_at"), get(data, "execution_validation.checked_at"), production.get("layout_prepared_at"), review.get("started_at"), review.get("quote_revealed_at"), review.get("completed_at"), get(data, "design_concept.written_at"), now_for_record(data)):
            errors.append("production and review timestamps are out of order")
        if not ordered_times(production.get("layout_prepared_at"), get(data, "layout.rendered_at"), review.get("quote_revealed_at")):
            errors.append("registered layout must precede quote revelation")
        if not ordered_times(attempt.get("completed_at"), review.get("image_only_reviewed_at"), review.get("quote_revealed_at")):
            errors.append("image-only observation must precede quote revelation")
        if not review.get("stage1_reused_from") and not ordered_times(review.get("started_at"), review.get("image_only_reviewed_at")):
            errors.append("fresh image-only review must follow this review session start")
    except (ValueError, TypeError) as exc:
        errors.append(f"invalid production timeline/attempt: {exc}")
    execution = data.get("execution_validation", {})
    errors += checked_asset(execution.get("raw_output"), "execution.raw_output")
    if execution.get("background_sha256") != assets.get("background", {}).get("sha256") or execution.get("decision") != "pass":
        errors.append("execution approval does not bind the current background")
    try:
        execution_raw = read_json(Path(execution["raw_output"]["path"]))
        for field in ("decision", "background_text_free", "text_safe_area_usable", "key_action_or_state_realized", "concept_fidelity"):
            if execution.get(field) != execution_raw.get(field):
                errors.append(f"execution.{field} differs from the raw review output")
        if execution.get("background_text_free") is not True or execution.get("text_safe_area_usable") is not True:
            errors.append("execution must verify a text-free background and usable text area")
    except (KeyError, OSError, ValueError, TypeError) as exc:
        errors.append(f"cannot read execution evidence: {exc}")
    try:
        manifest = read_json(Path(assets["render_manifest"]["path"]))
        expected = {"text_data": text_data(data), "base_sha256": assets["text_free"]["sha256"], "render_source_sha256": assets["render_source"]["sha256"], "final_sha256": assets["final"]["sha256"]}
        if any(manifest.get(key) != value for key, value in expected.items()):
            errors.append("render manifest no longer matches exact text and registered assets")
        from PIL import Image, ImageOps, ImageChops
        with Image.open(assets["background"]["path"]) as background, Image.open(assets["text_free"]["path"]) as text_free:
            expected_base = ImageOps.fit(background.convert("RGB"), (get(data, "layout.canvas_width"), get(data, "layout.canvas_height")), method=Image.Resampling.LANCZOS)
            if text_free.size != expected_base.size or ImageChops.difference(text_free.convert("RGB"), expected_base).getbbox():
                errors.append("text-free review image must be the deterministic registered background crop, not a masked final")
        for full, mobile in (("text_free", "text_free_mobile"), ("final", "final_mobile")):
            with Image.open(assets[full]["path"]) as large, Image.open(assets[mobile]["path"]) as small:
                expected_small = large.convert("RGB").resize((360, round(large.height * 360 / large.width)), Image.Resampling.LANCZOS)
                if small.size != expected_small.size or ImageChops.difference(small.convert("RGB"), expected_small).getbbox():
                    errors.append(f"{mobile} must be the exact 360px preview of {full}")
    except (KeyError, OSError, ValueError, TypeError) as exc:
        errors.append(f"invalid layout evidence: {exc}")
    errors += cold_review_errors(data)
    return errors


def cold_review_errors(data: dict) -> list[str]:
    review = data.get("semantic_cold_review", {})
    errors = []
    if not nonempty(review.get("reviewer_id")) or not nonempty(review.get("reviewer_context_id")) or review.get("reviewer_context_id") in designer_contexts(data):
        errors.append("cold review requires an independent reviewer/context id")
    if review.get("asset_hashes") != review_assets(data):
        errors.append("cold review belongs to different asset versions")
    for key in ("stage1_input", "stage1_output", "stage2_input", "stage2_output"):
        errors += checked_asset(review.get(key), f"cold_review.{key}")
    try:
        for key, asset in review["images"].items():
            errors += checked_asset(asset, f"cold_review.images.{key}")
            if asset["sha256"] != get(data, f"production.assets.{key}.sha256"):
                errors.append(f"cold review input image {key} differs from the current asset")
        first_input = read_json(Path(review["stage1_input"]["path"]))
        second_input = read_json(Path(review["stage2_input"]["path"]))
        expected_first = stage1_input(data, review["images"])
        expected_second = stage2_input(data, review, include_typography="typography_review" in second_input)
        expected_second = preserve_legacy_typography_contract(expected_second, second_input)
        if first_input != expected_first or second_input != expected_second:
            errors.append("cold review input must contain only the fixed staged images/questions and original quote/context")
        result1 = read_json(Path(review["stage1_output"]["path"]))
        if any(not nonempty(result1.get(key)) for key in ("image_only_first_read", "dominant_misreading", "uncertain_elements")):
            errors.append("stage1 raw reviewer output is incomplete")
        result = read_json(Path(review["stage2_output"]["path"]))
        from expression_contract import expression_result_errors
        result_errors = stage2_result_errors(result) + expression_result_errors(result, data, require_pass=True) + typography_result_errors(result, second_input, require_pass=True)
        errors += result_errors
        if result_errors:
            return errors
        if result.get("connection_assessment") != "natural" or result.get("decision") != "pass" or review.get("decision") != "pass":
            errors.append("cold review must find a natural connection and pass; explanation cannot rescue failure")
        if get(data, "qa.readability") != result.get("readability"):
            errors.append("qa.readability must match the raw reviewer output")
        for group in TEXT_GROUPS:
            for size in ("full_resolution",):
                if result.get("readability", {}).get(group, {}).get(size) != "pass":
                    errors.append(f"readability.{group}.{size} must pass")
        expected_basis = {"lock_hash": get(data, "pre_generation.lock_hash"), "stage1_output_sha256": review["stage1_output"]["sha256"], "stage2_output_sha256": review["stage2_output"]["sha256"]}
        if review.get("alignment_basis") != expected_basis:
            errors.append("creator alignment must bind the current lock and immutable raw review outputs")
        if not nonempty(review.get("plan_vs_observed")) or not nonempty(review.get("missing_link_note")):
            errors.append("creator must compare original meaning/editorial emphasis and planned mechanism with the actual independent observations")
        if review.get("missing_link") != "none" or review.get("explanation_required") is not False:
            errors.append("creator alignment must have missing_link=none and explanation_required=false")
    except (KeyError, OSError, ValueError, TypeError) as exc:
        errors.append(f"cannot read staged cold-review evidence: {exc}")
    return errors
