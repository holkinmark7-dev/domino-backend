"""
Полная симуляция онбординга — happy path + стресс-тест каждого шага.
Проверяет ВСЕ возможные пользовательские вводы.
Запуск: python -m tests.test_onboarding_full_flow
"""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.onboarding_ai import (
    _get_current_step, _get_step_quick_replies,
    _get_step_instruction, _parse_user_input,
    _get_fallback_text, _decline_pet_name,
    _BREED_CLARIFICATIONS,
)

PASS = 0
FAIL = 0
DETAILS = []

def log_pass(msg):
    global PASS
    PASS += 1

def log_fail(msg):
    global FAIL
    FAIL += 1
    DETAILS.append(f"❌ {msg}")
    print(f"  ❌ {msg}")

def send(collected, step, message):
    updates = _parse_user_input(message, step, collected)
    collected.update(updates)
    return updates

def stress_test_step(step, field_name, collected_base, garbage_list, description):
    """Проверить что мусор НЕ записывает поле."""
    fails = []
    for garbage in garbage_list:
        test_c = dict(collected_base)
        updates = _parse_user_input(garbage, step, test_c)
        if field_name and updates.get(field_name):
            fails.append((garbage, updates[field_name]))

    total = len(garbage_list)
    failed = len(fails)
    passed = total - failed

    if fails:
        log_fail(f"{description}: {failed}/{total} мусора прошло! Примеры: {fails[:5]}")
    else:
        log_pass(f"{description}: {total}/{total} мусора отфильтровано")
        print(f"  ✅ {description}: {total} вариантов мусора отфильтровано")


# ═══════════════════════════════════════════════════════════════
# ГИГАНТСКИЕ СПИСКИ МУСОРА ДЛЯ КАЖДОГО ШАГА
# ═══════════════════════════════════════════════════════════════

# Универсальный мусор — подходит для ЛЮБОГО шага
UNIVERSAL_GARBAGE = [
    # Пустое и пробелы
    "", " ", "  ", "   ", "\n", "\t",
    # Знаки препинания
    ".", "..", "...", "!", "!!", "!!!", "?", "??", "???",
    ",", ";", ":", "-", "--", "—", "_", "__",
    # Цифры
    "0", "1", "123", "456789", "0000", "999",
    # Спецсимволы
    "@", "#", "$", "%", "^", "&", "*", "(", ")", "=", "+",
    "@#$%", "***", "===", "---", "<<<", ">>>",
    # Ссылки
    "http://google.com", "https://vk.com", "www.test.ru",
    "t.me/channel", "instagram.com/user",
    # Эмодзи и unicode
    "😀", "🐕", "❤️", "👍", "🤬", "💩",
    "😀😀😀", "🐶🐱", "❤️❤️❤️",
]

# Приветствия, команды, вопросы
GREETINGS_AND_COMMANDS = [
    # Приветствия
    "привет", "Привет", "ПРИВЕТ", "привет!", "Привет!",
    "здравствуйте", "Здравствуйте", "здравствуй",
    "хай", "Хай", "хэй", "hey", "Hey", "HEY",
    "hi", "Hi", "HI", "hello", "Hello", "HELLO",
    "добрый день", "Добрый день", "добрый вечер", "доброе утро",
    "ку", "Ку", "КУ", "ку!", "йо", "Йо",
    "здарова", "здарово", "Здарова", "приветик", "Приветик",
    "хола", "салам", "алоха", "бонжур", "чао",
    # Прощания
    "пока", "до свидания", "бай", "bye", "пока-пока",
    # Команды
    "начать", "Начать", "старт", "Старт", "start", "Start",
    "/start", "/help", "/menu", "/reset",
    "помощь", "помоги", "help", "меню",
    # Согласия/отказы без контекста
    "да", "Да", "ДА", "нет", "Нет", "НЕТ",
    "ок", "Ок", "ОК", "ok", "OK", "ладно", "Ладно",
    "ага", "угу", "неа", "не-а", "ну да", "ну нет",
    # Вопросы
    "что?", "Что?", "ЧТО?", "чё?", "Чё?", "че?",
    "а?", "А?", "зачем?", "почему?", "как?", "когда?",
    "что это", "что это такое", "это что",
    "кто ты", "кто ты такой", "ты кто",
    "что ты умеешь", "что можешь",
]

