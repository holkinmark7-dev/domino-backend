"""
tests/test_routing_modes.py — 3-MODE AI ROUTING (CASUAL / PROFILE / CLINICAL)

19 tests:
  T01  _classify_message_mode: no-symptom dict + greeting → "CASUAL"
  T02  CASUAL mode: system_block NOT contains "медицинский ИИ-ассистент"
  T03  CASUAL mode: system_block NOT contains "АНТИ-ПОВТОР"
  T04  CASUAL mode: user_prompt == "Сообщение: <msg>", NOT "Medical history"
  T05  CASUAL via pipeline: no "debug" in result
  T06  _classify_message_mode: "чем кормить лабрадора" → "PROFILE"
  T07  _classify_message_mode: "как часто купать собаку" → "PROFILE"
  T08  PROFILE mode: system_block contains "помощник по уходу", NOT "медицинский ИИ-ассистент"
  T09  PROFILE mode: user_prompt contains pet name + species
  T10  PROFILE via pipeline: no "debug" in result
  T11  _classify_message_mode: symptom="vomiting" → "CLINICAL"
  T12  CLINICAL mode: system_block contains "медицинский ИИ-ассистент"
  T13  CLINICAL via pipeline: "debug" in result
  T14  CLINICAL + clinical_decision: deterministic template applied (symptom in user_prompt)
  T15  CLINICAL + clinical_decision + memory_context: "История болезней" in user_prompt
  T16  symptom="vomiting" + lifestyle keyword → "CLINICAL" (symptom wins)
  T17  extraction error → "CASUAL"
  T18  empty message, no symptom → "CASUAL"
  T19  Regression: 185/185 PASS (previous test suite)

No real OpenAI / Supabase calls — all stubbed.
"""

import sys
import os
import json
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import routers.chat as chat_module
import routers.services.ai as ai_module
from routers.chat import _classify_message_mode
from schemas.chat import ChatMessage


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_USER_ID = "11111111-1111-1111-1111-111111111111"
_PET_ID  = "22222222-2222-2222-2222-222222222222"

_DUMMY_PET = {
    "name": "Бони",
    "species": "dog",
    "breed": "labrador",
    "birth_date": "2020-01-01",
}

_DUMMY_CD = {
    "symptom": "vomiting",
    "escalation": "MODERATE",
    "stats": {"today": 2, "last_hour": 1, "last_24h": 2},
    "stop_questioning": False,
    "override_urgency": False,
    "episode_phase": "progressing",
    "reaction_type": "normal_progress",
    "response_type": "CLARIFY",
    "user_intent": None,
    "constraint": None,
}


# ─────────────────────────────────────────────────────────────────────────────
# _capture_ai — test generate_ai_response directly (no pipeline)
# ─────────────────────────────────────────────────────────────────────────────

def _capture_ai(
    *,
    message_mode: str = "CLINICAL",
    clinical_decision=None,
    previous_assistant_text: str | None = None,
    memory_context: str = "No prior medical history.",
    user_message: str = "тест",
):
    """
    Call generate_ai_response with a patched OpenAI client.
    Returns (system_block, user_prompt).
    """
    captured = {}

    fake_choice = MagicMock()
    fake_choice.message.content = "stub"
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]

    def _fake_create(**kwargs):
        captured["messages"] = kwargs["messages"]
        return fake_response

    with patch.object(ai_module.client.chat.completions, "create", side_effect=_fake_create):
        ai_module.generate_ai_response(
            pet_profile=_DUMMY_PET,
            recent_events=[],
            user_message=user_message,
            urgency_score=0,
            clinical_decision=clinical_decision,
            previous_assistant_text=previous_assistant_text,
            memory_context=memory_context,
            message_mode=message_mode,
        )

    system_block = captured["messages"][0]["content"]
    user_prompt  = captured["messages"][1]["content"]
    return system_block, user_prompt


# ─────────────────────────────────────────────────────────────────────────────
# _stub_supabase + _call_create — test full pipeline (no real DB/AI)
# ─────────────────────────────────────────────────────────────────────────────

