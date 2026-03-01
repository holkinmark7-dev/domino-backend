"""
test_phase_aware_tone.py — DAY 3.4 Phase-Aware Response Tone v1

8 tests:
  T1  initial    — no prefix injected
  T2  worsening  — prefix "Есть признаки ухудшения состояния."
  T3  progressing— prefix "Состояние требует дополнительного внимания."
  T4  stable     — prefix "Динамика без ухудшения."
  T5  improving  — prefix "Есть признаки улучшения состояния."
  T6  escalation unchanged — get_phase_prefix is pure, never mutates decision
  T7  contract unchanged  — llm_contract structure identical regardless of phase
  T8  guard unaffected    — count_questions still works on prefixed prompts

No Supabase / HTTP calls.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

from routers.services.response_templates import get_phase_prefix
import routers.services.ai as ai_module
from routers.services.ai import generate_ai_response
from routers.chat import count_questions


# ═════════════════════════════════════════════════════════════════════════════
# Section 1 — get_phase_prefix() unit tests (T1–T5)
# ═════════════════════════════════════════════════════════════════════════════

class TestGetPhasePrefix(unittest.TestCase):

    # T1: initial → empty string (no prefix)
    def test_initial_returns_empty_string(self):
        self.assertEqual(get_phase_prefix("initial"), "")

    # T2: worsening → correct Russian prefix
    def test_worsening_prefix(self):
        result = get_phase_prefix("worsening")
        self.assertTrue(result.startswith("Есть признаки ухудшения состояния."))

    # T3: progressing → correct Russian prefix
    def test_progressing_prefix(self):
        result = get_phase_prefix("progressing")
        self.assertTrue(result.startswith("Состояние требует дополнительного внимания."))

    # T4: stable → correct Russian prefix
    def test_stable_prefix(self):
        result = get_phase_prefix("stable")
        self.assertTrue(result.startswith("Динамика без ухудшения."))

    # T5: improving → correct Russian prefix
    def test_improving_prefix(self):
        result = get_phase_prefix("improving")
        self.assertTrue(result.startswith("Есть признаки улучшения состояния."))

    # Edge: unknown phase → empty string (no crash, no noise)
    def test_unknown_phase_returns_empty(self):
        self.assertEqual(get_phase_prefix("unknown_xyz"), "")

    # Edge: None → empty string
    def test_none_phase_returns_empty(self):
        self.assertEqual(get_phase_prefix(None), "")


# ═════════════════════════════════════════════════════════════════════════════
# Section 2 — Integration: prefix injected into deterministic_prompt (T2 variant)
# ═════════════════════════════════════════════════════════════════════════════

def _call_generate_with_phase(episode_phase: str):
    """
    Call generate_ai_response with a clinical_decision that has the given
    episode_phase. Captures the user_prompt sent to the LLM.
    """
    captured = {}

    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "Тестовый ответ."
        return mock_resp

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    clinical_decision = {
        "symptom": "vomiting",
        "escalation": "MODERATE",
        "response_type": "CLARIFY",
        "episode_phase": episode_phase,
        "stats": {"today": 2, "last_hour": 1, "last_24h": 2},
        "stop_questioning": False,
        "override_urgency": False,
        "reaction_type": "normal_progress",
        "user_intent": "NEUTRAL",
        "constraint": "none",
    }

    llm_contract = {
        "risk_level": "MODERATE",
        "response_type": "CLARIFY",
        "episode_phase": episode_phase,
        "known_facts": {"symptom": "vomiting"},
        "allowed_questions": ["blood", "refusing_water"],
        "max_questions": 2,
    }

    with patch.object(ai_module, "client", mock_client):
        generate_ai_response(
            pet_profile={"name": "Бони", "species": "dog", "breed": "beagle", "birth_date": "2020-01-01"},
            recent_events=[],
            user_message="Рвота снова",
            urgency_score=2,
            risk_level="moderate",
            clinical_decision=clinical_decision,
            llm_contract=llm_contract,
        )

    user_prompt = captured["messages"][1]["content"] if len(captured.get("messages", [])) > 1 else ""
    return user_prompt, clinical_decision, llm_contract


class TestPhaseIntegration(unittest.TestCase):

    # T6: escalation is never mutated by get_phase_prefix
    def test_escalation_unchanged_after_phase_prefix(self):
        """
        get_phase_prefix is a pure function. Calling it must never
        alter the decision dict — escalation stays MODERATE.
        """
        decision = {"escalation": "MODERATE", "episode_phase": "worsening"}
        _ = get_phase_prefix(decision.get("episode_phase"))
        self.assertEqual(decision["escalation"], "MODERATE")

    # T7: llm_contract structure is identical regardless of phase
    def test_contract_structure_unchanged_by_phase(self):
        """
        The llm_contract dict passed to generate_ai_response must have
        the same keys regardless of episode_phase value.
        """
        _, _, contract_initial = _call_generate_with_phase("initial")
        _, _, contract_worsening = _call_generate_with_phase("worsening")

        self.assertEqual(set(contract_initial.keys()), set(contract_worsening.keys()))
        self.assertEqual(contract_initial["risk_level"], contract_worsening["risk_level"])
        self.assertEqual(contract_initial["response_type"], contract_worsening["response_type"])
        self.assertEqual(contract_initial["max_questions"], contract_worsening["max_questions"])

    # T8: guard (count_questions) works correctly on a prefixed prompt
    def test_guard_unaffected_by_phase_prefix(self):
        """
        A phase prefix like "Динамика без ухудшения.\n\n" contains no '?',
        so it must not affect the question count.
        """
        prefix = get_phase_prefix("stable")     # "Динамика без ухудшения.\n\n"
        template_body = "Уточните: есть ли рвота? Пьёт ли воду?"  # 2 questions
        full_text = prefix + template_body

        # guard counts questions in the full text
        self.assertEqual(count_questions(full_text), 2)
        # prefix itself adds zero questions
        self.assertEqual(count_questions(prefix), 0)

    # Bonus: worsening phase prefix appears in the user_prompt sent to LLM
    def test_worsening_prefix_in_user_prompt(self):
        user_prompt, _, _ = _call_generate_with_phase("worsening")
        self.assertIn("Есть признаки ухудшения состояния.", user_prompt)

    # Bonus: initial phase produces no prefix in user_prompt
    def test_initial_phase_no_prefix_in_user_prompt(self):
        user_prompt, _, _ = _call_generate_with_phase("initial")
        self.assertNotIn("Есть признаки ухудшения", user_prompt)
        self.assertNotIn("Динамика без ухудшения", user_prompt)
        self.assertNotIn("Состояние требует дополнительного", user_prompt)
        self.assertNotIn("Есть признаки улучшения", user_prompt)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestGetPhasePrefix))
    suite.addTests(loader.loadTestsFromTestCase(TestPhaseIntegration))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
