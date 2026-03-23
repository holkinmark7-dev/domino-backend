"""
Глобальный тест: полные симуляции онбординга.
Прогоняет парсер + инструкции + AI на разных сценариях.
Выявляет: неправильные шаги, бот-фразы, склонения, пол, зацикливания.
"""
import sys, os, json
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

import anthropic
from routers.onboarding_steps import _get_current_step
from routers.onboarding_parser import _parse_user_input
from routers.onboarding_instructions import _get_step_instruction
from routers.onboarding_utils import _build_system_prompt, _remove_stop_phrases, _decline_pet_name

ant = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

def get_ai_response(collected, step, instruction, msg, history):
    """Симулирует вызов AI как в onboarding_ai.py"""
    question = None
    reaction_instruction = ""
    original_instruction = instruction

    if "[QUESTION]" in instruction:
        parts = instruction.split("[QUESTION]")
        reaction_instruction = parts[0].strip()
        question = parts[1].strip()
        instruction = reaction_instruction

    is_exact = instruction.startswith("Скажи РОВНО")
    prompt = _build_system_prompt(collected, instruction, step, [], question=question)

    if is_exact:
        msgs = [{"role": "user", "content": msg or "Начни онбординг"}]
        resp = ant.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=150,
            system=prompt, messages=msgs, temperature=0.0,
        )
        return resp.content[0].text.strip()

    elif question and not reaction_instruction:
        return question

    elif question and reaction_instruction:
        msgs = []
        for h in history[-10:]:
            msgs.append(h)
        msgs.append({"role": "user", "content": msg or "Продолжай"})
        # fix alternation
        fixed = []
        for m in msgs:
            if fixed and fixed[-1]["role"] == m["role"]:
                fixed[-1]["content"] += "\n" + m["content"]
            else:
                fixed.append(m)
        if fixed and fixed[0]["role"] == "assistant":
            fixed.insert(0, {"role": "user", "content": "..."})

        resp = ant.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=80,
            system=prompt, messages=fixed, temperature=0.5,
        )
        reaction = resp.content[0].text.strip()
        reaction = _remove_stop_phrases(reaction)
        if "?" in reaction:
            reaction = reaction.split("?")[0].rstrip() + "."
        return f"{reaction}\n\n{question}"

    else:
        msgs = []
        for h in history[-20:]:
            msgs.append(h)
        msgs.append({"role": "user", "content": msg or "Начни онбординг"})
        fixed = []
        for m in msgs:
            if fixed and fixed[-1]["role"] == m["role"]:
                fixed[-1]["content"] += "\n" + m["content"]
            else:
                fixed.append(m)
        if fixed and fixed[0]["role"] == "assistant":
            fixed.insert(0, {"role": "user", "content": "..."})

        resp = ant.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=150,
            system=prompt, messages=fixed, temperature=0.5,
        )
        return resp.content[0].text.strip()


def run_scenario(name, messages):
    """Прогоняет полный сценарий."""
    print(f"\n{'='*60}")
    print(f"СЦЕНАРИЙ: {name}")
    print(f"{'='*60}")

    collected = {}
    history = []
    issues = []
    prev_step = None
    step_count = 0

    for msg in messages:
        step = _get_current_step(collected)
        step_count += 1

        if step_count > 20:
            issues.append("ЗАЦИКЛИВАНИЕ: больше 20 шагов")
            break

        if step == "complete":
            print(f"  [COMPLETE] Онбординг завершён")
            break

        # Парсинг
        updates = _parse_user_input(msg, step, collected)
        collected.update(updates)
        new_step = _get_current_step(collected)

        # Инструкция
        instruction = _get_step_instruction(new_step, collected)

        # AI ответ
        try:
            ai_text = get_ai_response(collected, new_step, instruction, msg, history)
        except Exception as e:
            ai_text = f"[ОШИБКА AI: {e}]"
            issues.append(f"AI ОШИБКА на шаге {new_step}: {e}")

        # Проверки качества
        bad = ["замечательн", "отличн", "прекрасн", "рад знакомств",
               "что привело", "было бы здорово", "хочу узнать",
               "подскажи", "спасибо", "это может повлиять",
               "приятно познаком", "это важно для"]
        for b in bad:
            if b in ai_text.lower():
                issues.append(f"БОТ-ФРАЗА '{b}' на шаге {new_step}")

        pet = collected.get("pet_name", "")
        if pet and pet.endswith(("и", "о", "у")) and pet + "а" in ai_text:
            issues.append(f"СКЛОНЕНИЕ: '{pet}а' на шаге {new_step}")

        gender = collected.get("gender", "")
        if gender == "male" and " её " in ai_text.lower():
            issues.append(f"ПОЛ: мальчик назван 'её' на шаге {new_step}")
        if gender == "самка" and " его " in ai_text.lower() and "его здоровь" not in ai_text.lower():
            issues.append(f"ПОЛ: девочка названа 'его' на шаге {new_step}")

        if ai_text and ai_text[0].islower():
            issues.append(f"МАЛЕНЬКАЯ БУКВА на шаге {new_step}")

        print(f"\n  [{step}->{new_step}] User: '{msg}'")
        print(f"  Dominik: {ai_text[:120]}")

        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": ai_text})

        if new_step == prev_step and step == prev_step:
            if not updates or all(k.startswith("_") for k in updates):
                pass  # нормально, переспрос
        prev_step = new_step

    final = _get_current_step(collected)
    collected_clean = {k:v for k,v in collected.items() if not k.startswith("_")}
    print(f"\n  ИТОГ: шаг={final}, собрано={collected_clean}")

    if final != "complete" and final != "avatar":
        issues.append(f"НЕ ДОШЁЛ ДО КОНЦА: остановился на {final}")

    if issues:
        print(f"  ПРОБЛЕМЫ:")
        for i in issues:
            print(f"    ! {i}")
    else:
        print(f"  OK БЕЗ ПРОБЛЕМ")

    return issues