def _stub_supabase():
    sb = MagicMock()

    chat_insert_result = MagicMock()
    chat_insert_result.data = [{"id": "chat-mode-1"}]

    prev_ai_result = MagicMock()
    prev_ai_result.data = []

    _now_iso = datetime.now(timezone.utc).isoformat()
    ep_row_result = MagicMock()
    ep_row_result.data = {"started_at": _now_iso}

    def _table(name: str):
        m = MagicMock()
        if name == "chat":
            insert_r = MagicMock()
            insert_r.execute.return_value = chat_insert_result
            m.insert.return_value = insert_r
            sel = MagicMock()
            sel.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = prev_ai_result
            m.select.return_value = sel
        elif name == "episodes":
            sel = MagicMock()
            sel.eq.return_value.single.return_value.execute.return_value = ep_row_result
            m.select.return_value = sel
        return m

    sb.table.side_effect = _table
    return sb


def _call_create(
    message_text: str,
    *,
    extracted_symptom: str | None = None,
    extracted_symptom_class: str | None = None,
    stats_mock: dict | None = None,
    species: str = "dog",
) -> tuple[dict, dict]:
    """
    Call create_chat_message with all external deps stubbed.
    Returns (response_payload, captured_generate_ai_response_kwargs).
    """
    msg = ChatMessage(user_id=_USER_ID, pet_id=_PET_ID, message=message_text)

    extracted: dict = {
        "symptom": extracted_symptom,
        "symptom_class": extracted_symptom_class,
        "urgency_score": 2,
        "blood": False,
        "lethargy_level": "none",
        "refusing_water": False,
        "temperature_value": None,
        "respiratory_rate": None,
        "seizure_duration": None,
    }
    raw_extracted = json.dumps(extracted)

    _stats = dict(stats_mock) if stats_mock else {"today": 0, "last_hour": 0, "last_24h": 0}
    stub_sb = _stub_supabase()
    captured_gen: dict = {}

    def _fake_generate(**kwargs):
        captured_gen.update(kwargs)
        return "stub AI response"

    with (
        patch.object(chat_module.supabase, "table", stub_sb.table),
        patch("routers.chat.extract_event_data", return_value=raw_extracted),
        patch("routers.chat.get_pet_profile", return_value={
            "name": "Бони", "species": species, "breed": "labrador",
            "birth_date": "2022-01-01",
        }),
        patch("routers.chat.process_event", return_value={
            "episode_id": "ep-mode-1", "action": "updated",
        }),
        patch("routers.chat.get_symptom_stats",
              side_effect=lambda *a, **kw: dict(_stats)),
        patch("routers.chat.get_recent_events", return_value=[]),
        patch("routers.chat.get_medical_events", return_value=[]),
        patch("routers.chat.check_recurrence", return_value=False),
        patch("routers.chat.apply_cross_symptom_override",
              side_effect=lambda **kw: kw["decision"]),
        patch("routers.chat.update_episode_escalation"),
        patch("routers.chat.generate_ai_response", side_effect=_fake_generate),
        patch("routers.chat.save_event"),
        patch("routers.chat.save_medical_event"),
        patch("routers.chat.calculate_risk_score", return_value={
            "risk_score": 5,
            "calculated_escalation": "MODERATE",
        }),
        patch("routers.chat.get_onboarding_status", return_value={
            "complete": True,
            "next_question": None,
            "answered": ["species", "name", "gender", "neutered", "age"],
        }),
        patch("routers.chat.get_owner_name", return_value="Марк"),
        patch("routers.chat.save_owner_name"),
        patch("routers.chat.get_user_flags", return_value={}),
        patch("routers.chat.update_user_flags"),
    ):
        result = chat_module.create_chat_message(msg)

    return result, captured_gen


# ─────────────────────────────────────────────────────────────────────────────
# T01–T05  CASUAL mode
# ─────────────────────────────────────────────────────────────────────────────

