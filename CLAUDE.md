\# Domino Pets — Backend Context for Claude Code



\## Кто я и что строю

Domino Pets — AI-powered приложение для здоровья питомцев. Chat as single entry point, cards/dashboard/timeline as output.

AI-персонаж: \*\*Dominik\*\* (только латиница, никогда не "Доминик").

Марк — соло-фаундер, не разработчик. Работает через Claude (планирование) + Claude Code (исполнение).



\---



\## Стек

\- \*\*Backend:\*\* FastAPI + Python

\- \*\*DB:\*\* Supabase (PostgreSQL)

\- \*\*Storage:\*\* Supabase, бакет `pet-avatars` (публичный, 5MB, jpeg/png/webp)

\- \*\*Mobile:\*\* React Native + Expo (отдельная папка)

\- \*\*Путь бэкенда:\*\* `C:\\Users\\markh\\domino-backend`



\---



\## AI-роутинг — ТОЛЬКО в одном месте

Все модели только в `routers/services/model\_router.py`. Нигде больше хардкода нет.



| Провайдер | Модель | Когда |

|-----------|--------|-------|

| Google | Gemini 2.5 Flash | CASUAL, ONBOARDING, REGISTRATION |

| OpenAI | GPT-4o | Все задачи с изображениями (OCR, порода) |

| Anthropic | Claude Haiku 4.5 | CLINICAL LOW/MODERATE |

| Anthropic | Claude Sonnet 4.6 | CLINICAL HIGH/CRITICAL |



Точка диспетчеризации: `\_call\_llm()` в `ai.py` — единственный вход для всех AI-вызовов.



\---



\## Ключевые файлы



| Файл | Назначение |

|------|-----------|

| `routers/chat.py` | Основной chat endpoint |

| `routers/ai.py` | `\_call\_llm()` диспетчер |

| `routers/services/model\_router.py` | Единственный источник AI моделей |

| `design-reference/dominik-system-v2.3.md` | Система мышления Dominik, источник правды для всех разговорных сценариев |

| `routers/onboarding\_ai.py` | НОВЫЙ AI-first онбординг (в разработке) |

| `routers/onboarding\_new.py` | СТАРЫЙ FSM онбординг (удалить после теста нового) |

| `routers/services/vision\_service.py` | GPT-4o OCR и breed detection |

| `memory.py` | age\_skipped → birth\_date\_skipped |



\---



\## ЗАПРЕЩЁННЫЕ файлы — НИКОГДА НЕ ТРОГАТЬ

\- `breed\_risk\_modifiers.py` — медицинское ядро, абсолютный запрет



\---



\## База данных — важные детали



\*\*Таблица `pets` — правильные названия полей:\*\*

\- `avatar\_url` (НЕ photo\_url)

\- `age\_years` (НЕ age)

\- `chip\_id\_skipped` (НЕ chip\_skipped)

\- `stamp\_id\_skipped` (НЕ stamp\_skipped)

\- `birth\_date\_skipped`, `neutered\_skipped`, `photo\_avatar\_skipped`



\*\*RLS:\*\* применено на всех 9 таблицах. Бэкенд использует service key → обходит RLS.



\*\*Тестовый user ID:\*\* `bc3de4cc-df0f-4492-86f8-b21e077eb795`



\---



\## Текущая архитектура онбординга (AI-First, с 12 марта 2026)



Переход с 15-состояний FSM на AI-first подход:

\- \*\*Было:\*\* `onboarding\_new.py` — жёсткий FSM, 15 состояний

\- \*\*Стало:\*\* `onboarding\_ai.py` — Dominik ведёт разговор сам через системный промпт



\*\*Формат ответа бэкенда:\*\*

```json

{

&#x20; "text": "сообщение Dominik",

&#x20; "quick\_replies": \[{"label": "...", "value": "...", "preferred": true}],

&#x20; "collected": {"pet\_name": "...", "species": "..."},

&#x20; "onboarding\_phase": "active | complete",

&#x20; "pet\_id": "uuid если complete"

}

```



\*\*Логика:\*\* бэкенд только проверяет какие поля заполнены. Никаких состояний.



\---



\## Дизайн-система — абсолютные запреты



1\. \*\*НОЛЬ emoji\*\* нигде — ни в коде, ни в тестах, ни в текстах

2\. \*\*Quick reply кнопки\*\* — только кастомные SVG иконки из брендбука

3\. \*\*Шрифт\*\* — только Inter

4\. \*\*Тексты Dominik\*\* — переносить точно, без переформулирования



\*\*Цвета бренда:\*\*

\- Accent: `#2E8B6A`

\- Background: `#F5F4F0`

\- Ink: `#1B1B18`

\- Neutral Border: `#EFEEE9`



\---



\## Голос Dominik (Style В)

Заботливый, короткие предложения, никогда не звучит как бот.



\*\*ЗАПРЕЩЁННЫЕ фразы:\*\*

\- "С чего начнём?" 

\- "Введите дату рождения"

\- "Записал! Звучит замечательно"

\- "Я Домино"



\*\*Правильно:\*\*

\- "Лабрадоры — добряки с вечным аппетитом. Когда родился Моисей?"

\- "Моисея уже кастрировали?"



\---



\## Протокол работы — строго соблюдать



1\. \*\*Шаг 0 обязателен:\*\* сначала читай указанные файлы и докладывай что видишь

2\. Жди явного подтверждения \*\*"Согласовано — выполняй"\*\* перед реализацией

3\. Хирургические точечные изменения — не рефакторинг

4\. После выполнения: `pytest tests/ -q` → все зелёные → commit → push GitHub



\---



\## Критические ошибки которые нельзя повторять



\- `auto\_follow=True` как boolean → пустые пузыри (всегда проверять тип через `isinstance()`)

\- Hardcode моделей вне `model\_router.py` → grep аудит в Шаге 0

\- Unicode emoji в продукте → явная проверка после каждого ТЗ

\- Переформулирование текстов Dominik → тексты переносить дословно

\- Трогать лишние файлы → только указанные в ТЗ



\---



\## Текущий статус тестов

375+ тестов проходят. После каждого ТЗ количество не должно уменьшаться.



\---



\## IP для живого тестирования

`http://192.168.1.6:8000` — оба устройства в одной WiFi сети

