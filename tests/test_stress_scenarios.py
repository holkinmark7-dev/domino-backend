"""
tests/test_stress_scenarios.py — STRESS SCENARIOS (20 real-dialogue scenarios)

Covers all symptom classes and key escalation rules.
No real Supabase / OpenAI calls — all patched.

Each scenario checks:
  - debug["old_escalation"]   — final triage escalation
  - debug["response_type"]    — Escalation Behavior Lock result
  - captured dialogue_mode    — captured from generate_ai_response kwargs

Scenario map:
  S01  Single vomiting                   → LOW   / ASSESS  / normal
  S02  Vomiting 3× today                 → MOD   / CLARIFY / clinical_escalation
  S03  Vomiting 5× today                 → HIGH  / ACTION  / clinical_escalation
  S04  Vomiting + severe lethargy        → CRIT  / ACTION  / clinical_escalation
  S05  Vomiting + refusing_water         → CRIT  / ACTION  / clinical_escalation
  S06  Single cough                      → LOW   / ASSESS  / normal
  S07  Difficulty breathing              → HIGH  / ACTION  / clinical_escalation
  S08  Diff. breathing + lethargy (cat)  → CRIT  / ACTION  / clinical_escalation
  S09  Foreign body ingestion            → HIGH  / ACTION  / clinical_escalation
  S10  Xylitol toxicity                  → CRIT  / ACTION  / clinical_escalation
  S11  Single seizure (no duration)      → HIGH  / ACTION  / clinical_escalation
  S12  Seizure 3 min                     → CRIT  / ACTION  / clinical_escalation
  S13  Urinary obstruction + cat         → CRIT  / ACTION  / clinical_escalation
  S14  Temperature 41.0 (no symptom)     → CRIT  / ACTION  / clinical_escalation
  S15  Mild lethargy (GENERAL class)     → MOD   / CLARIFY / clinical_escalation
  S16  Coffee-ground vomit               → CRIT  / ACTION  / clinical_escalation
  S17  GDV keywords                      → CRIT  / ACTION  / clinical_escalation
  S18  Vomiting + food="банан"            → food in llm_contract.known_facts
  S19  Greeting ("привет как дела")      → no debug (decision=None)
  S20  Off-topic question                → no debug (decision=None)
"""

import sys
import os
import json
import unittest
import pytest
from unittest.mock import MagicMock, patch
from contextlib import ExitStack
from datetime import datetime, timezone
from freezegun import freeze_time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import routers.chat as chat_module
from schemas.chat import ChatMessage

_ONBOARDING_COMPLETE = {"complete": True, "next_question": None, "phase": "complete"}

@pytest.fixture(autouse=True)
def mock_onboarding_status():
    with patch(
        "routers.services.memory.get_onboarding_status",
        return_value=_ONBOARDING_COMPLETE,
    ):
        yield


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_USER_ID = "11111111-1111-1111-1111-111111111111"
_PET_ID  = "22222222-2222-2222-2222-222222222222"


# ─────────────────────────────────────────────────────────────────────────────
# Supabase stub
# ─────────────────────────────────────────────────────────────────────────────

def _stub_supabase():
    sb = MagicMock()

    chat_insert_result = MagicMock()
    chat_insert_result.data = [{"id": "chat-stress-1"}]

    prev_ai_result = MagicMock()
    prev_ai_result.data = []   # no previous AI message

    # Use current UTC time so episode_duration_hours ≈ 0 — no duration escalation fires
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


# ─────────────────────────────────────────────────────────────────────────────
# Core helper
# ─────────────────────────────────────────────────────────────────────────────

