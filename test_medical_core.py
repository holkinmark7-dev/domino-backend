import requests
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

URL = "http://localhost:8000/chat"

# Real pet/user IDs — unique pet per scenario to avoid cross-contamination
# PET_S1: 0 vomiting events, PET_S2: 0 vomiting events, PET_S3: ~1 vomiting event
PET_S1  = "7d6da31c-407b-4665-9c09-ba05be61d49b"
PET_S2  = "22222222-2222-2222-2222-222222222222"
PET_S3  = "0575f811-f9b4-49df-a1a9-37acb5df7cdb"

USER_S1 = "11111111-1111-1111-1111-111111111111"
USER_S2 = "11111111-1111-1111-1111-111111111111"
USER_S3 = "11111111-1111-1111-1111-111111111111"


def send_message(user_id, pet_id, message):
    try:
        r = requests.post(
            URL,
            json={"user_id": user_id, "pet_id": pet_id, "message": message},
            timeout=15
        )
        data = r.json()
        return data.get("ai_response", f"ОШИБКА: нет ai_response. Ключи: {list(data.keys())}")
    except Exception as e:
        return f"ОШИБКА: {e}"


def test_scenario_1():
    """
    Build up to CRITICAL (3 vomiting events in last hour), then
    combine symptom + 'что делать' in one message.
    Expected: response_type=ACTION → no questions, action steps.
    """
    print("=" * 60)
    print("СЦЕНАРИЙ 1: CRITICAL + 'что делать'")
    print("Логика: 3 сообщения с рвотой → last_hour=3 → CRITICAL")
    print("         3-е сообщение: 'рвёт снова что делать'")
    print("         user_intent=SEEKING_ACTION → response_type=ACTION")
    print("=" * 60)

    print(f'\n[1/3] "собака рвёт"')
    r1 = send_message(USER_S1, PET_S1, "собака рвёт")
    print(f"Бот: {r1[:150]}...")

    print(f'\n[2/3] "рвота снова"')
    r2 = send_message(USER_S1, PET_S1, "рвота снова")
    print(f"Бот: {r2[:150]}...")

    print(f'\n[3/3] "рвёт снова что делать" ← проверяем этот ответ')
    r3 = send_message(USER_S1, PET_S1, "рвёт снова что делать")
    print(f"Бот:\n{r3}")

    has_question = "?" in r3
    action_words = ["немедленно", "срочно", "сейчас", "шаг", "обратитесь",
                    "позвоните", "действуйте", "сделайте", "первое", "второе"]
    has_action_words = any(w in r3.lower() for w in action_words)

    print(f"\n{'─' * 60}")
    if not has_question and has_action_words:
        print("ТЕСТ ПРОЙДЕН: Нет вопросов, есть призыв к действию")
        return True
    else:
        print("ТЕСТ ПРОВАЛЕН:")
        if has_question:
            print("   - Бот задаёт вопросы вместо действий!")
        if not has_action_words:
            print("   - Нет слов о действиях! (проверяются:", action_words[:4], "...)")
        return False


def test_scenario_2():
    """
    Build up to CRITICAL, then combine symptom + constraint in one message.
    'нет клиники' + 'далеко до ветеринара' trigger constraint=no_vet_access.
    Expected: response_type=ACTION_HOME_PROTOCOL → home steps + mention vet ASAP.
    """
    print("\n" + "=" * 60)
    print("СЦЕНАРИЙ 2: CRITICAL + нет доступа к ветеринару")
    print("Логика: 3 сообщения с рвотой → last_hour=3 → CRITICAL")
    print("         3-е сообщение: симптом + 'нет клиники далеко до ветеринара'")
    print("         constraint=no_vet_access → response_type=ACTION_HOME_PROTOCOL")
    print("=" * 60)

    print(f'\n[1/3] "собака рвёт"')
    r1 = send_message(USER_S2, PET_S2, "собака рвёт")
    print(f"Бот: {r1[:150]}...")

    print(f'\n[2/3] "рвота снова"')
    r2 = send_message(USER_S2, PET_S2, "рвота снова")
    print(f"Бот: {r2[:150]}...")

    print(f'\n[3/3] "рвёт снова нет клиники рядом далеко до ветеринара" ← проверяем')
    r3 = send_message(USER_S2, PET_S2, "рвёт снова нет клиники рядом далеко до ветеринара")
    print(f"Бот:\n{r3}")

    home_words = ["дома", "самостоятельно", "стабилизация", "до врача",
                  "как можно скорее", "ветеринар", "покой", "вода", "не кормите"]
    has_home_protocol = any(w in r3.lower() for w in home_words)
    no_questions = "?" not in r3

    print(f"\n{'─' * 60}")
    if has_home_protocol and no_questions:
        print("ТЕСТ ПРОЙДЕН: Домашний протокол, нет вопросов")
        return True
    else:
        print("ТЕСТ ПРОВАЛЕН:")
        if not has_home_protocol:
            print("   - Нет домашнего протокола! (проверяются:", home_words[:4], "...)")
        if not no_questions:
            print("   - Есть вопросы!")
        return False


def test_scenario_3():
    """
    Single vomiting message on a pet with low history.
    Expected: response_type=ASSESS → clarifying questions (data gathering).
    """
    print("\n" + "=" * 60)
    print("СЦЕНАРИЙ 3: LOW — сбор данных")
    print("Логика: first/second episode → LOW → response_type=ASSESS → вопросы")
    print("=" * 60)

    print(f'\n[1/1] "собака рвёт"')
    r1 = send_message(USER_S3, PET_S3, "собака рвёт")
    print(f"Бот:\n{r1}")

    has_questions = "?" in r1
    gathering_words = ["сколько", "когда", "кровь", "цвет", "уточните",
                       "как", "есть ли", "изменилось", "пьёт", "ел"]
    has_gathering = any(w in r1.lower() for w in gathering_words)

    print(f"\n{'─' * 60}")
    if has_questions or has_gathering:
        print("ТЕСТ ПРОЙДЕН: Бот собирает данные (как должно быть)")
        return True
    else:
        print("ТЕСТ ПРОВАЛЕН: Бот не задаёт уточняющих вопросов!")
        return False


def main():
    print("ЗАПУСК ТЕСТОВ МЕДИЦИНСКОГО ЯДРА")
    print(f"URL: {URL}")
    print("=" * 60)

    results = []

    results.append(("CRITICAL + действие (ACTION)", test_scenario_1()))
    results.append(("CRITICAL + нет врача (ACTION_HOME_PROTOCOL)", test_scenario_2()))
    results.append(("LOW + сбор данных (ASSESS)", test_scenario_3()))

    print("\n" + "=" * 60)
    print("ИТОГОВЫЙ ОТЧЁТ")
    print("=" * 60)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)

    for name, ok in results:
        icon = "OK" if ok else "FAIL"
        print(f"[{icon}] {name}")

    print(f"\nВсего: {passed}/{total} тестов пройдено")

    if passed == total:
        print("Все тесты пройдены! Мед-ядро работает.")
    else:
        print("Есть проблемы. Смотри детали выше.")


if __name__ == "__main__":
    main()