# Мат, оскорбления, агрессия
PROFANITY_AND_ABUSE = [
    "блять", "бля", "блядь", "сука", "хуй", "пиздец",
    "нахуй", "иди нахуй", "пошёл нахуй", "пошел нахуй",
    "иди в жопу", "пошёл в жопу",
    "дурак", "идиот", "дебил", "тупой", "мудак",
    "урод", "козёл", "козел", "баран",
    "отвали", "отстань", "заткнись", "закройся",
    "fuck", "fuck you", "shit", "damn", "bitch",
    "ненавижу", "убейся", "сдохни",
    "ты тупой", "ты дебил", "ты идиот",
    "тупая программа", "тупой бот", "глупый бот",
    "не работает", "всё сломано", "ничего не работает",
]

# Случайные фразы не по теме
OFF_TOPIC = [
    "хочу пиццу", "закажи такси", "какая погода",
    "расскажи анекдот", "расскажи шутку", "пошути",
    "сколько время", "который час", "какой сегодня день",
    "как дела", "как дела?", "как ты?", "как жизнь",
    "что нового", "что делаешь",
    "я устал", "мне скучно", "мне грустно",
    "хочу спать", "хочу есть", "хочу домой",
    "позвони маме", "напиши сообщение",
    "включи музыку", "выключи свет",
    "купи молоко", "что на ужин",
    "когда выходные", "сколько до нового года",
    "рассчитай ипотеку", "курс доллара",
    "кто президент", "столица франции",
    "формула воды", "теорема пифагора",
    "смысл жизни", "есть ли бог",
    "я люблю тебя", "выходи за меня",
    "ты живой?", "ты робот?", "ты настоящий?",
    "у тебя есть чувства?", "ты думаешь?",
    "могу я поговорить с человеком",
    "дай мне менеджера", "позови оператора",
    "я хочу вернуть деньги", "верните деньги",
    "удали мой аккаунт", "удали все данные",
    "это безопасно?", "вы храните мои данные?",
    "политика конфиденциальности",
    "а что если написать очень длинное сообщение которое вообще ни о чём и просто занимает место",
    "аааааааааааааааааааа", "ыыыыыыыыыы", "ааа ааа ааа",
    "лалалала", "хахахаха", "хехехе", "ололо",
    "тест", "test", "TEST", "тестирование", "проверка",
    "asdf", "qwerty", "zxcvbn", "йцукен", "фывапр",
    "1234567890", "абвгдеж", "abcdefg",
]

# Имена которые НЕ должны быть именами
NOT_NAMES = [
    # Длинные фразы
    "меня зовут не скажу как потому что не хочу",
    "а зачем тебе моё имя вообще",
    "имя это персональные данные я не буду говорить",
    "Путин", "Навальный", "Трамп", "Байден",  # Публичные фигуры — допустимы как имена? Спорно
    # Нечитаемое
    "ааааааааааааааа", "хххххх", "ъъъъъ",
    # Числа как текст
    "ноль", "один", "сто", "миллион",
]

# Всё что пользователь может написать вместо клички
NOT_PET_NAMES = [
    "у меня нет питомца", "я ещё не завёл",
    "собака", "кошка", "пёс", "кот",  # Вид вместо клички
    "не решил ещё", "думаю", "подскажи имя",
    "какие бывают клички", "посоветуй кличку",
]

# Породы с ошибками
BREED_TYPOS = [
    ("лобрадор", True, None, "Опечатка в лабрадор"),
    ("лабродор", True, None, "Другая опечатка"),
    ("лабрадр", True, None, "Пропущены буквы"),
    ("мопс", True, None, "Точное"),
    ("Мопс", True, None, "С заглавной"),
    ("МОПС", True, None, "Капс"),
    ("хаски", True, None, "Хаски точное"),
    ("хасски", True, None, "Двойная с"),
    ("чихуахуа", True, None, "Чихуахуа"),
    ("чихуа", True, None, "Сокращение чихуахуа"),
    ("чихуа-хуа", True, None, "С дефисом"),
    ("шпиц", False, True, "Шпиц → подвиды"),
    ("терьер", False, True, "Терьер → подвиды"),
    ("колли", False, True, "Колли → подвиды"),
    ("бульдог", False, True, "Бульдог → подвиды"),
    ("овчарка", False, True, "Овчарка → подвиды"),
    ("ретривер", False, True, "Ретривер → подвиды"),
    ("пинчер", False, True, "Пинчер → подвиды"),
    ("дог", False, True, "Дог → подвиды"),
    ("спаниель", False, True, "Спаниель → подвиды"),
    ("сеттер", False, True, "Сеттер → подвиды"),
    ("лайка", False, True, "Лайка → подвиды"),
    ("борзая", False, True, "Борзая → подвиды"),
    ("дворняга", True, None, "Дворняга → Метис"),
    ("дворняжка", True, None, "Дворняжка → Метис"),
    ("метис", True, None, "Метис прямой"),
    ("беспородная", True, None, "Беспородная → Метис"),
    ("беспородный", True, None, "Беспородный → Метис"),
    ("двортерьер", True, None, "Двортерьер → Метис"),
    ("помесь", True, None, "Помесь → Метис"),
    ("смесь", True, None, "Смесь → Метис"),
    ("не знаю породу", False, None, "_breed_unknown"),
    ("не знаю", False, None, "_breed_unknown"),
    ("хз", False, None, "_breed_unknown"),
    ("без понятия", False, None, "_breed_unknown"),
]