class TestCasualMode(unittest.TestCase):

    def test_t01_classify_greeting_casual(self):
        """T01: no symptom + greeting → CASUAL"""
        mode = _classify_message_mode({"symptom": None}, "привет как дела")
        self.assertEqual(mode, "CASUAL",
                         "T01: greeting should be classified as CASUAL")

    def test_t02_casual_system_no_medical_ai(self):
        """T02: CASUAL system_block must NOT contain 'медицинский AI-ассистент'"""
        system_block, _ = _capture_ai(message_mode="CASUAL")
        self.assertNotIn("медицинский AI-ассистент", system_block,
                         "T02: CASUAL system_block must not contain medical AI text")

    def test_t03_casual_system_no_redundancy_guard(self):
        """T03: CASUAL system_block must NOT contain 'АНТИ-ПОВТОР'"""
        system_block, _ = _capture_ai(
            message_mode="CASUAL",
            previous_assistant_text="Предыдущий ответ.",
        )
        self.assertNotIn("АНТИ-ПОВТОР", system_block,
                         "T03: CASUAL system_block must not include redundancy guard")

    def test_t04_casual_user_prompt_is_message_only(self):
        """T04: CASUAL user_prompt = 'Сообщение: <msg>', no 'Medical history'"""
        msg = "привет как дела"
        _, user_prompt = _capture_ai(message_mode="CASUAL", user_message=msg)
        self.assertEqual(user_prompt, f"Сообщение: {msg}",
                         "T04: CASUAL user_prompt must be exactly 'Сообщение: <msg>'")
        self.assertNotIn("Medical history", user_prompt,
                         "T04: CASUAL user_prompt must not contain Medical history")

    def test_t05_casual_pipeline_no_debug(self):
        """T05: CASUAL message through pipeline → no debug in result"""
        result, gen = _call_create(
            "привет как дела",
            extracted_symptom=None,
            extracted_symptom_class=None,
        )
        self.assertNotIn("debug", result,
                         "T05: CASUAL pipeline must not produce a debug block")
        self.assertEqual(gen.get("message_mode"), "CASUAL",
                         "T05: message_mode='CASUAL' must be passed to generate_ai_response")


# ─────────────────────────────────────────────────────────────────────────────
# T06–T10  PROFILE mode
# ─────────────────────────────────────────────────────────────────────────────

class TestProfileMode(unittest.TestCase):

    def test_t06_classify_food_profile(self):
        """T06: 'чем кормить лабрадора' → PROFILE"""
        mode = _classify_message_mode({"symptom": None}, "чем кормить лабрадора")
        self.assertEqual(mode, "PROFILE",
                         "T06: food question must be classified as PROFILE")

    def test_t07_classify_grooming_profile(self):
        """T07: 'как часто купать собаку' → PROFILE"""
        mode = _classify_message_mode({"symptom": None}, "как часто купать собаку")
        self.assertEqual(mode, "PROFILE",
                         "T07: grooming question must be classified as PROFILE")

    def test_t08_profile_system_block(self):
        """T08: PROFILE system_block contains 'заботливый помощник', NOT 'медицинский AI-ассистент'"""
        system_block, _ = _capture_ai(message_mode="PROFILE")
        self.assertIn("заботливый помощник", system_block,
                      "T08: PROFILE system_block must contain 'заботливый помощник'")
        self.assertNotIn("медицинский AI-ассистент", system_block,
                         "T08: PROFILE system_block must NOT contain medical AI text")

    def test_t09_profile_user_prompt_has_pet_data(self):
        """T09: PROFILE user_prompt contains pet name and species"""
        _, user_prompt = _capture_ai(
            message_mode="PROFILE",
            user_message="чем кормить лабрадора",
        )
        self.assertIn("Бони", user_prompt,
                      "T09: PROFILE user_prompt must contain pet name")
        self.assertIn("dog", user_prompt,
                      "T09: PROFILE user_prompt must contain species")

    def test_t10_profile_pipeline_no_debug(self):
        """T10: PROFILE message through pipeline → no debug in result"""
        result, gen = _call_create(
            "чем кормить лабрадора",
            extracted_symptom=None,
            extracted_symptom_class=None,
        )
        self.assertNotIn("debug", result,
                         "T10: PROFILE pipeline must not produce a debug block")
        self.assertEqual(gen.get("message_mode"), "PROFILE",
                         "T10: message_mode='PROFILE' must be passed to generate_ai_response")


