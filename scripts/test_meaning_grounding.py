"""Source-grounding contract tests; synthetic text is not literary evidence."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from record_utils import compute_lock_hash, meaning_grounding_errors, source_meaning_review_input, v13_art_direction_errors
from integrated_production import review_input
from production_integrity import stage2_input
from test_art_direction_v13 import art_direction_record


def record():
    data = art_direction_record()
    quote = "校准原句：比较使差异显现。"
    context = "合成访谈问题：讨论怎样认识差异。合成回答：" + quote + "不涉及必然变好。"
    data["run"]["meaning_grounding_required"] = True
    data["content"].update(text_type="exact_quote", text=quote, chapter_or_context=context)
    data["plain_brief"].update(
        meaning_basis={
            "source_locator": "synthetic:test-only#answer",
            "supporting_text": context,
            "attribution_scope": "Synthetic interview speaker, discussing differences.",
            "support_note": "The synthetic answer explicitly links comparison to visible differences.",
            "limits": "No promise that comparison improves both parties.",
        },
        editorial_extension="Designer-only reflection, not author meaning.",
    )
    return data


class MeaningGroundingTests(unittest.TestCase):
    def test_complete_source_binding_passes_existing_art_gate(self):
        data = record()
        self.assertEqual(meaning_grounding_errors(data), [])
        self.assertEqual(v13_art_direction_errors(data), [])

    def test_missing_evidence_or_attribution_is_blocked(self):
        for field in ("source_locator", "supporting_text", "attribution_scope", "support_note", "limits"):
            data = record()
            data["plain_brief"]["meaning_basis"][field] = ""
            self.assertTrue(meaning_grounding_errors(data), field)

    def test_context_cannot_be_designer_summary(self):
        data = record()
        data["content"]["chapter_or_context"] = "Designer summary: everyone becomes better."
        self.assertTrue(meaning_grounding_errors(data))

    def test_excerpt_must_include_the_selected_quote(self):
        data = record()
        data["plain_brief"]["meaning_basis"]["supporting_text"] = "不涉及必然变好。"
        self.assertTrue(meaning_grounding_errors(data))

    def test_only_whitespace_variation_is_allowed_in_binding(self):
        data = record()
        data["plain_brief"]["meaning_basis"]["supporting_text"] = data["content"]["chapter_or_context"].replace("。", "。\n")
        self.assertEqual(meaning_grounding_errors(data), [])
        data["plain_brief"]["meaning_basis"]["supporting_text"] += "新增的劝告。"
        self.assertTrue(meaning_grounding_errors(data))

    def test_extension_can_be_absent_but_not_merged_or_untyped(self):
        data = record()
        data["plain_brief"]["editorial_extension"] = ""
        self.assertEqual(meaning_grounding_errors(data), [])
        del data["plain_brief"]["editorial_extension"]
        self.assertTrue(meaning_grounding_errors(data))

    def test_source_changes_and_disabling_contract_break_lock(self):
        data = record()
        before = compute_lock_hash(data)
        data["plain_brief"]["meaning_basis"]["limits"] += "Changed."
        self.assertNotEqual(before, compute_lock_hash(data))
        data = record()
        data["run"]["meaning_grounding_required"] = False
        self.assertTrue(meaning_grounding_errors(data))
        self.assertNotEqual(before, compute_lock_hash(data))
        del data["run"]["meaning_grounding_required"]
        self.assertNotEqual(before, compute_lock_hash(data))

    def test_legacy_records_not_retroactively_certified(self):
        data = record()
        del data["run"]["meaning_grounding_required"]
        data["plain_brief"].pop("meaning_basis")
        self.assertEqual(meaning_grounding_errors(data), [])
        self.assertEqual(source_meaning_review_input(data), {})

    def test_both_review_routes_receive_source_not_designer_answer(self):
        data = record()
        data["schema_version"] = "1.5"
        images = {"final": {"path": "synthetic-full.png"}, "final_mobile": {"path": "synthetic-small.png"}}
        for result in (review_input(data, images), stage2_input(data, {"images": images})):
            source = result["meaning_grounding"]
            self.assertEqual(source["supporting_text"], data["content"]["chapter_or_context"])
            for field in ("core_meaning", "support_note", "editorial_extension", "attribution_scope", "limits"):
                self.assertNotIn(field, source)
            self.assertNotIn(data["plain_brief"]["editorial_extension"], json.dumps(result))

    def test_new_initializer_enables_contract_in_both_modes(self):
        script = Path(__file__).with_name("init_run.py")
        with tempfile.TemporaryDirectory() as root:
            for mode in ("integrated_image_text", "local_typesetting"):
                out = Path(root) / mode
                result = subprocess.run(
                    [sys.executable, str(script), "--date", "2026-10-12", "--slug", "test", "--out-dir", str(out), "--rendering-mode", mode],
                    capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                initialized = json.loads((out / "design-record.json").read_text())
                self.assertIs(initialized["run"]["meaning_grounding_required"], True)
                self.assertTrue(meaning_grounding_errors(initialized))


if __name__ == "__main__":
    unittest.main()
