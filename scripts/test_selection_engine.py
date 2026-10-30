#!/usr/bin/env python3
"""Regression tests for the schema 1.2+ daily-quote selection gates."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from record_utils import content_selection_errors, v12_selection_system_errors


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATE = SKILL_DIR / "assets" / "design-record.template.json"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def delivered_record(date_value: str, text: str, author: str, work: str) -> dict:
    return {
        "run": {"date": date_value},
        "content_selection": {
            "desired_effect": "test",
            "candidates": [
                {
                    "candidate_id": "c1",
                    "text": text,
                    "author": author,
                    "work": work,
                    "decision": "selected",
                }
            ],
        },
        "content": {
            "text": text,
            "author": author,
            "work": work,
            "text_type": "exact_quote",
        },
        "semantic_card": {
            "core_tension": "test tension",
            "source_of_strength": "test strength",
            "emotional_temperature": "test temperature",
        },
        "layout": {"final_image_path": "/tmp/test.png"},
        "qa": {"final_status": "passed"},
    }


def candidate(
    candidate_id: str,
    text: str,
    author: str,
    work: str,
    source_type: str,
    route_id: str,
    effect: str,
    decision: str,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "text_type": "exact_quote",
        "text": text,
        "author": author,
        "work": work,
        "source_type": source_type,
        "cultural_context": "test cultural context",
        "period": "test period",
        "discovery_route_id": route_id,
        "semantic_signature": {
            "desired_effect": effect,
            "core_tension": f"{effect}-tension",
            "source_of_strength": f"{effect}-strength",
            "emotional_temperature": f"{effect}-temperature",
        },
        "novelty_note": "Compared with the delivered series rather than model familiarity.",
        "source_status": "verified" if decision == "selected" else "locatable",
        "relevance": "Strong standalone meaning and a non-literal visual relationship.",
        "risk": "Requires source and context verification.",
        "decision": decision,
    }


class SelectionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"
        self.index = self.root / "series-index.json"
        hu = delivered_record(
            "2026-07-28",
            "不怕他真理无穷，进一寸有一寸的欢喜。",
            "胡适",
            "拟中国科学社社歌",
        )
        write_json(self.runs / "hu-a" / "design-record.json", hu)
        write_json(self.runs / "hu-b" / "design-record.json", hu)
        write_json(
            self.runs / "tagore" / "design-record.json",
            delivered_record(
                "2026-07-26",
                "如果你把所有的错误都关在门外时，真理也要被关在外面了。",
                "泰戈尔",
                "飞鸟集",
            ),
        )
        for day in ("2026-08-01", "2026-08-02", "2026-08-03"):
            exposed = delivered_record(
                day,
                "这是一条反复进入候选池但尚未交付的文本。",
                "循环作者",
                "循环作品",
            )
            exposed["qa"]["final_status"] = "pending"
            write_json(
                self.runs / f"exposure-{day}" / "design-record.json",
                exposed,
            )
        result = subprocess.run(
            [
                "python3",
                str(SCRIPT_DIR / "build_series_index.py"),
                "--runs-dir",
                str(self.runs),
                "--out",
                str(self.index),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_record(self, selected: dict, mode: str = "open_search") -> Path:
        data = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        # These regression fixtures exercise the existing v1.3 contract, even as the live template evolves.
        data["schema_version"] = "1.3"
        data["run"].pop("rendering_mode", None)  # Historical fixture, not a new integrated run.
        data["run"].update(
            {
                "date": "2026-08-06",
                "weekday": "星期四",
                "slug": "selection-test",
                "initialized_at": "2026-08-06T07:00:00+08:00",
            }
        )
        reserves = [
            candidate("c2", "候选文本二具有足够长度。", "作者乙", "作品乙", "小说", "r2", "好奇", "reserve"),
            candidate("c3", "候选文本三具有足够长度。", "作者丙", "作品丙", "书信", "r3", "幽默", "reserve"),
            candidate("c4", "候选文本四具有足够长度。", "作者丁", "作品丁", "散文", "r4", "清醒", "reserve"),
            candidate("c5", "候选文本五具有足够长度。", "作者戊", "作品戊", "戏剧", "r1", "陪伴", "reserve"),
        ]
        data["content_selection"].update(
            {
                "selection_mode": mode,
                "user_direction": "User did not specify; select openly.",
                "desired_effect": "A fresh form of constructive reflection.",
                "scope_note": "Search across independent semantic and source routes.",
                "range_check": "Authors, source types, and semantic signatures are not concentrated.",
                "pool_stop_reason": "Five effective candidates remain after twelve raw leads and history checks.",
                "candidates": [selected] + reserves if mode == "open_search" else [selected],
                "selected_candidate_id": selected["candidate_id"],
                "selection_rationale": "The winner has the strongest editorial value without sacrificing source integrity.",
            }
        )
        if mode == "open_search":
            data["content_selection"]["finalist_comparison"] = [
                {
                    "candidate_id": selected["candidate_id"],
                    "quality_case": "The selected text is source-sound, dense, and independently meaningful.",
                    "core_relationship": selected["semantic_signature"]["core_tension"],
                    "comparison_to_winner": "This is the winner because it best serves today's editorial need.",
                },
                {
                    "candidate_id": "c2",
                    "quality_case": "The reserve is also source-sound and has comparable standalone value.",
                    "core_relationship": "A different relation centered on curiosity rather than release.",
                    "comparison_to_winner": "It remains second because its current series value is slightly lower.",
                },
            ]
        data["content"].update(
            {
                "text_type": selected["text_type"],
                "text": selected["text"],
                "author": selected["author"],
                "work": selected["work"],
            }
        )
        data["editorial_brief"].update(
            {
                "today_need": "Create a relationship not saturated in the recent series.",
                "recent_saturation": ["endurance"],
                "underexplored_directions": ["curiosity"],
                "avoid_repeating": ["famous motivational aphorisms"],
                "exploration_priority": ["letters", "drama", "less-used essays"],
                "quality_guardrail": "Do not trade source accuracy or semantic density for novelty.",
                "selection_risk": "The model may recall familiar canonical authors first.",
            }
        )
        if mode == "open_search":
            data["discovery_routes"] = [
                {
                    "route_id": f"r{number}",
                    "route_type": ["semantic", "genre", "culture", "work"][number - 1],
                    "search_intent": f"Independent search intent {number}",
                    "scope": f"Independent source scope {number}",
                    "raw_count": 3,
                    "effective_candidate_ids": [
                        row["candidate_id"]
                        for row in data["content_selection"]["candidates"]
                        if row["discovery_route_id"] == f"r{number}"
                    ],
                    "finding": f"Distinct finding {number}",
                }
                for number in range(1, 5)
            ]
        from record_utils import now_for_record
        data["content_selection"]["author_review"] = {
            "candidate_id": selected["candidate_id"], "author": selected["author"],
            "checked_at": now_for_record(data), "identity_note": "Synthetic test identity.",
            "queries": ["Synthetic background", "Synthetic risk"],
            "sources": [{"url": "https://example.test/author", "title": "Synthetic source", "note": "Fixture only."}],
            "findings": [], "decision": "pass", "rationale": "Synthetic positive branch.",
            "limitations": "Not a real author investigation."
        }
        path = self.root / "current" / "design-record.json"
        write_json(path, data)
        return path

    def run_history(self, record: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(SCRIPT_DIR / "check_quote_history.py"),
                str(record),
                "--history-index",
                str(self.index),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def fill_pre_generation(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["content"].update(
            {
                "source_url": "https://example.test/source",
                "verification_note": "Primary source text and context were verified.",
                "verified": True,
            }
        )
        data["plain_brief"].update(
            {
                "core_meaning": "A complete contextual meaning for the selected text.",
                "editorial_emphasis_options": [
                    "Notice how a bounded change affects a larger field.",
                    "Keep the change concrete rather than rhetorical.",
                ],
                "selected_emphasis": "Notice how a bounded change affects a larger field.",
                "common_misreading": "Treating the sentence as generic motivation without a visible change.",
                "must_be_visible_relation": "A bounded element changes a larger field without filling it.",
                "emotional_temperature": "Calm and alert.",
                "source_of_strength": "Strength comes from a concrete change in attention.",
                "forbidden_literal_elements": ["literal nouns from the quote"],
                "intended_aftertaste": "First feel calm, then notice the active shift.",
            }
        )
        data["recent_inertia_check"].update(
            {
                "recent_cards_reviewed": ["recent-a", "recent-b", "recent-c"],
                "repeated_theme_risk": "The plan avoids the recent endurance theme.",
                "recent_expression_mechanisms": ["photographic observation", "abstract material"],
                "repeated_expression_mechanism_risk": "The plan does not default to the recent abstract-material mechanism.",
                "novelty_priority_check": "Semantic clarity remains more important than a new medium.",
                "decision": "pass",
            }
        )
        concepts = [
            {
                "concept_id": "v1",
                "core_visual_proposition": "A bounded element gradually alters a larger field.",
                "first_read_relationship": "A bounded element changes a larger field without filling it.",
                "representation_mode": "object-state change",
                "implementation": "A restrained object-state composition with a visible local cause and larger response.",
                "misreading_risk": "The local element may look merely decorative.",
                "comparison_note": "Strongest visible causal relation and reliable text space.",
                "decision": "selected",
            },
            {
                "concept_id": "v2",
                "core_visual_proposition": "A quiet spatial boundary reveals a change in pressure.",
                "first_read_relationship": "A boundary holds while nearby space changes density.",
                "representation_mode": "semi-figurative space",
                "implementation": "A shallow architectural space using interval and compression.",
                "misreading_risk": "May read as stillness rather than an active change.",
                "comparison_note": "Clear spatial logic but weaker causal visibility.",
                "decision": "reserve",
            },
            {
                "concept_id": "v3",
                "core_visual_proposition": "Repeated marks accumulate into a structural displacement.",
                "first_read_relationship": "Small repeated marks create one visible displacement.",
                "representation_mode": "abstract material",
                "implementation": "A tactile relief in which accumulated marks physically lift one plane.",
                "misreading_risk": "Could become a generic texture if displacement is weak.",
                "comparison_note": "Rich material fit but higher execution risk.",
                "decision": "reserve",
            },
        ]
        data["concept_competition"].update(
            {
                "mode": "standard",
                "concepts": concepts,
                "selected_concept_id": "v1",
                "selection_rationale": "The selected concept preserves semantic accuracy and makes the causal relation most visible before novelty is considered.",
            }
        )
        data["pre_generation"].update(
            {
                "selected_concept_id": "v1",
                "core_visual_relationship": "A bounded element changes a larger field without filling it.",
                "medium": "Layered paper relief scan.",
                "style_language": "Tactile abstract editorial image.",
                "composition": "Relationship at lower right with a large quiet text field.",
                "typography_direction": "Modern sans serif with restrained hierarchy.",
                "color_functions": "Cool neutral field with one active warm counterpoint.",
                "negative_space_plan": "Keep the left fifty-eight percent quiet for typography.",
                "avoid_cliches": ["light beams", "roads", "arrows"],
                "difference_from_recent": "Different medium, relation, palette, and movement.",
                "prompt": "Vertical editorial background, no text, no watermark, no logo.",
            }
        )
        data["layout"].update(
            {
                "canvas_width": 1080,
                "canvas_height": 1920,
                "date_text": "2026-08-06",
                "source_label": f"{data['content']['author']}｜《{data['content']['work']}》",
                "yi_text": "宜｜验证一个具体发现",
                "ji_text": "忌｜用熟悉答案代替观察",
                "font_rationale": "The type voice matches the direct contemporary rhythm.",
                "line_break_rationale": "The line break follows the semantic turn.",
            }
        )
        write_json(path, data)

    def test_index_groups_same_day_visual_variants(self) -> None:
        index = json.loads(self.index.read_text(encoding="utf-8"))
        self.assertEqual(index["records_read"], 6)
        self.assertEqual(index["delivered_card_count"], 2)
        hu = next(row for row in index["delivered_cards"] if row["author"] == "胡适")
        self.assertEqual(hu["variant_count"], 2)

    def test_index_build_fails_closed_on_unreadable_history(self) -> None:
        broken_runs = self.root / "broken-runs"
        broken_record = broken_runs / "broken" / "design-record.json"
        broken_record.parent.mkdir(parents=True, exist_ok=True)
        broken_record.write_text("{not-json", encoding="utf-8")
        broken_index = self.root / "broken-index.json"
        result = subprocess.run(
            [
                "python3",
                str(SCRIPT_DIR / "build_series_index.py"),
                "--runs-dir",
                str(broken_runs),
                "--out",
                str(broken_index),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertFalse(broken_index.exists())

    def test_repeated_candidate_exposure_requires_review(self) -> None:
        selected = candidate(
            "c1",
            "这是一条反复进入候选池但尚未交付的文本。",
            "循环作者",
            "循环作品",
            "散文",
            "r1",
            "观察",
            "selected",
        )
        path = self.make_record(selected)
        first = self.run_history(path)
        self.assertEqual(first.returncode, 1)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["history_dedup"]["decision"], "review_required")
        data["history_dedup"]["candidate_exposure_decision"] = "justified"
        data["history_dedup"]["candidate_exposure_rationale"] = (
            "The broader search found this candidate materially stronger than fresh alternatives."
        )
        write_json(path, data)
        second = self.run_history(path)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

    def test_author_cooldown_requires_expansion_or_justification(self) -> None:
        selected = candidate(
            "c1",
            "这是同一作者另一部作品中尚未出现的新句子。",
            "胡适",
            "另一部作品",
            "散文",
            "r1",
            "辨析",
            "selected",
        )
        path = self.make_record(selected)
        first = self.run_history(path)
        self.assertEqual(first.returncode, 1)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(
            data["history_dedup"]["selected_history_check"]["author_in_cooldown"]
        )
        self.assertEqual(data["history_dedup"]["decision"], "review_required")
        data["history_dedup"]["cooldown_decision"] = "justified"
        data["history_dedup"]["cooldown_rationale"] = (
            "Four independent routes found no equally strong fresh-author alternative."
        )
        write_json(path, data)
        second = self.run_history(path)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

    def test_exact_duplicate_fails_open_search(self) -> None:
        selected = candidate(
            "c1",
            "不怕他真理无穷，进一寸有一寸的欢喜。",
            "胡适",
            "拟中国科学社社歌",
            "诗歌",
            "r1",
            "求知",
            "selected",
        )
        path = self.make_record(selected)
        result = self.run_history(path)
        self.assertEqual(result.returncode, 1)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["history_dedup"]["decision"], "failed")
        self.assertTrue(data["history_dedup"]["selected_history_check"]["exact_matches"])

    def test_near_duplicate_fails_open_search(self) -> None:
        selected = candidate(
            "c1",
            "如果你把所有的错误都关在门外，真理也要被关在外面。",
            "泰戈尔",
            "飞鸟集",
            "诗歌",
            "r1",
            "试错",
            "selected",
        )
        path = self.make_record(selected)
        result = self.run_history(path)
        self.assertEqual(result.returncode, 1)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(data["history_dedup"]["selected_history_check"]["near_matches"])

    def test_traditional_character_variant_fails_open_search(self) -> None:
        selected = candidate(
            "c1",
            "不怕他真理無窮，進一寸有一寸的歡喜。",
            "胡適",
            "擬中國科學社社歌",
            "詩歌",
            "r1",
            "求知",
            "selected",
        )
        path = self.make_record(selected)
        result = self.run_history(path)
        self.assertEqual(result.returncode, 1)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(data["history_dedup"]["selected_history_check"]["near_matches"])

    def test_explicit_revision_can_override_duplicate(self) -> None:
        selected = candidate(
            "c1",
            "不怕他真理无穷，进一寸有一寸的欢喜。",
            "胡适",
            "拟中国科学社社歌",
            "诗歌",
            "r1",
            "求知",
            "selected",
        )
        path = self.make_record(selected, mode="revision")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["history_dedup"]["reuse_authorized"] = True
        data["history_dedup"]["reuse_authorization_reason"] = "User explicitly requested a new design for the same quote."
        write_json(path, data)
        result = self.run_history(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["history_dedup"]["decision"], "passed_with_user_override")

    def test_fresh_open_search_record_passes_breadth_and_history_checks(self) -> None:
        selected = candidate(
            "c1",
            "一条此前没有出现而且足够完整的新文本。",
            "作者甲",
            "作品甲",
            "诗歌",
            "r1",
            "松动",
            "selected",
        )
        path = self.make_record(selected)
        result = self.run_history(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(content_selection_errors(data), [])
        self.assertEqual(v12_selection_system_errors(data, path), [])

    def test_concentrated_candidate_pool_is_rejected(self) -> None:
        selected = candidate(
            "c1",
            "一条用于测试候选集中问题的新文本。",
            "作者甲",
            "作品甲",
            "诗歌",
            "r1",
            "坚持",
            "selected",
        )
        path = self.make_record(selected)
        self.assertEqual(self.run_history(path).returncode, 0)
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["content_selection"]["candidates"]:
            row["author"] = "同一熟悉作者"
            row["source_type"] = "语录"
            row["semantic_signature"] = {
                "desired_effect": "坚持",
                "core_tension": "困难与坚持",
                "source_of_strength": "意志",
                "emotional_temperature": "激昂",
            }
        errors = content_selection_errors(data)
        self.assertTrue(any("distinct authors" in error for error in errors))
        self.assertTrue(any("3 source types" in error for error in errors))
        self.assertTrue(any("3 distinct semantic" in error for error in errors))

    def test_fresh_record_can_lock_and_pass_pre_validation(self) -> None:
        selected = candidate(
            "c1",
            "一条此前没有出现并且能够独立成立的新文本。",
            "作者甲",
            "作品甲",
            "诗歌",
            "r1",
            "松动",
            "selected",
        )
        path = self.make_record(selected)
        self.assertEqual(self.run_history(path).returncode, 0)
        selected_gate = subprocess.run(
            ["python3", str(SCRIPT_DIR / "validate_selection.py"), str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            selected_gate.returncode,
            0,
            selected_gate.stdout + selected_gate.stderr,
        )
        self.fill_pre_generation(path)
        locked = subprocess.run(
            ["python3", str(SCRIPT_DIR / "lock_pre_generation.py"), str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
        validated = subprocess.run(
            [
                "python3",
                str(SCRIPT_DIR / "validate_record.py"),
                str(path),
                "--stage",
                "pre",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

    def test_duplicate_record_cannot_lock(self) -> None:
        selected = candidate(
            "c1",
            "不怕他真理无穷，进一寸有一寸的欢喜。",
            "胡适",
            "拟中国科学社社歌",
            "诗歌",
            "r1",
            "求知",
            "selected",
        )
        path = self.make_record(selected)
        self.assertEqual(self.run_history(path).returncode, 1)
        self.fill_pre_generation(path)
        locked = subprocess.run(
            ["python3", str(SCRIPT_DIR / "lock_pre_generation.py"), str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(locked.returncode, 1)
        self.assertIn("historical", (locked.stdout + locked.stderr).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
