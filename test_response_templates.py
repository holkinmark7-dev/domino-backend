"""
test_response_templates.py — Unit tests for DAY 2 Deterministic Template Selector
Tests: select_template() + integration with generate_ai_response()
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

from routers.services.response_templates import select_template
import routers.services.ai as ai_module
from routers.services.ai import generate_ai_response, AIResponseRequest


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_decision(response_type="ASSESS", symptom="vomiting", today=2):
    return {
        "symptom": symptom,
        "escalation": "MODERATE",
        "response_type": response_type,
        "stats": {"today": today, "last_hour": 1},
        "stop_questioning": False,
        "override_urgency": False,
        "episode_phase": "ongoing",
        "reaction_type": "normal_progress",
        "user_intent": None,
        "constraint": None,
        "consecutive_escalations": 0,
        "consecutive_critical": 0,
    }


def _call_generate_and_capture(decision, llm_contract=None):
    """Call generate_ai_response with mock _call_llm; return (user_prompt_sent, ai_response)."""
    captured = {}

    def _fake_call_llm(config, system_prompt, user_prompt, max_tokens=600):
        captured["system"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "Тестовый детерминированный ответ."

    with patch.object(ai_module, "_call_llm", side_effect=_fake_call_llm):
        result = generate_ai_response(AIResponseRequest(
            pet_profile={"name": "Бони", "species": "dog", "breed": "beagle", "birth_date": "2020-01-01"},
            recent_events=[],
            user_message="У питомца рвота",
            urgency_score=2,
            risk_level="moderate",
            memory_context="No prior medical history.",
            clinical_decision=decision,
            dialogue_mode="clinical_escalation",
            previous_assistant_text=None,
            strict_override=None,
            llm_contract=llm_contract,
        ))

    user_prompt = captured.get("user_prompt", "")
    return user_prompt, result


# ═════════════════════════════════════════════════════════════════════════════
# Section 1 — select_template() pure unit tests
# ═════════════════════════════════════════════════════════════════════════════

class TestSelectTemplate(unittest.TestCase):

    # T1: ACTION template contains "Действия:"
    def test_action_template_contains_actions_block(self):
        tmpl = select_template("ACTION")
        self.assertIn("Действия:", tmpl)
        self.assertIn("{actions_block}", tmpl)

    # T2: CLARIFY template contains questions_block placeholder
    def test_clarify_template_contains_questions_block(self):
        tmpl = select_template("CLARIFY")
        self.assertIn("Уточните:", tmpl)
        self.assertIn("{questions_block}", tmpl)

    # T3: ASSESS fallback for unknown response_type
    def test_unknown_type_falls_back_to_assess(self):
        tmpl = select_template("UNKNOWN_TYPE_XYZ")
        assess_tmpl = select_template("ASSESS")
        self.assertEqual(tmpl, assess_tmpl)

    # T4: ASSESS template has symptom placeholder
    def test_assess_template_has_symptom(self):
        tmpl = select_template("ASSESS")
        self.assertIn("{symptom}", tmpl)

    # T5: ACTION_HOME_PROTOCOL has actions_block but no episodes_today
    def test_action_home_protocol_no_episodes_today(self):
        tmpl = select_template("ACTION_HOME_PROTOCOL")
        self.assertIn("{actions_block}", tmpl)
        self.assertNotIn("{episodes_today}", tmpl)

    # T6: URGENT_GUIDANCE available
    def test_urgent_guidance_template_exists(self):
        tmpl = select_template("URGENT_GUIDANCE")
        self.assertIn("Уточните:", tmpl)

    # T7: None falls back to ASSESS (not exception)
    def test_none_type_falls_back_to_assess(self):
        tmpl = select_template(None)
        assess_tmpl = select_template("ASSESS")
        self.assertEqual(tmpl, assess_tmpl)

    # T8: returns str
    def test_returns_string(self):
        self.assertIsInstance(select_template("ACTION"), str)
        self.assertIsInstance(select_template("ASSESS"), str)


# ═════════════════════════════════════════════════════════════════════════════
# Section 2 — Integration: deterministic prompt injected into generate_ai_response
# ═════════════════════════════════════════════════════════════════════════════

class TestDeterministicPromptInjection(unittest.TestCase):

    # T1: ACTION → "Действия:" appears in user_prompt sent to OpenAI
    def test_action_user_prompt_contains_actions(self):
        decision = _make_decision(response_type="ACTION")
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("Действия:", user_prompt)

    # T2: CLARIFY + allowed_questions → "- Есть ли vomiting?" in prompt
    def test_clarify_prompt_contains_allowed_question(self):
        decision = _make_decision(response_type="CLARIFY")
        contract = {
            "risk_level": "MODERATE",
            "response_type": "CLARIFY",
            "episode_phase": "ongoing",
            "known_facts": {},
            "allowed_questions": ["vomiting"],
            "max_questions": 2,
        }
        user_prompt, _ = _call_generate_and_capture(decision, llm_contract=contract)
        self.assertIn("Есть ли vomiting?", user_prompt)

    # T3: ASSESS fallback — unknown response_type still gets ASSESS template
    def test_assess_fallback_in_prompt(self):
        decision = _make_decision(response_type="WEIRD_TYPE")
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("Кратко опишите", user_prompt)

    # T4: symptom name appears in the prompt
    def test_symptom_in_prompt(self):
        decision = _make_decision(response_type="CLARIFY", symptom="diarrhea")
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("diarrhea", user_prompt)

    # T5: episodes_today value appears in CLARIFY prompt
    def test_episodes_today_in_clarify_prompt(self):
        decision = _make_decision(response_type="CLARIFY", today=5)
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("5", user_prompt)

    # T6: Without clinical_decision → original free-form prompt used (contains "Профиль")
    def test_no_decision_uses_freeform_prompt(self):
        captured = {}

        def _fake_call_llm(config, system_prompt, user_prompt, max_tokens=600):
            captured["system"] = system_prompt
            captured["user_prompt"] = user_prompt
            return "ok"

        with patch.object(ai_module, "_call_llm", side_effect=_fake_call_llm):
            generate_ai_response(AIResponseRequest(
                pet_profile={"name": "X", "species": "dog", "breed": "lab", "birth_date": "2020-01-01"},
                recent_events=[],
                user_message="test",
                clinical_decision=None,
            ))

        user_prompt = captured["user_prompt"]
        self.assertIn("Профиль", user_prompt)

    # T7: With clinical_decision → deterministic prompt replaces freeform (no "Профиль")
    def test_with_decision_no_freeform_content(self):
        decision = _make_decision(response_type="ACTION")
        user_prompt, _ = _call_generate_and_capture(decision)
        # The freeform header is NOT in the deterministic prompt
        self.assertNotIn("Профиль", user_prompt)
        self.assertNotIn("Medical history:", user_prompt)

    # T8: Multiple allowed_questions all appear as bullet items
    def test_multiple_allowed_questions_in_prompt(self):
        decision = _make_decision(response_type="CLARIFY")
        contract = {
            "risk_level": "MODERATE",
            "response_type": "CLARIFY",
            "episode_phase": "initial",
            "known_facts": {},
            "allowed_questions": ["vomiting", "drinking"],
            "max_questions": 2,
        }
        user_prompt, _ = _call_generate_and_capture(decision, llm_contract=contract)
        self.assertIn("Есть ли vomiting?", user_prompt)
        self.assertIn("Есть ли drinking?", user_prompt)

    # T9: No allowed_questions → fallback placeholder present
    def test_no_allowed_questions_shows_placeholder(self):
        decision = _make_decision(response_type="CLARIFY")
        contract = {
            "risk_level": "LOW",
            "response_type": "CLARIFY",
            "episode_phase": "initial",
            "known_facts": {},
            "allowed_questions": [],
            "max_questions": 0,
        }
        user_prompt, _ = _call_generate_and_capture(decision, llm_contract=contract)
        self.assertIn("(нет уточняющих вопросов)", user_prompt)


# ═════════════════════════════════════════════════════════════════════════════
# Section 3 — Smoke test: Бони, MODERATE + CLARIFY
# ═════════════════════════════════════════════════════════════════════════════

class TestSmokeTemplateBonya(unittest.TestCase):

    def setUp(self):
        self.decision = _make_decision(
            response_type="CLARIFY",
            symptom="diarrhea",
            today=3,
        )
        self.contract = {
            "risk_level": "MODERATE",
            "response_type": "CLARIFY",
            "episode_phase": "ongoing",
            "known_facts": {
                "symptom": "diarrhea",
                "blood": False,
                "refusing_water": False,
            },
            "allowed_questions": ["vomiting"],
            "max_questions": 2,
        }

    def test_smoke_prompt_is_template_not_freeform(self):
        user_prompt, _ = _call_generate_and_capture(self.decision, self.contract)
        # Template header present
        self.assertIn("Уточните:", user_prompt)
        # No freeform fields
        self.assertNotIn("Medical history:", user_prompt)

    def test_smoke_symptom_in_prompt(self):
        user_prompt, _ = _call_generate_and_capture(self.decision, self.contract)
        self.assertIn("diarrhea", user_prompt)

    def test_smoke_allowed_question_in_prompt(self):
        user_prompt, _ = _call_generate_and_capture(self.decision, self.contract)
        self.assertIn("Есть ли vomiting?", user_prompt)

    def test_smoke_episodes_today_in_prompt(self):
        user_prompt, _ = _call_generate_and_capture(self.decision, self.contract)
        self.assertIn("3", user_prompt)

    def test_smoke_result_string(self):
        _, result = _call_generate_and_capture(self.decision, self.contract)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


# ═════════════════════════════════════════════════════════════════════════════
# Section 4 — Controlled Context Block (DAY 2.1)
# ═════════════════════════════════════════════════════════════════════════════

def _make_decision_full(
    response_type="CLARIFY",
    symptom="vomiting",
    today=2,
    episode_phase="ongoing",
    reaction_type="normal_progress",
    user_intent=None,
    constraint=None,
):
    """Extended decision with all context fields."""
    return {
        "symptom": symptom,
        "escalation": "MODERATE",
        "response_type": response_type,
        "stats": {"today": today, "last_hour": 1},
        "stop_questioning": False,
        "override_urgency": False,
        "episode_phase": episode_phase,
        "reaction_type": reaction_type,
        "user_intent": user_intent,
        "constraint": constraint,
        "consecutive_escalations": 0,
        "consecutive_critical": 0,
    }


class TestControlledContextBlock(unittest.TestCase):

    # T1: Context injection — prompt contains all 4 Контекст fields
    def test_context_block_present_in_prompt(self):
        decision = _make_decision_full(response_type="CLARIFY", episode_phase="ongoing")
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("Контекст:", user_prompt)
        self.assertIn("Фаза эпизода:", user_prompt)
        self.assertIn("Тип реакции:", user_prompt)
        self.assertIn("Намерение пользователя:", user_prompt)
        self.assertIn("Ограничения:", user_prompt)

    # T2: Constraint propagation
    def test_constraint_in_prompt(self):
        decision = _make_decision_full(constraint="no_vet_access")
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("Ограничения: no_vet_access", user_prompt)

    # T3: reaction_type propagation
    def test_reaction_type_in_prompt(self):
        decision = _make_decision_full(reaction_type="panic")
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("Тип реакции: panic", user_prompt)

    # T4: episode_phase value in prompt
    def test_episode_phase_in_prompt(self):
        decision = _make_decision_full(episode_phase="prolonged")
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("Фаза эпизода: prolonged", user_prompt)

    # T5: user_intent propagation
    def test_user_intent_in_prompt(self):
        decision = _make_decision_full(user_intent="seeking_reassurance")
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("Намерение пользователя: seeking_reassurance", user_prompt)

    # T6: memory_context NOT in prompt (strictly excluded)
    def test_memory_context_not_in_prompt(self):
        decision = _make_decision_full()
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertNotIn("Medical history:", user_prompt)
        self.assertNotIn("No prior medical history", user_prompt)

    # T7: recent_events NOT in prompt
    def test_recent_events_not_in_prompt(self):
        decision = _make_decision_full()
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertNotIn("Recent events:", user_prompt)

    # T8: template part + context part both present in final prompt
    def test_template_and_context_both_in_prompt(self):
        decision = _make_decision_full(response_type="CLARIFY", episode_phase="initial")
        user_prompt, _ = _call_generate_and_capture(decision)
        # Template part
        self.assertIn("Уточните:", user_prompt)
        # Context part
        self.assertIn("Контекст:", user_prompt)

    # Smoke: Бони, CLARIFY + ongoing — template + context, no memory
    def test_smoke_bonya_clarify_ongoing(self):
        decision = _make_decision_full(
            response_type="CLARIFY",
            symptom="diarrhea",
            today=3,
            episode_phase="ongoing",
            reaction_type="normal_progress",
        )
        contract = {
            "risk_level": "MODERATE",
            "response_type": "CLARIFY",
            "episode_phase": "ongoing",
            "known_facts": {"symptom": "diarrhea", "blood": False},
            "allowed_questions": ["vomiting"],
            "max_questions": 2,
        }
        user_prompt, _ = _call_generate_and_capture(decision, llm_contract=contract)
        # Template part
        self.assertIn("Уточните:", user_prompt)
        self.assertIn("diarrhea", user_prompt)
        self.assertIn("Есть ли vomiting?", user_prompt)
        # Context part
        self.assertIn("Фаза эпизода: ongoing", user_prompt)
        self.assertIn("Тип реакции: normal_progress", user_prompt)
        # Excluded
        self.assertNotIn("Medical history:", user_prompt)
        self.assertNotIn("Recent events:", user_prompt)


# ═════════════════════════════════════════════════════════════════════════════
# Section 5 — Clean Context Normalization (DAY 2.2)
# ═════════════════════════════════════════════════════════════════════════════

class TestCleanContextNormalization(unittest.TestCase):

    # T1: None value → "-" in prompt
    def test_none_value_replaced_with_dash(self):
        decision = _make_decision_full(user_intent=None)
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("Намерение пользователя: -", user_prompt)

    # T2: Empty string value → "-" in prompt
    def test_empty_string_replaced_with_dash(self):
        decision = _make_decision_full(constraint="")
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("Ограничения: -", user_prompt)

    # T3: Whitespace-only string → "-" in prompt
    def test_whitespace_only_replaced_with_dash(self):
        decision = _make_decision_full(reaction_type="   ")
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("Тип реакции: -", user_prompt)

    # T4: Valid value preserved as-is
    def test_valid_value_preserved(self):
        decision = _make_decision_full(episode_phase="ongoing", constraint="no_vet_access")
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("Фаза эпизода: ongoing", user_prompt)
        self.assertIn("Ограничения: no_vet_access", user_prompt)

    # T5: Smoke — "None" string never appears in prompt
    def test_none_string_never_in_prompt(self):
        decision = _make_decision_full(
            episode_phase=None,
            reaction_type=None,
            user_intent=None,
            constraint=None,
        )
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertNotIn("None", user_prompt)

    # T6: All 4 fields produce "-" when all None
    def test_all_none_fields_produce_dashes(self):
        decision = _make_decision_full(
            episode_phase=None,
            reaction_type=None,
            user_intent=None,
            constraint=None,
        )
        user_prompt, _ = _call_generate_and_capture(decision)
        self.assertIn("Фаза эпизода: -", user_prompt)
        self.assertIn("Тип реакции: -", user_prompt)
        self.assertIn("Намерение пользователя: -", user_prompt)
        self.assertIn("Ограничения: -", user_prompt)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestSelectTemplate))
    suite.addTests(loader.loadTestsFromTestCase(TestDeterministicPromptInjection))
    suite.addTests(loader.loadTestsFromTestCase(TestSmokeTemplateBonya))
    suite.addTests(loader.loadTestsFromTestCase(TestControlledContextBlock))
    suite.addTests(loader.loadTestsFromTestCase(TestCleanContextNormalization))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-'*60}")
    print(f"TOTAL: {passed}/{total} PASS")
