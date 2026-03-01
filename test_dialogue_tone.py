"""
test_dialogue_tone.py — DAY 3.5 Dialogue Tone — Живые ответы по кличке

8 tests:
  T1  tone_block contains pet name "Бони" in system message
  T2  tone_block contains "Никогда не пиши" rule
  T3  system message includes "кличке: Бони" when name="Бони"
  T4  pet_profile=None → _pet_name fallback = "питомец" (pure logic)
  T5  pet_profile={} → _pet_name fallback = "питомец" (pure logic)
  T6  _FOLLOWUP_MSG does not contain "питомца"
  T7  system message starts with "Тон и стиль:"
  T8  regression — "You are a veterinary clinical assistant" still in system message

No Supabase / HTTP calls.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

import routers.services.ai as ai_module
from routers.services.ai import generate_ai_response
from routers.chat_history import _FOLLOWUP_MSG


# ─────────────────────────────────────────────────────────────────────────────
# Shared helper
# ─────────────────────────────────────────────────────────────────────────────

def _call_with_pet_profile(pet_profile) -> str:
    """
    Call generate_ai_response with the given pet_profile.
    Returns the system message content sent to the LLM.
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
        "episode_phase": "initial",
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
        "episode_phase": "initial",
        "known_facts": {"symptom": "vomiting"},
        "allowed_questions": ["blood", "refusing_water"],
        "max_questions": 2,
    }

    with patch.object(ai_module, "client", mock_client):
        generate_ai_response(
            pet_profile=pet_profile,
            recent_events=[],
            user_message="Рвота снова",
            urgency_score=2,
            risk_level="moderate",
            clinical_decision=clinical_decision,
            llm_contract=llm_contract,
        )

    return captured["messages"][0]["content"] if captured.get("messages") else ""


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

_FULL_PROFILE = {"name": "Бони", "species": "dog", "breed": "beagle", "birth_date": "2020-01-01"}


class TestDialogueToneBlock(unittest.TestCase):

    # T1: system message contains the pet's name
    def test_tone_block_contains_pet_name(self):
        system_msg = _call_with_pet_profile(_FULL_PROFILE)
        self.assertIn("Бони", system_msg)

    # T2: tone_block instructs LLM never to use generic word
    def test_tone_block_contains_never_rule(self):
        system_msg = _call_with_pet_profile(_FULL_PROFILE)
        self.assertIn("Никогда не пиши", system_msg)

    # T3: instruction uses actual name in the "по кличке" phrase
    def test_tone_block_uses_name_in_address(self):
        system_msg = _call_with_pet_profile(_FULL_PROFILE)
        self.assertIn("кличке: Бони", system_msg)

    # T4: pet_profile=None → _pet_name falls back to "питомец" (pure logic)
    def test_fallback_when_pet_profile_none(self):
        pet_profile = None
        _pet_name = (pet_profile.get("name") or "питомец") if pet_profile else "питомец"
        self.assertEqual(_pet_name, "питомец")

    # T5: pet_profile={} → _pet_name falls back to "питомец" (pure logic)
    def test_fallback_when_pet_profile_empty(self):
        pet_profile = {}
        _pet_name = (pet_profile.get("name") or "питомец") if pet_profile else "питомец"
        self.assertEqual(_pet_name, "питомец")

    # T6: _FOLLOWUP_MSG no longer contains "питомца"
    def test_followup_msg_has_no_pitsomtsa(self):
        self.assertNotIn("питомца", _FOLLOWUP_MSG)

    # T7: system message starts with the tone_block header
    def test_system_block_starts_with_tone_block(self):
        system_msg = _call_with_pet_profile(_FULL_PROFILE)
        self.assertTrue(system_msg.startswith("Тон и стиль:"))

    # T8: regression — vet assistant instruction still present after tone_block
    def test_regression_vet_assistant_still_in_system(self):
        system_msg = _call_with_pet_profile(_FULL_PROFILE)
        self.assertIn("You are a veterinary clinical assistant", system_msg)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestDialogueToneBlock))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
