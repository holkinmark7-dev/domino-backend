from openai import OpenAI
from config import OPENAI_API_KEY
from routers.services.response_templates import select_template, get_phase_prefix

client = OpenAI(api_key=OPENAI_API_KEY)


def _build_actions_block(clinical_decision: dict) -> str:
    symptom = clinical_decision.get("symptom") or ""

    if symptom in ["xylitol_toxicity", "antifreeze", "rodenticide"]:
        return (
            "- Немедленно везите в клинику\n"
            "- Не вызывайте рвоту без указания врача\n"
            "- Сообщите врачу что именно съело животное"
        )
    elif symptom == "seizure":
        return (
            "- Уберите опасные предметы рядом\n"
            "- Не держите животное — не мешайте судорогам\n"
            "- Засеките время приступа\n"
            "- После окончания — срочно в клинику"
        )
    elif symptom in ["difficulty_breathing", "choking", "bone_stuck"]:
        return (
            "- Не кормите и не поите\n"
            "- Обеспечьте покой и свежий воздух\n"
            "- Срочно везите в клинику"
        )
    elif symptom == "foreign_body_ingestion":
        return (
            "- Не вызывайте рвоту\n"
            "- Не кормите\n"
            "- Срочно везите в клинику"
        )
    elif symptom == "urinary_obstruction":
        return (
            "- Не давайте мочегонные\n"
            "- Обеспечьте покой\n"
            "- Срочно везите в клинику"
        )
    else:
        return (
            "- Ограничьте корм на 8–12 часов\n"
            "- Обеспечьте доступ к воде\n"
            "- Контролируйте вялость и активность"
        )


