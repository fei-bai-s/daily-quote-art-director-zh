#!/usr/bin/env python3
"""v1.4 selection/history regression fixtures. All writes stay in TemporaryDirectory."""

from __future__ import annotations

import copy
import json
import subprocess
import unittest
from pathlib import Path

from record_utils import (
    candidate_input_sha256, compute_lock_hash, content_selection_errors,
    file_sha256, history_freshness_errors, pre_generation_required_fields,
    source_locator_errors, v12_selection_system_errors, v13_art_direction_errors, now_for_record,
)
import test_selection_engine as legacy_tests
from test_selection_engine import SCRIPT_DIR, candidate, delivered_record, write_json


class SelectionV14Tests(unittest.TestCase):
    def setUp(self):
        self.base = legacy_tests.SelectionEngineTests()
        self.base.setUp()

    def tearDown(self):
        self.base.tearDown()

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def make(self, text="一条此前没有出现而且能够独立成立的新文本。", author="作者甲", work="作品甲"):
        original = self.base.make_record(candidate("c1", text, author, work, "诗歌", "r1", "松动", "selected"))
        data = self.read(original)
        data["schema_version"] = "1.4"
        data["content"]["verified"] = True
        data["content_selection"]["author_review"] = {
            "candidate_id": "c1", "author": author, "checked_at": now_for_record(data),
            "identity_note": "Synthetic author identity for isolated regression only.",
            "queries": ["Synthetic background query", "Synthetic risk query"],
            "sources": [{"url": "https://example.test/author", "title": "Synthetic source", "note": "Fixture, not a real investigation."}],
            "findings": [], "decision": "pass", "rationale": "Synthetic positive branch.",
            "limitations": "No real author was investigated by this test."
        }
        data["content_selection"]["semantic_diversity_review"] = {
            "decision": "pass",
            "note": "人工比较 c1 的边界松动、c2 的主动探问、c3 的自我距离三种关系；签名文本不是机器语义证明。",
        }
        for i, row in enumerate(data["content_selection"]["candidates"]):
            row["source_type"] = ["poetry", "fiction", "letter", "prose", "drama"][i]
            row["source_locator"] = {"url": f"https://example.test/primary-{i}", "local_path": "", "location": ""}
            row["source_note"] = "Synthetic fixture: candidate text and context have a resolvable source pointer."
        for i, route in enumerate(data["discovery_routes"]):
            route["route_type"] = ["semantic", "genre", "culture_period", "primary_work"][i]
            route["leads"] = [{
                "locator": {"url": f"https://example.test/route-{i}/lead-{j}", "local_path": "", "location": ""},
                "observation": f"Synthetic observed lead {i}-{j}; scope and exclusion differ from final candidates.",
            } for j in range(route["raw_count"])]
        # Put this record inside the indexed tree to exercise current-run exclusion.
        path = self.base.runs / "current" / "design-record.json"
        write_json(path, data)
        return path.resolve()

    def build(self):
        result = subprocess.run(["python3", str(SCRIPT_DIR / "build_series_index.py"), "--runs-dir", str(self.base.runs), "--out", str(self.base.index)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def check(self, path):
        return self.base.run_history(path)

    def gate(self, path, archive=False):
        args = ["python3", str(SCRIPT_DIR / "validate_selection.py"), str(path)]
        if archive:
            args.append("--archive")
        return subprocess.run(args, capture_output=True, text=True)

    def checked(self, **kwargs):
        path = self.make(**kwargs)
        result = self.check(path)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return path

    def test_positive_selection_snapshot_and_self_exclusion(self):
        path = self.checked()
        data = self.read(path)
        snapshot = Path(data["history_dedup"]["history_index_path"])
        self.assertNotEqual(snapshot, self.base.index)
        self.assertEqual(snapshot.parent, path.parent / "history")
        self.assertEqual(file_sha256(snapshot), data["history_dedup"]["history_index_sha256"])
        self.assertNotIn(str(path), [row["path"] for row in self.read(snapshot)["source_manifest"]])
        self.assertEqual(self.gate(path).returncode, 0)
        data["qa"]["final_status"] = "passed"
        write_json(path, data)
        self.assertEqual(history_freshness_errors(data, path), [])

    def test_missing_author_review_still_blocks(self):
        data = self.read(self.checked())
        data["content_selection"].pop("author_review")
        self.assertTrue(any("author_review" in e for e in content_selection_errors(data)))

    def test_quote_author_and_work_mutations_invalidate_input(self):
        path = self.checked()
        data = self.read(path)
        for field in ("text", "author", "work"):
            with self.subTest(field=field):
                changed = copy.deepcopy(data)
                changed["content_selection"]["candidates"][0][field] += "改"
                changed["content"][field] += "改"
                errors = content_selection_errors(changed)
                self.assertTrue(any("history input changed" in value for value in errors), errors)

    def test_run_date_change_requires_history_recheck(self):
        path = self.checked()
        data = self.read(path)
        data["run"]["date"] = "2026-08-07"
        self.assertTrue(any("history run date changed" in error for error in v12_selection_system_errors(data, path)))

    def test_stale_source_index_is_rejected_before_check(self):
        path = self.make()
        row = self.read(path)["content_selection"]["candidates"][0]
        write_json(self.base.runs / "new-delivery" / "design-record.json", delivered_record("2026-08-05", row["text"], row["author"], row["work"]))
        result = self.check(path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("source records changed", result.stderr)

    def test_snapshot_survives_global_rebuild_but_not_new_production(self):
        path = self.checked()
        data = self.read(path)
        snapshot = Path(data["history_dedup"]["history_index_path"])
        old_hash = file_sha256(snapshot)
        write_json(self.base.runs / "later" / "design-record.json", delivered_record("2026-08-07", "无关的新增历史文字用于改变源集合。", "另一作者", "另一作品"))
        self.build()
        self.assertEqual(file_sha256(snapshot), old_hash)
        self.assertEqual(v12_selection_system_errors(data, path), [])
        self.assertEqual(self.gate(path).returncode, 1)
        archived = self.gate(path, archive=True)
        self.assertEqual(archived.returncode, 0, archived.stdout)
        self.assertIn("not valid for new delivery", archived.stdout)

    def test_snapshot_recheck_does_not_overwrite(self):
        path = self.checked()
        snapshot = Path(self.read(path)["history_dedup"]["history_index_path"])
        before = snapshot.stat().st_mtime_ns
        self.assertEqual(self.check(path).returncode, 0)
        self.assertEqual(Path(self.read(path)["history_dedup"]["history_index_path"]), snapshot)
        self.assertEqual(snapshot.stat().st_mtime_ns, before)

    def test_future_date_does_not_hide_recent_author_or_work(self):
        write_json(self.base.runs / "future" / "design-record.json", delivered_record("2026-08-20", "独立的未来句子不应遮蔽过去的冷却。", "胡适", "拟中国科学社社歌"))
        self.build()
        path = self.make(author="胡适", work="拟中国科学社社歌")
        self.assertEqual(self.check(path).returncode, 1)
        result = self.read(path)["history_dedup"]["selected_history_check"]
        self.assertEqual(result["author_last_used"], "2026-07-28")
        self.assertTrue(result["author_in_cooldown"])
        self.assertTrue(result["work_in_cooldown"])

    def test_current_run_exposure_never_changes_threshold(self):
        text = "反复露面但尚未交付的一段独立候选文本。"
        for day in ("2026-08-01", "2026-08-02"):
            data = delivered_record(day, text, "曝光作者", "曝光作品")
            data["qa"]["final_status"] = "pending"
            write_json(self.base.runs / day / "design-record.json", data)
        self.build()
        path = self.checked(text=text, author="曝光作者", work="曝光作品")
        self.assertEqual(self.read(path)["history_dedup"]["selected_history_check"]["recent_candidate_exposure_count"], 2)
        self.build()
        self.assertEqual(self.check(path).returncode, 0)
        self.assertEqual(self.read(path)["history_dedup"]["selected_history_check"]["recent_candidate_exposure_count"], 2)

    def test_effective_source_status_and_evidence_are_required(self):
        path = self.checked()
        data = self.read(path)
        for field, value, fragment in (("source_status", "rejected", "source_status"), ("source_locator", {}, "source_locator"), ("source_note", "", "source_note")):
            changed = copy.deepcopy(data)
            changed["content_selection"]["candidates"][1][field] = value
            self.assertTrue(any(fragment in error for error in content_selection_errors(changed)))
        self.assertEqual(source_locator_errors({"local_path": str(path), "location": "candidate c1"}, "source"), [])
        self.assertTrue(source_locator_errors({"local_path": str(path.parent / "missing.pdf"), "location": "p. 21"}, "source"))
        self.assertTrue(source_locator_errors({"local_path": "book.pdf", "location": "p. 21"}, "source"))
        self.assertTrue(source_locator_errors({"url": "javascript:alert(1)"}, "source"))

    def test_translator_and_edition_are_bound_for_selected_translation(self):
        path = self.checked()
        data = self.read(path)
        row = data["content_selection"]["candidates"][0]
        row["text_type"] = data["content"]["text_type"] = "translated_quote"
        self.assertTrue(any("translator" in error for error in content_selection_errors(data)))
        self.assertTrue(any("edition" in error for error in content_selection_errors(data)))
        row["translator"] = data["content"]["translator"] = "测试译者"
        row["edition"] = data["content"]["edition"] = "测试出版社，2020年版，第21页"
        self.assertEqual(content_selection_errors(data), [])
        data["content"]["edition"] = "另一译本"
        self.assertTrue(any("edition" in error for error in content_selection_errors(data)))

    def test_canonical_types_and_observed_leads_replace_label_counts(self):
        path = self.checked()
        data = self.read(path)
        data["content_selection"]["candidates"][1]["source_type"] = "诗歌"
        self.assertTrue(any("canonical" in error for error in content_selection_errors(data)))
        data = self.read(path)
        data["discovery_routes"][0]["route_type"] = "same-website-new-label"
        data["discovery_routes"][1]["leads"].pop()
        data["discovery_routes"][2]["leads"][0]["observation"] = ""
        errors = v12_selection_system_errors(data, path)
        self.assertTrue(any("canonical" in error for error in errors))
        self.assertTrue(any("len(leads)" in error for error in errors))
        self.assertTrue(any("observation" in error for error in errors))

    def test_semantic_review_is_explicit_not_a_string_distinctness_score(self):
        path = self.checked()
        data = self.read(path)
        signature = data["content_selection"]["candidates"][0]["semantic_signature"]
        for row in data["content_selection"]["candidates"]:
            row["semantic_signature"] = copy.deepcopy(signature)
        self.assertEqual(content_selection_errors(data), [])
        data["content_selection"]["semantic_diversity_review"]["decision"] = "pending"
        self.assertTrue(any("semantic_diversity_review" in error for error in content_selection_errors(data)))

    def test_v14_semantic_invariant_and_run_identity_lock(self):
        path = self.checked()
        self.base.fill_pre_generation(path)
        data = self.read(path)
        data["plain_brief"]["semantic_invariant"] = data["plain_brief"].pop("must_be_visible_relation")
        data["plain_brief"].pop("forbidden_literal_elements", None)
        self.assertEqual(v13_art_direction_errors(data), [])
        fields = pre_generation_required_fields(data)
        self.assertIn("plain_brief.semantic_invariant", fields)
        self.assertNotIn("plain_brief.must_be_visible_relation", fields)
        initial_hash = compute_lock_hash(data)
        data["run"]["date"] = "2026-08-07"
        self.assertNotEqual(compute_lock_hash(data), initial_hash)
        data["run"]["date"] = "2026-08-06"
        data["layout"]["yi_text"] = "宜｜修改独立排版"
        self.assertEqual(compute_lock_hash(data), initial_hash)

    def test_receipt_updates_do_not_stale_history_sources(self):
        path = self.checked()
        data = self.read(path)
        history_path = self.base.runs / "hu-a" / "design-record.json"
        old = self.read(history_path)
        old["run"]["status"] = "delivered"
        old["qa"]["operator_note"] = "只补回执，没有改变验收结论。"
        old["wecom_receipt"] = {"delivered_at": "2026-08-06T09:00:00+08:00"}
        write_json(history_path, old)
        self.assertEqual(history_freshness_errors(data, path), [])

    def test_refreshing_history_does_not_change_art_lock(self):
        path = self.checked()
        data = self.read(path)
        art_hash = compute_lock_hash(data)
        old_snapshot = data["history_dedup"]["history_index_path"]
        write_json(self.base.runs / "unrelated-history" / "design-record.json", delivered_record("2026-08-05", "完全不同作者的新内容只更新系列历史。", "无关作者", "无关作品"))
        self.build()
        self.assertEqual(self.check(path).returncode, 0)
        updated = self.read(path)
        self.assertNotEqual(updated["history_dedup"]["history_index_path"], old_snapshot)
        self.assertEqual(compute_lock_hash(updated), art_hash)


if __name__ == "__main__":
    unittest.main(verbosity=2)
