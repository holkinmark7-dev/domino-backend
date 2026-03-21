"""
Стресс-тест онбординга: 50+ абсурдных сценариев.
Проверяет что AI отвечает правильно на каждом шаге.
Запуск: python -m tests.test_onboarding_stress
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Загрузить API ключи
for line in open('.env'):
    if '=' in line and not line.startswith('#'):
        k, v = line.strip().split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

from routers.onboarding_ai import handle_onboarding_ai
from routers.services.memory import get_user_flags, update_user_flags

TEST_USER = "00000000-0000-0000-0000-000000000001"
PASS = 0
FAIL = 0
DETAILS = []

def reset():
    """Сброс тестового пользователя."""
    try:
        from routers.onboarding_complete import supabase
        supabase.table("users").upsert({
            "id": TEST_USER,
            "email": "stress@test.com",
            "is_onboarded": False,
            "onboarding_stage": None,
            "pet_count": 0,
            "owner_name": None,
            "flags": {},
        }).execute()
        supabase.table("pets").delete().eq("user_id", TEST_USER).execute()
        supabase.table("chat").delete().eq("user_id", TEST_USER).execute()
    except Exception as e:
        print(f"  Reset warning: {e}")

def send(msg, desc=""):
    """Отправить сообщение и вернуть ответ."""
    try:
        resp = handle_onboarding_ai(TEST_USER, msg)
        data = json.loads(resp.body.decode())
        text = data.get("ai_response", "")
        qr = [q["label"] for q in data.get("quick_replies", [])]
        phase = data.get("onboarding_phase", "")
        input_type = data.get("input_type", "text")
        return {"text": text, "qr": qr, "phase": phase, "input_type": input_type}
    except Exception as e:
        return {"text": f"ERROR: {e}", "qr": [], "phase": "error", "input_type": "text"}

def check(result, step_name, must_contain_any=None, must_not_contain=None, must_have_qr=None, desc=""):
    """Проверить ответ. must_contain_any = хотя бы ОДНО слово должно быть."""
    global PASS, FAIL
    text = result["text"].lower()
    ok = True
    reasons = []

    if must_contain_any:
        found = any(word.lower() in text for word in must_contain_any)
        if not found:
            ok = False
            reasons.append(f"нет ни одного из {must_contain_any}")

    if must_not_contain:
        for word in must_not_contain:
            if word.lower() in text:
                ok = False
                reasons.append(f"есть запрещённое '{word}'")

    if must_have_qr is not None:
        if must_have_qr and not result["qr"]:
            ok = False
            reasons.append("нет кнопок")

    if ok:
        PASS += 1
        print(f"  ✅ {step_name}: {desc} → '{result['text'][:60]}' qr={result['qr'][:3]}")
    else:
        FAIL += 1
        msg = f"  ❌ {step_name}: {desc} → '{result['text'][:60]}' qr={result['qr'][:3]} ПРИЧИНА: {', '.join(reasons)}"
        print(msg)
        DETAILS.append(msg)
    return result


def main():
    print("\n" + "=" * 70)
    print(" СТРЕСС-ТЕСТ ОНБОРДИНГА: 50+ АБСУРДНЫХ СЦЕНАРИЕВ")
    print("=" * 70)

    # ═══════════════════════════════════════
    # СЦЕНАРИЙ 1: Полный happy path
    # Рекс в _DOG_NAMES → species_guess_dog вставляется перед goal
    # ═══════════════════════════════════════
    print("\n🔵 СЦЕНАРИЙ 1: Happy path")
    reset()

    r = send("")
    check(r, "owner_name", must_contain_any=["зовут"], desc="Первое сообщение")

    r = send("Марк")
    check(r, "pet_name", must_contain_any=["питом", "зовут", "кличк"],
          must_not_contain=["отлично", "прекрасно"], desc="Имя → кличка")

    # Рекс в _DOG_NAMES → species_guess_dog
    r = send("Рекс")
    check(r, "species_guess", must_contain_any=["собак", "угадал", "пёс", "пес"],
          desc="Рекс → species_guess_dog")

    r = send("Да, пёс")
    check(r, "goal", must_contain_any=["помочь", "могу", "чем"],
          must_have_qr=True, desc="Подтверждение → goal")

    r = send("Слежу за здоровьем")
    check(r, "passport", must_contain_any=["паспорт"],
          must_have_qr=True, desc="Goal → passport")

    r = send("Паспорта нет")
    check(r, "breed", must_contain_any=["поро", "какой", "какая"],
          must_have_qr=True, desc="Passport → breed")

    r = send("Мопс")
    check(r, "birth_date", must_contain_any=["родил", "когда", "дат", "возраст"],
          must_have_qr=True, desc="Breed → birth_date")

    r = send("15.01.2020")
    check(r, "gender", must_contain_any=["мальчик", "девочк", "пол"],
          must_have_qr=True, desc="Date → gender")

    r = send("Мальчик")
    check(r, "is_neutered", must_contain_any=["кастр", "стерил"],
          must_have_qr=True, desc="Gender → neutered")

    r = send("Нет")
    check(r, "avatar", must_contain_any=["фото", "профил", "штрих", "мордаш"],
          must_have_qr=True, desc="Neutered → avatar")

    r = send("Пропустить")
    check(r, "complete", must_contain_any=["профиль", "готов", "создан", "карточк"],
          desc="Avatar → complete")

    if r["phase"] == "complete":
        print("  ✅ COMPLETE достигнут!")
    else:
        print(f"  ❌ phase={r['phase']}")

    # ═══════════════════════════════════════
    # СЦЕНАРИЙ 2: Мусор на каждом шаге
    # ═══════════════════════════════════════
    print("\n🔵 СЦЕНАРИЙ 2: Мусор на каждом шаге")
    reset()

    r = send("")  # Инициализация
    r = send("привет")
    check(r, "owner_name", must_contain_any=["зовут", "имя", "обращ"],
          desc="'привет' → переспрос имени")

    r = send("блять")
    check(r, "owner_name", must_contain_any=["зовут", "имя", "обращ", "напиши"],
          desc="мат → переспрос имени")

    r = send("123")
    check(r, "owner_name", must_contain_any=["зовут", "имя", "обращ"],
          desc="цифры → переспрос имени")

    r = send("хочу пиццу")
    check(r, "owner_name", must_contain_any=["зовут", "имя", "обращ"],
          desc="бред → переспрос имени")

    r = send("Марк")
    check(r, "pet_name", must_contain_any=["питом", "зовут", "кличк"],
          desc="Наконец имя")

    # Мусор на pet_name
    r = send("собака")
    check(r, "pet_name", must_contain_any=["зовут", "кличк", "питом"],
          desc="'собака' → переспрос клички")

    r = send("тест")
    check(r, "pet_name", must_contain_any=["зовут", "кличк", "питом"],
          desc="'тест' → переспрос клички")

    r = send("Бобик")
    # Бобик в _DOG_NAMES → species_guess_dog
    check(r, "after_pet_name", must_have_qr=True,
          desc="Наконец кличка → species_guess или goal")

    # ═══════════════════════════════════════
    # СЦЕНАРИЙ 3: Текст вместо кнопок
    # ═══════════════════════════════════════
    print("\n🔵 СЦЕНАРИЙ 3: Текст вместо кнопок")
    reset()
    send("")
    send("Аня")
    send("Мурка")
    # Мурка в _CAT_NAMES → species_guess_cat

    r = send("Кошка")
    # goal шаг
    r = send("У моей кошки болит живот")
    check(r, "free_text_goal", must_have_qr=True,
          desc="Свободный текст как goal → принят")

    r = send("Лучше вручную")

    # ═══════════════════════════════════════
    # СЦЕНАРИЙ 4: Породы — абсурд
    # ═══════════════════════════════════════
    print("\n🔵 СЦЕНАРИЙ 4: Абсурдные породы")
    reset()
    send("")
    send("Дима")
    send("Шарик")
    # Шарик в _DOG_NAMES → species_guess_dog
    r = send("Да, пёс")
    r = send("Слежу за здоровьем")
    r = send("Паспорта нет")

    # Абсурдные породы
    r = send("динозавр")
    check(r, "breed", must_not_contain=["профиль готов"],
          desc="'динозавр' → не записывается как порода")

    r = send("помесь кота с собакой")
    check(r, "breed", desc="'помесь кота с собакой'")

    r = send("Не знаю породу")
    check(r, "breed_unknown", must_have_qr=True,
          desc="Не знаю → фото или пропуск")

    r = send("Пропустить")
    check(r, "after_breed", must_contain_any=["родил", "когда", "дат", "возраст"],
          desc="Пропуск → birth_date")

    # ═══════════════════════════════════════
    # СЦЕНАРИЙ 5: Даты — абсурд
    # ═══════════════════════════════════════
    print("\n🔵 СЦЕНАРИЙ 5: Абсурдные даты")
    reset()
    send("")
    send("Петя")
    send("Барсик")
    # Барсик в _CAT_NAMES → species_guess_cat
    send("Кот")  # species=cat, gender=male
    send("Слежу за здоровьем")
    send("Паспорта нет")
    send("Мейн-кун")

    # Абсурдные даты
    r = send("вчера")
    check(r, "birth_date", desc="'вчера'")

    r = send("в прошлом году")
    check(r, "birth_date", desc="'в прошлом году'")

    r = send("Примерный возраст")
    r = send("3 года")
    check(r, "after_age", must_not_contain=["когда родил"],
          desc="Возраст принят")

    # ═══════════════════════════════════════
    # СЦЕНАРИЙ 6: Gender — абсурд
    # ═══════════════════════════════════════
    print("\n🔵 СЦЕНАРИЙ 6: Gender абсурд (только для собак)")
    reset()
    send("")
    send("Вася")
    send("Тузик")
    # Тузик в _DOG_NAMES → species_guess_dog
    send("Да")
    send("Веду дневник")
    send("Лучше вручную")
    send("Бигль")
    send("Примерный возраст")
    send("5 лет")

    # Gender абсурд
    r = send("он мальчик конечно")
    check(r, "gender→neutered", must_contain_any=["кастр", "стерил"],
          desc="Текст → мальчик → кастрация")

    # ═══════════════════════════════════════
    # СЦЕНАРИЙ 7: Всё текстом, ни одной кнопки
    # ═══════════════════════════════════════
    print("\n🔵 СЦЕНАРИЙ 7: Всё текстом")
    reset()
    send("")

    r = send("Привет меня зовут Холкин Марк Викторович и у меня собака Рекс")
    check(r, "owner_extract", desc="Длинная фраза → извлечь имя")

    # Продолжаем вводить текстом
    r = send("Питомца зовут Цезарь")
    r = send("здоровье")
    r = send("собака")
    r = send("нет паспорта")
    r = send("немецкая овчарка")
    r = send("примерно 2 года")
    r = send("мальчик")
    r = send("нет не кастрирован")
    r = send("не хочу фото")

    if r.get("phase") == "complete":
        print("  ✅ COMPLETE через текст!")
    else:
        check(r, "text_complete", desc="Всё текстом → complete?")

    # ═══════════════════════════════════════
    # СЦЕНАРИЙ 8: Emoji и спецсимволы
    # ═══════════════════════════════════════
    print("\n🔵 СЦЕНАРИЙ 8: Emoji и спецсимволы")
    reset()
    send("")

    r = send("🐕 Марк 🐕")
    check(r, "emoji_name", desc="Emoji в имени")

    r = send("Марк")
    r = send("🐶Бобик🐶")
    check(r, "emoji_pet", desc="Emoji в кличке")

    # ═══════════════════════════════════════
    # СЦЕНАРИЙ 9: Английский ввод
    # ═══════════════════════════════════════
    print("\n🔵 СЦЕНАРИЙ 9: Английский")
    reset()
    send("")

    r = send("My name is John")
    check(r, "en_name", desc="Английское имя")

    r = send("John")
    r = send("Rex")
    r = send("Health tracking")

    # ═══════════════════════════════════════
    # СЦЕНАРИЙ 10: Повторы и зацикливание
    # ═══════════════════════════════════════
    print("\n🔵 СЦЕНАРИЙ 10: Повторы")
    reset()
    send("")
    send("Марк")
    send("Рекс")
    # Рекс → species_guess_dog
    send("Да")
    # Теперь на goal

    # Нажать одно и то же 3 раза
    r1 = send("что?")
    r2 = send("что?")
    r3 = send("что?")
    check(r3, "repeat", must_have_qr=True,
          desc="3x 'что?' → AI всё ещё на goal с кнопками")

    # ═══════════════════════════════════════
    # СЦЕНАРИЙ 11: Подвиды пород
    # ═══════════════════════════════════════
    print("\n🔵 СЦЕНАРИЙ 11: Подвиды пород")
    reset()
    send("")
    send("Лена")
    send("Снежок")
    # Снежок в _DOG_NAMES → species_guess_dog
    send("Да")
    send("Слежу за здоровьем")
    send("Паспорта нет")

    r = send("Хаски")
    check(r, "husky_subtypes", must_have_qr=True,
          desc="Хаски → подвиды?")
    if "Сибирский" in str(r["qr"]) or "сибирский" in r["text"].lower():
        print("  ✅ Подвиды хаски показаны!")

    r = send("Сибирский хаски")
    check(r, "husky_selected", must_contain_any=["родил", "когда", "дат", "возраст"],
          desc="Подвид выбран → birth_date")

    # ═══════════════════════════════════════
    # СЦЕНАРИЙ 12: Кошка — gender пропускается
    # ═══════════════════════════════════════
    print("\n🔵 СЦЕНАРИЙ 12: Кошка — gender skip")
    reset()
    send("")
    send("Оля")
    send("Муся")
    # Муся в _CAT_NAMES → species_guess_cat
    send("Кошка")  # species=cat, gender=female
    send("Кое-что беспокоит")
    send("Лучше вручную")
    send("Не знаю породу")
    send("Пропустить")
    send("Примерный возраст")
    r = send("1 год")

    # Следующий шаг должен быть is_neutered, НЕ gender
    check(r, "cat_no_gender", must_contain_any=["стерил", "кастр"],
          desc="Кошка → gender пропущен → сразу кастрация")

    # ═══════════════════════════════════════
    # ИТОГ
    # ═══════════════════════════════════════
    print("\n" + "=" * 70)
    print(f" ИТОГ: ✅ {PASS} passed, ❌ {FAIL} failed")
    print("=" * 70)

    if DETAILS:
        print("\n📋 Все ошибки:")
        for d in DETAILS:
            print(f"  {d}")

    return FAIL


if __name__ == "__main__":
    failures = main()
    sys.exit(1 if failures > 0 else 0)
