from pydantic import BaseModel, Field
from typing import Dict
from datetime import date


class CalendarDayEntry(BaseModel):
    heatmap_score: int = Field(..., ge=0, le=3, description="0=none, 1=LOW, 2=MODERATE, 3=HIGH/CRITICAL")
    event_count: int = Field(..., ge=0)
    has_critical: bool = False


class CalendarPeriod(BaseModel):
    from_date: date = Field(..., alias="from")
    to_date: date = Field(..., alias="to")

    class Config:
        populate_by_name = True


class CalendarSummary(BaseModel):
    total_events: int = 0
    days_with_events: int = 0
    max_heatmap_score: int = Field(0, ge=0, le=3)
    critical_days: int = 0


class CalendarHeatmapResponse(BaseModel):
    pet_id: str
    period: CalendarPeriod
    days: Dict[str, CalendarDayEntry]
    summary: CalendarSummary