def _call_create(
    message_text: str,
    *,
    extracted_symptom: str | None = None,
    extracted_symptom_class: str | None = None,
    extracted_lethargy_level: str = "none",
    extracted_refusing_water: bool = False,
    extracted_temperature_value: float | None = None,
    extracted_seizure_duration: float | None = None,
    extracted_food: str | None = None,
    stats_mock: dict | None = None,
    species: str = "dog",
    birth_date: str = "2022-01-01",
) -> tuple[dict, dict]:
    """
    Call create_chat_message with all external dependencies stubbed.

    Returns:
      (response_payload, generate_ai_response_kwargs)

    generate_ai_response_kwargs["dialogue_mode"] gives the dialogue_mode
    captured from the patched generate_ai_response call.
    """
    msg = ChatMessage(user_id=_USER_ID, pet_id=_PET_ID, message=message_text)

    extracted: dict = {
        "symptom": extracted_symptom,
        "symptom_class": extracted_symptom_class,
        "urgency_score": 2,
        "blood": False,
        "lethargy_level": extracted_lethargy_level,
        "refusing_water": extracted_refusing_water,
        "temperature_value": extracted_temperature_value,
        "respiratory_rate": None,
        "seizure_duration": extracted_seizure_duration,
    }
    if extracted_food is not None:
        extracted["food"] = extracted_food

    raw_extracted = json.dumps(extracted)

    _stats = dict(stats_mock) if stats_mock is not None else {"today": 0, "last_hour": 0, "last_24h": 0}

    stub_sb = _stub_supabase()
    captured_gen: dict = {}

    def _fake_generate(req):
        from dataclasses import asdict
        captured_gen.update(asdict(req))
        return "stub AI response"

    with (
        patch.object(chat_module.supabase, "table", stub_sb.table),
        patch("routers.chat.extract_event_data", return_value=raw_extracted),
        patch("routers.chat.get_pet_profile", return_value={
            "name": "Бони", "species": species, "breed": "labrador",
            "birth_date": birth_date,
        }),
        patch("routers.chat.process_event", return_value={
            "episode_id": "ep-stress-1", "action": "updated",
        }),
        patch("routers.services.clinical_router.get_symptom_stats",
              side_effect=lambda *a, **kw: dict(_stats)),
        patch("routers.chat.get_recent_events", return_value=[]),
        patch("routers.chat.get_medical_events", return_value=[]),
        patch("routers.services.clinical_router.get_medical_events", return_value=[]),
        patch("routers.services.decision_postprocess.check_recurrence", return_value=False),
        patch("routers.services.decision_postprocess.apply_cross_symptom_override",
              side_effect=lambda **kw: kw["decision"]),
        patch("routers.chat.update_episode_escalation"),
        patch("routers.chat.generate_ai_response", side_effect=_fake_generate),
        patch("routers.chat.save_event"),
        patch("routers.chat.save_medical_event"),
        patch("routers.services.decision_postprocess.calculate_risk_score", return_value={
            "risk_score": 5,
            "calculated_escalation": "MODERATE",
        }),
    ):
        result = chat_module.create_chat_message(msg)

    return result, captured_gen


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _esc(result: dict) -> str | None:
    return result.get("debug", {}).get("old_escalation")

def _rtype(result: dict) -> str | None:
    return result.get("debug", {}).get("response_type")

def _dmode(gen_kwargs: dict) -> str | None:
    return gen_kwargs.get("dialogue_mode")


# ─────────────────────────────────────────────────────────────────────────────
# S01–S05  GI class
# ─────────────────────────────────────────────────────────────────────────────

