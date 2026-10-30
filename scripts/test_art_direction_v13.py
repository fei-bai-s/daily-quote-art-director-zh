#!/usr/bin/env python3
"""Behavioral regression tests for schema 1.3 art-direction decisions."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from record_utils import v13_art_direction_errors
from validate_record import validate_cold_review_v13, validate_design_concept_v13


SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE = SCRIPT_DIR.parent / "assets" / "design-record.template.json"


def concept(
    concept_id: str,
    representation_mode: str,
    first_read: str,
    decision: str,
) -> dict:
    return {
        "concept_id": concept_id,
        "core_visual_proposition": f"A complete visual proposition for {concept_id}.",
        "first_read_relationship": first_read,
        "representation_mode": representation_mode,
        "implementation": "Subject, space, medium, composition, motion, color, and negative space work together.",
        "misreading_risk": "The central relation could become decorative if execution is weak.",
        "comparison_note": "This note compares semantic clarity and perceptual risk with the other concepts.",
        "decision": decision,
    }


def art_direction_record(mode: str = "standard") -> dict:
    data = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    data["schema_version"] = "1.3"  # Keep the legacy contract independent of the current template.
    data["plain_brief"].update(
        {
            "core_meaning": "Small forces accumulate and begin to make reality change.",
            "editorial_emphasis_options": [
                "Accumulation becomes causally effective.",
                "Hope is grounded in an observable change.",
            ],
            "selected_emphasis": "Accumulation becomes causally effective.",
            "common_misreading": "Generic optimism without an observable causal change.",
            "must_be_visible_relation": "Small forces jointly cause a larger surface to move.",
            "emotional_temperature": "Restrained and cautiously warm.",
            "source_of_strength": "Strength comes from accumulated small actions.",
            "forbidden_literal_elements": ["literal weather", "literal sunrise"],
            "intended_aftertaste": "Hope should feel earned by visible change.",
        }
    )
    data["recent_inertia_check"].update(
        {
            "recent_cards_reviewed": ["a", "b", "c"],
            "recent_expression_mechanisms": ["abstract material"],
            "repeated_theme_risk": "Avoid generic endurance.",
            "repeated_expression_mechanism_risk": "Do not default to tactile abstraction.",
            "novelty_priority_check": "Clarity remains more important than novelty.",
            "decision": "pass",
        }
    )
    concepts = [
        concept(
            "c1",
            "object-state change",
            "Small forces jointly cause a larger surface to move.",
            "selected",
        ),
        concept(
            "c2",
            "semi-figurative space",
            "Several small supports visibly shift one larger plane.",
            "reserve",
        ),
        concept(
            "c3",
            "abstract material",
            "Repeated marks accumulate into one visible displacement.",
            "reserve",
        ),
    ]
    if mode == "directed":
        concepts = concepts[:1]
        data["concept_competition"]["directed_reason"] = (
            "The user explicitly fixed the object-state visual mechanism."
        )
    data["concept_competition"].update(
        {
            "mode": mode,
            "concepts": concepts,
            "selected_concept_id": "c1",
            "selection_rationale": "The selected concept makes the required causal relationship most legible.",
        }
    )
    data["pre_generation"].update(
        {
            "selected_concept_id": "c1",
            "core_visual_relationship": "Small forces jointly cause a larger surface to move.",
        }
    )
    return data


class ArtDirectionV13Tests(unittest.TestCase):
    def test_standard_competition_passes_with_three_distinct_complete_concepts(self) -> None:
        self.assertEqual(v13_art_direction_errors(art_direction_record()), [])

    def test_first_reasonable_concept_cannot_bypass_standard_competition(self) -> None:
        data = art_direction_record()
        data["concept_competition"]["concepts"] = data["concept_competition"]["concepts"][:1]
        errors = v13_art_direction_errors(data)
        self.assertTrue(any("at least 3" in error for error in errors))

    def test_same_underlying_mechanism_is_rejected_even_if_concepts_are_many(self) -> None:
        data = art_direction_record()
        for row in data["concept_competition"]["concepts"]:
            row["representation_mode"] = "abstract material"
        errors = v13_art_direction_errors(data)
        self.assertTrue(any("2 representation modes" in error for error in errors))

    def test_user_directed_visual_can_take_the_light_path(self) -> None:
        self.assertEqual(v13_art_direction_errors(art_direction_record("directed")), [])

    def test_liang_hong_missing_causal_link_cannot_pass_cold_review(self) -> None:
        data = art_direction_record()
        data["semantic_cold_review"].update(
            {
                "review_input_isolated": True,
                "image_only_reviewed_at": "2026-09-04T08:00:00+08:00",
                "image_only_first_read": "The stitches become denser, but the felt surface itself does not visibly move.",
                "dominant_misreading": "A decorative gradient of thread density.",
                "quote_revealed_at": "2026-09-04T08:01:00+08:00",
                "shared_relationship": "Both the quote and image contain gradual accumulation, but not the resulting change.",
                "missing_link": "causal_link",
                "missing_link_note": "The image does not show accumulated stitches causing the larger surface to change.",
                "explanation_required": True,
                "full_resolution_checked": True,
                "mobile_checked": True,
                "decision": "return_to_concepts",
            }
        )
        errors = validate_cold_review_v13(data)
        self.assertTrue(any("missing_link must be 'none'" in error for error in errors))
        self.assertTrue(any("explanation_required must be false" in error for error in errors))
        self.assertTrue(any("decision must be 'pass'" in error for error in errors))

    def test_optional_genericity_test_is_not_a_daily_hard_gate(self) -> None:
        data = art_direction_record()
        data["semantic_cold_review"].update(
            {
                "review_input_isolated": True,
                "image_only_reviewed_at": "2026-09-04T08:00:00+08:00",
                "image_only_first_read": "Several small supports visibly push and displace one much larger surface.",
                "dominant_misreading": "It might read as careful structural repair.",
                "quote_revealed_at": "2026-09-04T08:01:00+08:00",
                "shared_relationship": "Accumulated small forces become causally effective and make a larger reality change.",
                "missing_link": "none",
                "missing_link_note": "No key action, state, or causal link is missing.",
                "explanation_required": False,
                "optional_genericity_test": "",
                "full_resolution_checked": True,
                "mobile_checked": True,
                "decision": "pass",
            }
        )
        self.assertEqual(validate_cold_review_v13(data), [])

    def test_four_part_concept_is_not_forced_to_500_characters(self) -> None:
        data = art_direction_record()
        data["content"].update(
            {
                "text": "一切还没有完全好起来。",
                "author": "梁鸿",
                "work": "梁庄十年",
            }
        )
        full_text = (
            "选择的句子：梁鸿《梁庄十年》中的“一切还没有完全好起来。”这句话没有把希望写成口号。"
            "这句话在说什么：现实仍有缺口，但判断不必停在缺口上；真正值得注意的是已经出现、能够被观察的变化。"
            "希望配图表达什么：让人先看到微小力量共同作用，而不是只看到轻快、温暖或聚集。"
            "画面为什么这样设计：用多个小支点共同推移一块较重平面，位移必须清楚可见；低饱和材料维持克制，"
            "局部暖色只标示变化发生的位置，大块留白交给正文。画面不直画未来或希望，却让积累开始改变现实的关系成立。"
        )
        with tempfile.TemporaryDirectory() as tmp:
            record_path = Path(tmp) / "design-record.json"
            concept_path = Path(tmp) / "design-concept.txt"
            concept_path.write_text(full_text, encoding="utf-8")
            data["design_concept"].update(
                {
                    "file_path": str(concept_path),
                    "written_at": "2026-09-04T08:02:00+08:00",
                    "selected_quote": "梁鸿《梁庄十年》：“一切还没有完全好起来。”",
                    "quote_meaning": "现实仍不完整，但应辨认已经出现并能够改变现实的变化。",
                    "intended_picture_message": "微小力量共同作用，并使较大的现实结构出现可见变化。",
                    "visual_design": "多个小支点共同推移一块较重平面，位移必须可见；色彩只标示变化发生的位置，留白承接正文。",
                    "full_text": full_text,
                }
            )
            self.assertLess(len(full_text), 500)
            self.assertEqual(validate_design_concept_v13(data, record_path), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
