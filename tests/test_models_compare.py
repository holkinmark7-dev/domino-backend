import sys, os
sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv()

import openai
import anthropic
from routers.onboarding_ai import _CHARACTER_TEXT, _get_step_instruction, _build_system_prompt

# Тестовые сценарии: шаг + collected + сообщение пользователя
scenarios = [
    ("owner_name переспрос", "owner_name", "Привет привет",
     {"_input_hint": "x", "_owner_name_refusals": 1}),

    ("owner_name грубость", "owner_name", "Отстань, не скажу",
     {"_input_hint": "x", "_owner_name_refusals": 2}),

    ("pet_name простое", "pet_name", "Бобик",
     {"owner_name": "Марк"}),

    ("pet_name история", "pet_name", "У меня собака, подобрал на улице",
     {"owner_name": "Марк"}),

    ("pet_name юмор", "pet_name", "Тараканы )",
     {"owner_name": "Марк"}),

    ("pet_name не знаю", "pet_name", "Не знаю ещё имя",
     {"owner_name": "Марк"}),

    ("goal", "goal", "Слежу за здоровьем",
     {"owner_name": "Марк", "pet_name": "Бобик"}),

    ("breed дефолт", "breed", "Хаски",
     {"owner_name": "Марк", "pet_name": "Бобик", "species": "dog",
      "goal": "Слежу за здоровьем", "_passport_skipped": True}),

    ("gender", "gender", "",
     {"owner_name": "Марк", "pet_name": "Бобик", "species": "dog",
      "breed": "Хаски", "age_years": 3, "_detected_gender_hint": "male"}),

    ("is_neutered девочка", "is_neutered", "",
     {"owner_name": "Аня", "pet_name": "Мурка", "species": "cat",
      "gender": "female"}),
]

def call_gpt(system_prompt, user_msg):
    oai = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    resp = oai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg or "Начни"},
        ],
        max_tokens=150, temperature=0.5,
    )
    return (resp.choices[0].message.content or "").strip()

def call_haiku(system_prompt, user_msg):
    ant = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    resp = ant.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg or "Начни"}],
        temperature=0.5,
    )
    return resp.content[0].text.strip()

def call_deepseek(system_prompt, user_msg):
    ds = openai.OpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com"
    )
    resp = ds.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg or "Начни"},
        ],
        max_tokens=150, temperature=0.5,
    )
    return (resp.choices[0].message.content or "").strip()

print("=" * 70)
print("СРАВНЕНИЕ: GPT-4o vs Claude Haiku vs DeepSeek V3")
print("=" * 70)

for name, step, msg, collected in scenarios:
    instruction = _get_step_instruction(step, collected)
    qr = []  # пустые кнопки для теста
    prompt = _build_system_prompt(collected, instruction, step, qr)

    print(f"\n{'─' * 60}")
    print(f"[{name}] User: '{msg}'")

    try:
        gpt = call_gpt(prompt, msg)
        print(f"  GPT-4o:    {gpt}")
    except Exception as e:
        print(f"  GPT-4o:    ОШИБКА: {e}")

    try:
        haiku = call_haiku(prompt, msg)
        print(f"  Haiku:     {haiku}")
    except Exception as e:
        print(f"  Haiku:     ОШИБКА: {e}")

    try:
        ds = call_deepseek(prompt, msg)
        print(f"  DeepSeek:  {ds}")
    except Exception as e:
        print(f"  DeepSeek:  ОШИБКА: {e}")

print(f"\n{'=' * 70}")
print("СРАВНИ СТИЛЬ — кто звучит как друг, а кто как бот?")
