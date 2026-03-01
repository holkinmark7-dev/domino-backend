"""
response_templates.py — Deterministic response template selector (DAY 2)

Backend selects a structural template by response_type.
LLM fills in the variables — it does NOT generate free-form text from scratch.
"""

_TEMPLATES = {
    "ASSESS": """\
Кратко опишите текущее состояние.
Симптом: {symptom}

Уточните:
{questions_block}
""",

    "CLARIFY": """\
Сейчас важно уточнить детали по симптомам.

Симптом: {symptom}
Эпизодов сегодня: {episodes_today}

Уточните:
{questions_block}
""",

    "ACTION": """\
Состояние требует действий.

Симптом: {symptom}
Эпизодов сегодня: {episodes_today}

Действия:
{actions_block}
""",

    "ACTION_HOME_PROTOCOL": """\
Необходимо стабилизировать состояние дома.

Симптом: {symptom}

Шаги:
{actions_block}
""",

    "URGENT_GUIDANCE": """\
Ситуация требует срочного внимания.

Симптом: {symptom}
Эпизодов сегодня: {episodes_today}

Уточните:
{questions_block}
""",

    "URGENT_QUESTIONS": """\
Необходимо срочно уточнить детали.

Симптом: {symptom}
Эпизодов сегодня: {episodes_today}

Уточните:
{questions_block}
""",
}

_DEFAULT = "ASSESS"


def select_template(response_type: str) -> str:
    """Return the structural template string for the given response_type.
    Falls back to ASSESS for unknown types.
    """
    return _TEMPLATES.get(response_type, _TEMPLATES[_DEFAULT])


def get_phase_prefix(episode_phase: str) -> str:
    """Return a short tone-setting prefix for the given episode phase.
    Returns an empty string for "initial" or any unknown phase.
    Never affects escalation or contract — text only.
    """
    mapping = {
        "initial": "",
        "worsening": "Есть признаки ухудшения состояния.\n\n",
        "progressing": "Состояние требует дополнительного внимания.\n\n",
        "stable": "Динамика без ухудшения.\n\n",
        "improving": "Есть признаки улучшения состояния.\n\n",
    }
    return mapping.get(episode_phase, "")
