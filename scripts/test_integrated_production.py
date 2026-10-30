"""B-mode contracts, using synthetic files/observations, not visual approval."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from record_utils import compute_lock_hash, rendering_mode
from integrated_production import (
    GUIDANCE, GROUPS, exact_copy, prompt_errors, register_integrated,
    register_integrated_review, result_errors, review_input,
)
from production_integrity import (
    complete_generation, prepare_layout, production_errors, read_json,
    record_execution, register_background_v14, register_cold_stage1,
    start_cold_review, start_generation, TYPOGRAPHY_REVIEW_V1,
    preserve_legacy_typography_contract, typography_result_errors,
)
import test_expression_v15 as fixtures


class IntegratedTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.ExpressionProductionTests()
        self.base.setUp()
        self.f = self.base.fx
        d = self.f.data
        d["run"]["rendering_mode"] = "integrated_image_text"
        d["layout"]["font_rationale"] = ""
        d["layout"]["line_break_rationale"] = ""
        d["pre_generation"]["prompt"] = "Synthetic joint card request; no watermark.\n" + "\n".join(exact_copy(d).values()) + "\n" + GUIDANCE
        self.f.save()
        result = self.f.cli("lock_pre_generation.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.f.data = read_json(self.f.path)
        self.f.prompt.write_text(self.f.data["pre_generation"]["prompt"], encoding="utf-8")

    def tearDown(self):
        self.base.tearDown()

    def generated(self):
        f = self.f
        start_generation(f.data, f.path, "joint-1", f.prompt, "designer-context")
        complete_generation(f.data, f.path, "joint-1", f.tool_result, "synthetic:joint-1", f.background)
        register_background_v14(f.data, f.path, f.background, "joint-1")
        result = f.json_file("joint-execution.json", {"key_action_or_state_realized": "Synthetic lines share a region.", "concept_fidelity": "Synthetic contract fixture, not image quality proof.", "text_safe_area_usable": True, "decision": "pass"})
        record_execution(f.data, f.path, result)
        register_integrated(f.data, f.path, f.root / "joint-final.png")

    def review_result(self):
        return {"actual_image_observation": "Two synthetic lines share a region; no chronology visible.",
            "first_attention": "Synthetic observation of text region, then lines.",
            "dominant_misreading": "Crossing rather than proximity.",
            "quote_meaning_in_own_words": "Original source concerns the observable shared region.",
            "connection_assessment": "natural", "connection_reason": "Visible relationship is compatible without additional events.",
            "expression_review": fixtures.judgement(decision="pass"), "typography_design_review": fixtures.typography(),
            "copy_check": {g: {"observed_text": value, "matches": True} for g, value in exact_copy(self.f.data).items()},
            "extra_text_absent": True,
            "readability": {g: {"full_resolution": "pass", "evidence": "Synthetic contract fixture, not real visual approval."} for g in GROUPS}, "decision": "pass"}

    def reviewed(self, result=None):
        f = self.f
        request = start_cold_review(f.data, f.path, "reviewer", "new-isolated-context")
        input_data = read_json(Path(request["input"]["path"]))
        self.assertFalse(input_data["quote_blind"])
        self.assertTrue(input_data["text_visible"])
        for key in ("plain_brief", "pre_generation", "concept_competition", "layout", "prompt"):
            self.assertNotIn(key, input_data)
        register_integrated_review(f.data, f.path, f.json_file("joint-review.json", result or self.review_result()))

    def finish(self):
        self.f.finish()
        self.f.data["qa"]["final_text_rendered_deterministically"] = False
        self.f.save()

    def test_positive_full_cli_free_typography_no_local_artifacts(self):
        self.generated(); self.reviewed(); self.finish()
        self.assertEqual(production_errors(self.f.data, self.f.path), [])
        result = self.f.cli("validate_record.py", "--stage", "final")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(Path(self.f.data["layout"]["final_image_path"]).read_bytes(), self.f.background.read_bytes())
        self.assertNotIn("render_source", self.f.data["production"]["assets"])

    def test_new_init_default_and_explicit_local(self):
        scripts = Path(__file__).parent
        with tempfile.TemporaryDirectory() as root:
            for mode in ("integrated_image_text", "local_typesetting"):
                out = Path(root) / mode
                args = [sys.executable, str(scripts / "init_run.py"), "--date", "2026-10-05", "--slug", "test", "--out-dir", str(out)]
                if mode == "local_typesetting": args += ["--rendering-mode", mode]
                result = subprocess.run(args, capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(rendering_mode(read_json(out / "design-record.json")), mode)

    def test_new_meaning_grounding_contract_full_positive_chain(self):
        # Synthetic source and observations test binding, not interpretation quality.
        d = self.f.data
        d["run"]["meaning_grounding_required"] = True
        context = "Synthetic fixture source, not literary evidence: " + d["content"]["text"] + " Synthetic surrounding context."
        d["content"]["chapter_or_context"] = context
        d["plain_brief"].update(
            meaning_basis={"source_locator": "synthetic:context", "supporting_text": context,
                           "attribution_scope": "Synthetic fixture speaker.",
                           "support_note": "Synthetic binding test only.", "limits": "Not a real semantic verdict."},
            editorial_extension="",
        )
        self.f.save()
        result = self.f.cli("lock_pre_generation.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.f.data = read_json(self.f.path)
        self.generated(); self.reviewed(); self.finish()
        result = self.f.cli("validate_record.py", "--stage", "final")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_absence_keeps_old_lock_payload(self):
        d = copy.deepcopy(self.f.data)
        d["run"].pop("rendering_mode")
        self.assertEqual(rendering_mode(d), "local_typesetting")
        before = compute_lock_hash(d)
        d["layout"]["yi_text"] += "新版"
        self.assertEqual(before, compute_lock_hash(d))  # Old independent local text binding retained.

    def test_copy_and_mode_are_locked(self):
        d = self.f.data; before = compute_lock_hash(d)
        d["layout"]["yi_text"] += "新版"
        self.assertNotEqual(before, compute_lock_hash(d))
        d["run"]["rendering_mode"] = "local_typesetting"
        self.assertNotEqual(before, compute_lock_hash(d))

    def test_integrated_canvas_is_locked(self):
        d = self.f.data; before = compute_lock_hash(d)
        d["layout"]["canvas_height"] += 1
        self.assertNotEqual(before, compute_lock_hash(d))
        self.assertTrue(any("unlocked" in e or "changed" in e for e in production_errors(d, self.f.path, "pre")))

    def test_attempt_budget_requires_user_authorization_for_each_extra_call(self):
        f = self.f
        start_generation(f.data, f.path, "a1", f.prompt, "designer")
        start_generation(f.data, f.path, "a2", f.prompt, "designer")
        with self.assertRaisesRegex(ValueError, "attempt limit"):
            start_generation(f.data, f.path, "a3", f.prompt, "designer")
        start_generation(f.data, f.path, "a3", f.prompt, "designer", retry_authorization="用户明确说：再重试一次，保持原方案。")
        self.assertEqual(f.data["production"]["attempts"][-1]["user_retry_authorization"], "用户明确说：再重试一次，保持原方案。")
        with self.assertRaisesRegex(ValueError, "attempt limit"):
            start_generation(f.data, f.path, "a4", f.prompt, "designer")
    def test_conflicting_or_incomplete_prompt_rejected(self):
        d = self.f.data; prompt = d["pre_generation"]["prompt"]
        self.assertTrue(prompt_errors(d, prompt + " no text"))
        self.assertTrue(prompt_errors(d, prompt.replace(d["run"]["weekday"], "")))
        changed = self.f.root / "changed.txt"; changed.write_text("no watermark", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exact"):
            start_generation(d, self.f.path, "bad", changed, "designer", "execution adjustment")

    def test_typography_or_expression_failure_blocks(self):
        result = self.review_result()
        result["typography_design_review"]["decision"] = "revise"
        self.assertTrue(result_errors(result, self.f.data, True))
        result = self.review_result(); result["expression_review"] = fixtures.judgement("direct_depiction", "primary", "fail")
        self.assertTrue(result_errors(result, self.f.data, True))

    def test_negative_space_guidance_and_review_are_explicit(self):
        self.assertIn("所有文字由专门设计的留白托住", GUIDANCE)
        request = review_input(self.f.data, {"final": {}, "final_mobile": {}})
        contract = request["typography_review"]
        self.assertEqual(contract["profile"], "voice-layout-v2-negative-space")
        self.assertIn("即使可读也 revise", contract["questions"]["image_text_relationship"])
        result = self.review_result()
        result["typography_design_review"].update(
            image_text_relationship="正文和页脚直接叠在实景纹理上，没有承托文字的设计留白。",
            decision="revise")
        self.assertTrue(result_errors(result, self.f.data, True))

    def test_exact_legacy_typography_contract_preserved_but_mutations_rejected(self):
        images = {"final": {}, "final_mobile": {}}
        old = review_input(self.f.data, images)
        old["typography_review"] = copy.deepcopy(TYPOGRAPHY_REVIEW_V1)
        expected = preserve_legacy_typography_contract(review_input(self.f.data, images), old)
        self.assertEqual(old, expected)
        self.assertEqual(typography_result_errors(self.review_result(), old, True), [])
        old["typography_review"]["questions"]["image_text_relationship"] = "Pass everything."
        self.assertNotEqual(old, preserve_legacy_typography_contract(review_input(self.f.data, images), old))
        self.assertTrue(typography_result_errors(self.review_result(), old, True))

    def test_incorrect_copy_and_extra_text_block(self):
        result = self.review_result()
        result["copy_check"]["quote"].update(observed_text="Wrong quote.", matches=True)
        self.assertTrue(result_errors(result, self.f.data))
        result["copy_check"]["quote"]["matches"] = False
        self.assertFalse(result_errors(result, self.f.data))
        self.assertTrue(result_errors(result, self.f.data, True))
        result = self.review_result(); result["extra_text_absent"] = False
        self.assertTrue(result_errors(result, self.f.data, True))

    def test_no_fake_text_free_or_local_render_path(self):
        self.generated()
        with self.assertRaisesRegex(ValueError, "local_typesetting"):
            prepare_layout(self.f.data, self.f.path)
        with self.assertRaisesRegex(ValueError, "visible text"):
            register_cold_stage1(self.f.data, self.f.path, self.f.json_file("fake.json", {}))
        self.reviewed(); self.finish()
        self.f.data["semantic_cold_review"]["quote_blind"] = True
        self.assertTrue(production_errors(self.f.data, self.f.path))

    def test_image_or_review_mutation_invalidates(self):
        self.generated(); self.reviewed(); self.finish()
        output = Path(self.f.data["semantic_cold_review"]["integrated_output"]["path"])
        output.write_text(json.dumps(self.review_result()) + "\n\n", encoding="utf-8")
        self.assertTrue(any("sha256 changed" in e for e in production_errors(self.f.data, self.f.path)))
        self.f.data["production"]["assets"]["final"]["sha256"] = "changed"
        self.assertTrue(any("generated PNG bytes" in e for e in production_errors(self.f.data, self.f.path)))

    def test_no_false_deterministic_claim_or_missing_semantic_link(self):
        self.generated(); self.reviewed(); self.finish()
        self.f.data["qa"]["final_text_rendered_deterministically"] = True
        self.assertTrue(any("deterministic typography" in e for e in production_errors(self.f.data, self.f.path)))
        self.f.data["qa"]["final_text_rendered_deterministically"] = False
        self.f.data["semantic_cold_review"]["missing_link"] = "causal_link"
        self.assertTrue(any("sentence-to-image" in e for e in production_errors(self.f.data, self.f.path)))

    def test_incomplete_review_and_self_review_rejected(self):
        self.generated()
        with self.assertRaisesRegex(ValueError, "independent"):
            start_cold_review(self.f.data, self.f.path, "reviewer", "designer-context")
        result = self.review_result(); result["readability"].pop("weekday")
        self.assertTrue(any("weekday" in e for e in result_errors(result, self.f.data)))

    def test_review_snapshot_is_immutable_and_no_overwrite_output(self):
        self.generated(); self.reviewed()
        with self.assertRaisesRegex(ValueError, "already sealed"):
            register_integrated_review(self.f.data, self.f.path, self.f.json_file("new-review.json", self.review_result()))
        with self.assertRaisesRegex(ValueError, "already registered"):
            register_integrated(self.f.data, self.f.path, self.f.root / "another.png")


if __name__ == "__main__":
    unittest.main()