@freeze_time("2024-06-15 12:00:00", tz_offset=0)
class TestStressGI(unittest.TestCase):

    def test_s01_single_vomiting_low(self):
        """S01: 1st vomiting episode → LOW / ASSESS / normal"""
        result, gen = _call_create(
            "собака рвала один раз",
            extracted_symptom="vomiting",
            extracted_symptom_class="GI",
            stats_mock={"today": 0, "last_hour": 0, "last_24h": 0},
        )
        self.assertEqual(_esc(result), "LOW",   "S01: expected LOW")
        self.assertEqual(_rtype(result), "ASSESS", "S01: expected ASSESS")
        self.assertEqual(_dmode(gen), "normal",   "S01: expected normal dialogue_mode")

    def test_s02_vomiting_moderate(self):
        """S02: 3rd vomiting today → MODERATE / CLARIFY / clinical_escalation"""
        result, gen = _call_create(
            "собака рвала 3 раза сегодня",
            extracted_symptom="vomiting",
            extracted_symptom_class="GI",
            stats_mock={"today": 2, "last_hour": 0, "last_24h": 2},  # +1 → today=3
        )
        self.assertEqual(_esc(result), "MODERATE",           "S02: expected MODERATE")
        self.assertEqual(_rtype(result), "CLARIFY",           "S02: expected CLARIFY")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S02: expected clinical_escalation")

    def test_s03_vomiting_high(self):
        """S03: 5th vomiting today → HIGH / ACTION / clinical_escalation"""
        result, gen = _call_create(
            "собака рвала 5 раз сегодня",
            extracted_symptom="vomiting",
            extracted_symptom_class="GI",
            stats_mock={"today": 4, "last_hour": 0, "last_24h": 4},  # +1 → today=5
        )
        self.assertEqual(_esc(result), "HIGH",               "S03: expected HIGH")
        self.assertEqual(_rtype(result), "ACTION",            "S03: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S03: expected clinical_escalation")

    def test_s04_vomiting_severe_lethargy_critical(self):
        """S04: vomiting + severe lethargy → CRITICAL (GI+severe_lethargy v4.4)"""
        result, gen = _call_create(
            "рвота и вялость",
            extracted_symptom="vomiting",
            extracted_symptom_class="GI",
            extracted_lethargy_level="severe",
            stats_mock={"today": 0, "last_hour": 0, "last_24h": 0},
        )
        self.assertEqual(_esc(result), "CRITICAL",           "S04: expected CRITICAL")
        self.assertEqual(_rtype(result), "ACTION",            "S04: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S04: expected clinical_escalation")

    def test_s05_vomiting_refusing_water_critical(self):
        """S05: vomiting + refusing_water → CRITICAL (GI+refusing_water v4.4)"""
        result, gen = _call_create(
            "рвота и не пьёт",
            extracted_symptom="vomiting",
            extracted_symptom_class="GI",
            extracted_refusing_water=True,
            stats_mock={"today": 0, "last_hour": 0, "last_24h": 0},
        )
        self.assertEqual(_esc(result), "CRITICAL",           "S05: expected CRITICAL")
        self.assertEqual(_rtype(result), "ACTION",            "S05: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S05: expected clinical_escalation")


# ─────────────────────────────────────────────────────────────────────────────
# S06–S08  RESPIRATORY class
# ─────────────────────────────────────────────────────────────────────────────

@freeze_time("2024-06-15 12:00:00", tz_offset=0)
class TestStressRespiratory(unittest.TestCase):

    def test_s06_single_cough_low(self):
        """S06: isolated cough → LOW / ASSESS / normal"""
        result, gen = _call_create(
            "собака кашляет",
            extracted_symptom="cough",
            extracted_symptom_class="RESPIRATORY",
        )
        self.assertEqual(_esc(result), "LOW",   "S06: expected LOW")
        self.assertEqual(_rtype(result), "ASSESS", "S06: expected ASSESS")
        self.assertEqual(_dmode(gen), "normal",   "S06: expected normal")

    def test_s07_difficulty_breathing_high(self):
        """S07: difficulty_breathing alone → HIGH / ACTION / clinical_escalation"""
        result, gen = _call_create(
            "тяжело дышит",
            extracted_symptom="difficulty_breathing",
            extracted_symptom_class="RESPIRATORY",
        )
        self.assertEqual(_esc(result), "HIGH",               "S07: expected HIGH")
        self.assertEqual(_rtype(result), "ACTION",            "S07: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S07: expected clinical_escalation")

    def test_s08_difficulty_breathing_lethargy_cat_critical(self):
        """S08: diff_breathing + lethargy (cat) → CRITICAL / ACTION / clinical_escalation"""
        result, gen = _call_create(
            "кот тяжело дышит и вялый",
            extracted_symptom="difficulty_breathing",
            extracted_symptom_class="RESPIRATORY",
            extracted_lethargy_level="severe",
            species="cat",
        )
        self.assertEqual(_esc(result), "CRITICAL",           "S08: expected CRITICAL")
        self.assertEqual(_rtype(result), "ACTION",            "S08: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S08: expected clinical_escalation")


# ─────────────────────────────────────────────────────────────────────────────
# S09–S10  INGESTION / TOXIC
# ─────────────────────────────────────────────────────────────────────────────

