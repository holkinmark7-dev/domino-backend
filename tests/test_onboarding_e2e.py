"""
tests/test_onboarding_e2e.py — Onboarding end-to-end tests.

3 scenarios:
  1. Happy path — all fields filled, reaches ONBOARDING_COMPLETE
  2. Skip path — optional_gate "Позже" → ONBOARDING_COMPLETE
  3. Error handling — update_pet_profile raises → stays on same step

All Supabase and external calls are mocked.
"""

import sys
import os
import json
import unittest
from unittest.mock import MagicMock, patch
from contextlib import ExitStack

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import routers.chat as chat_module
from schemas.chat import ChatMessage

_USER_ID = "11111111-1111-1111-1111-111111111111"
_PET_ID = "22222222-2222-2222-2222-222222222222"


# ── Supabase stub ────────────────────────────────────────────────────────────

def _stub_supabase():
    sb = MagicMock()

    chat_insert_result = MagicMock()
    chat_insert_result.data = [{"id": "chat-ob-1"}]

    prev_ai_result = MagicMock()
    prev_ai_result.data = []

    # owner_name check: prior AI messages exist (so name-parse branch fires)
    prior_ai_check = MagicMock()
    prior_ai_check.data = [{"id": "ai-1"}]

    def _table(name: str):
        m = MagicMock()
        if name == "chat":
            insert_r = MagicMock()
            insert_r.execute.return_value = chat_insert_result
            m.insert.return_value = insert_r

            sel = MagicMock()
            # .select().eq().eq().order().limit().execute() — prev AI message
            sel.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = prev_ai_result
            # .select().eq().eq().limit().execute() — prior AI check for owner name
            sel.eq.return_value.eq.return_value.limit.return_value.execute.return_value = prior_ai_check
            m.select.return_value = sel
        return m

    sb.table.side_effect = _table
    return sb


# ── Shared patches ────────────────────────────────────────────────────────────

def _call_onboarding(
    message_text: str,
    *,
    onboarding_status: dict,
    pet_profile: dict | None = None,
    update_side_effect=None,
):
    """
    Call create_chat_message with onboarding-focused mocks.
    Returns the response payload dict.
    """
    msg = ChatMessage(user_id=_USER_ID, pet_id=_PET_ID, message=message_text)

    _profile = pet_profile or {
        "name": "Бони", "species": "dog", "breed": None,
        "birth_date": "2022-01-01", "onboarding_step": None,
    }

    extracted = json.dumps({"symptom": None})

    stub_sb = _stub_supabase()

    update_kwargs = {"return_value": None}
    if update_side_effect is not None:
        update_kwargs = {"side_effect": update_side_effect}

    with ExitStack() as stack:
        stack.enter_context(patch.object(chat_module.supabase, "table", stub_sb.table))
        stack.enter_context(patch("routers.chat.extract_event_data", return_value=extracted))
        stack.enter_context(patch("routers.chat.save_event"))
        stack.enter_context(patch("routers.chat.save_medical_event"))
        stack.enter_context(patch("routers.chat.generate_ai_response", return_value="ai_mock"))
        stack.enter_context(patch("routers.chat.get_recent_events", return_value=[]))
        stack.enter_context(patch("routers.chat.get_medical_events", return_value=[]))
        stack.enter_context(patch("routers.chat.process_event", return_value={
            "episode_id": None, "action": "standalone",
        }))
        stack.enter_context(patch("routers.chat.update_episode_escalation"))

        # Onboarding-specific mocks — patch at the module where they're imported
        stack.enter_context(patch("routers.chat.get_pet_profile", return_value=_profile))
        stack.enter_context(patch(
            "routers.services.onboarding_router.get_pet_profile", return_value=_profile,
        ))
        stack.enter_context(patch(
            "routers.services.onboarding_router.get_onboarding_status",
            return_value=onboarding_status,
        ))
        stack.enter_context(patch(
            "routers.services.onboarding_router.get_owner_name", return_value="Марк",
        ))
        stack.enter_context(patch(
            "routers.services.onboarding_router.update_pet_profile", **update_kwargs,
        ))
        stack.enter_context(patch(
            "routers.services.onboarding_router.update_user_flags",
        ))

        # Clinical router mocks (not the focus but needed)
        stack.enter_context(patch(
            "routers.services.clinical_router.get_symptom_stats",
            return_value={"today": 0, "last_hour": 0, "last_24h": 0},
        ))
        stack.enter_context(patch(
            "routers.services.clinical_router.get_medical_events", return_value=[],
        ))

        result = chat_module.create_chat_message(msg)

    return result


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestOnboardingHappyPath(unittest.TestCase):
    """Test 1: All required + optional fields filled → ONBOARDING_COMPLETE."""

    def test_happy_path_complete(self):
        # Simulate the LAST step: stamp_id_ask answered "Нет" → complete
        # get_onboarding_status returns complete after recheck
        result = _call_onboarding(
            "Нет",
            onboarding_status={"complete": True, "next_question": None, "phase": "done"},
        )
        # Onboarding is complete → mode should NOT be ONBOARDING
        self.assertNotEqual(result["response_type"], "ONBOARDING")

    def test_species_step_returns_onboarding(self):
        # First step: species not yet filled
        result = _call_onboarding(
            "Собака",
            onboarding_status={
                "complete": False, "next_question": "species", "phase": "required",
            },
            pet_profile={
                "name": None, "species": None, "breed": None,
                "birth_date": None, "onboarding_step": None,
            },
        )
        self.assertEqual(result["response_type"], "ONBOARDING")
        # Should have an ai_response (deterministic onboarding message)
        self.assertIn("ai_response", result)


class TestOnboardingSkipPath(unittest.TestCase):
    """Test 2: Optional gate → 'Позже' → ONBOARDING_COMPLETE."""

    def test_skip_optional_goes_to_complete(self):
        # All required filled, optional_gate step, user says "Позже"
        # After "Позже" validation returns next_step="complete"
        # Then get_onboarding_status (recheck) returns complete
        result = _call_onboarding(
            "Позже",
            onboarding_status={
                "complete": False, "next_question": "breed", "phase": "optional",
            },
            pet_profile={
                "name": "Бони", "species": "dog", "gender": "male",
                "neutered": True, "birth_date": "2022-01-01",
                "breed": None, "onboarding_step": None,
            },
        )
        # optional_gate → "Позже" → complete
        self.assertEqual(result["response_type"], "ONBOARDING_COMPLETE")


class TestOnboardingErrorHandling(unittest.TestCase):
    """Test 3: update_pet_profile raises → user stays on same step."""

    def test_db_error_stays_on_step(self):
        result = _call_onboarding(
            "Собака",
            onboarding_status={
                "complete": False, "next_question": "species", "phase": "required",
            },
            pet_profile={
                "name": None, "species": None, "breed": None,
                "birth_date": None, "onboarding_step": None,
            },
            update_side_effect=Exception("DB error"),
        )
        # Should contain error message
        self.assertIn("Не удалось сохранить", result["ai_response"])
        # Should still be in ONBOARDING mode
        self.assertEqual(result["response_type"], "ONBOARDING")


if __name__ == "__main__":
    unittest.main()
