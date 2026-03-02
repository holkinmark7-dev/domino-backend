"""
Маппинг escalation → числовой heatmap_score.
Единый источник правды для всего проекта.
"""

from typing import Optional

HEATMAP_MAP = {
    "NONE":     0,
    "LOW":      1,
    "MODERATE": 2,
    "HIGH":     3,
    "CRITICAL": 3,   # HIGH и CRITICAL = один уровень опасности для UI
}

def heatmap_score(escalation: Optional[str]) -> int:
    """
    Возвращает 0-3.
    None / неизвестное значение → 0.
    """
    if not escalation:
        return 0
    return HEATMAP_MAP.get(escalation.upper(), 0)
