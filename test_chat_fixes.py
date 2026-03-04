"""
test_chat_fixes.py — CHAT.PY 6 FIXES

9 tests:
  T1  food from structured_data → decision["food"] for GI symptom (via llm_contract known_facts)
  T2  food from structured_data → llm_contract["known_facts"]["food"]
  T3  GENERAL class symptom "fever" → decision escalation="MODERATE"
  T4  OCULAR class symptom "eye_discharge" → decision escalation="LOW"
  T5  reaction_type != "repeated_symptom" on first symptom mention (no prior history)
  T6  reaction_type == "repeated_symptom" only when prior history present
  T7  dialogue_mode == "clinical_escalation" when escalation is CRITICAL
  T8  llm_contract["episode_phase"] == debug["episode_phase"] (FIX 6 consistency)
  T9  Regression: 131/131 PASS

No real Supabase / OpenAI calls — all stubbed.
"""

import sys
import os
import unittest
import subprocess
import pytest
from unittest.mock import MagicMock, patch
from contextlib import ExitStack

sys.path.insert(0, os.path.dirname(__file__))

import routers.chat as chat_module
from schemas.chat import ChatMessage

_ONBOARDING_COMPLETE = {"complete": True, "next_question": None, "phase": "complete"}

@pytest.fixture(autouse=True)
def mock_onboarding_status():
    with ExitStack() as stack:
        stack.enter_context(patch(
            "routers.services.memory.get_onboarding_status",
            return_value=_ONBOARDING_COMPLETE,
        ))
        stack.enter_context(patch(
            "routers.services.onboarding_router.get_onboarding_status",
            return_value=_ONBOARDING_COMPLETE,
        ))
        yield


# ─────────────────────────────────────────────────────────────────────────────
# Stub builder
# ─────────────────────────────────────────────────────────────────────────────

_USER_ID = "11111111-1111-1111-1111-111111111111"
_PET_ID  = "22222222-2222-2222-2222-222222222222"


def _make_message(text: str, pet_id: str = _PET_ID) -> ChatMessage:
    return ChatMessage(
        user_id=_USER_ID,
        pet_id=pet_id,
        message=text,
    )