def generate_ai_response(pet_profile: dict, recent_events: list, user_message: str, urgency_score: int = 0, risk_level: str = None, memory_context: str = "No prior medical history.", clinical_decision=None, dialogue_mode: str = "normal", previous_assistant_text: str = None, strict_override: str = None, llm_contract: dict = None, message_mode: str = "CLINICAL", client_time: str = None, owner_name: str = None):
    """
    Генерация AI-ответа с учётом профиля, истории и уровня срочности
    """

    if urgency_score is None:
        urgency_instructions = (
            "Urgency could not be determined automatically. "
            "Assess the situation yourself based on the user message. "
            "If in doubt, recommend consulting a veterinarian."
        )
    elif urgency_score == 0:
        urgency_instructions = "This is not concerning. Provide calm guidance. Do not recommend a vet."
    elif urgency_score == 1:
        urgency_instructions = "Mild situation. Suggest monitoring and practical steps. Do not push vet visit."
    elif urgency_score == 2:
        urgency_instructions = "Moderate concern. Recommend contacting a veterinarian if symptoms persist."
    elif urgency_score == 3:
        urgency_instructions = "High concern. Clearly recommend urgent veterinary attention."
    else:
        urgency_instructions = (
            "Urgency could not be determined automatically. "
            "Assess the situation yourself based on the user message. "
            "If in doubt, recommend consulting a veterinarian."
        )

    # When clinical_decision is present — urgency_score is irrelevant
    if clinical_decision:
        urgency_instructions = ""

    clinical_escalation_block = ""
    if dialogue_mode == "clinical_escalation" and clinical_decision:
        _dlg_level = clinical_decision["escalation"]
        _response_type = clinical_decision.get("response_type", "ASSESS")
        _episode_phase = clinical_decision.get("episode_phase", "initial")

        if _response_type == "ACTION":
            _strategy = """\
Response type: ACTION
- No questions.
- Provide immediate concrete steps.
- Direct tone.
- No soft language."""
        elif _response_type == "URGENT_GUIDANCE":
            _strategy = """\
Response type: URGENT_GUIDANCE
- 1 focused medical question max.
- Strong urgency tone.
- Mention vet immediately."""
        elif _response_type == "URGENT_QUESTIONS":
            _strategy = """\
Response type: URGENT_QUESTIONS
- 1–2 targeted questions.
- Clear urgency."""
        elif _response_type == "CLARIFY":
            if _episode_phase == "progressing":
                _strategy = """\
Response type: CLARIFY (progressing)
- Ask 2 focused questions.
- Do NOT ask frequency question."""
            else:
                _strategy = """\
Response type: CLARIFY
- Ask 2 focused questions."""
        elif _response_type == "ACTION_HOME_PROTOCOL":
            _strategy = """\
Response type: ACTION_HOME_PROTOCOL
- Provide short, structured home stabilization steps.
- Maximum 6 short bullet points.
- Do NOT ask any questions.
- Do NOT use English words or phrases.
- Direct, calm tone.
- Do NOT exceed 1200 characters.
Use these steps as guidance (adapt to the pet's situation):
1. Уберите корм на 8–12 часов.
2. Давайте небольшие порции воды.
3. Следите за появлением крови.
4. Если рвота продолжается более 1–2 часов — срочно ищите возможность доставки к врачу.
5. Если появляется вялость или слабость — это критично."""
        else:
            _strategy = """\
Response type: ASSESS
- Ask necessary medical clarification.
- Calm tone."""

        _reaction = clinical_decision.get("reaction_type", "normal_progress")

        if _reaction == "repeated_symptom":
            _reaction_tone = "Tone: Shorten introduction. Do not re-summarize previous episode."
        elif _reaction == "ignored_urgent_advice":
            _reaction_tone = "Tone: Increase directness in wording."
        elif _reaction == "topic_shift":
            _reaction_tone = "Tone: Open with one-line redirect to primary symptom, then continue."
        elif _reaction == "panic":
            _reaction_tone = "Tone: Begin with one grounding sentence before escalation content."
        else:
            _reaction_tone = ""

        clinical_escalation_block = f"""

Dialogue mode: CLINICAL_ESCALATION (level: {_dlg_level})
Never reuse the same opening sentence as the previous assistant response.

{_strategy}{chr(10) + _reaction_tone if _reaction_tone else ""}"""

    escalation_instructions = ""
    if "Escalation flag: high_repetition" in memory_context:
        escalation_instructions = """
Escalation mode (ACTIVE - HIGH REPETITION):
If "Escalation flag: high_repetition" is present:
- Clearly state this is a repeated episode.
- Explicitly mention the number of repetitions from "Repetition count" in the medical history.
- Reduce neutral tone.
- Strongly recommend vet consultation.
- Avoid repeating generic advice list.
- Focus on risk progression.
"""

    continuation_instructions = ""
    if "Temporal status: continuation" in memory_context:
        continuation_instructions = """
Continuation mode (ACTIVE):
If "Temporal status: continuation" is present:
- Do NOT repeat general advice list.
- Do NOT provide the same feeding/water instructions again.
- Treat this as an ongoing episode.
- Ask targeted follow-up questions: how many times has the symptom occurred, is there blood, is the pet drinking water, has the condition changed.
- Evaluate progression, not repetition.
- Escalate urgency if symptoms persist.
- Focus on progression, not repetition.
"""

    contract_block = ""
    if llm_contract:
        known_facts = llm_contract.get("known_facts", {})
        allowed_questions = llm_contract.get("allowed_questions", [])

        known_facts_str = "\n".join(
            f"- {k}: {v}" for k, v in known_facts.items()
        ) or "None"

        allowed_questions_str = "\n".join(
            f"- {q}" for q in allowed_questions
        ) or "None"

        contract_block = f"""
LLM CONTRACT (STRICT MODE):

Risk level: {llm_contract.get("risk_level")}
Response type: {llm_contract.get("response_type")}
Episode phase: {llm_contract.get("episode_phase")}

KNOWN FACTS (DO NOT ASK ABOUT THESE):
{known_facts_str}

ALLOWED QUESTIONS (YOU MAY ASK ONLY THESE):
{allowed_questions_str}

MAX QUESTIONS ALLOWED:
{llm_contract.get("max_questions")}

STRICT RULES:
- You MUST NOT ask about known facts.
- You MUST NOT ask questions outside ALLOWED QUESTIONS.
- You MUST NOT exceed MAX QUESTIONS.
- You MUST NOT escalate beyond provided Risk level.
"""

    _pet_name = (pet_profile.get("name") or "питомец") if pet_profile else "питомец"
    _pet_species = (pet_profile.get("species") or "").lower()
    _pet_gender = (pet_profile.get("gender") or "") if pet_profile else ""
    _pet_neutered = pet_profile.get("neutered") if pet_profile else None
    _pet_age = pet_profile.get("age_years") if pet_profile else None
    _pet_breed = (pet_profile.get("breed") or "неизвестна") if pet_profile else "неизвестна"
    _pet_color = (pet_profile.get("color") or "") if pet_profile else ""
    _pet_weight = pet_profile.get("weight_kg") if pet_profile else None
    _pet_medical = pet_profile.get("medical") if pet_profile else None

    # Медкарта
    _chronic = ""
    _allergies = ""
    _diet = ""
    _last_vet = ""
    if _pet_medical:
        _chronic = ", ".join(_pet_medical.get("chronic_conditions") or []) or ""
        _allergies = ", ".join(_pet_medical.get("allergies") or []) or ""
        _diet = _pet_medical.get("diet_type") or ""
        _last_vet = str(_pet_medical.get("last_vet_visit") or "")

    # Строим блок профиля для промпта
    _gender_ru = {"male": "самец", "female": "самка"}.get(_pet_gender, "")
    _neutered_ru = ""
    if _pet_neutered is True:
        _neutered_ru = "кастрирован" if _pet_gender == "male" else "стерилизована"
    elif _pet_neutered is False:
        _neutered_ru = "не кастрирован" if _pet_gender == "male" else "не стерилизована"

    _profile_block = (
        f"Профиль {_pet_name}:\n"
        f"- Вид: {_pet_species or '—'}\n"
        f"- Порода: {_pet_breed}\n"
        f"- Пол: {_gender_ru or '—'}\n"
        f"- Кастрация: {_neutered_ru or '—'}\n"
        + (f"- Возраст: {_pet_age} лет\n" if _pet_age else "")
        + (f"- Вес: {_pet_weight} кг\n" if _pet_weight else "")
        + (f"- Окрас: {_pet_color}\n" if _pet_color else "")
        + (f"- Хронические болезни: {_chronic}\n" if _chronic else "")
        + (f"- Аллергии: {_allergies}\n" if _allergies else "")
        + (f"- Тип питания: {_diet}\n" if _diet else "")
        + (f"- Последний визит к врачу: {_last_vet}\n" if _last_vet else "")
    )

    tone_block = (
        "Тон и стиль:\n"
        "- Ты заботливый, тёплый помощник — не робот и не врач.\n"
        f"- Всегда обращайся к животному по кличке: {_pet_name}. Никогда не пиши \"питомец\" или \"животное\".\n"
        "- Короткие фразы. Без канцелярита. Без сухих формулировок.\n"
        "- Если ситуация серьёзная — сохраняй спокойствие, не пугай.\n"
        "- Если ситуация лёгкая — можно добавить тепло и заботу.\n"
        "- Никогда не начинай ответ с \"Я понимаю\" или \"Конечно\".\n"
    )

    _off_topic_block = ""
    if not clinical_decision:
        _off_topic_block = (
            "\nВАЖНО: Ты отвечаешь ТОЛЬКО на вопросы о здоровье и самочувствии питомца.\n"
            "Если пользователь спрашивает о развлечениях, играх, прогулках, еде как образе жизни — "
            "мягко перенаправь: скажи что ты медицинский помощник и можешь помочь только по вопросам здоровья.\n"
            "Не давай советов по развлечениям. Не давай рецептов. Не давай советов по уходу.\n"
        )

    _redundancy_block = ""
    if previous_assistant_text:
        _redundancy_block = (
            "\nАНТИ-ПОВТОР (СТРОГО):\n"
            "Предыдущий ответ уже был отправлен. НЕ повторяй:\n"
            "- те же советы дословно или близко к тексту\n"
            "- те же вводные фразы\n"
            "- тот же список действий если ситуация не изменилась\n"
            "Вместо повтора:\n"
            "- задай уточняющий вопрос если фаза CLARIFY/ASSESS\n"
            "- оцени динамику: стало лучше или хуже\n"
            "- если ACTION — дай новый шаг или уточни предыдущий\n"
            f"Предыдущий ответ (первые 300 символов): {(previous_assistant_text or '')[:300]}\n"
        )

    if message_mode == "REGISTRATION_PROMPT":
        _pet_name_reg = pet_profile.get("name") if pet_profile else "питомец"
        _owner_reg = owner_name or ""
        _address_reg = f"{_owner_reg}, " if _owner_reg else ""

        system_block = (
            f"Ты — Dominik.\n"
            f"Пользователь только что создал профиль питомца {_pet_name_reg}.\n"
            f"Твоя задача: предложить зарегистрироваться, чтобы сохранить данные.\n"
            f"\n"
            f"МОТИВАЦИЯ (используй один из этих аргументов):\n"
            f"- 'Профиль {_pet_name_reg} хранится только на этом устройстве. "
            f"Зарегистрируйся — и он сохранится навсегда, даже если сменишь телефон.'\n"
            f"- 'Регистрация займёт 10 секунд. Потом доступ с любого устройства.'\n"
            f"- 'Если потеряешь телефон — все данные {_pet_name_reg} останутся у тебя.'\n"
            f"\n"
            f"Обратись по имени: {_address_reg}\n"
            f"Формат: 1-2 предложения мотивации + призыв к действию.\n"
            f"НЕ давай медицинских советов.\n"
            f"Тон: тёплый, не навязчивый, честный.\n"
            f"Максимум 3 предложения.\n"
            f"Отвечай только на русском языке.\n"
        )
        user_prompt = f"Сообщение пользователя: {user_message}"

    elif message_mode == "ONBOARDING_COMPLETE":
        _pet_name_done = pet_profile.get("name") if pet_profile else "питомец"
        _owner = owner_name or ""
        _address_done = f"{_owner}! " if _owner else ""

        system_block = (
            f"Ты — Dominik.\n"
            f"Онбординг завершён. Профиль {_pet_name_done} только что создан.\n"
            f"Твоя задача: написать тёплое короткое сообщение о том что профиль готов.\n"
            f"Обратись к пользователю по имени: {_address_done}\n"
            f"Скажи что карточка {_pet_name_done} появилась в разделе Профиль.\n"
            f"НЕ предлагай регистрацию — это сделает система отдельно.\n"
            f"Максимум 2-3 предложения. Тепло. На ты.\n"
            f"Никогда не начинай с 'Я понимаю' или 'Конечно'.\n"
            f"Отвечай только на русском языке.\n"
        )
        user_prompt = f"Сообщение пользователя: {user_message}"

    elif message_mode == "ONBOARDING":
        # Детерминированные вопросы — LLM НЕ МОЖЕТ менять суть

        # ШАГ 0 — имя владельца (особый случай)
        if strict_override == "owner_name":
            _welcome_block = (
                "Это ПЕРВОЕ сообщение пользователя в приложении.\n"
                "Начни с тёплого приветствия (учитывай время суток).\n"
                "Представься: 'Я Dominik — твой помощник по здоровью питомца.'\n"
                "Кратко (1 предложение) что умеешь: симптомы, напоминания, экстренная помощь.\n"
                "Затем задай вопрос: как тебя зовут?\n"
                "Всё вместе — 3-4 предложения максимум.\n"
            )
            system_block = (
                f"Ты — Dominik, тёплый помощник для владельцев питомцев.\n"
                f"Текущее время: {client_time or 'неизвестно'}.\n"
                f"Учитывай время суток: 6-12 'Доброе утро', 12-18 'Добрый день', 18-23 'Добрый вечер'.\n"
                f"\n"
                f"СТРОГИЕ ПРАВИЛА:\n"
                f"1. Задай ровно один вопрос — как зовут пользователя.\n"
                f"2. Максимум 3-4 предложения.\n"
                f"3. Отвечай только на русском языке.\n"
                f"4. Никогда не начинай с 'Я понимаю' или 'Конечно'.\n"
                f"\n"
                f"{_welcome_block}"
            )
            user_prompt = f"Сообщение пользователя: {user_message}"
        else:
            # Получаем имя из профиля и владельца
            _pet_name_hint = ""
            _owner_name_hint = ""
            if pet_profile and pet_profile.get("name"):
                _pet_name_hint = pet_profile.get("name")
            if owner_name:
                _owner_name_hint = owner_name

            # Обращение к владельцу по имени если известно
            _address = f"{_owner_name_hint}, " if _owner_name_hint else ""

            _onboarding_questions = {
                # ОБЯЗАТЕЛЬНЫЕ
                "species": f"Спроси кошка или собака. Одно предложение. Обратись по имени: '{_address}'.",
                "name": f"Спроси как зовут питомца. Одно предложение. Обратись: '{_address}'.",
                "name_reaction": f"Коротко отреагируй на кличку {_pet_name_hint}. 2-4 слова без смайлов. Примеры: 'Красивое имя', 'Редкая кличка', 'Хорошо звучит'. Никаких вопросов. Никаких оценок хозяина.",
                "gender": f"Спроси пол {_pet_name_hint}. Используй кличку. Одно предложение.",
                "neutered": f"Спроси кастрирован ли {_pet_name_hint} — используй правильную форму по полу. Одно предложение.",
                "age": f"Спроси сколько лет {_pet_name_hint} или когда родился. Одно предложение.",
                # НЕОБЯЗАТЕЛЬНЫЕ
                "photo": f"Предложи загрузить фото {_pet_name_hint} для аватарки профиля. Скажи что можно пропустить и добавить позже. Одно-два предложения.",
                "breed": f"Спроси породу {_pet_name_hint}. Скажи что можно написать 'не знаю' и пропустить. Одно предложение.",
                "color": f"Спроси окрас {_pet_name_hint}. Можно пропустить. Одно предложение.",
                "features": f"Спроси есть ли особые приметы у {_pet_name_hint} — пятна, шрамы, необычный окрас. Можно пропустить. Одно предложение.",
                "chip_id": f"Спроси есть ли у {_pet_name_hint} микрочип и если да — его номер. Можно пропустить. Одно предложение.",
                "stamp_id": f"Спроси есть ли у {_pet_name_hint} клеймо и если да — его номер. Можно пропустить. Одно предложение.",
            }

            _question_instruction = _onboarding_questions.get(
                strict_override, "Спроси следующий вопрос о питомце."
            )

            system_block = (
                f"Ты — Dominik, тёплый помощник для владельцев питомцев.\n"
                f"Сейчас ты заполняешь профиль питомца через диалог.\n"
                f"Текущее время пользователя: {client_time or 'неизвестно'}.\n"
                f"Учитывай время суток: 6-12 'Доброе утро', 12-18 'Добрый день', 18-23 'Добрый вечер'.\n"
                f"\n"
                f"СТРОГИЕ ПРАВИЛА:\n"
                f"1. Задай РОВНО ОДИН вопрос — тот что указан ниже. Никаких других вопросов.\n"
                f"2. НЕ спрашивай про характер, игры, прогулки, привычки — это не твоя задача сейчас.\n"
                f"3. НЕ давай медицинских советов на этом этапе.\n"
                f"4. Если пользователь пишет что-то не по теме — мягко верни к вопросу.\n"
                f"5. Если пользователь дал ответ на текущий вопрос — подтверди и ОСТАНОВИСЬ. Не задавай следующий вопрос.\n"
                f"6. Отвечай только на русском языке.\n"
                f"7. Максимум 2-3 предложения.\n"
                f"\n"
                f"ТЕКУЩИЙ ВОПРОС (задай ТОЛЬКО его):\n"
                f"{_question_instruction}\n"
            )

            user_prompt = f"Сообщение пользователя: {user_message}"

    elif message_mode == "CASUAL":
        system_block = (
            f"Ты — Dominik, тёплый и заботливый помощник для владельцев питомцев.\n"
            f"Тебя создали чтобы ты был рядом — как друг который всегда готов помочь.\n"
            f"Питомец: {_pet_name}, {_pet_species}.\n"
            f"Ты говоришь с ХОЗЯИНОМ питомца, не с питомцем.\n"
            f"Упоминай питомца по имени {_pet_name} в третьем лице.\n"
            f"Тон: тёплый, живой, на ты. Короткие фразы. Без канцелярита.\n"
            f"Текущее время пользователя: {client_time or 'неизвестно'}.\n"
            f"\n"
            f"СТРОГИЕ ПРАВИЛА:\n"
            f"1. НЕ спрашивай про характер, игры, прогулки, привычки.\n"
            f"2. НЕ задавай вопросов ради вопросов — отвечай по существу.\n"
            f"3. Если пользователь просто здоровается — ответь коротко и спроси чем помочь по здоровью {_pet_name}.\n"
            f"4. Если нечего спросить по медицине — просто скажи что ты рядом если понадобишься.\n"
            f"5. Максимум 2-3 предложения.\n"
            f"6. Отвечай только на русском языке.\n"
            f"Никогда не начинай с 'Я понимаю' или 'Конечно'.\n"
        )
    elif message_mode == "PROFILE":
        system_block = (
            tone_block
            + f"Ты — Dominik, заботливый помощник для владельцев питомцев.\n"
            + f"Ты говоришь с ХОЗЯИНОМ питомца, не с питомцем. Упоминай питомца по имени {_pet_name} в третьем лице — 'Боня', 'у Бони', 'Боня сейчас'. Никогда не обращайся напрямую к питомцу.\n"
            + f"Текущее время пользователя: {client_time or 'неизвестно'}.\n"
            + f"Приветствуй ТОЛЬКО если previous_assistant_text пустой или None — значит это первое сообщение сессии.\n"
            + f"Если уже общались (previous_assistant_text не пустой) — без приветствий, продолжай разговор.\n"
            + f"Учитывай время суток: 6-12 'Доброе утро', 12-18 'Добрый день', 18-23 'Добрый вечер', 23-6 'Не сплю, всегда рядом'.\n"
            + f"Используй данные профиля питомца чтобы ответ был личным и точным.\n"
            + f"Если вопрос касается здоровья — мягко уточни детали.\n"
            + f"Отвечай только на русском языке. Никаких английских слов.\n"
            + (f"OVERRIDE: {strict_override}\n" if strict_override else "")
        )
    else:  # CLINICAL
        system_block = (
            tone_block
            + _off_topic_block
            + _redundancy_block
            + f"Ты — Dominik. Сейчас ты в режиме медицинской помощи.\n"
            + f"Ты говоришь с ХОЗЯИНОМ питомца, не с питомцем. Упоминай питомца по имени {_pet_name} в третьем лице — 'Боня', 'у Бони', 'Боня сейчас'. Никогда не обращайся напрямую к питомцу.\n"
            + f"Текущее время пользователя: {client_time or 'неизвестно'}.\n"
            + f"Приветствуй ТОЛЬКО если previous_assistant_text пустой или None — значит это первое сообщение сессии.\n"
            + f"Если уже общались (previous_assistant_text не пустой) — без приветствий, продолжай разговор.\n"
            + f"Учитывай время суток: 6-12 'Доброе утро', 12-18 'Добрый день', 18-23 'Добрый вечер', 23-6 'Не сплю, всегда рядом'.\n"
            + "Ты медицинский AI-ассистент для здоровья питомцев.\n"
            + "Отвечай ТОЛЬКО на русском языке. Никаких английских слов и фраз.\n"
            + "Твоя роль: здоровье животного. Не советы по развлечениям, питанию образу жизни.\n"
            + "Если clinical_decision передан — следуй ему строго. Он важнее urgency_score.\n"
            + "Если escalation >= MODERATE — явно упомяни количество эпизодов.\n"
            + (f"OVERRIDE: {strict_override}\n" if strict_override else "")
            + contract_block
            + clinical_escalation_block
        )

    if message_mode == "CASUAL":
        user_prompt = f"Сообщение: {user_message}"

    elif message_mode == "PROFILE":
        _mem_short = (
            memory_context[:300]
            if memory_context and memory_context != "No prior medical history."
            else "нет"
        )
        user_prompt = f"""\
{_profile_block}
Важные медицинские факты (если есть):
{_mem_short}

Сообщение: {user_message}"""

    else:  # CLINICAL
        user_prompt = f"""\
{_profile_block}
Medical history:
{memory_context}

Recent events:
{recent_events}

Urgency level: {urgency_score}
Risk level: {risk_level}
{escalation_instructions}{continuation_instructions}
Instructions:
{urgency_instructions}

Clinical decision:
Symptom: {clinical_decision["symptom"] if clinical_decision else None}
Episodes today: {clinical_decision["stats"]["today"] if clinical_decision else None}
Episodes last hour: {clinical_decision["stats"]["last_hour"] if clinical_decision else None}
Escalation level: {clinical_decision["escalation"] if clinical_decision else None}
Stop questioning: {clinical_decision["stop_questioning"] if clinical_decision else None}
Override urgency: {clinical_decision["override_urgency"] if clinical_decision else None}
Consecutive escalations: {clinical_decision.get("consecutive_escalations", 0) if clinical_decision else None}
Consecutive critical: {clinical_decision.get("consecutive_critical", 0) if clinical_decision else None}
Episode phase: {clinical_decision.get("episode_phase") if clinical_decision else None}
Reaction type: {clinical_decision.get("reaction_type", "normal_progress") if clinical_decision else None}
Response type: {clinical_decision.get("response_type") if clinical_decision else None}
User intent: {clinical_decision.get("user_intent") if clinical_decision else None}
Constraint: {clinical_decision.get("constraint") if clinical_decision else None}

Previous assistant summary: {previous_assistant_text or "none"}

User message:
{user_message}"""

    # --- DETERMINISTIC TEMPLATE OVERRIDE + CONTROLLED CONTEXT ---
    # Only for CLINICAL mode when clinical_decision is available.
    # Replaces the free-form user_prompt with a structured template + limited context block.
    if message_mode == "CLINICAL" and clinical_decision:
        template = select_template(clinical_decision.get("response_type"))
        phase_prefix = get_phase_prefix(clinical_decision.get("episode_phase"))

        questions = llm_contract.get("allowed_questions", []) if llm_contract else []
        questions_block = "\n".join(
            f"- Есть ли {q}?" for q in questions
        ) or "- (нет уточняющих вопросов)"

        actions_block = _build_actions_block(clinical_decision)

        deterministic_prompt = phase_prefix + template.format(
            symptom=clinical_decision.get("symptom"),
            episodes_today=clinical_decision["stats"]["today"],
            questions_block=questions_block,
            actions_block=actions_block,
        )

        # Controlled context: strictly 4 clinical fields, nothing else
        def _clean(value):
            if value is None:
                return "-"
            if isinstance(value, str) and not value.strip():
                return "-"
            return value

        _food_item = _clean(clinical_decision.get("food"))
        _food_line = f"- Съеденное до симптома: {_food_item}\n" if _food_item != "-" else ""

        _history_block = (
            f"- История болезней: {memory_context}\n"
            if memory_context and memory_context != "No prior medical history."
            else ""
        )

        context_block = f"""Контекст:
- Фаза эпизода: {_clean(clinical_decision.get("episode_phase"))}
- Тип реакции: {_clean(clinical_decision.get("reaction_type"))}
- Намерение пользователя: {_clean(clinical_decision.get("user_intent"))}
- Ограничения: {_clean(clinical_decision.get("constraint"))}
{_food_line}{_history_block}"""

        user_prompt = f"{deterministic_prompt}\n{context_block}\n"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_block},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.4
    )

    return response.choices[0].message.content