# Edge cases дат
DATE_TESTS = [
    ("15.01.2020", True, "DD.MM.YYYY нормальная"),
    ("01.06.2023", True, "DD.MM.YYYY недавняя"),
    ("2020-01-15", True, "YYYY-MM-DD"),
    ("2023-06-01", True, "YYYY-MM-DD недавняя"),
    ("01.01.2030", False, "Будущее"),
    ("15.06.2028", False, "Будущее"),
    ("01.01.1980", False, "45+ лет"),
    ("01.01.1950", False, "75+ лет"),
    ("2 года", True, "Текст: 2 года"),
    ("3 года", True, "Текст: 3 года"),
    ("6 месяцев", True, "Текст: 6 месяцев"),
    ("полтора года", True, "Текст: полтора года"),
    ("выбрать дату", False, "Кнопка DatePicker"),
    ("примерный возраст", False, "Кнопка примерный"),
    ("не знаю", False, "Кнопка не знаю"),
]

# Gender edge cases
GENDER_TESTS = [
    ("Да, мальчик", "male", "Кнопка мальчик"),
    ("Нет, девочка", "female", "Кнопка девочка"),
    ("мальчик", "male", "Просто мальчик"),
    ("девочка", "female", "Просто девочка"),
    ("Мальчик", "male", "С заглавной"),
    ("Девочка", "female", "С заглавной"),
    ("МАЛЬЧИК", "male", "Капс"),
    ("кобель", "male", "Синоним"),
    ("самец", "male", "Синоним"),
    ("самка", "female", "Синоним"),
    ("пацан", "male", "Сленг"),
    ("парень", "male", "Сленг"),
    ("мальч", "male", "Сокращение"),
    ("девоч", "female", "Сокращение"),
]

# Neutered edge cases
NEUTERED_TESTS = [
    ("Да", True), ("да", True), ("Да.", True), ("да!", True),
    ("ага", True), ("угу", True), ("кастрирован", True),
    ("стерилизована", True), ("давно", True), ("да давно", True),
    ("Нет", False), ("нет", False), ("Нет.", False), ("нет!", False),
    ("неа", False), ("нет ещё", False), ("нет еще", False), ("пока нет", False),
]

# Avatar edge cases
AVATAR_TESTS_SKIP = [
    "Пропустить", "пропустить", "ПРОПУСТИТЬ",
    "пропуск", "потом", "позже",
    "не сейчас", "скип", "нет", "не хочу",
    "Потом", "Позже", "Нет", "Не хочу",
    "Не сейчас", "ПОТОМ",
]


