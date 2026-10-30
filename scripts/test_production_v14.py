#!/usr/bin/env python3
"""Isolated schema 1.4 production regressions; no historical outputs are modified."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from PIL import Image, ImageDraw
import test_selection_v14 as selection_fixtures
from record_utils import atomic_write_json, compute_lock_hash, file_sha256, now_for_record
from production_integrity import (TEXT_GROUPS, canonical_hash, complete_generation, image_asset, prepare_layout, production_errors, read_json, record_execution, register_background_v14, register_cold_stage1, register_cold_stage2, register_layout, start_cold_review, start_generation, text_data)
from validate_record import BASE_REQUIRED_QA_TRUE, V13_REQUIRED_QA_TRUE

SCRIPTS = Path(__file__).resolve().parent


class ProductionV14Tests(unittest.TestCase):
    def setUp(self):
        self.selection = selection_fixtures.SelectionV14Tests()
        self.selection.setUp()
        self.path = self.selection.checked()
        self.selection.base.fill_pre_generation(self.path)
        self.data = read_json(self.path)
        brief = self.data["plain_brief"]
        brief["semantic_invariant"] = brief.pop("must_be_visible_relation")
        brief.pop("forbidden_literal_elements", None)
        self.data["content"]["chapter_or_context"] = "Synthetic original source context: the speaker describes an observable change, not a designer explanation."
        self.data["layout"].update(canvas_width=240, canvas_height=320)
        self.root = self.path.parent
        self.save()
        result = self.cli("lock_pre_generation.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.data = read_json(self.path)
        self.prompt = self.root / "request.txt"
        self.prompt.write_text(self.data["pre_generation"]["prompt"], encoding="utf-8")
        self.background = self.root / "generated.png"
        image = Image.new("RGB", (240, 320), "ivory")
        draw = ImageDraw.Draw(image)
        draw.line((10, 290, 160, 210), fill="navy", width=15)
        draw.line((230, 290, 90, 210), fill="coral", width=15)
        image.save(self.background)
        self.tool_result = self.root / "tool-result.txt"
        self.tool_result.write_text("Synthetic tool response: request-test; output generated.png", encoding="utf-8")

    def tearDown(self):
        self.selection.tearDown()

    def save(self):
        atomic_write_json(self.path, self.data)

    def cli(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), str(self.path), *map(str, args)], capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))

    def json_file(self, name, value):
        path = self.root / name
        atomic_write_json(path, value)
        return path

    def generated(self):
        start_generation(self.data, self.path, "attempt-1", self.prompt, "designer-context")
        complete_generation(self.data, self.path, "attempt-1", self.tool_result, "synthetic:request-test", self.background)
        register_background_v14(self.data, self.path, self.background, "attempt-1")
        result = self.json_file("execution.json", {"key_action_or_state_realized": "Synthetic structural test: two bands occupy a shared area.", "concept_fidelity": "Synthetic test confirms the specified test geometry.", "text_safe_area_usable": True, "background_text_free": True, "decision": "pass"})
        record_execution(self.data, self.path, result)

    def rendered(self, version="first", prepared=False):
        if not prepared:
            prepare_layout(self.data, self.path)
        source = self.root / f"render-{version}.py"
        source.write_text(f"# Synthetic renderer fixture: {version}\n", encoding="utf-8")
        base = self.data["production"]["assets"]["text_free"]
        final = self.root / f"final-{version}.png"
        with Image.open(base["path"]) as image:
            draw = ImageDraw.Draw(image)
            draw.text((10, 25), f"SYNTHETIC {version}", fill="black")
            image.save(final)
        manifest = self.json_file(f"manifest-{version}.json", {"text_data": text_data(self.data), "base_sha256": base["sha256"], "render_source_sha256": file_sha256(source), "final_sha256": file_sha256(final)})
        register_layout(self.data, self.path, source, final, manifest)

    def reviewed(self):
        start = start_cold_review(self.data, self.path, "reviewer", "independent-context")
        if start["next_stage"] == "stage1":
            result = self.json_file("stage1.json", {"image_only_first_read": "Two synthetic colored lines share a limited lower region.", "dominant_misreading": "Could be crossing rather than overlapping.", "uncertain_elements": "No unique chronology can be observed."})
            register_cold_stage1(self.data, self.path, result)
        readability = {group: {"full_resolution": "pass", "evidence": f"Synthetic fixture observation for {group}; not real visual approval."} for group in TEXT_GROUPS}
        result = self.json_file("stage2.json", {"quote_meaning_in_own_words": "The source describes change that has become observable.", "connection_assessment": "natural", "connection_reason": "The observed relationship is compatible without an invented causal sequence.", "readability": readability, "decision": "pass"})
        register_cold_stage2(self.data, self.path, result)

    def finish(self):
        self.data["semantic_cold_review"].update(plan_vs_observed="The editorial emphasis remains compatible with the source; the raw observations support a shared region but not a chronological transformation, and no such additional claim is made.", missing_link="none", missing_link_note="The specified observable relationship remains supported within the stated limits.", explanation_required=False)
        self.data["post_generation"].update(planned_relationships_realized=["Synthetic planned relation observed."], regeneration_or_fix_decision="Synthetic fixture passed the execution gate.", literalness_test="No source nouns are literally illustrated.")
        quote = self.data["content"]["text"]
        author, work = self.data["content"]["author"], self.data["content"]["work"]
        concept = f"选择的句子：{author}《{work}》：“{quote}”。" + "这句话说明眼前的状态可以被重新理解，已经出现的变化值得具体辨认。希望配图呈现能够被直接观察的关系，保持独立的部分在局部接近，并不承诺它们之后必然如何发展。画面使用安静浅色与两条不同方向的色带，留白交给文字，局部颜色只承担必要的关系表达。" * 2
        concept_path = self.root / "concept.txt"
        concept_path.write_text(concept, encoding="utf-8")
        self.data["design_concept"] = {"file_path": str(concept_path), "written_at": now_for_record(self.data), "selected_quote": quote, "quote_meaning": "Synthetic meaning.", "intended_picture_message": "Observable relation.", "visual_design": "Two synthetic bands.", "full_text": concept}
        for flag in BASE_REQUIRED_QA_TRUE + V13_REQUIRED_QA_TRUE:
            self.data["qa"][flag] = True
        self.data["qa"].pop("content_score", None)
        self.data["qa"].pop("typography_score", None)
        self.data["qa"]["final_status"] = "passed"
        self.save()

    def complete(self):
        self.generated()
        self.rendered()
        self.reviewed()
        self.finish()

    def test_positive_complete_cli_without_unanchored_scores(self):
        self.complete()
        self.assertEqual(production_errors(self.data, self.path), [])
        result = self.cli("validate_record.py", "--stage", "final")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VALIDATION PASSED", result.stdout)

    def test_parallel_cold_start_before_render(self):
        self.generated()
        prepare_layout(self.data, self.path)
        result = start_cold_review(self.data, self.path, "reviewer", "parallel-context")
        first = read_json(Path(result["input"]["path"]))
        self.assertNotIn("quote", first)
        self.assertNotIn("final", self.data["semantic_cold_review"]["images"])
        raw = self.json_file("parallel-stage1.json", {"image_only_first_read": "Synthetic two lines", "dominant_misreading": "Crossing", "uncertain_elements": "No time sequence"})
        with self.assertRaises(ValueError):
            register_cold_stage1(self.data, self.path, raw)
        self.assertNotIn("quote_revealed_at", self.data["semantic_cold_review"])
        self.rendered(prepared=True)
        register_cold_stage1(self.data, self.path, raw)
        readability = {g: {"full_resolution": "pass", "evidence": "Synthetic test observation"} for g in TEXT_GROUPS}
        second = self.json_file("parallel-stage2.json", {"quote_meaning_in_own_words": "Synthetic meaning", "connection_assessment": "natural", "connection_reason": "Synthetic relationship", "readability": readability, "decision": "pass"})
        register_cold_stage2(self.data, self.path, second)
        self.finish()
        self.assertEqual(production_errors(self.data, self.path), [])
        # A final rendered after quote disclosure must still fail.
        self.data["layout"]["rendered_at"] = "2099-01-01T00:00:00+08:00"
        self.assertTrue(any("layout must precede" in e for e in production_errors(self.data, self.path)))

    def test_parallel_crop_mutation_rejected(self):
        self.generated()
        prepare_layout(self.data, self.path)
        start_cold_review(self.data, self.path, "reviewer", "parallel-context")
        self.rendered(prepared=True)
        self.data["production"]["assets"]["text_free"]["sha256"] = "changed"
        raw = self.json_file("changed-stage1.json", {"image_only_first_read": "Synthetic lines", "dominant_misreading": "Crossing", "uncertain_elements": "No time"})
        with self.assertRaisesRegex(ValueError, "assets changed"):
            register_cold_stage1(self.data, self.path, raw)

    def test_timestamp_preserves_subsecond_order(self):
        from production_integrity import ordered_times
        current = datetime(2026, 9, 10, 15, 50, 48, 800000, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch("record_utils.datetime") as clock:
            clock.now.return_value = current
            now = now_for_record(self.data)
        self.assertTrue(ordered_times("2026-09-10T15:50:48.064000+08:00", now))
        self.assertFalse(ordered_times("2026-09-10T15:50:48.900000+08:00", now))

    def test_combined_commands_preserve_execution_gate(self):
        start_generation(self.data, self.path, "a1", self.prompt, "designer-context")
        self.save()
        result = self.cli("production_evidence.py", "generation-complete", "--attempt-id", "a1", "--tool-result", self.tool_result, "--tool-result-locator", "synthetic:combined", "--background", self.background, "--select")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.data = read_json(self.path)
        self.assertEqual(self.data["production"]["current_attempt_id"], "a1")
        self.assertNotEqual(self.data.get("execution_validation", {}).get("decision"), "pass")
        failed = self.json_file("failed-execution.json", {"key_action_or_state_realized": "Missing", "concept_fidelity": "Failed synthetic test", "text_safe_area_usable": False, "background_text_free": True, "decision": "regenerate_same_concept"})
        before = self.path.read_bytes()
        rejected = self.cli("production_evidence.py", "execution", "--result", failed, "--prepare-layout")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(self.path.read_bytes(), before)
        passed = self.json_file("passed-execution.json", {"key_action_or_state_realized": "Synthetic lines visible", "concept_fidelity": "Synthetic match", "text_safe_area_usable": True, "background_text_free": True, "decision": "pass"})
        result = self.cli("production_evidence.py", "execution", "--result", passed, "--prepare-layout")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(read_json(self.path)["production"]["assets"]["layout_request"])

    def test_corrupt_png_and_non_image_background_rejected(self):
        bad = self.root / "truncated.png"
        bad.write_bytes(self.background.read_bytes()[:24])
        with self.assertRaisesRegex(ValueError, "fully decoded"):
            image_asset(bad, True)
        start_generation(self.data, self.path, "a1", self.prompt, "designer")
        with self.assertRaisesRegex(ValueError, "fully decoded"):
            complete_generation(self.data, self.path, "a1", self.tool_result, "tool-call:1", self.tool_result)

    def test_completed_attempt_required_not_registration_timestamp(self):
        with self.assertRaisesRegex(ValueError, "attempt_id"):
            register_background_v14(self.data, self.path, self.background, "not-an-attempt")
        self.generated()
        self.assertEqual(self.data["post_generation"]["generated_at"], self.data["production"]["attempts"][0]["completed_at"])
        self.assertIn("registered_at", self.data["post_generation"])

    def test_mutated_actual_prompt_requires_new_attempt_and_concept_stays_locked(self):
        self.prompt.write_text(self.prompt.read_text() + " Changed composition execution.", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "change_note"):
            start_generation(self.data, self.path, "changed", self.prompt, "designer")
        start_generation(self.data, self.path, "changed", self.prompt, "designer", "Clarify execution without changing the concept.")
        self.data["pre_generation"]["composition"] += " Back-edited after request."
        with self.assertRaisesRegex(ValueError, "plan changed"):
            complete_generation(self.data, self.path, "changed", self.tool_result, "tool:changed", self.background)

    def test_mutated_quote_after_history_cannot_lock(self):
        for field in ("text", "author", "work"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.data)
                changed["content"][field] += "变更"
                changed["content_selection"]["candidates"][0][field] += "变更"
                atomic_write_json(self.path, changed)
                result = self.cli("lock_pre_generation.py")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("history input changed", result.stdout + result.stderr)

    def test_initialization_and_production_time_order(self):
        self.data["run"]["initialized_at"] = "2099-01-01T00:00:00+08:00"
        self.save()
        result = self.cli("lock_pre_generation.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("initialized_at", result.stdout + result.stderr)

    def test_date_and_yi_ji_drift_fail_without_reselecting_quote(self):
        self.complete()
        locked = compute_lock_hash(self.data)
        self.data["layout"].update(date_text="2099-12-31", yi_text="忌｜标签错位")
        self.assertEqual(compute_lock_hash(self.data), locked)
        errors = production_errors(self.data, self.path)
        self.assertTrue(any("date_text" in error for error in errors))
        self.assertTrue(any("yi_text" in error for error in errors))
        self.assertTrue(any("exact layout text changed" in error for error in errors))

    def test_wrong_source_label_rejected(self):
        self.complete()
        self.data["layout"]["source_label"] = self.data["content"]["author"] + "《" + self.data["content"]["work"] + "改写》"
        self.assertTrue(any("complete work title" in error for error in production_errors(self.data, self.path)))

    def test_swapped_rejected_background_and_final_are_rejected(self):
        self.complete()
        for field in ("background", "final"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.data)
                replacement = self.root / f"unreviewed-{field}.png"
                Image.new("RGB", (240, 320), "white").save(replacement)
                section, key = ("post_generation", "background_path") if field == "background" else ("layout", "final_image_path")
                changed[section][key] = str(replacement)
                self.assertTrue(any("not the registered asset" in error for error in production_errors(changed, self.path)))

    def test_overwrite_same_path_and_render_source_invalidates_review(self):
        self.complete()
        final = Path(self.data["layout"]["final_image_path"])
        Image.new("RGB", (240, 320), "white").save(final)
        source = Path(self.data["layout"]["render_source_path"])
        source.write_text("# another render source", encoding="utf-8")
        errors = production_errors(self.data, self.path)
        self.assertTrue(any("assets.final.sha256 changed" in error for error in errors))
        self.assertTrue(any("assets.render_source.sha256 changed" in error for error in errors))

    def test_real_text_free_images_and_staged_inputs(self):
        self.complete()
        review = self.data["semantic_cold_review"]
        first = read_json(Path(review["stage1_input"]["path"]))
        second = read_json(Path(review["stage2_input"]["path"]))
        self.assertEqual(set(first), {"images", "questions"})
        self.assertEqual(set(second), {"quote", "author", "work", "original_context", "images", "questions"})
        self.assertNotEqual(review["images"]["text_free"]["sha256"], review["images"]["final"]["sha256"])
        self.assertNotIn("plain_brief", json.dumps(second))

    def test_independent_context_required_and_stage2_cannot_go_first(self):
        self.generated()
        self.rendered()
        with self.assertRaisesRegex(ValueError, "independent"):
            start_cold_review(self.data, self.path, "reviewer", "designer-context")
        result = self.json_file("not-stage2.json", {})
        with self.assertRaisesRegex(ValueError, "follow immutable stage1"):
            register_cold_stage2(self.data, self.path, result)

    def test_raw_review_cannot_be_rewritten_to_improve_verdict(self):
        self.complete()
        stage1 = Path(self.data["semantic_cold_review"]["stage1_output"]["path"])
        stage1.write_text(json.dumps({"image_only_first_read": "changed"}), encoding="utf-8")
        self.assertTrue(any("stage1_output.sha256 changed" in error for error in production_errors(self.data, self.path)))

    def test_creator_alignment_required_even_after_natural_review(self):
        self.complete()
        self.data["semantic_cold_review"].update(missing_link="causal_link", explanation_required=True)
        self.assertTrue(any("missing_link=none" in error for error in production_errors(self.data, self.path)))

    def test_font_revision_reuses_stage1_only_and_preserves_history(self):
        self.complete()
        previous = copy.deepcopy(self.data["semantic_cold_review"])
        lock = self.data["pre_generation"]["lock_hash"]
        self.data["delivery"] = {"receipt_path": "synthetic-old-receipt", "delivered": True}
        self.rendered("larger-font")
        self.assertNotIn("delivery", self.data)
        self.assertEqual(self.data["qa"]["final_status"], "pending")
        self.assertEqual(self.data["pre_generation"]["lock_hash"], lock)
        self.assertEqual(len(self.data["production"]["attempts"]), 1)
        result = start_cold_review(self.data, self.path, "reviewer", "independent-context")
        self.assertEqual(result["next_stage"], "stage2")
        self.assertEqual(self.data["semantic_cold_review"]["stage1_output"], previous["stage1_output"])
        self.assertNotIn("stage2_output", self.data["semantic_cold_review"])
        self.assertTrue(self.data["production"]["revisions"])
        old_record = read_json(Path(self.data["production"]["revisions"][-1]["record"]["path"]))
        self.assertIn("delivery", old_record)
        self.assertNotEqual(old_record["layout"]["final_image_path"], self.data["layout"]["final_image_path"])
        old_concept_text = Path(old_record["design_concept"]["file_path"]).read_text(encoding="utf-8")
        (self.root / "concept.txt").write_text("Changed after archive", encoding="utf-8")
        self.assertEqual(Path(old_record["design_concept"]["file_path"]).read_text(encoding="utf-8"), old_concept_text)
        result_path = self.root / "stage2.json"
        register_cold_stage2(self.data, self.path, result_path)
        self.finish()
        self.assertEqual(production_errors(self.data, self.path), [])
        final = self.cli("validate_record.py", "--stage", "final")
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)

    def test_background_reregistration_clears_review_qa_and_receipt(self):
        self.complete()
        self.data["delivery"] = {"receipt_path": "synthetic-old-receipt"}
        register_background_v14(self.data, self.path, self.background, "attempt-1")
        self.assertNotIn("delivery", self.data)
        self.assertEqual(self.data["qa"]["final_status"], "pending")
        self.assertEqual(self.data["layout"]["final_image_path"], "")
        self.assertEqual(self.data["semantic_cold_review"]["decision"], "pending")

    def test_changed_blind_image_cannot_reuse_quote_exposed_context(self):
        self.complete()
        self.data["layout"]["canvas_width"] = 260
        self.rendered("new-crop")
        with self.assertRaisesRegex(ValueError, "already saw the quote"):
            start_cold_review(self.data, self.path, "reviewer", "independent-context")
        result = start_cold_review(self.data, self.path, "new-reviewer", "new-independent-context")
        self.assertEqual(result["next_stage"], "stage1")

    def test_archive_mode_is_labeled_not_for_delivery(self):
        self.complete()
        path = self.selection.base.runs / "later" / "design-record.json"
        path.parent.mkdir(parents=True)
        atomic_write_json(path, selection_fixtures.delivered_record("2026-08-07", "新增不重复历史。", "另一作者", "另一作品"))
        live = self.cli("validate_record.py", "--stage", "final")
        self.assertNotEqual(live.returncode, 0)
        archived = self.cli("validate_record.py", "--stage", "final", "--archive")
        self.assertEqual(archived.returncode, 0, archived.stdout + archived.stderr)
        self.assertIn("NOT VALID FOR NEW DELIVERY", archived.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
