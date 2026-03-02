"""
tests/test_heatmap.py — Unit tests for heatmap_score + calendar_index enrichment
6 tests:
  T1: heatmap_score parametric mapping
  T2: calendar_index includes heatmap_score (from get_timeline_month)
  T3: CRITICAL day has_critical=True
  T4: multiple events same day → max escalation wins
  T5: empty month → calendar_index is empty dict
  T6: resolved episode day still in calendar_index
"""
import sys, os, unittest
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.services.heatmap import heatmap_score
import routers.timeline as tl_module


# ── Unit tests for heatmap_score() ──────────────────────────────────────────

@pytest.mark.parametrize("escalation, expected", [
    (None, 0),
    ("", 0),
    ("NONE", 0),
    ("LOW", 1),
    ("low", 1),           # case-insensitive
    ("MODERATE", 2),
    ("HIGH", 3),
    ("CRITICAL", 3),
    ("UNKNOWN_VALUE", 0),  # fallback
])
def test_heatmap_score_mapping(escalation, expected):
    assert heatmap_score(escalation) == expected


# ── Mock helper ─────────────────────────────────────────────────────────────

def _make_sb(days=None, episodes=None):
    """Build a mock supabase with timeline_days and episodes tables."""
    sb = MagicMock()
    _cache = {}

    def _table(name):
        if name in _cache:
            return _cache[name]
        m = MagicMock()
        sel = MagicMock()

        if name == "timeline_days":
            result = MagicMock()
            result.data = days if days is not None else []
            sel.eq.return_value = sel
            sel.gte.return_value = sel
            sel.lte.return_value = sel
            sel.lt.return_value = sel
            sel.order.return_value = sel
            sel.limit.return_value = sel
            sel.single.return_value = sel
            sel.execute.return_value = result
            m.select.return_value = sel
            ups = MagicMock()
            ups.execute.return_value = MagicMock()
            m.upsert.return_value = ups

        elif name == "episodes":
            result = MagicMock()
            result.data = episodes if episodes is not None else []
            sel.eq.return_value = sel
            sel.in_.return_value = sel
            sel.order.return_value = sel
            sel.limit.return_value = sel
            sel.gte.return_value = sel
            sel.lte.return_value = sel
            sel.execute.return_value = result
            m.select.return_value = sel

        _cache[name] = m
        return m

    sb.table.side_effect = _table
    return sb


# ── Integration tests with get_timeline_month ────────────────────────────────

class TestCalendarIndexHeatmap(unittest.TestCase):

    def test_calendar_index_includes_heatmap_score(self):
        """T2: timeline_days row with HIGH → calendar_index has heatmap_score=3."""
        days = [{"date": "2026-03-01", "max_escalation": "HIGH", "event_count": 2}]
        with patch.object(tl_module, "supabase", _make_sb(days=days)):
            result = tl_module.get_timeline_month("pet-1", year=2026, month=3)
        ci = result["calendar_index"]
        self.assertIn("2026-03-01", ci)
        self.assertEqual(ci["2026-03-01"]["heatmap_score"], 3)
        self.assertEqual(ci["2026-03-01"]["event_count"], 2)
        self.assertFalse(ci["2026-03-01"]["has_critical"])

    def test_critical_day_flag(self):
        """T3: Day with CRITICAL → has_critical=True, heatmap_score=3."""
        days = [{"date": "2026-03-05", "max_escalation": "CRITICAL", "event_count": 3}]
        with patch.object(tl_module, "supabase", _make_sb(days=days)):
            result = tl_module.get_timeline_month("pet-1", year=2026, month=3)
        day = result["calendar_index"]["2026-03-05"]
        self.assertTrue(day["has_critical"])
        self.assertEqual(day["heatmap_score"], 3)

    def test_multiple_days_max_escalation(self):
        """T4: Multiple days → each gets correct heatmap_score."""
        days = [
            {"date": "2026-03-01", "max_escalation": "LOW", "event_count": 1},
            {"date": "2026-03-02", "max_escalation": "MODERATE", "event_count": 2},
            {"date": "2026-03-03", "max_escalation": "HIGH", "event_count": 3},
        ]
        with patch.object(tl_module, "supabase", _make_sb(days=days)):
            result = tl_module.get_timeline_month("pet-1", year=2026, month=3)
        ci = result["calendar_index"]
        self.assertEqual(ci["2026-03-01"]["heatmap_score"], 1)
        self.assertEqual(ci["2026-03-02"]["heatmap_score"], 2)
        self.assertEqual(ci["2026-03-03"]["heatmap_score"], 3)

    def test_empty_month_calendar_index(self):
        """T5: No timeline_days → calendar_index is empty dict."""
        with patch.object(tl_module, "supabase", _make_sb(days=[])):
            result = tl_module.get_timeline_month("pet-1", year=2026, month=3)
        self.assertEqual(result["calendar_index"], {})

    def test_resolved_day_still_visible(self):
        """T6: Day with resolved episode (LOW) still in calendar_index."""
        days = [{"date": "2026-02-15", "max_escalation": "MODERATE", "event_count": 1}]
        with patch.object(tl_module, "supabase", _make_sb(days=days)):
            result = tl_module.get_timeline_month("pet-1", year=2026, month=2)
        self.assertIn("2026-02-15", result["calendar_index"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
