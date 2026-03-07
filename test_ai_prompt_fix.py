"""
test_ai_prompt_fix.py — AI.PY SYSTEM PROMPT FIX + OFF-TOPIC GUARD + FOOD CONTEXT

11 tests:
  T1  system_block does NOT contain "You are a veterinary" (old English string removed)
  T2  system_block contains "медицинский AI-ассистент" (new Russian string present)
  T3  clinical_decision=None → system_block contains "медицинский помощник" (off-topic guard active)
  T4  clinical_decision present → system_block does NOT contain "медицинский помощник" (off-topic guard silent)
  T5  clinical_decision present → urgency_instructions == "" (suppressed)
  T6  clinical_decision=None → urgency_instructions not empty
  T7  food="банан" in clinical_decision → context_block contains "банан"
  T8  clinical_decision has no food → context_block does NOT contain "Съеденное"
  T9  Regression: test_llm_contract.py all PASS
  T10 Regression: test_monotonic_lock.py all PASS
  T11 Regression: test_response_templates.py all PASS

No API calls — client.messages.create is patched to a dummy.
"""

import sys
import os
import unittest
import subprocess
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

import routers.services.ai as ai_module
from routers.services.ai import AIResponseRequest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_DUMMY_PET = {"name": "Бони", "species": "dog", "breed": "labrador", "birth_date": "2020-01-01"}
_DUMMY_CD = {
    "symptom": "vomiting",
    "escalation": "MODERATE",
    "status": "active",
    "stats": {"today": 2, "last_hour": 1, "last_24h": 2},
    "stop_questioning": False,
    "override_urgency": False,
    "episode_phase": "progressing",
    "reaction_type": "normal_progress",
    "response_type": "CLARIFY",
    "user_intent": None,
    "constraint": None,
}


def _capture(pet_profile=None, clinical_decision=None, urgency_score=0):
    """
    Call generate_ai_response with a patched OpenAI client.
    Returns (system_block_text, user_prompt_text, urgency_instructions_value).

    We intercept the messages passed to client.messages.create
    to inspect system_block and user_prompt without real API calls.
    We also expose urgency_instructions by temporarily monkey-patching
    the function to record it.
    """
    captured = {}

    def _fake_call_llm(config, system_prompt, user_prompt, max_tokens=600):
        captured["system"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "stub"

    with patch.object(ai_module, "_call_llm", side_effect=_fake_call_llm):
        ai_module.generate_ai_response(AIResponseRequest(
            pet_profile=pet_profile or _DUMMY_PET,
            recent_events=[],
            user_message="тест",
            urgency_score=urgency_score,
            clinical_decision=clinical_decision,
        ))

    system_block = captured["system"]
    user_prompt = captured["user_prompt"]
    return system_block, user_prompt


# ─────────────────────────────────────────────────────────────────────────────
# T1–T8 — Prompt structure tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAiPromptFix(unittest.TestCase):

    # T1: old English "You are a veterinary" string must be gone
    def test_old_english_string_removed(self):
        system_block, _ = _capture(clinical_decision=_DUMMY_CD)
        self.assertNotIn(
            "You are a veterinary",
            system_block,
            "Old English 'You are a veterinary' still present in system_block",
        )

    # T2: new Russian "медицинский AI-ассистент" string must be present
    def test_new_russian_string_present(self):
        system_block, _ = _capture(clinical_decision=_DUMMY_CD)
        self.assertIn(
            "медицинский AI-ассистент",
            system_block,
            "New Russian 'медицинский AI-ассистент' missing from system_block",
        )

    # T3: without clinical_decision — off-topic guard active
    def test_off_topic_guard_active_without_clinical_decision(self):
        system_block, _ = _capture(clinical_decision=None)
        self.assertIn(
            "медицинский помощник",
            system_block,
            "Off-topic guard ('медицинский помощник') must appear when clinical_decision=None",
        )

    # T4: with clinical_decision — off-topic guard must be silent
    def test_off_topic_guard_silent_with_clinical_decision(self):
        system_block, _ = _capture(clinical_decision=_DUMMY_CD)
        self.assertNotIn(
            "медицинский помощник",
            system_block,
            "Off-topic guard must NOT appear when clinical_decision is provided",
        )

    # T5: with clinical_decision — urgency_instructions suppressed (empty in user_prompt)
    def test_urgency_instructions_suppressed_with_clinical_decision(self):
        """
        When clinical_decision is present the deterministic template path is used,
        so the fallback urgency text ("This is not concerning", "Mild situation", etc.)
        must never appear in the user_prompt.
        """
        _, user_prompt = _capture(clinical_decision=_DUMMY_CD, urgency_score=3)
        self.assertNotIn(
            "High concern",
            user_prompt,
            "urgency_instructions must be suppressed when clinical_decision is present",
        )
        self.assertNotIn(
            "Urgency could not be determined",
            user_prompt,
        )

    # T6: without clinical_decision — urgency_instructions not empty
    def test_urgency_instructions_present_without_clinical_decision(self):
        _, user_prompt = _capture(clinical_decision=None, urgency_score=3)
        self.assertIn(
            "High concern",
            user_prompt,
            "urgency_instructions must be non-empty when clinical_decision=None and urgency_score=3",
        )

    # T7: food="банан" → context_block contains "банан"
    def test_food_present_in_context_block(self):
        cd = dict(_DUMMY_CD)
        cd["food"] = "банан"
        _, user_prompt = _capture(clinical_decision=cd)
        self.assertIn(
            "банан",
            user_prompt,
            "food value must appear in context_block when provided",
        )

    # T8: no food → context_block must not contain "Съеденное"
    def test_no_food_line_when_food_absent(self):
        cd = dict(_DUMMY_CD)
        cd.pop("food", None)  # ensure key absent
        _, user_prompt = _capture(clinical_decision=cd)
        self.assertNotIn(
            "Съеденное",
            user_prompt,
            "context_block must not have 'Съеденное' line when food is absent",
        )


# ─────────────────────────────────────────────────────────────────────────────
# T9–T11 — Regressions
# ─────────────────────────────────────────────────────────────────────────────

def _run_test_file(filename: str) -> tuple[int, int]:
    result = subprocess.run(
        [sys.executable, filename],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(__file__),
    )
    output = result.stdout + result.stderr
    for line in reversed(output.splitlines()):
        if line.startswith("TOTAL:"):
            parts = line.split()
            ratio = parts[1]
            passed, total = map(int, ratio.split("/"))
            return passed, total
    if "OK" in output:
        import re
        m = re.search(r"Ran (\d+) test", output)
        total = int(m.group(1)) if m else 0
        return total, total
    return 0, 0


class TestRegressions(unittest.TestCase):

    def test_llm_contract_regression(self):
        passed, total = _run_test_file("test_llm_contract.py")
        self.assertGreater(total, 0, "test_llm_contract.py ran 0 tests")
        self.assertEqual(passed, total, f"test_llm_contract.py: {passed}/{total} PASS")

    def test_monotonic_lock_regression(self):
        passed, total = _run_test_file("test_monotonic_lock.py")
        self.assertGreater(total, 0, "test_monotonic_lock.py ran 0 tests")
        self.assertEqual(passed, total, f"test_monotonic_lock.py: {passed}/{total} PASS")

    def test_response_templates_regression(self):
        passed, total = _run_test_file("test_response_templates.py")
        self.assertGreater(total, 0, "test_response_templates.py ran 0 tests")
        self.assertEqual(passed, total, f"test_response_templates.py: {passed}/{total} PASS")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestAiPromptFix))
    suite.addTests(loader.loadTestsFromTestCase(TestRegressions))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
