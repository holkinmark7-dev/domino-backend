"""
tests/test_anti_redundancy.py — ANTI-REDUNDANCY GUARD in ai.py

5 tests:
  T1  previous_assistant_text present → "АНТИ-ПОВТОР" in system_block
  T2  previous_assistant_text=None   → "АНТИ-ПОВТОР" NOT in system_block
  T3  _redundancy_block contains first 300 chars of previous_assistant_text
  T4  _redundancy_block appears after _off_topic_block and before main Russian text
  T5  Regression: full suite (test_ai_prompt_fix.py) all PASS

No API calls — client.messages.create is patched to a dummy.
"""

import sys
import os
import unittest
import subprocess
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import routers.services.ai as ai_module
from routers.services.ai import AIResponseRequest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_DUMMY_PET = {
    "name": "Бони",
    "species": "dog",
    "breed": "labrador",
    "birth_date": "2020-01-01",
}

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


def _capture(
    pet_profile=None,
    clinical_decision=None,
    urgency_score=0,
    previous_assistant_text=None,
):
    """
    Call generate_ai_response with a patched OpenAI client.
    Returns system_block (str).
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
            previous_assistant_text=previous_assistant_text,
        ))

    system_block = captured["system"]
    return system_block


# ─────────────────────────────────────────────────────────────────────────────
# T1–T4 — Anti-redundancy guard tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAntiRedundancy(unittest.TestCase):

    # T1: previous_assistant_text present → "АНТИ-ПОВТОР" in system_block
    def test_redundancy_block_present_when_previous_text_given(self):
        system_block = _capture(
            clinical_decision=_DUMMY_CD,
            previous_assistant_text="Рвота у Бони продолжается. Ограничьте корм на 8 часов.",
        )
        self.assertIn(
            "АНТИ-ПОВТОР",
            system_block,
            "_redundancy_block must appear in system_block when previous_assistant_text is provided",
        )

    # T2: previous_assistant_text=None → "АНТИ-ПОВТОР" NOT in system_block
    def test_redundancy_block_absent_when_no_previous_text(self):
        system_block = _capture(
            clinical_decision=_DUMMY_CD,
            previous_assistant_text=None,
        )
        self.assertNotIn(
            "АНТИ-ПОВТОР",
            system_block,
            "_redundancy_block must NOT appear when previous_assistant_text=None",
        )

    # T3: _redundancy_block contains first 300 chars of previous_assistant_text
    def test_redundancy_block_contains_first_300_chars(self):
        long_text = "А" * 400  # 400 identical chars
        system_block = _capture(
            clinical_decision=_DUMMY_CD,
            previous_assistant_text=long_text,
        )
        first_300 = long_text[:300]
        self.assertIn(
            first_300,
            system_block,
            "system_block must contain the first 300 chars of previous_assistant_text",
        )
        # Ensure the 301st char is NOT included
        self.assertNotIn(
            long_text[:301],
            system_block,
            "system_block must NOT contain more than 300 chars of previous_assistant_text",
        )

    # T4: _redundancy_block appears AFTER _off_topic_block and BEFORE main Russian text
    def test_redundancy_block_position(self):
        """
        Without clinical_decision: _off_topic_block is present (contains "медицинский помощник").
        _redundancy_block must come AFTER "медицинский помощник" and BEFORE
        "медицинский AI-ассистент".
        """
        system_block = _capture(
            clinical_decision=None,
            previous_assistant_text="Это предыдущий ответ.",
        )
        redundancy_pos = system_block.find("АНТИ-ПОВТОР")
        off_topic_pos = system_block.find("медицинский помощник")
        main_pos = system_block.find("медицинский AI-ассистент")

        self.assertGreater(
            redundancy_pos,
            off_topic_pos,
            "_redundancy_block must appear AFTER _off_topic_block",
        )
        self.assertLess(
            redundancy_pos,
            main_pos,
            "_redundancy_block must appear BEFORE the main 'медицинский AI-ассистент' line",
        )


# ─────────────────────────────────────────────────────────────────────────────
# T5 — Regression
# ─────────────────────────────────────────────────────────────────────────────

def _run_test_file(filename: str) -> tuple[int, int]:
    result = subprocess.run(
        [sys.executable, filename],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(__file__)),
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

    def test_ai_prompt_fix_regression(self):
        passed, total = _run_test_file("test_ai_prompt_fix.py")
        self.assertGreater(total, 0, "test_ai_prompt_fix.py ran 0 tests")
        self.assertEqual(passed, total, f"test_ai_prompt_fix.py: {passed}/{total} PASS")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestAntiRedundancy))
    suite.addTests(loader.loadTestsFromTestCase(TestRegressions))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