@freeze_time("2024-06-15 12:00:00", tz_offset=0)
class TestStressIngestionToxic(unittest.TestCase):

    def test_s09_foreign_body_high(self):
        """S09: foreign_body_ingestion → HIGH / ACTION / clinical_escalation"""
        result, gen = _call_create(
            "проглотил носок",
            extracted_symptom="foreign_body_ingestion",
            extracted_symptom_class="INGESTION",
        )
        self.assertEqual(_esc(result), "HIGH",               "S09: expected HIGH")
        self.assertEqual(_rtype(result), "ACTION",            "S09: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S09: expected clinical_escalation")

    def test_s10_xylitol_critical(self):
        """S10: xylitol_toxicity → CRITICAL / ACTION / clinical_escalation"""
        result, gen = _call_create(
            "собака съела ксилит",   # keyword override fires
            extracted_symptom="xylitol_toxicity",
            extracted_symptom_class="TOXIC",
        )
        self.assertEqual(_esc(result), "CRITICAL",           "S10: expected CRITICAL")
        self.assertEqual(_rtype(result), "ACTION",            "S10: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S10: expected clinical_escalation")


# ─────────────────────────────────────────────────────────────────────────────
# S11–S12  NEURO (seizure)
# ─────────────────────────────────────────────────────────────────────────────

@freeze_time("2024-06-15 12:00:00", tz_offset=0)
class TestStressNeuro(unittest.TestCase):

    def test_s11_seizure_no_duration_high(self):
        """S11: single seizure, no duration → HIGH / ACTION / clinical_escalation"""
        result, gen = _call_create(
            "у собаки был судорожный приступ",
            extracted_symptom="seizure",
            extracted_symptom_class="NEURO",
            extracted_seizure_duration=None,
            stats_mock={"today": 0, "last_hour": 0, "last_24h": 0},
        )
        self.assertEqual(_esc(result), "HIGH",               "S11: expected HIGH")
        self.assertEqual(_rtype(result), "ACTION",            "S11: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S11: expected clinical_escalation")

    def test_s12_seizure_3min_critical(self):
        """S12: seizure 3 min → CRITICAL (seizure_duration >= 2.0 rule)"""
        result, gen = _call_create(
            "судороги длились 3 минуты",
            extracted_symptom="seizure",
            extracted_symptom_class="NEURO",
            extracted_seizure_duration=3.0,
            stats_mock={"today": 0, "last_hour": 0, "last_24h": 0},
        )
        self.assertEqual(_esc(result), "CRITICAL",           "S12: expected CRITICAL")
        self.assertEqual(_rtype(result), "ACTION",            "S12: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S12: expected clinical_escalation")


# ─────────────────────────────────────────────────────────────────────────────
# S13  URINARY (cat + straining)
# ─────────────────────────────────────────────────────────────────────────────

@freeze_time("2024-06-15 12:00:00", tz_offset=0)
class TestStressUrinary(unittest.TestCase):

    def test_s13_urinary_cat_straining_critical(self):
        """S13: urinary_obstruction + cat + 'тужится' → CRITICAL / ACTION"""
        result, gen = _call_create(
            "кот тужится и не может пописать",   # keyword override fires
            extracted_symptom="urinary_obstruction",
            extracted_symptom_class="URINARY",
            species="cat",
        )
        self.assertEqual(_esc(result), "CRITICAL",           "S13: expected CRITICAL")
        self.assertEqual(_rtype(result), "ACTION",            "S13: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S13: expected clinical_escalation")


# ─────────────────────────────────────────────────────────────────────────────
# S14  Absolute Critical (hyperthermia)
# ─────────────────────────────────────────────────────────────────────────────

@freeze_time("2024-06-15 12:00:00", tz_offset=0)
class TestStressAbsoluteCritical(unittest.TestCase):

    def test_s14_temperature_41_critical(self):
        """S14: temperature 41.0, no other symptom → CRITICAL (hyperthermia rule)"""
        result, gen = _call_create(
            "температура 41 градус",
            extracted_symptom=None,
            extracted_symptom_class=None,
            extracted_temperature_value=41.0,
        )
        self.assertEqual(_esc(result), "CRITICAL",           "S14: expected CRITICAL")
        self.assertEqual(_rtype(result), "ACTION",            "S14: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S14: expected clinical_escalation")


# ─────────────────────────────────────────────────────────────────────────────
# S15  GENERAL class (mild lethargy)
# ─────────────────────────────────────────────────────────────────────────────