def extract_event_data(user_message: str):
    """
    Извлекает структурированные данные из сообщения
    """

    extraction_prompt = f"""
Extract structured data from the user message.

Return JSON only.

Fields:
- symptom
- food
- medication
- behavior
- urgency_score (0-3)
- blood (boolean, default false)
- lethargy_level ("none" | "mild" | "severe", default "none")
- refusing_water (boolean, default false)
- temperature_value (float | null, temperature in Celsius if mentioned, null otherwise)
- respiratory_rate (int | null, breathing rate per minute if mentioned, null otherwise)
- seizure_duration (float | null, duration of seizure in minutes if mentioned, null otherwise)

Urgency scale:
0 = normal
1 = monitor
2 = recommend vet
3 = urgent

blood = true if user mentions any of:
кровь, с кровью, кровавая, кровавый, кровит, кровь в рвоте, кровь в стуле
Otherwise false.

User message:
{user_message}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": (
                "You are a veterinary triage extraction engine.\n"
                "Your ONLY job: extract structured medical data from owner messages.\n"
                "Return ONLY valid JSON. No explanations. No markdown. No code blocks.\n\n"
                "Extract this exact structure:\n"
                "{\n"
                '  "symptoms": [],\n'
                '  "duration_hours": null,\n'
                '  "species": "dog|cat|unknown",\n'
                '  "size": "small|medium|large|unknown",\n'
                '  "age_category": "puppy|kitten|adult|senior|unknown",\n'
                '  "severity_hints": [],\n'
                '  "is_ingestion": false,\n'
                '  "ingested_substance": null,\n'
                '  "mode": "CASUAL|CLINICAL|PROFILE"\n'
                "}\n\n"
                "EXTRACTION RULES — apply strictly:\n\n"
                "SYMPTOMS (use exact keys below):\n"
                '- "рвёт" / "рвота" / "тошнит" → ["vomiting"]\n'
                '- "не может удержать воду" / "рвёт сразу после питья" → ["vomiting_water_immediately"]\n'
                '- "кровь в рвоте тёмная" / "кофейная гуща" → ["vomiting_coffee_grounds"]\n'
                '- "понос" / "диарея" / "жидкий стул" → ["diarrhea"]\n'
                '- "кровь в стуле" / "кровавый понос" → ["blood_in_stool"]\n'
                '- "чёрный стул" / "дёгтеобразный" → ["melena"]\n'
                '- "не ест" / "отказ от еды" → ["anorexia"]\n'
                '- "не пьёт" / "отказ от воды" → ["refusing_water"]\n'
                '- "живот вздулся" / "живот твёрдый" → ["abdominal_distension"]\n'
                '- "вялый" / "лежит" / "слабый" / "апатичный" → ["lethargy"]\n'
                '- "совсем не встаёт" / "не реагирует" → ["severe_lethargy"]\n'
                '- "тяжело дышит" / "дышит животом" / "живот ходит" → ["dyspnea"]\n'
                '- "кот дышит ртом" / "пасть открыта" → ["open_mouth_breathing_cat"]\n'
                '- "не может лечь" / "ночью задыхается" → ["cannot_lie_down_breathing"]\n'
                '- "вытянул шею при дыхании" → ["neck_extended_breathing"]\n'
                '- "синюшные дёсны" / "синий язык" → ["cyanosis"]\n'
                '- "сидит в лотке" / "тужится" / "плачет в туалете" → ["urinary_straining"]\n'
                '- "совсем не мочится" / "ни капли" → ["urinary_no_output"]\n'
                '- "кричит в лотке" / "орёт когда писает" → ["urinary_crying_in_litter"]\n'
                '- "судороги" / "трясло" / "конвульсии" / "припадок" → ["seizure_short"]\n'
                '- "судороги больше 3 минут" / "не останавливается" → ["seizure_long"]\n'
                '- "два или больше припадка за день" → ["seizure_cluster"]\n'
                '- "шатается" / "теряет равновесие" → ["ataxia"]\n'
                '- "зад волочит" / "задние лапы не работают" → ["dragging_hind_legs", "paralysis_acute"]\n'
                '- "упал и не встаёт" / "потерял сознание" → ["collapse"]\n'
                '- "упал на секунду" / "как отключился" / "ноги разъехались" → ["syncope"]\n'
                '- "не видит" / "врезается в предметы" → ["sudden_blindness"]\n'
                '- "хромает" / "поджимает лапу" / "бережёт лапу" → ["mild_lameness"]\n'
                '- "совсем не ставит лапу" → ["non_weight_bearing"]\n'
                '- "не может встать" / "лежит и не поднимается" → ["cannot_stand"]\n'
                '- "попал под машину" / "сбили" → ["trauma_hit_by_car"]\n'
                '- "пищит от боли" / "рычит при касании" / "кричит если трогать" → ["pain_on_touch"]\n'
                '- "температура высокая" / "горячий" / "жар" → ["fever_high"]\n'
                '- "температура 41" / "выше 41" → ["fever_critical"]\n'
                '- "холодный" / "замёрз" / "температура низкая" → ["hypothermia"]\n'
                '- "перегрелся" / "тепловой удар" / "был в машине жара" → ["heatstroke"]\n'
                '- "красный глаз" → ["red_eye"]\n'
                '- "слезятся глаза" / "выделения из глаза" → ["ocular_discharge"]\n'
                '- "щурится" / "держит глаз закрытым" → ["squinting_eye_pain"]\n'
                '- "ослеп внезапно" / "не видит" → ["sudden_blindness_eye"]\n'
                '- "сердце колотится" / "бьётся сильно" → ["tachycardia_resting"]\n'
                '- "упал в обморок" / "терял сознание" → ["syncope"]\n'
                '- "живот стал больше за дни" / "набрал вес резко" → ["ascites_suspected"]\n'
                '- "быстро устаёт на прогулке" / "стал менее активным" → ["exercise_intolerance"]\n'
                '- "не ложится из-за дыхания" / "сидит ночью" → ["orthopnea"]\n'
                '- "съел жвачку" / "ксилит" / "зубную пасту" → ["xylitol_ingestion"]\n'
                '- "выпил антифриз" / "тосол" / "незамерзайка" → ["antifreeze_ingestion"]\n'
                '- "съел лилию" (кошка) → ["lily_ingestion_cat"]\n'
                '- "батарейку проглотил" → ["battery_ingestion"]\n'
                '- "съел пакет" / "пластик проглотил" → ["plastic_swallowed"]\n'
                '- "съел нитку" / "верёвку" / "ленточку" → ["string_thread_swallowed"]\n'
                '- "проглотил кость" / "съел кость" → ["bone_swallowed"]\n'
                '- "съел игрушку" → ["toy_swallowed"]\n'
                '- "съел носок" / "тряпку проглотил" → ["sock_clothing_swallowed"]\n'
                '- "съел шоколад" → ["chocolate_ingestion"]\n'
                '- "съел виноград" / "изюм" → ["grape_raisin_ingestion"]\n\n'
                "DURATION:\n"
                '- "час" = 1, "два часа" = 2, "полдня" = 12\n'
                '- "день" = 24, "сутки" = 24, "два дня" = 48, "трое суток" = 72\n'
                '- "с утра" = 8, "со вчера" = 24, "неделю" = 168\n\n'
                "SPECIES:\n"
                '- кот / кошка → "cat"\n'
                '- собака / пёс / щенок → "dog"\n\n'
                "SIZE (для собак):\n"
                '- той, чихуахуа, шпиц, йорк → "small"\n'
                '- лабрадор, хаски, немецкая овчарка → "medium"\n'
                '- дог, ротвейлер, мастиф → "large"\n\n'
                "AGE_CATEGORY:\n"
                '- щенок / котёнок / до года → "puppy"/"kitten"\n'
                '- пожилой / старый / 10+ лет → "senior"\n\n'
                "SEVERITY_HINTS — включать слова типа:\n"
                '"кричит", "не встаёт", "потерял сознание", "синий язык", "не дышит", "рухнул"\n\n'
                "MODE:\n"
                "- CLINICAL: есть симптомы болезни\n"
                '- CASUAL: общий вопрос без симптомов ("как часто купать?")\n'
                '- PROFILE: вопрос про данные питомца ("сколько весит?")\n\n'
                "is_ingestion = true если что-то проглочено.\n"
                "ingested_substance = название того что проглочено."
            )},
            {"role": "user", "content": extraction_prompt}
        ],
        temperature=0
    )

    return response.choices[0].message.content