# ─────────────────────────────────────────────────────────────────────────────
# T11–T15  CLINICAL mode
# ─────────────────────────────────────────────────────────────────────────────

class TestClinicalMode(unittest.TestCase):

    def test_t11_classify_symptom_clinical(self):
        """T11: structured_data with symptom='vomiting' → CLINICAL"""
        mode = _classify_message_mode({"symptom": "vomiting"}, "собака рвёт")
        self.assertEqual(mode, "CLINICAL",
                         "T11: symptom present must be classified as CLINICAL")

    def test_t12_clinical_system_block(self):
        """T12: CLINICAL system_block contains 'медицинский AI-ассистент'"""
        system_block, _ = _capture_ai(message_mode="CLINICAL")
        self.assertIn("медицинский AI-ассистент", system_block,
                      "T12: CLINICAL system_block must contain 'медицинский AI-ассистент'")

    def test_t13_clinical_pipeline_has_debug(self):
        """T13: CLINICAL message with symptom through pipeline → debug in result"""
        result, gen = _call_create(
            "собака рвёт",
            extracted_symptom="vomiting",
            extracted_symptom_class="GI",
        )
        self.assertIn("debug", result,
                      "T13: CLINICAL pipeline must produce a debug block")
        self.assertEqual(gen.get("message_mode"), "CLINICAL",
                         "T13: message_mode='CLINICAL' must be passed to generate_ai_response")

    def test_t14_clinical_deterministic_template_applied(self):
        """T14: CLINICAL + clinical_decision → deterministic template (symptom in user_prompt)"""
        _, user_prompt = _capture_ai(
            message_mode="CLINICAL",
            clinical_decision=_DUMMY_CD,
        )
        # Deterministic template includes the symptom name
        self.assertIn("vomiting", user_prompt,
                      "T14: CLINICAL deterministic user_prompt must include symptom")
        # Must NOT include raw medical history block (deterministic skips it)
        self.assertNotIn("Medical history:", user_prompt,
                         "T14: deterministic prompt must not include 'Medical history:' section")

    def test_t15_clinical_history_in_context_block(self):
        """T15: CLINICAL + clinical_decision + memory_context → 'История болезней' in user_prompt"""
        _, user_prompt = _capture_ai(
            message_mode="CLINICAL",
            clinical_decision=_DUMMY_CD,
            memory_context="Бони болел рвотой трижды в прошлом месяце.",
        )
        self.assertIn("История болезней", user_prompt,
                      "T15: context_block must contain 'История болезней' when memory_context is present")


# ─────────────────────────────────────────────────────────────────────────────
# T16–T18  Edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def test_t16_symptom_wins_over_lifestyle_keyword(self):
        """T16: symptom present + lifestyle keyword → CLINICAL (symptom takes priority)"""
        mode = _classify_message_mode(
            {"symptom": "vomiting"},
            "корм вызвал рвоту",   # has "корм" (PROFILE keyword) AND vomiting
        )
        self.assertEqual(mode, "CLINICAL",
                         "T16: symptom must take priority over lifestyle keyword")

    def test_t17_extraction_error_is_casual(self):
        """T17: structured_data with 'error' key → CASUAL"""
        mode = _classify_message_mode({"error": "invalid_json"}, "some message")
        self.assertEqual(mode, "CASUAL",
                         "T17: extraction error must fall back to CASUAL")

    def test_t18_empty_message_no_symptom_is_casual(self):
        """T18: no symptom, empty message → CASUAL"""
        mode = _classify_message_mode({"symptom": None}, "")
        self.assertEqual(mode, "CASUAL",
                         "T18: empty message with no symptom must be CASUAL")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestCasualMode,
        TestProfileMode,
        TestClinicalMode,
        TestEdgeCases,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