@freeze_time("2024-06-15 12:00:00", tz_offset=0)
class TestStressGeneral(unittest.TestCase):

    def test_s15_mild_lethargy_general_moderate(self):
        """S15: lethargy GENERAL + mild → MODERATE (FIX2 + systemic +1 level)"""
        result, gen = _call_create(
            "слегка вялый",
            extracted_symptom="lethargy",
            extracted_symptom_class="GENERAL",
            extracted_lethargy_level="mild",
        )
        self.assertEqual(_esc(result), "MODERATE",           "S15: expected MODERATE")
        self.assertEqual(_rtype(result), "CLARIFY",           "S15: expected CLARIFY")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S15: expected clinical_escalation")


# ─────────────────────────────────────────────────────────────────────────────
# S16–S17  Blood type + GDV overrides
# ─────────────────────────────────────────────────────────────────────────────

@freeze_time("2024-06-15 12:00:00", tz_offset=0)
class TestStressBloodGDV(unittest.TestCase):

    def test_s16_coffee_ground_vomit_critical(self):
        """S16: coffee_ground_vomit → CRITICAL (blood_type_adjusted rule)"""
        result, gen = _call_create(
            "рвёт кофейной гущей",   # keyword override: coffee_ground_vomit
            extracted_symptom="vomiting",   # gets overridden by keyword
            extracted_symptom_class="GI",
            stats_mock={"today": 0, "last_hour": 0, "last_24h": 0},
        )
        self.assertEqual(_esc(result), "CRITICAL",           "S16: expected CRITICAL")
        self.assertEqual(_rtype(result), "ACTION",            "S16: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S16: expected clinical_escalation")

    def test_s17_gdv_keywords_critical(self):
        """S17: 'живот как барабан' → CRITICAL (GDV override)"""
        result, gen = _call_create(
            "живот как барабан",   # GDV keyword
            extracted_symptom=None,
            extracted_symptom_class=None,
        )
        self.assertEqual(_esc(result), "CRITICAL",           "S17: expected CRITICAL")
        self.assertEqual(_rtype(result), "ACTION",            "S17: expected ACTION")
        self.assertEqual(_dmode(gen), "clinical_escalation", "S17: expected clinical_escalation")


# ─────────────────────────────────────────────────────────────────────────────
# S18  Food context
# ─────────────────────────────────────────────────────────────────────────────

@freeze_time("2024-06-15 12:00:00", tz_offset=0)
class TestStressFoodContext(unittest.TestCase):

    def test_s18_food_in_llm_contract_known_facts(self):
        """S18: vomiting + food='банан' → food propagated to llm_contract.known_facts"""
        result, gen = _call_create(
            "рвота после банана",
            extracted_symptom="vomiting",
            extracted_symptom_class="GI",
            extracted_food="банан",
            stats_mock={"today": 0, "last_hour": 0, "last_24h": 0},
        )
        known_facts = result.get("debug", {}).get("llm_contract", {}).get("known_facts", {})
        self.assertIn("food", known_facts,
                      "S18: food must be in llm_contract.known_facts")
        self.assertEqual(known_facts["food"], "банан",
                         "S18: food value must be 'банан'")


# ─────────────────────────────────────────────────────────────────────────────
# S19–S20  No decision (off-topic / greeting)
# ─────────────────────────────────────────────────────────────────────────────

@freeze_time("2024-06-15 12:00:00", tz_offset=0)
class TestStressNoDecision(unittest.TestCase):

    def test_s19_greeting_no_debug(self):
        """S19: greeting 'привет как дела' → no clinical decision, no debug block"""
        result, gen = _call_create(
            "привет как дела",
            extracted_symptom=None,
            extracted_symptom_class=None,
        )
        self.assertNotIn("debug", result,
                         "S19: greeting must not produce a debug block")
        self.assertEqual(_dmode(gen), "normal",
                         "S19: dialogue_mode must be 'normal'")

    def test_s20_offtopic_no_debug(self):
        """S20: off-topic question → no clinical decision, no debug block"""
        result, gen = _call_create(
            "что покормить питомца",
            extracted_symptom=None,
            extracted_symptom_class=None,
        )
        self.assertNotIn("debug", result,
                         "S20: off-topic question must not produce a debug block")
        self.assertEqual(_dmode(gen), "normal",
                         "S20: dialogue_mode must be 'normal'")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestStressGI,
        TestStressRespiratory,
        TestStressIngestionToxic,
        TestStressNeuro,
        TestStressUrinary,
        TestStressAbsoluteCritical,
        TestStressGeneral,
        TestStressBloodGDV,
        TestStressFoodContext,
        TestStressNoDecision,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
