"""1.5 contract regressions. Synthetic fixtures test gates, not aesthetic truth."""
import copy
import json
import unittest
from pathlib import Path
import test_production_v14 as fixtures
from record_utils import compute_lock_hash
from expression_contract import concept_expression_errors, expression_result_errors, policy_errors
from production_integrity import start_cold_review, register_cold_stage1, register_cold_stage2, production_errors, read_json, require_lock, snapshot_json, typography_result_errors, TYPOGRAPHY_REVIEW

def policy():
    return {"profile":"implicit_relation","user_override":{"allow_primary_figures":False,"allow_direct_depiction":False,"instruction":""}}

def judgement(mode="relational_metaphor", figures="none", decision="admit"):
    return {"mode":mode,"figure_role":figures,"decision":decision,"evidence":"Synthetic classification: the visible relationship, rather than a performed story, carries the connection."}

def plan():
    return {"schema_version":"1.5","expression_policy":policy(),"concept_competition":{"concepts":[
        {"concept_id":"a","metaphor_bridge":"Surface continuity and local roughness coexist without erasing each other.","admission":judgement(),"decision":"selected"}]}}

def typography(decision="pass"):
    return {"reading_rhythm":"Synthetic fixture: two line groups pause at clause boundaries.",
            "image_text_relationship":"Synthetic fixture: left text edge and shared band region balance across the canvas.",
            "hierarchy_and_breathing":"Synthetic fixture: quote first, then source; footer does not compete.",
            "font_fit":"Synthetic fixture: uniform unaccented letter weight carries a neutral observational voice.",
            "decision":decision}

class ExpressionContractTests(unittest.TestCase):
    def test_relation_candidate_is_admitted(self):
        self.assertEqual(concept_expression_errors(plan()), [])

    def test_direct_people_not_saved_by_admit(self):
        d=plan(); d["concept_competition"]["concepts"][0]["admission"]=judgement("direct_depiction","primary")
        errors=concept_expression_errors(d)
        self.assertTrue(any("direct depiction" in e for e in errors))
        self.assertTrue(any("primary human" in e for e in errors))

    def test_no_people_is_not_enough(self):
        for mode in ("decorative","unclear"):
            d=plan(); d["concept_competition"]["concepts"][0]["admission"]=judgement(mode)
            self.assertTrue(concept_expression_errors(d))

    def test_rejected_candidate_can_be_recorded_not_selected(self):
        d=plan(); c=d["concept_competition"]["concepts"][0]
        c["admission"]=judgement("direct_depiction","primary","reject")
        self.assertTrue(concept_expression_errors(d))
        c["decision"]="rejected"
        self.assertEqual(concept_expression_errors(d), [])

    def test_incidental_figure_is_not_blanket_banned(self):
        d=plan(); d["concept_competition"]["concepts"][0]["admission"]=judgement(figures="incidental")
        self.assertEqual(concept_expression_errors(d), [])

    def test_explicit_exceptions_are_separate(self):
        d=plan(); c=d["concept_competition"]["concepts"][0]
        c["admission"]=judgement("direct_depiction","primary")
        override=d["expression_policy"]["user_override"]
        override.update(allow_primary_figures=True)
        self.assertTrue(policy_errors(d))
        override["instruction"]="本轮明确用人物主体表现休息场景。"
        self.assertTrue(concept_expression_errors(d))  # figures does not authorize direct depiction
        override["allow_direct_depiction"]=True
        self.assertEqual(concept_expression_errors(d), [])

    def test_no_missing_policy_or_bridge(self):
        d=plan(); del d["expression_policy"]
        self.assertTrue(concept_expression_errors(d))
        d=plan(); del d["concept_competition"]["concepts"][0]["metaphor_bridge"]
        self.assertTrue(concept_expression_errors(d))

    def test_natural_connection_cannot_cancel_expression_failure(self):
        d=plan()
        for mode,decision in (("direct_depiction","pass"),("relational_metaphor","fail")):
            result={"connection_assessment":"natural","decision":"pass","expression_review":judgement(mode,decision=decision)}
            self.assertTrue(expression_result_errors(result,d,require_pass=True))

    def test_review_needs_concrete_evidence_and_structured_result(self):
        d=plan()
        for value in (None,"pass",{"mode":"relational_metaphor","figure_role":"none","decision":"pass","evidence":""}):
            self.assertTrue(expression_result_errors({"expression_review":value},d))

    def test_policy_and_admission_are_art_locked(self):
        d=plan(); before=compute_lock_hash(d)
        d["expression_policy"]["user_override"]["allow_primary_figures"]=True
        self.assertNotEqual(before,compute_lock_hash(d))
        d=plan(); before=compute_lock_hash(d)
        d["concept_competition"]["concepts"][0]["admission"]["decision"]="reject"
        self.assertNotEqual(before,compute_lock_hash(d))

    def test_old_schema_not_retroactively_claimed(self):
        d=plan(); d["schema_version"]="1.4"; del d["expression_policy"]
        self.assertEqual(concept_expression_errors(d), [])
        self.assertEqual(expression_result_errors({},d), [])

    def test_standard_competition_cannot_use_only_rejected_strawmen(self):
        d=plan(); d["concept_competition"]["mode"]="standard"
        self.assertTrue(concept_expression_errors(d))
        d["concept_competition"]["concepts"].append(copy.deepcopy(d["concept_competition"]["concepts"][0]))
        self.assertEqual(concept_expression_errors(d), [])

class ExpressionProductionTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ProductionV14Tests()
        self.fx.setUp()
        self.fx.data["schema_version"]="1.5"
        self.fx.data["expression_policy"]=policy()
        for c in self.fx.data["concept_competition"]["concepts"]:
            c["metaphor_bridge"]="Synthetic fixture: a shared region connects distinct areas without erasing them."
            c["admission"]=judgement()
        self.fx.save()
        result=self.fx.cli("lock_pre_generation.py")
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.fx.data=read_json(self.fx.path)

    def tearDown(self):
        self.fx.tearDown()

    def review(self, expression=None, typography_review=True, legacy=False):
        f=self.fx
        start=start_cold_review(f.data,f.path,"reviewer","independent-context")
        first=read_json(Path(f.data["semantic_cold_review"]["stage1_input"]["path"]))
        self.assertIn("series_boundary", first)
        self.assertNotIn("expression_policy", first) # no quote-containing user instruction before reveal
        self.assertNotIn("quote", first)
        self.assertNotIn("concept_competition", first)
        self.assertNotIn("typography_review", first)
        if start["next_stage"]=="stage1":
            register_cold_stage1(f.data,f.path,f.json_file("stage1.json",{"image_only_first_read":"Synthetic lines overlap.","dominant_misreading":"Could be crossing.","uncertain_elements":"Time direction unknown."}))
        second=read_json(Path(f.data["semantic_cold_review"]["stage2_input"]["path"]))
        self.assertEqual(second["expression_policy"],f.data["expression_policy"])
        self.assertNotIn("plain_brief",second)
        self.assertNotIn("pre_generation",second)
        self.assertNotIn("layout",second)
        self.assertEqual(second["typography_review"],TYPOGRAPHY_REVIEW)
        if legacy:
            # Simulate an immutable pre-update input, not a production downgrade switch.
            second.pop("typography_review")
            directory=f.root / "legacy-review"
            directory.mkdir()
            f.data["semantic_cold_review"]["stage2_input"] = snapshot_json(second, directory, "stage2-input.json")
        result={"quote_meaning_in_own_words":"Source describes the observable shared region.","connection_assessment":"natural","connection_reason":"Synthetic shared region matches the source relationship.","readability":{g:{"full_resolution":"pass","evidence":"Synthetic legibility fixture."} for g in fixtures.TEXT_GROUPS},"decision":"pass"}
        if expression is not None: result["expression_review"]=expression
        if typography_review is True:
            result["typography_design_review"]=typography()
        elif isinstance(typography_review,dict):
            result["typography_design_review"]=typography_review
        register_cold_stage2(f.data,f.path,f.json_file("stage2.json",result))

    def test_full_v15_chain_and_font_revision(self):
        f=self.fx; f.generated(); f.rendered()
        self.review(judgement(decision="pass")); f.finish()
        result=f.cli("validate_record.py","--stage","final")
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        stage1=copy.deepcopy(f.data["semantic_cold_review"]["stage1_output"])
        f.rendered("large-font")
        self.review(judgement(decision="pass")); f.finish()
        self.assertEqual(stage1,f.data["semantic_cold_review"]["stage1_output"])
        self.assertEqual(production_errors(f.data,f.path),[])

    def test_natural_but_direct_actual_image_is_blocked(self):
        f=self.fx; f.generated(); f.rendered()
        self.review(judgement("direct_depiction","primary","fail")); f.finish()
        self.assertEqual(f.data["semantic_cold_review"]["decision"],"revise")
        self.assertTrue(f.data["qa"]["no_overlap_or_clipping"])  # expression failure is not a typography failure
        result=f.cli("validate_record.py","--stage","final")
        self.assertNotEqual(result.returncode,0)
        self.assertIn("expression",result.stdout+result.stderr)

    def test_missing_expression_output_does_not_register(self):
        f=self.fx; f.generated(); f.rendered()
        with self.assertRaisesRegex(ValueError,"expression_review"):
            self.review()
        self.assertNotIn("stage2_output",f.data["semantic_cold_review"])

    def test_exception_mutation_requires_relock(self):
        self.fx.data["expression_policy"]["user_override"]["allow_primary_figures"]=True
        with self.assertRaisesRegex(ValueError,"plan changed"):
            require_lock(self.fx.data)

    def test_missing_typography_output_does_not_register(self):
        f=self.fx; f.generated(); f.rendered()
        with self.assertRaisesRegex(ValueError,"typography_design_review"):
            self.review(judgement(decision="pass"),typography_review=False)
        self.assertNotIn("stage2_output",f.data["semantic_cold_review"])

    def test_typography_revise_blocks_even_when_readable_and_overall_pass(self):
        f=self.fx; f.generated(); f.rendered()
        self.review(judgement(decision="pass"),typography_review=typography("revise")); f.finish()
        self.assertTrue(f.data["qa"]["no_overlap_or_clipping"])
        self.assertEqual(f.data["semantic_cold_review"]["decision"],"revise")
        errors=production_errors(f.data,f.path)
        self.assertTrue(any("typography_design_review must pass" in e for e in errors))
        result=f.cli("validate_record.py","--stage","final")
        self.assertNotEqual(result.returncode,0)

    def test_every_typography_observation_and_decision_required(self):
        for field in (*TYPOGRAPHY_REVIEW["questions"],"decision"):
            with self.subTest(field=field):
                row=typography(); row[field]=""
                errors=typography_result_errors({"typography_design_review":row},{"typography_review":TYPOGRAPHY_REVIEW})
                self.assertTrue(any(field in e for e in errors))

    def test_unknown_typography_contract_rejected(self):
        bad=copy.deepcopy(TYPOGRAPHY_REVIEW); bad["profile"]="unknown"
        self.assertTrue(typography_result_errors({"typography_design_review":typography()},{"typography_review":bad}))

    def test_changed_review_contract_blocks_final(self):
        f=self.fx; f.generated(); f.rendered()
        self.review(judgement(decision="pass")); f.finish()
        review=f.data["semantic_cold_review"]
        second=read_json(Path(review["stage2_input"]["path"]))
        second["typography_review"]["questions"]["font_fit"]="Only check readability."
        directory=f.root / "tampered-review"
        directory.mkdir()
        review["stage2_input"]=snapshot_json(second,directory,"stage2-input.json")
        self.assertTrue(any("fixed staged" in e or "changed typography" in e for e in production_errors(f.data,f.path)))

    def test_old_v15_input_keeps_original_contract(self):
        f=self.fx; f.generated(); f.rendered()
        self.review(judgement(decision="pass"),typography_review=False,legacy=True); f.finish()
        self.assertEqual(production_errors(f.data,f.path),[])
        result=f.cli("validate_record.py","--stage","final")
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        # A new layout keeps no-text observations but receives the new staged contract.
        stage1=copy.deepcopy(f.data["semantic_cold_review"]["stage1_output"])
        f.rendered("new-typography")
        self.review(judgement(decision="pass")); f.finish()
        self.assertEqual(stage1,f.data["semantic_cold_review"]["stage1_output"])
        self.assertEqual(production_errors(f.data,f.path),[])

if __name__=="__main__":
    unittest.main(verbosity=2)