# ═══════════════════════════════════════
# СЦЕНАРИИ
# ═══════════════════════════════════════

all_issues = []

# 1. Идеальный путь
issues = run_scenario("Идеальный путь", [
    "Марк", "Бобик", "Слежу за здоровьем", "Собака",
    "Лучше вручную", "Лабрадор", "25.01.2020",
    "Мальчик", "Нет", "Пропустить",
])
all_issues.extend(issues)

# 2. Путь с юмором и дичью
issues = run_scenario("Юмор и дичь", [
    "Привет привет", "А зачем тебе?", "Ну Марк",
    "Тараканы )", "Бетти", "Веду дневник", "Собака",
    "Паспорта нет", "Не знаю породу", "Пропустить",
    "Не знаю", "Девочка", "Да", "Пропустить",
])
all_issues.extend(issues)

# 3. Несклоняемые имена
issues = run_scenario("Несклоняемые: Ричи", [
    "Аня", "Ричи", "Кое-что беспокоит", "Собака",
    "Лучше вручную", "Шпиц", "Финский шпиц",
    "16.01.2020", "Мальчик", "Нет", "Пропустить",
])
all_issues.extend(issues)

# 4. Девочка — проверка пола
issues = run_scenario("Девочка Мурка — пол", [
    "Саша", "Мурка", "Слежу за здоровьем", "Кошка",
    "Паспорта нет", "Британская", "01.06.2021",
    "Да", "Пропустить",
])
all_issues.extend(issues)

# 5. Агрессивный пользователь
issues = run_scenario("Агрессивный", [
    "Отстань", "Не скажу", "Рекс",
    "Прививки и плановое", "Собака",
    "Лучше вручную", "Овчарка", "Немецкая овчарка",
    "12.03.2019", "Мальчик", "Да", "Пропустить",
])
all_issues.extend(issues)

# 6. Цифры и мусор
issues = run_scenario("Цифры и мусор", [
    "12345", "Марк", "Бобик",
    "Слежу за здоровьем", "Собака", "Лучше вручную",
    "Хаски", "25.01.2020", "Мальчик", "Нет", "Пропустить",
])
all_issues.extend(issues)

# 7. Кот Лео — несклоняемое + кот
issues = run_scenario("Кот Лео", [
    "Дима", "Лео", "Веду дневник", "Кот",
    "Паспорта нет", "Мейн-кун", "20.05.2022",
    "Да", "Пропустить",
])
all_issues.extend(issues)

# 8. Максимум информации сразу
issues = run_scenario("Всё сразу", [
    "Меня зовут Марк у меня собака Бобик лабрадор 3 года",
    "Бобик", "Слежу за здоровьем", "Собака",
    "Лучше вручную", "Лабрадор", "25.01.2022",
    "Мальчик", "Нет", "Пропустить",
])
all_issues.extend(issues)

print(f"\n{'='*60}")
print(f"ОБЩИЙ ИТОГ: {len(all_issues)} проблем в 8 сценариях")
print(f"{'='*60}")
for i in all_issues:
    print(f"  ! {i}")
if not all_issues:
    print("  OK ВСЕ СЦЕНАРИИ БЕЗ ПРОБЛЕМ")