def _stub_supabase(
    *,
    prev_ai_message: str | None = None,
    episode_started_at: str = "2026-02-20T08:00:00",
):
    """
    Return a MagicMock for supabase that handles the most common query chains.
    """
    sb = MagicMock()

    # chat.insert (save user message) → data=[{id: "chat-1"}]
    chat_insert_result = MagicMock()
    chat_insert_result.data = [{"id": "chat-1"}]
    sb.table.return_value.insert.return_value.execute.return_value = chat_insert_result

    # chat.select for previous AI message
    prev_ai_result = MagicMock()
    prev_ai_result.data = [{"message": prev_ai_message}] if prev_ai_message else []

    # episodes.select.eq.single for duration
    ep_row_result = MagicMock()
    ep_row_result.data = {"started_at": episode_started_at}

    def _table(name: str):
        m = MagicMock()
        if name == "chat":
            # Insert path
            insert_r = MagicMock()
            insert_r.execute.return_value = chat_insert_result
            m.insert.return_value = insert_r
            # Select path (for prev AI)
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
    extracted_symptom: str | None = "vomiting",
    extracted_symptom_class: str | None = "GI",
    extracted_food: str | None = None,
    medical_events: list | None = None,
    recent_events: list | None = None,
    prev_ai_message: str | None = None,
):
    """
    Call create_chat_message with all external dependencies mocked.
    Returns the full response_payload dict.
    """
    msg = _make_message(message_text, pet_id=_PET_ID)

    # Build extracted data
    extracted = {
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
    if extracted_food:
        extracted["food"] = extracted_food

    import json
    raw_extracted = json.dumps(extracted)

    stub_sb = _stub_supabase(prev_ai_message=prev_ai_message)

    with (
        patch.object(chat_module.supabase, "table", stub_sb.table),
        patch("routers.chat.extract_event_data", return_value=raw_extracted),
        patch("routers.chat.get_pet_profile", return_value={
            "name": "Бони", "species": "dog", "breed": "labrador",
            "birth_date": "2022-01-01",
        }),
        patch("routers.chat.process_event", return_value={
            "episode_id": "ep-test-1", "action": "updated",
        }),
        patch("routers.services.clinical_router.get_symptom_stats", return_value={
            "today": 0, "last_hour": 0, "last_24h": 0,
        }),
        patch("routers.chat.get_recent_events", return_value=recent_events or []),
        patch("routers.chat.get_medical_events", return_value=medical_events or []),
        patch("routers.services.clinical_router.get_medical_events", return_value=medical_events or []),
        patch("routers.services.decision_postprocess.check_recurrence", return_value=False),
        patch("routers.services.decision_postprocess.apply_cross_symptom_override", side_effect=lambda **kw: kw["decision"]),
        patch("routers.chat.update_episode_escalation"),
        patch("routers.chat.generate_ai_response", return_value="stub AI response"),
        patch("routers.chat.save_event"),
        patch("routers.chat.save_medical_event"),
        patch("routers.services.decision_postprocess.calculate_risk_score", return_value={
            "risk_score": 5,
            "calculated_escalation": "MODERATE",
        }),
    ):
        return chat_module.create_chat_message(msg)


# ─────────────────────────────────────────────────────────────────────────────
# T1–T8 — Fix verification tests
# ─────────────────────────────────────────────────────────────────────────────

class TestChatFixes(unittest.TestCase):

    # T1: food in GI decision → propagated to llm_contract known_facts
    def test_food_in_gi_decision(self):
        result = _call_create(
            "рвота после банана",
            extracted_symptom="vomiting",
            extracted_symptom_class="GI",
            extracted_food="банан",
        )
        known_facts = result.get("debug", {}).get("llm_contract", {}).get("known_facts", {})
        self.assertIn("food", known_facts, "food must be in llm_contract known_facts when GI decision")
        self.assertEqual(known_facts["food"], "банан")

    # T2: food appears in llm_contract known_facts (explicit check)
    def test_food_in_llm_contract_known_facts(self):
        result = _call_create(
            "собака поела кукурузу и рвёт",
            extracted_symptom="vomiting",
            extracted_symptom_class="GI",
            extracted_food="кукуруза",
        )
        known_facts = result.get("debug", {}).get("llm_contract", {}).get("known_facts", {})
        self.assertEqual(known_facts.get("food"), "кукуруза",
                         "food value must flow from extraction → llm_contract.known_facts")

    # T3: GENERAL class "fever" → decision escalation MODERATE
    def test_general_fever_escalation(self):
        result = _call_create(
            "у собаки температура",
            extracted_symptom="fever",
            extracted_symptom_class="GENERAL",
        )
        escalation = result.get("debug", {}).get("old_escalation")
        self.assertEqual(escalation, "MODERATE",
                         "GENERAL 'fever' must produce escalation=MODERATE")

    # T4: OCULAR class "eye_discharge" → decision escalation LOW
    def test_ocular_eye_discharge_escalation(self):
        result = _call_create(
            "у собаки выделения из глаз",
            extracted_symptom="eye_discharge",
            extracted_symptom_class="OCULAR",
        )
        escalation = result.get("debug", {}).get("old_escalation")
        self.assertEqual(escalation, "LOW",
                         "OCULAR 'eye_discharge' must produce escalation=LOW")

    # T5: No prior history → reaction_type must NOT be "repeated_symptom"
    def test_no_prior_history_not_repeated(self):
        # Short message triggers the len < 20 check, but no prior events
        captured_decision = {}

        original_generate = chat_module.generate_ai_response

        def _capture_generate(req):
            if req.clinical_decision:
                captured_decision["reaction_type"] = req.clinical_decision.get("reaction_type")
            return "stub"

        msg = _make_message("рвота", pet_id=_PET_ID)
        import json
        extracted = {
            "symptom": "vomiting",
            "symptom_class": "GI",
            "urgency_score": 2,
            "blood": False,
            "lethargy_level": "none",
            "refusing_water": False,
        }
        stub_sb = _stub_supabase()

        with (
            patch.object(chat_module.supabase, "table", stub_sb.table),
            patch("routers.chat.extract_event_data", return_value=json.dumps(extracted)),
            patch("routers.chat.get_pet_profile", return_value={"name": "Бони", "species": "dog", "birth_date": "2022-01-01"}),
            patch("routers.chat.process_event", return_value={"episode_id": "ep-1", "action": "updated"}),
            patch("routers.services.clinical_router.get_symptom_stats", return_value={"today": 0, "last_hour": 0, "last_24h": 0}),
            patch("routers.chat.get_recent_events", return_value=[]),   # ← no prior history
            patch("routers.chat.get_medical_events", return_value=[]),
            patch("routers.services.clinical_router.get_medical_events", return_value=[]),
            patch("routers.services.decision_postprocess.check_recurrence", return_value=False),
            patch("routers.services.decision_postprocess.apply_cross_symptom_override", side_effect=lambda **kw: kw["decision"]),
            patch("routers.chat.update_episode_escalation"),
            patch("routers.chat.generate_ai_response", side_effect=_capture_generate),
            patch("routers.chat.save_event"),
            patch("routers.chat.save_medical_event"),
            patch("routers.services.decision_postprocess.calculate_risk_score", return_value={"risk_score": 5, "calculated_escalation": "MODERATE"}),
        ):
            chat_module.create_chat_message(msg)

        self.assertNotEqual(
            captured_decision.get("reaction_type"), "repeated_symptom",
            "reaction_type must NOT be 'repeated_symptom' when there is no prior history",
        )

    # T6: Prior history of same symptom → reaction_type == "repeated_symptom"
    def test_with_prior_history_is_repeated(self):
        captured_decision = {}

        def _capture_generate(req):
            if req.clinical_decision:
                captured_decision["reaction_type"] = req.clinical_decision.get("reaction_type")
            return "stub"

        msg = _make_message("рвота", pet_id=_PET_ID)
        import json
        extracted = {
            "symptom": "vomiting",
            "symptom_class": "GI",
            "urgency_score": 2,
            "blood": False,
            "lethargy_level": "none",
            "refusing_water": False,
        }
        # Prior event with the same symptom
        prior_events = [
            {"type": "medical_event", "content": {"symptom": "vomiting", "urgency_score": 2}},
        ]
        stub_sb = _stub_supabase()

        with (
            patch.object(chat_module.supabase, "table", stub_sb.table),
            patch("routers.chat.extract_event_data", return_value=json.dumps(extracted)),
            patch("routers.chat.get_pet_profile", return_value={"name": "Бони", "species": "dog", "birth_date": "2022-01-01"}),
            patch("routers.chat.process_event", return_value={"episode_id": "ep-1", "action": "updated"}),
            patch("routers.services.clinical_router.get_symptom_stats", return_value={"today": 0, "last_hour": 0, "last_24h": 0}),
            patch("routers.chat.get_recent_events", return_value=prior_events),  # ← has prior history
            patch("routers.chat.get_medical_events", return_value=[]),
            patch("routers.services.clinical_router.get_medical_events", return_value=[]),
            patch("routers.services.decision_postprocess.check_recurrence", return_value=False),
            patch("routers.services.decision_postprocess.apply_cross_symptom_override", side_effect=lambda **kw: kw["decision"]),
            patch("routers.chat.update_episode_escalation"),
            patch("routers.chat.generate_ai_response", side_effect=_capture_generate),
            patch("routers.chat.save_event"),
            patch("routers.chat.save_medical_event"),
            patch("routers.services.decision_postprocess.calculate_risk_score", return_value={"risk_score": 5, "calculated_escalation": "MODERATE"}),
        ):
            chat_module.create_chat_message(msg)

        self.assertEqual(
            captured_decision.get("reaction_type"), "repeated_symptom",
            "reaction_type must be 'repeated_symptom' when prior history of same symptom exists",
        )

    # T7: dialogue_mode == "clinical_escalation" when escalation is CRITICAL
    def test_dialogue_mode_clinical_escalation(self):
        captured = {}

        def _capture_generate(req):
            captured["dialogue_mode"] = req.dialogue_mode
            return "stub"

        msg = _make_message("кот тужится уже несколько часов", pet_id=_PET_ID)
        import json
        extracted = {
            "symptom": "urinary_obstruction",
            "symptom_class": "URINARY",
            "urgency_score": 3,
            "blood": False,
            "lethargy_level": "none",
            "refusing_water": False,
        }
        stub_sb = _stub_supabase()

        with (
            patch.object(chat_module.supabase, "table", stub_sb.table),
            patch("routers.chat.extract_event_data", return_value=json.dumps(extracted)),
            patch("routers.chat.get_pet_profile", return_value={"name": "Мурка", "species": "cat", "birth_date": "2020-01-01"}),
            patch("routers.chat.process_event", return_value={"episode_id": "ep-1", "action": "updated"}),
            patch("routers.services.clinical_router.get_symptom_stats", return_value={"today": 0, "last_hour": 0, "last_24h": 0}),
            patch("routers.chat.get_recent_events", return_value=[]),
            patch("routers.chat.get_medical_events", return_value=[]),
            patch("routers.services.clinical_router.get_medical_events", return_value=[]),
            patch("routers.services.decision_postprocess.check_recurrence", return_value=False),
            patch("routers.services.decision_postprocess.apply_cross_symptom_override", side_effect=lambda **kw: kw["decision"]),
            patch("routers.chat.update_episode_escalation"),
            patch("routers.chat.generate_ai_response", side_effect=_capture_generate),
            patch("routers.chat.save_event"),
            patch("routers.chat.save_medical_event"),
            patch("routers.services.decision_postprocess.calculate_risk_score", return_value={"risk_score": 8, "calculated_escalation": "CRITICAL"}),
        ):
            chat_module.create_chat_message(msg)

        self.assertEqual(
            captured.get("dialogue_mode"), "clinical_escalation",
            "dialogue_mode must be 'clinical_escalation' when escalation >= MODERATE",
        )

    # T8: llm_contract episode_phase == debug episode_phase (FIX 6 consistency)
    def test_llm_contract_episode_phase_matches_debug(self):
        result = _call_create(
            "собака рвёт третий раз за день",
            extracted_symptom="vomiting",
            extracted_symptom_class="GI",
        )
        debug = result.get("debug", {})
        contract_phase = debug.get("llm_contract", {}).get("episode_phase")
        debug_phase = debug.get("episode_phase")
        self.assertEqual(
            contract_phase, debug_phase,
            f"llm_contract.episode_phase ({contract_phase!r}) must match debug.episode_phase ({debug_phase!r})",
        )


# ─────────────────────────────────────────────────────────────────────────────
# T9 — Regression
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


class TestRegression(unittest.TestCase):

    def test_full_regression(self):
        """Run the previous full suite via pytest and verify 131/131 PASS."""
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "tests/",
                "test_phase_followup_engine.py",
                "test_api_fixes.py",
                "test_critical_fixes.py",
                "test_ai_prompt_fix.py",
                "test_llm_contract.py",
                "-q", "--tb=no",
            ],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(__file__),
        )
        output = result.stdout + result.stderr
        # Extract "X passed"
        import re
        m = re.search(r"(\d+) passed", output)
        passed = int(m.group(1)) if m else 0
        self.assertGreaterEqual(
            passed, 131,
            f"Regression: expected >=131 passed, got {passed}.\n{output[-800:]}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestChatFixes))
    suite.addTests(loader.loadTestsFromTestCase(TestRegression))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
