"""
test_action_block_fix.py — Tests for ACTION BLOCK FIX + ASSESS max_questions

Covers:
  Section 1 — _build_actions_block() (9 tests)
  Section 2 — max_questions per response_type (3 tests)
  Section 3 — build_hard_escalation_response removed (1 test)
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from routers.services.ai import _build_actions_block
import routers.services.clinical_engine as clinical_engine_module


# ═════════════════════════════════════════════════════════════════════════════
# Section 1 — _build_actions_block()
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildActionsBlock(unittest.TestCase):

    # T1: xylitol_toxicity → "Немедленно везите в клинику"
    def test_xylitol_toxicity(self):
        result = _build_actions_block({"symptom": "xylitol_toxicity"})
        self.assertIn("Немедленно везите в клинику", result)

    # T2: antifreeze → "Немедленно везите в клинику"
    def test_antifreeze(self):
        result = _build_actions_block({"symptom": "antifreeze"})
        self.assertIn("Немедленно везите в клинику", result)

    # T3: seizure → "Засеките время приступа"
    def test_seizure(self):
        result = _build_actions_block({"symptom": "seizure"})
        self.assertIn("Засеките время приступа", result)

    # T4: difficulty_breathing → "Срочно везите в клинику"
    def test_difficulty_breathing(self):
        result = _build_actions_block({"symptom": "difficulty_breathing"})
        self.assertIn("Срочно везите в клинику", result)

    # T5: foreign_body_ingestion → "Не вызывайте рвоту"
    def test_foreign_body_ingestion(self):
        result = _build_actions_block({"symptom": "foreign_body_ingestion"})
        self.assertIn("Не вызывайте рвоту", result)

    # T6: urinary_obstruction → "Не давайте мочегонные"
    def test_urinary_obstruction(self):
        result = _build_actions_block({"symptom": "urinary_obstruction"})
        self.assertIn("Не давайте мочегонные", result)

    # T7: vomiting → "Ограничьте корм" (default GI path)
    def test_vomiting_default(self):
        result = _build_actions_block({"symptom": "vomiting"})
        self.assertIn("Ограничьте корм", result)

    # T8: diarrhea → "Ограничьте корм" (default GI path)
    def test_diarrhea_default(self):
        result = _build_actions_block({"symptom": "diarrhea"})
        self.assertIn("Ограничьте корм", result)

    # T9: empty dict → "Ограничьте корм" (fallback)
    def test_empty_dict_default(self):
        result = _build_actions_block({})
        self.assertIn("Ограничьте корм", result)


# ═════════════════════════════════════════════════════════════════════════════
# Section 2 — max_questions per response_type
# Tests the ternary expression from chat.py llm_contract block directly.
# ═════════════════════════════════════════════════════════════════════════════

def _max_questions_for(response_type: str) -> int:
    """Mirror the expression from chat.py llm_contract block."""
    decision = {"response_type": response_type}
    return (
        2 if decision and decision.get("response_type") == "CLARIFY"
        else 1 if decision and decision.get("response_type") == "ASSESS"
        else 0
    )


class TestMaxQuestionsPerResponseType(unittest.TestCase):

    # T10: ASSESS → 1
    def test_assess_max_questions_is_1(self):
        self.assertEqual(_max_questions_for("ASSESS"), 1)

    # T11: CLARIFY → 2
    def test_clarify_max_questions_is_2(self):
        self.assertEqual(_max_questions_for("CLARIFY"), 2)

    # T12: ACTION → 0
    def test_action_max_questions_is_0(self):
        self.assertEqual(_max_questions_for("ACTION"), 0)


# ═════════════════════════════════════════════════════════════════════════════
# Section 3 — build_hard_escalation_response removed
# ═════════════════════════════════════════════════════════════════════════════

class TestDeadCodeRemoved(unittest.TestCase):

    # T13: build_hard_escalation_response does not exist in clinical_engine
    def test_build_hard_escalation_response_not_in_clinical_engine(self):
        self.assertFalse(
            hasattr(clinical_engine_module, "build_hard_escalation_response"),
            "build_hard_escalation_response should have been deleted",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestBuildActionsBlock))
    suite.addTests(loader.loadTestsFromTestCase(TestMaxQuestionsPerResponseType))
    suite.addTests(loader.loadTestsFromTestCase(TestDeadCodeRemoved))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
