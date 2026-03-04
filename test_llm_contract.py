"""
test_llm_contract.py — Unit tests for LLM Contract v1
Tests: build_missing_facts() + contract_block injection in generate_ai_response()
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

# ─── Import build_missing_facts + count_questions from chat.py ───────────────
from routers.services.chat_helpers import build_missing_facts, count_questions

# ─── Import generate_ai_response from ai.py ───────────────────────────────────
import routers.services.ai as ai_module
from routers.services.ai import generate_ai_response, AIResponseRequest


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_contract(
    risk_level="MODERATE",
    response_type="CLARIFY",
    episode_phase="initial",
    known_facts=None,
    allowed_questions=None,
    max_questions=2,
):
    return {
        "risk_level": risk_level,
        "response_type": response_type,
        "episode_phase": episode_phase,
        "known_facts": known_facts or {},
        "allowed_questions": allowed_questions or [],
        "max_questions": max_questions,
    }


def _call_generate(contract, extra_system_override=None):
    """Call generate_ai_response with a mock OpenAI client; returns (system_prompt, user_prompt)."""
    captured = {}

    def fake_create(**kwargs):
        captured["messages"] = kwargs.get("messages", [])
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "Тестовый ответ без вопросов."
        return mock_resp

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    with patch.object(ai_module, "client", mock_client):
        result = generate_ai_response(AIResponseRequest(
            pet_profile={"name": "Бони", "species": "dog", "breed": "beagle", "birth_date": "2020-01-01"},
            recent_events=[],
            user_message="У Бони понос уже 3 раза за час",
            urgency_score=2,
            risk_level="moderate",
            memory_context="No prior medical history.",
            clinical_decision=None,
            dialogue_mode="normal",
            previous_assistant_text=None,
            strict_override=extra_system_override,
            llm_contract=contract,
        ))

    system_msg = captured["messages"][0]["content"] if captured.get("messages") else ""
    user_msg = captured["messages"][1]["content"] if len(captured.get("messages", [])) > 1 else ""
    return system_msg, user_msg, result


# ═════════════════════════════════════════════════════════════════════════════
# Section 1 — build_missing_facts() unit tests
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildMissingFacts(unittest.TestCase):

    def test_empty_dict_returns_blood_and_drinking(self):
        result = build_missing_facts({})
        self.assertIn("blood", result)
        self.assertIn("drinking", result)

    def test_blood_present_not_in_missing(self):
        result = build_missing_facts({"blood": False})
        self.assertNotIn("blood", result)

    def test_refusing_water_present_not_in_missing(self):
        result = build_missing_facts({"refusing_water": False})
        self.assertNotIn("drinking", result)

    def test_diarrhea_adds_vomiting_question(self):
        result = build_missing_facts({"symptom": "diarrhea"})
        self.assertIn("vomiting", result)

    def test_diarrhea_vomiting_known_no_duplicate(self):
        result = build_missing_facts({"symptom": "diarrhea", "vomiting": True})
        self.assertNotIn("vomiting", result)

    def test_vomiting_adds_diarrhea_question(self):
        result = build_missing_facts({"symptom": "vomiting"})
        self.assertIn("diarrhea", result)

    def test_vomiting_diarrhea_known_no_duplicate(self):
        result = build_missing_facts({"symptom": "vomiting", "diarrhea": False})
        self.assertNotIn("diarrhea", result)

    def test_non_dict_returns_empty(self):
        self.assertEqual(build_missing_facts(None), [])
        self.assertEqual(build_missing_facts("bad"), [])
        self.assertEqual(build_missing_facts(42), [])

    def test_result_is_list(self):
        result = build_missing_facts({"symptom": "diarrhea"})
        self.assertIsInstance(result, list)

    def test_no_duplicates(self):
        result = build_missing_facts({})
        self.assertEqual(len(result), len(set(result)))


# ═════════════════════════════════════════════════════════════════════════════
# Section 2 — contract_block injection in generate_ai_response()
# ═════════════════════════════════════════════════════════════════════════════

class TestContractBlockInjection(unittest.TestCase):

    # T1 — Known Facts Guard: "blood: False" in known_facts → system must mention it
    def test_t1_known_facts_in_system_prompt(self):
        contract = _make_contract(
            known_facts={"blood": False},
            allowed_questions=["drinking"],
            max_questions=1,
        )
        system_msg, _, _ = _call_generate(contract)
        self.assertIn("KNOWN FACTS", system_msg)
        self.assertIn("blood", system_msg)
        self.assertIn("DO NOT ASK ABOUT THESE", system_msg)

    # T2 — Max Questions Guard: max_questions=0 injected when ACTION
    def test_t2_max_questions_zero_for_action(self):
        contract = _make_contract(
            response_type="ACTION",
            max_questions=0,
            known_facts={"symptom": "vomiting"},
            allowed_questions=[],
        )
        system_msg, _, _ = _call_generate(contract)
        self.assertIn("MAX QUESTIONS ALLOWED", system_msg)
        self.assertIn("0", system_msg)

    # T3 — Allowed Questions Guard: only allowed questions shown
    def test_t3_allowed_questions_in_system_prompt(self):
        contract = _make_contract(
            known_facts={"blood": False, "refusing_water": False},
            allowed_questions=["vomiting"],
            max_questions=1,
        )
        system_msg, _, _ = _call_generate(contract)
        self.assertIn("ALLOWED QUESTIONS", system_msg)
        self.assertIn("vomiting", system_msg)

    # T4 — Escalation Obedience: risk_level=MODERATE appears in contract_block
    def test_t4_risk_level_in_system_prompt(self):
        contract = _make_contract(risk_level="MODERATE")
        system_msg, _, _ = _call_generate(contract)
        self.assertIn("Risk level: MODERATE", system_msg)
        self.assertIn("MUST NOT escalate beyond provided Risk level", system_msg)

    # Contract block appears after the Russian language rule
    def test_contract_block_after_language_rule(self):
        contract = _make_contract(known_facts={"symptom": "diarrhea"})
        system_msg, _, _ = _call_generate(contract)
        contract_pos = system_msg.find("LLM CONTRACT")
        language_pos = system_msg.find("Отвечай ТОЛЬКО на русском языке")
        self.assertGreater(contract_pos, language_pos)

    # No contract → no LLM CONTRACT section in system prompt
    def test_no_contract_no_block(self):
        captured = {}

        def fake_create(**kwargs):
            captured["messages"] = kwargs.get("messages", [])
            mock_resp = MagicMock()
            mock_resp.choices[0].message.content = "ok"
            return mock_resp

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = fake_create

        with patch.object(ai_module, "client", mock_client):
            generate_ai_response(AIResponseRequest(
                pet_profile={"name": "X", "species": "dog", "breed": "lab", "birth_date": "2020-01-01"},
                recent_events=[],
                user_message="test",
                llm_contract=None,
            ))

        system_msg = captured["messages"][0]["content"]
        self.assertNotIn("LLM CONTRACT", system_msg)

    # Known facts formatted as bullet list
    def test_known_facts_formatted_as_bullets(self):
        contract = _make_contract(
            known_facts={"blood": False, "symptom": "diarrhea"},
            allowed_questions=[],
        )
        system_msg, _, _ = _call_generate(contract)
        self.assertIn("- blood:", system_msg)
        self.assertIn("- symptom:", system_msg)

    # Allowed questions formatted as bullet list
    def test_allowed_questions_formatted_as_bullets(self):
        contract = _make_contract(
            allowed_questions=["vomiting", "drinking"],
        )
        system_msg, _, _ = _call_generate(contract)
        self.assertIn("- vomiting", system_msg)
        self.assertIn("- drinking", system_msg)

    # Empty known_facts → "None" shown
    def test_empty_known_facts_shows_none(self):
        contract = _make_contract(known_facts={}, allowed_questions=[])
        system_msg, _, _ = _call_generate(contract)
        # "None" appears after KNOWN FACTS block
        self.assertIn("None", system_msg)

    # Strict rules section present
    def test_strict_rules_present(self):
        contract = _make_contract()
        system_msg, _, _ = _call_generate(contract)
        self.assertIn("STRICT RULES", system_msg)
        self.assertIn("MUST NOT ask about known facts", system_msg)


# ═════════════════════════════════════════════════════════════════════════════
# Section 3 — Smoke test: Бони с поносом
# ═════════════════════════════════════════════════════════════════════════════

class TestSmokeBonya(unittest.TestCase):

    def setUp(self):
        # Сценарий: понос 3 раза за час, blood=False, refusing_water=False
        self.structured_data = {
            "symptom": "diarrhea",
            "blood": False,
            "refusing_water": False,
        }
        self.contract = {
            "risk_level": "MODERATE",
            "response_type": "CLARIFY",
            "episode_phase": "ongoing",
            "known_facts": {
                "symptom": "diarrhea",
                "blood": False,
                "refusing_water": False,
            },
            "allowed_questions": ["vomiting"],  # только этот вопрос допустим
            "max_questions": 2,
        }

    def test_smoke_known_facts_in_contract_block(self):
        system_msg, _, _ = _call_generate(self.contract)
        # blood и refusing_water должны быть в KNOWN FACTS
        self.assertIn("blood", system_msg)
        self.assertIn("refusing_water", system_msg)

    def test_smoke_allowed_only_vomiting(self):
        system_msg, _, _ = _call_generate(self.contract)
        # Только vomiting в ALLOWED QUESTIONS
        self.assertIn("vomiting", system_msg)

    def test_smoke_max_questions_two(self):
        system_msg, _, _ = _call_generate(self.contract)
        self.assertIn("MAX QUESTIONS ALLOWED", system_msg)
        self.assertIn("2", system_msg)

    def test_smoke_risk_moderate_not_critical(self):
        system_msg, _, _ = _call_generate(self.contract)
        self.assertIn("MODERATE", system_msg)
        # CRITICAL не должен фигурировать в contract_block
        self.assertNotIn("Risk level: CRITICAL", system_msg)

    def test_build_missing_facts_smoke(self):
        # Понос + blood и refusing_water уже известны → только vomiting в missing
        result = build_missing_facts(self.structured_data)
        self.assertNotIn("blood", result)
        self.assertNotIn("drinking", result)
        self.assertIn("vomiting", result)


# ═════════════════════════════════════════════════════════════════════════════
# Section 4 — MAX QUESTIONS ENFORCEMENT GUARD
# Tests the guard logic extracted from create_chat_message()
# ═════════════════════════════════════════════════════════════════════════════

def _run_guard(first_response: str, contract: dict, regen_response: str = "Чистый ответ."):
    """
    Simulate the guard block from create_chat_message():
      1. Call generate_ai_response → first_response (mocked)
      2. Run MAX QUESTIONS ENFORCEMENT GUARD
      3. If triggered → call generate_ai_response again → regen_response (mocked)
    Returns (final_response, question_guard_triggered, call_count)
    """
    call_results = iter([first_response, regen_response])
    call_count = 0

    def fake_generate(**kwargs):
        nonlocal call_count
        call_count += 1
        return next(call_results)

    with patch.object(ai_module, "generate_ai_response", side_effect=fake_generate):
        # Simulate the guard block directly
        from routers.services.ai import generate_ai_response as gen

        # First call (already done before guard in real code)
        ai_response = fake_generate()

        # Guard block
        question_guard_triggered = False
        if contract:
            max_q = contract.get("max_questions", 0)
            if isinstance(max_q, int) and max_q >= 0:
                actual_q = ai_response.count("?")
                if actual_q > max_q:
                    question_guard_triggered = True
                    ai_response = fake_generate()

    return ai_response, question_guard_triggered, call_count


class TestMaxQuestionsGuard(unittest.TestCase):

    # Guard Test 1: max_questions=0, response has "?" → guard_triggered=True
    def test_guard_triggered_when_zero_max_and_question_present(self):
        contract = _make_contract(max_questions=0)
        first = "Как давно это началось?"
        final, triggered, _ = _run_guard(first, contract)
        self.assertTrue(triggered)

    # Guard Test 2: max_questions=2, AI gives 3 questions → regenerate
    def test_guard_triggers_regen_when_exceeds_max(self):
        contract = _make_contract(max_questions=2)
        first = "Как давно? Есть рвота? Пьёт воду?"  # 3 вопроса
        regen = "Расскажите подробнее о симптомах."    # 0 вопросов
        final, triggered, call_count = _run_guard(first, contract, regen_response=regen)
        self.assertTrue(triggered)
        self.assertEqual(final, regen)
        # Total calls: 1 (first) + 1 (regen) = 2
        self.assertEqual(call_count, 2)

    # Guard Test 2b: regenerated response has ≤ max_questions "?" characters
    def test_regen_response_within_limit(self):
        contract = _make_contract(max_questions=2)
        first = "Как давно? Есть рвота? Пьёт воду?"  # 3 вопроса
        regen = "Есть ли рвота?"                       # 1 вопрос — в пределах
        final, triggered, _ = _run_guard(first, contract, regen_response=regen)
        self.assertTrue(triggered)
        self.assertLessEqual(final.count("?"), 2)

    # Guard Test 3: max_questions=2, AI gives 1 question → guard NOT triggered
    def test_guard_not_triggered_when_within_limit(self):
        contract = _make_contract(max_questions=2)
        first = "Есть ли у питомца рвота?"  # 1 вопрос
        final, triggered, call_count = _run_guard(first, contract)
        self.assertFalse(triggered)
        self.assertEqual(final, first)       # ответ не изменён
        self.assertEqual(call_count, 1)      # второй вызов не произошёл

    # Guard skipped when llm_contract is None
    def test_guard_skipped_without_contract(self):
        first = "Как давно? Есть рвота? Пьёт воду?"
        final, triggered, call_count = _run_guard(first, contract=None)
        self.assertFalse(triggered)
        self.assertEqual(final, first)
        self.assertEqual(call_count, 1)

    # max_questions=0, response has NO "?" → not triggered
    def test_guard_not_triggered_when_no_questions_and_zero_max(self):
        contract = _make_contract(max_questions=0)
        first = "Уберите корм на 8 часов."
        final, triggered, _ = _run_guard(first, contract)
        self.assertFalse(triggered)

    # Exact boundary: actual_q == max_q → NOT triggered
    def test_guard_not_triggered_at_exact_boundary(self):
        contract = _make_contract(max_questions=2)
        first = "Есть рвота? Пьёт воду?"  # ровно 2 вопроса
        final, triggered, _ = _run_guard(first, contract)
        self.assertFalse(triggered)

    # One over boundary → triggered
    def test_guard_triggered_one_over_boundary(self):
        contract = _make_contract(max_questions=2)
        first = "Есть рвота? Пьёт воду? Вялый?"  # 3 = 2+1
        final, triggered, _ = _run_guard(first, contract)
        self.assertTrue(triggered)


# ═════════════════════════════════════════════════════════════════════════════
# Section 5 — Smoke test: Бони, понос, known facts → guard не срабатывает
# ═════════════════════════════════════════════════════════════════════════════

class TestSmokeGuardBonya(unittest.TestCase):

    def setUp(self):
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

    def test_smoke_single_question_no_guard(self):
        # Хороший ответ: 1 вопрос (в пределах max=2)
        first = "Есть ли рвота?"
        final, triggered, call_count = _run_guard(first, self.contract)
        self.assertFalse(triggered)
        self.assertEqual(call_count, 1)
        self.assertLessEqual(final.count("?"), 2)

    def test_smoke_three_questions_triggers_guard(self):
        # Плохой ответ: 3 вопроса → guard срабатывает
        first = "Есть рвота? Пьёт воду? Как давно?"
        regen = "Расскажите о наличии рвоты."
        final, triggered, call_count = _run_guard(first, self.contract, regen_response=regen)
        self.assertTrue(triggered)
        self.assertEqual(call_count, 2)

    def test_smoke_no_critical_in_contract(self):
        # При MODERATE contract_block не содержит CRITICAL
        system_msg, _, _ = _call_generate(self.contract)
        self.assertNotIn("Risk level: CRITICAL", system_msg)


# ═════════════════════════════════════════════════════════════════════════════
# Section 6 — DOUBLE-PASS MAX QUESTIONS ENFORCEMENT (DAY 1.2)
# Simulates the updated guard: 2 regen attempts + final fallback replace
# ═════════════════════════════════════════════════════════════════════════════

def _run_guard_v2(first_response: str, contract: dict, regen_responses: list = None):
    """
    Simulate the Day 1.2 guard block (double-pass + fallback):
      - first_response: the initial ai_response
      - regen_responses: list of responses for successive regen calls (up to 2)
    Returns (final_response, question_guard_triggered, regen_call_count)
    """
    if regen_responses is None:
        regen_responses = ["Чистый ответ."]

    regen_iter = iter(regen_responses)
    regen_call_count = 0

    def fake_regen(**kwargs):
        nonlocal regen_call_count
        regen_call_count += 1
        try:
            return next(regen_iter)
        except StopIteration:
            return "Fallback ответ."

    ai_response = first_response
    question_guard_triggered = False

    if contract:
        max_q = contract.get("max_questions", 0)
        if isinstance(max_q, int) and max_q >= 0:
            for _ in range(2):
                actual_q = ai_response.count("?")
                if actual_q <= max_q:
                    break
                question_guard_triggered = True
                ai_response = fake_regen()
            # финальный аварийный fallback
            if ai_response.count("?") > max_q:
                question_guard_triggered = True
                ai_response = ai_response.replace("?", ".")

    return ai_response, question_guard_triggered, regen_call_count


class TestDoublePassGuard(unittest.TestCase):

    # Test 1 — Double violation: both regen attempts fail → fallback replaces "?"
    def test_double_violation_fallback_applied(self):
        contract = _make_contract(max_questions=1)
        first = "Как давно? Есть рвота? Вялый?"   # 3 вопроса
        regen1 = "Есть рвота? Пьёт воду?"           # 2 вопроса — iter 1, still > 1
        regen2 = "Вялый? Пьёт?"                     # 2 вопроса — iter 2, still > 1
        final, triggered, call_count = _run_guard_v2(first, contract, [regen1, regen2])
        # guard triggered
        self.assertTrue(triggered)
        # loop made 2 regen calls
        self.assertEqual(call_count, 2)
        # fallback applied after loop → final must have ≤ max_q "?"
        self.assertLessEqual(final.count("?"), 1)

    # Test 2 — Double violation (two regen calls, second also fails) → fallback
    def test_two_regen_calls_then_fallback(self):
        contract = _make_contract(max_questions=0)
        first = "Есть рвота?"     # 1 вопрос (> 0)
        regen1 = "Вялый?"         # iter 1: 1 вопрос (> 0)
        regen2 = "Пьёт воду?"     # iter 2: 1 вопрос (> 0)
        final, triggered, call_count = _run_guard_v2(first, contract, [regen1, regen2])
        self.assertTrue(triggered)
        # loop made 2 regen calls
        self.assertEqual(call_count, 2)
        # fallback: replace("?", ".") → no "?" left
        self.assertEqual(final.count("?"), 0)

    # Test 3 — Clean path: first response within limit → no regen at all
    def test_clean_path_no_regen(self):
        contract = _make_contract(max_questions=2)
        first = "Есть ли рвота?"   # 1 вопрос (≤ 2)
        final, triggered, call_count = _run_guard_v2(first, contract)
        self.assertFalse(triggered)
        self.assertEqual(final, first)
        self.assertEqual(call_count, 0)

    # Test 4 — Zero questions max: response with "?" → fallback cleans it
    def test_zero_max_question_cleaned_by_fallback(self):
        contract = _make_contract(max_questions=0)
        first = "Как давно это началось?"   # 1 вопрос
        regen1 = "Расскажите подробнее?"    # ещё 1 вопрос
        final, triggered, call_count = _run_guard_v2(first, contract, [regen1])
        self.assertTrue(triggered)
        self.assertEqual(final.count("?"), 0)  # fallback убрал все "?"

    # Test 5 — First regen fixes it: exactly one regen call, no fallback
    def test_first_regen_succeeds(self):
        contract = _make_contract(max_questions=1)
        first = "Как давно? Есть рвота?"   # 2 вопроса (> 1)
        regen1 = "Есть ли рвота?"           # 1 вопрос (= max, OK)
        final, triggered, call_count = _run_guard_v2(first, contract, [regen1])
        self.assertTrue(triggered)
        self.assertEqual(final, regen1)
        self.assertEqual(call_count, 1)
        self.assertLessEqual(final.count("?"), 1)

    # Test 6 — Contract None → guard never runs
    def test_no_contract_guard_skipped(self):
        first = "Как давно? Есть рвота? Вялый?"
        final, triggered, call_count = _run_guard_v2(first, contract=None)
        self.assertFalse(triggered)
        self.assertEqual(final, first)
        self.assertEqual(call_count, 0)

    # Smoke test: Бони, понос, max=2, 1 вопрос → guard не срабатывает
    def test_smoke_bonya_within_limit(self):
        contract = {
            "risk_level": "MODERATE",
            "response_type": "CLARIFY",
            "episode_phase": "ongoing",
            "known_facts": {"symptom": "diarrhea", "blood": False, "refusing_water": False},
            "allowed_questions": ["vomiting"],
            "max_questions": 2,
        }
        first = "Есть ли рвота?"  # 1 вопрос ≤ 2
        final, triggered, call_count = _run_guard_v2(first, contract)
        self.assertFalse(triggered)
        self.assertLessEqual(final.count("?"), 2)
        self.assertEqual(call_count, 0)


# ═════════════════════════════════════════════════════════════════════════════
# Section 7 — count_questions() unit tests (DAY 1.3)
# ═════════════════════════════════════════════════════════════════════════════

class TestCountQuestions(unittest.TestCase):

    # T1: consecutive "???" counts as ONE question
    def test_consecutive_question_marks_count_as_one(self):
        self.assertEqual(count_questions("Что происходит???"), 1)

    # T1b: many consecutive in a row still one
    def test_many_consecutive_still_one(self):
        self.assertEqual(count_questions("Правда?????"), 1)

    # T2: two distinct questions count as 2
    def test_two_real_questions(self):
        self.assertEqual(count_questions("Есть ли кровь? Пьёт ли воду?"), 2)

    # T3: question inside double quotes is ignored
    def test_question_inside_quotes_ignored(self):
        self.assertEqual(count_questions('Он сказал "что делать?" и убежал.'), 0)

    # T3b: question outside quotes still counted, inside ignored
    def test_mixed_quoted_and_real(self):
        self.assertEqual(count_questions('Он сказал "что делать?" и убежал. Как он?'), 1)

    # T4: question inside markdown code block is ignored
    def test_question_in_markdown_code_block_ignored(self):
        text = 'Вот код:\n```python\nprint("Что?")\n```\nЕсть ли кровь?'
        self.assertEqual(count_questions(text), 1)

    # T4b: code block with multiple "?" only exposes outside ones
    def test_multiple_in_code_block_only_outside_counts(self):
        text = '```python\nx = "а?" if y else "б?"\n```\nЕсть ли рвота? Пьёт воду?'
        self.assertEqual(count_questions(text), 2)

    # T5: no questions → 0
    def test_clean_text_no_questions(self):
        self.assertEqual(count_questions("Уберите корм на 8 часов. Давайте воду."), 0)

    # T5b: empty string → 0
    def test_empty_string(self):
        self.assertEqual(count_questions(""), 0)

    # non-string → 0
    def test_non_string_input(self):
        self.assertEqual(count_questions(None), 0)
        self.assertEqual(count_questions(42), 0)
        self.assertEqual(count_questions([]), 0)

    # Smoke: Бони ответ — один вопрос про рвоту
    def test_smoke_bonya_one_question(self):
        text = "Ваша кошка уже трижды сходила в туалет за час. Есть ли у неё рвота?"
        self.assertEqual(count_questions(text), 1)

    # Smoke: ACTION ответ — ноль вопросов
    def test_smoke_action_no_questions(self):
        text = (
            "1. Уберите корм на 8–12 часов.\n"
            "2. Давайте небольшие порции воды каждые 30 минут.\n"
            "3. Следите за появлением крови.\n"
            "4. Если рвота продолжается — обратитесь к ветеринару."
        )
        self.assertEqual(count_questions(text), 0)

    # Boundary: collapsed ??? + real question = 2 logical questions total
    def test_collapsed_plus_real(self):
        self.assertEqual(count_questions("Вялый??? Пьёт воду?"), 2)


# ═════════════════════════════════════════════════════════════════════════════
# Section 8 — Unicode Quote Hardening (DAY 1.4)
# ═════════════════════════════════════════════════════════════════════════════

class TestUnicodeQuoteHardening(unittest.TestCase):

    # T1: Russian guillemets «...»
    def test_russian_guillemets_ignored(self):
        self.assertEqual(count_questions("Он сказал \u00abчто делать?\u00bb и убежал."), 0)

    # T2: ASCII single quotes '...'
    def test_single_quotes_ignored(self):
        self.assertEqual(count_questions("Он спросил 'что делать?' и молчит."), 0)

    # T3: Typographic double quotes \u201c...\u201d
    def test_typographic_double_quotes_ignored(self):
        self.assertEqual(count_questions("\u201cчто теперь?\u201d — он ушёл."), 0)

    # T4: Mixed — Russian guillemet quoted + real question outside
    def test_mixed_russian_quote_and_real(self):
        self.assertEqual(count_questions("Он сказал \u00abчто делать?\u00bb А теперь как он?"), 1)

    # T5: Nested minimal — inner quote inside outer (surface-level safe)
    def test_nested_quotes_outer_removed(self):
        # Outer «...» removes the whole chunk including inner content; real question remains
        text = "Он сказал \u00abона спросила \u201cчто делать?\u201d\u00bb\nЕсть ли кровь?"
        self.assertEqual(count_questions(text), 1)

    # T6: Typographic single quotes \u2018...\u2019
    def test_typographic_single_quotes_ignored(self):
        self.assertEqual(count_questions("\u2018что это?\u2019 — неизвестно."), 0)

    # T7: Question outside after closing guillemet still counted
    def test_question_after_guillemet_counted(self):
        self.assertEqual(count_questions("\u00abвсё хорошо\u00bb? Есть ли рвота?"), 2)

    # T8: Multiple quote styles in one string
    def test_multiple_quote_styles_all_ignored(self):
        text = (
            "\u00abчто?\u00bb "       # Russian «что?» → stripped
            "\u201cкак?\u201d "       # Typographic "как?" → stripped
            "Пьёт ли воду?"            # real question
        )
        self.assertEqual(count_questions(text), 1)

    # Smoke: Бони — ответ с типографскими кавычками не создаёт ложных вопросов
    def test_smoke_bonya_typographic_no_false_positive(self):
        text = (
            "\u201cСобака хорошо себя чувствует\u201d — не причина для беспокойства. "
            "Есть ли у неё рвота?"
        )
        self.assertEqual(count_questions(text), 1)


if __name__ == "__main__":
    import unittest
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestBuildMissingFacts))
    suite.addTests(loader.loadTestsFromTestCase(TestContractBlockInjection))
    suite.addTests(loader.loadTestsFromTestCase(TestSmokeBonya))
    suite.addTests(loader.loadTestsFromTestCase(TestMaxQuestionsGuard))
    suite.addTests(loader.loadTestsFromTestCase(TestSmokeGuardBonya))
    suite.addTests(loader.loadTestsFromTestCase(TestDoublePassGuard))
    suite.addTests(loader.loadTestsFromTestCase(TestCountQuestions))
    suite.addTests(loader.loadTestsFromTestCase(TestUnicodeQuoteHardening))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-'*60}")
    print(f"TOTAL: {passed}/{total} PASS")