def main():
    print("\n" + "=" * 70)
    print(" ПОЛНАЯ СИМУЛЯЦИЯ ОНБОРДИНГА: HAPPY PATH + СТРЕСС-ТЕСТ")
    print("=" * 70)

    # ══════════════════════════════════════
    # СТРЕСС-ТЕСТ OWNER_NAME
    # ══════════════════════════════════════
    print("\n\n🔴 СТРЕСС-ТЕСТ: owner_name")
    print("-" * 50)

    all_garbage = UNIVERSAL_GARBAGE + GREETINGS_AND_COMMANDS + PROFANITY_AND_ABUSE + OFF_TOPIC
    stress_test_step("owner_name", "owner_name", {}, all_garbage,
                     "owner_name мусор")

    # Проверить что реальные имена работают
    real_names = [
        ("Марк", "Марк"), ("марк", "Марк"), ("МАРК", "Марк"),
        ("Аня", "Аня"), ("Дмитрий", "Дмитрий"),
        ("Александр Петрович", "Александр"),
        ("Холкин Марк Викторович", None),  # _parse_name может вернуть "Холкин" или "Марк"
    ]
    for text, expected in real_names:
        test_c = {}
        updates = _parse_user_input(text, "owner_name", test_c)
        name = updates.get("owner_name")
        if name and len(name) > 1 and name[0].isupper():
            log_pass(f"'{text}' → '{name}'")
            print(f"  ✅ '{text}' → '{name}'")
        else:
            log_fail(f"'{text}' → '{name}' (ожидали имя)")

    # ══════════════════════════════════════
    # СТРЕСС-ТЕСТ PET_NAME
    # ══════════════════════════════════════
    print("\n\n🔴 СТРЕСС-ТЕСТ: pet_name")
    print("-" * 50)

    pet_garbage = UNIVERSAL_GARBAGE + NOT_PET_NAMES
    collected_base = {"owner_name": "Марк"}
    stress_test_step("pet_name", "pet_name", collected_base, pet_garbage,
                     "pet_name мусор")

    # Реальные клички
    real_pets = ["Бобик", "Рекс", "Мурка", "Славик", "Бублик", "Солнышко", "Цезарь", "Найда"]
    for name in real_pets:
        test_c = dict(collected_base)
        updates = _parse_user_input(name, "pet_name", test_c)
        if updates.get("pet_name"):
            log_pass(f"'{name}' → '{updates['pet_name']}'")
            print(f"  ✅ Кличка '{name}' принята")
        else:
            log_fail(f"Кличка '{name}' не принята!")

    # ══════════════════════════════════════
    # СТРЕСС-ТЕСТ SPECIES
    # ══════════════════════════════════════
    print("\n\n🔴 СТРЕСС-ТЕСТ: species")
    print("-" * 50)

    species_base = {"owner_name": "Марк", "pet_name": "Славик", "goal": "Здоровье"}
    species_garbage = UNIVERSAL_GARBAGE + GREETINGS_AND_COMMANDS + OFF_TOPIC
    stress_test_step("species", "species", species_base, species_garbage,
                     "species мусор")

    # Экзотика — не должна записать species
    exotic = ["попугай", "хомяк", "рыбка", "черепаха", "кролик", "крыса",
              "морская свинка", "хорёк", "ящерица", "змея", "шиншилла",
              "игуана", "хамелеон", "паук", "улитка", "канарейка"]
    exotic_fails = 0
    for animal in exotic:
        test_c = dict(species_base)
        updates = _parse_user_input(animal, "species", test_c)
        if updates.get("species"):
            exotic_fails += 1
            log_fail(f"Экзотика '{animal}' записалась как species!")
    if exotic_fails == 0:
        log_pass(f"Все {len(exotic)} экзотических животных отфильтрованы")
        print(f"  ✅ {len(exotic)} экзотических животных отфильтрованы")

    # ══════════════════════════════════════
    # СТРЕСС-ТЕСТ BREED
    # ══════════════════════════════════════
    print("\n\n🔴 СТРЕСС-ТЕСТ: breed (опечатки и подвиды)")
    print("-" * 50)

    breed_base = {"owner_name": "Т", "pet_name": "Т", "goal": "Т",
                  "species": "dog", "_passport_skipped": True}

    for text, expect_breed, expect_clarify, desc in BREED_TYPOS:
        test_c = dict(breed_base)
        updates = _parse_user_input(text, "breed", test_c)

        if text in ("не знаю породу", "не знаю", "хз", "без понятия"):
            if updates.get("_breed_unknown"):
                log_pass(f"'{text}' → _breed_unknown ({desc})")
                print(f"  ✅ '{text}' → _breed_unknown")
            else:
                log_fail(f"'{text}' → {updates} ({desc})")
        elif expect_breed and updates.get("breed"):
            log_pass(f"'{text}' → breed='{updates['breed']}' ({desc})")
            print(f"  ✅ '{text}' → '{updates['breed']}'")
        elif expect_clarify and updates.get("_breed_clarification_options"):
            opts = updates["_breed_clarification_options"]
            log_pass(f"'{text}' → подвиды: {len(opts)} шт ({desc})")
            print(f"  ✅ '{text}' → {len(opts)} подвидов")
        else:
            log_fail(f"'{text}' → {updates} ({desc})")

    # Проверка что подвиды НЕ зацикливаются
    print("\n  🔄 Проверка антицикла подвидов:")
    loop_tests = [
        ("Овчарка", "Среднеазиатская овчарка"),
        ("Овчарка", "Немецкая овчарка"),
        ("Йорк", "Йоркширский терьер"),
        ("Йорк", "Бивер-йорк"),
        ("Шпиц", "Померанский шпиц"),
        ("Терьер", "Джек-рассел-терьер"),
        ("Бульдог", "Французский бульдог"),
        ("Колли", "Бордер-колли"),
        ("Ретривер", "Золотистый ретривер"),
        ("Дог", "Немецкий дог"),
        ("Спаниель", "Кокер-спаниель"),
        ("Пинчер", "Доберман"),
        ("Сеттер", "Ирландский сеттер"),
        ("Лайка", "Западно-сибирская лайка"),
        ("Борзая", "Грейхаунд"),
        ("Британская", "Британская короткошёрстная"),
        ("Шотландская", "Скоттиш-фолд"),
        ("Сфинкс", "Канадский сфинкс"),
    ]
    for group, specific in loop_tests:
        test_c = dict(breed_base)
        # Шаг 1: групповое → подвиды
        updates1 = _parse_user_input(group, "breed", test_c)
        test_c.update(updates1)
        if not test_c.get("_breed_clarification_options"):
            log_fail(f"'{group}' не вызвал подвиды!")
            continue
        # Шаг 2: конкретный подвид → должен записаться
        updates2 = _parse_user_input(specific, "breed", test_c)
        test_c.update(updates2)
        if test_c.get("breed") == specific:
            log_pass(f"'{group}' → '{specific}' ✓ (не зациклился)")
            print(f"  ✅ {group} → {specific}")
        else:
            log_fail(f"'{group}' → '{specific}' ЗАЦИКЛИВАНИЕ! breed={test_c.get('breed')}, clarify={test_c.get('_breed_clarification_options')}")

    # ══════════════════════════════════════
    # СТРЕСС-ТЕСТ BIRTH_DATE
    # ══════════════════════════════════════
    print("\n\n🔴 СТРЕСС-ТЕСТ: birth_date")
    print("-" * 50)

    date_base = {"owner_name": "Т", "pet_name": "Т", "goal": "Т",
                 "species": "dog", "_passport_skipped": True, "breed": "Мопс"}

    for text, expect_ok, desc in DATE_TESTS:
        test_c = dict(date_base)
        updates = _parse_user_input(text, "birth_date", test_c)
        has_date = updates.get("birth_date") or updates.get("age_years")
        has_flag = updates.get("_wants_date_picker") or updates.get("_age_approximate") or updates.get("_age_skipped")

        if expect_ok and has_date:
            log_pass(f"'{text}' → данные записаны ({desc})")
            print(f"  ✅ '{text}' → OK")
        elif not expect_ok and not has_date:
            if has_flag:
                log_pass(f"'{text}' → флаг установлен ({desc})")
                print(f"  ✅ '{text}' → флаг")
            else:
                log_pass(f"'{text}' → отклонено ({desc})")
                print(f"  ✅ '{text}' → отклонено")
        elif expect_ok and not has_date and has_flag:
            log_pass(f"'{text}' → флаг ({desc})")
            print(f"  ✅ '{text}' → флаг")
        else:
            log_fail(f"'{text}' → {updates} ({desc})")

    # Мусор на birth_date
    date_garbage = UNIVERSAL_GARBAGE + OFF_TOPIC[:20]
    stress_test_step("birth_date", "birth_date", date_base, date_garbage,
                     "birth_date мусор")

    # ══════════════════════════════════════
    # СТРЕСС-ТЕСТ GENDER
    # ══════════════════════════════════════
    print("\n\n🔴 СТРЕСС-ТЕСТ: gender")
    print("-" * 50)

    gender_base = {"owner_name": "Т", "pet_name": "Бобик", "goal": "Т",
                   "species": "dog", "_passport_skipped": True, "breed": "Мопс",
                   "birth_date": "2020-01-01", "age_years": 5,
                   "_detected_gender_hint": "male"}

    for text, expected, desc in GENDER_TESTS:
        test_c = dict(gender_base)
        updates = _parse_user_input(text, "gender", test_c)
        if updates.get("gender") == expected:
            log_pass(f"'{text}' → {expected} ({desc})")
            print(f"  ✅ '{text}' → {expected}")
        else:
            log_fail(f"'{text}' → {updates.get('gender')} (ожидали {expected}) ({desc})")

    # hint=male, "Да" → male, "Нет" → female
    test_c = dict(gender_base)
    test_c["_detected_gender_hint"] = "male"
    updates = _parse_user_input("да", "gender", test_c)
    if updates.get("gender") == "male":
        log_pass("hint=male + 'да' → male")
        print("  ✅ hint=male + 'да' → male")
    else:
        log_fail(f"hint=male + 'да' → {updates.get('gender')}")

    test_c["_detected_gender_hint"] = "male"
    updates = _parse_user_input("нет", "gender", test_c)
    if updates.get("gender") == "female":
        log_pass("hint=male + 'нет' → female (инверсия)")
        print("  ✅ hint=male + 'нет' → female")
    else:
        log_fail(f"hint=male + 'нет' → {updates.get('gender')}")

    # ══════════════════════════════════════
    # СТРЕСС-ТЕСТ IS_NEUTERED
    # ══════════════════════════════════════
    print("\n\n🔴 СТРЕСС-ТЕСТ: is_neutered")
    print("-" * 50)

    neutered_base = dict(gender_base)
    neutered_base["gender"] = "male"

    for text, expected in NEUTERED_TESTS:
        test_c = dict(neutered_base)
        updates = _parse_user_input(text, "is_neutered", test_c)
        if updates.get("is_neutered") == expected:
            log_pass(f"'{text}' → {expected}")
            print(f"  ✅ '{text}' → {expected}")
        else:
            log_fail(f"'{text}' → {updates.get('is_neutered')} (ожидали {expected})")

    # ══════════════════════════════════════
    # СТРЕСС-ТЕСТ AVATAR
    # ══════════════════════════════════════
    print("\n\n🔴 СТРЕСС-ТЕСТ: avatar skip")
    print("-" * 50)

    avatar_base = dict(neutered_base)
    avatar_base["is_neutered"] = False

    for text in AVATAR_TESTS_SKIP:
        test_c = dict(avatar_base)
        updates = _parse_user_input(text, "avatar", test_c)
        if updates.get("_avatar_skipped"):
            log_pass(f"'{text}' → skip")
            print(f"  ✅ '{text}' → skip")
        else:
            log_fail(f"'{text}' НЕ распарсился как skip!")

    # ══════════════════════════════════════
    # HAPPY PATH — ТРИ ПОЛНЫХ СЦЕНАРИЯ
    # ══════════════════════════════════════
    print("\n\n🔵 HAPPY PATH: Сценарий 1 — Собака, овчарка, дата")
    print("-" * 50)
    c = {}
    send(c, "owner_name", "Марк")
    send(c, "pet_name", "Славик")
    assert _get_current_step(c) == "goal"
    send(c, "goal", "Слежу за здоровьем")
    send(c, "species", "Собака")
    send(c, "passport_offer", "Паспорта нет")
    send(c, "breed", "Овчарка")
    assert c.get("_breed_clarification_options"), "Нет подвидов овчарки!"
    send(c, "breed", "Немецкая овчарка")
    assert c.get("breed") == "Немецкая овчарка"
    assert _get_current_step(c) == "birth_date"
    send(c, "birth_date", "Выбрать дату")
    send(c, "birth_date", "15.01.2020")
    assert c.get("birth_date")
    send(c, "gender", "Да, мальчик")
    send(c, "is_neutered", "Нет")
    send(c, "avatar", "Пропустить")
    step = _get_current_step(c)
    if step == "complete":
        log_pass("СЦЕНАРИЙ 1: COMPLETE")
        print("  ✅ СЦЕНАРИЙ 1: COMPLETE")
    else:
        log_fail(f"СЦЕНАРИЙ 1: step={step}")

    print("\n\n🔵 HAPPY PATH: Сценарий 2 — Кошка, тревога")
    print("-" * 50)
    c = {}
    send(c, "owner_name", "Аня")
    send(c, "pet_name", "Мурка")
    step = _get_current_step(c)
    if step == "species_guess_cat":
        log_pass("Мурка → species_guess_cat")
        print("  ✅ Мурка → species_guess_cat")
    send(c, "species_guess_cat", "Кошка")
    assert c.get("species") == "cat" and c.get("gender") == "female"
    send(c, "goal", "Кое-что беспокоит")
    assert c.get("goal") == "Есть тревога"
    assert c.get("_concern_heard") == True
    step = _get_current_step(c)
    assert step == "passport_offer", f"После тревоги step={step}"
    log_pass("Concern убран, сразу passport")
    print("  ✅ Concern убран, сразу passport")
    send(c, "passport_offer", "Лучше вручную")
    send(c, "breed", "Не знаю породу")
    send(c, "breed", "Пропустить")
    assert c.get("breed") == "Метис"
    send(c, "birth_date", "Примерный возраст")
    send(c, "birth_date", "2 года")
    step = _get_current_step(c)
    assert step == "is_neutered", f"Кошка gender пропущен? step={step}"
    log_pass("Gender пропущен для кошки")
    print("  ✅ Gender пропущен для кошки")
    send(c, "is_neutered", "Да")
    send(c, "avatar", "Пропустить")
    if _get_current_step(c) == "complete":
        log_pass("СЦЕНАРИЙ 2: COMPLETE")
        print("  ✅ СЦЕНАРИЙ 2: COMPLETE")
    else:
        log_fail(f"СЦЕНАРИЙ 2: step={_get_current_step(c)}")

    print("\n\n🔵 HAPPY PATH: Сценарий 3 — Йорк → подвид")
    print("-" * 50)
    c = {}
    send(c, "owner_name", "Дима")
    send(c, "pet_name", "Бобик")
    send(c, "goal", "Веду дневник")
    send(c, "species", "Собака")
    send(c, "passport_offer", "Нет")
    send(c, "breed", "Йорк")
    assert c.get("_breed_clarification_options")
    send(c, "breed", "Бивер-йорк")
    assert c.get("breed") == "Бивер-йорк"
    send(c, "birth_date", "Не знаю")
    send(c, "gender", "Мальчик")
    send(c, "is_neutered", "Да.")
    assert c.get("is_neutered") == True
    send(c, "avatar", "Пропустить")
    if _get_current_step(c) == "complete":
        log_pass("СЦЕНАРИЙ 3: COMPLETE")
        print("  ✅ СЦЕНАРИЙ 3: COMPLETE")
    else:
        log_fail(f"СЦЕНАРИЙ 3: step={_get_current_step(c)}")

    # ══════════════════════════════════════
    # СКЛОНЕНИЯ
    # ══════════════════════════════════════
    print("\n\n🔴 СТРЕСС-ТЕСТ: склонения")
    print("-" * 50)
    declensions = [
        ("Рекс", "gen", "Рекса"), ("Рекс", "dat", "Рексу"),
        ("Рекс", "inst", "Рексом"), ("Рекс", "prep", "Рексе"),
        ("Мурка", "gen", "Мурки"), ("Мурка", "dat", "Мурке"),
        ("Мурка", "inst", "Муркой"), ("Мурка", "acc", "Мурку"),
        ("Соня", "gen", "Сони"), ("Соня", "dat", "Соне"),
        ("Соня", "inst", "Соней"),
        ("Бублик", "gen", "Бублика"), ("Бублик", "dat", "Бублику"),
        ("Славик", "gen", "Славика"), ("Славик", "dat", "Славику"),
        ("Солнышко", "gen", "Солнышка"), ("Солнышко", "dat", "Солнышку"),
        ("Жучка", "gen", "Жучки"), ("Жучка", "dat", "Жучке"),
    ]
    for name, case, expected in declensions:
        result = _decline_pet_name(name, case)
        if result == expected:
            log_pass(f"'{name}' {case} → '{result}'")
            print(f"  ✅ '{name}' {case} → '{result}'")
        else:
            log_fail(f"'{name}' {case} → '{result}' (ожидали '{expected}')")

    # ══════════════════════════════════════
    # ИТОГ
    # ══════════════════════════════════════
    print("\n" + "=" * 70)
    print(f" ИТОГ: ✅ {PASS} passed, ❌ {FAIL} failed")
    print("=" * 70)

    if DETAILS:
        print("\n📋 Все ошибки:")
        for d in DETAILS:
            print(f"  {d}")

    if FAIL > 0:
        print(f"\n⚠️  {FAIL} проблем найдено — нужны правки!")
    else:
        print("\n🎉 ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!")

    return FAIL


if __name__ == "__main__":
    failures = main()
    sys.exit(1 if failures > 0 else 0)
