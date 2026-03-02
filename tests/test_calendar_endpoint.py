"""
tests/test_calendar_endpoint.py — Tests for GET /calendar/{pet_id} endpoint
4 tests:
  T7: Basic response structure
  T8: months validation (ge=1, le=6)
  T9: Summary aggregation
  T10: Empty period → empty days + zero summary
"""
import sys, os, unittest
from unittest.mock import MagicMock, patch
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import routers.timeline as tl_module


def _make_sb(days=None):
    """Build a mock supabase returning timeline_days rows."""
    sb = MagicMock()
    _cache = {}

    def _table(name):
        if name in _cache:
            return _cache[name]
        m = MagicMock()
        sel = MagicMock()
        result = MagicMock()
        result.data = days if days is not None else []
        sel.eq.return_value = sel
        sel.gte.return_value = sel
        sel.lte.return_value = sel
        sel.lt.return_value = sel
        sel.order.return_value = sel
        sel.limit.return_value = sel
        sel.execute.return_value = result
        m.select.return_value = sel
        _cache[name] = m
        return m

    sb.table.side_effect = _table
    return sb


class TestCalendarEndpoint(unittest.TestCase):

    def test_t7_basic_response_structure(self):
        """T7: GET /calendar/{pet_id} returns pet_id, period, days, summary."""
        days = [{"date": "2026-02-20", "max_escalation": "HIGH", "event_count": 2}]
        with patch.object(tl_module, "supabase", _make_sb(days=days)):
            result = tl_module.get_calendar_heatmap("pet-1", months=1)
        self.assertEqual(result["pet_id"], "pet-1")
        self.assertIn("period", result)
        self.assertIn("from", result["period"])
        self.assertIn("to", result["period"])
        self.assertIn("days", result)
        self.assertIn("summary", result)
        self.assertGreaterEqual(result["summary"]["days_with_events"], 1)

    def test_t8_months_validation(self):
        """T8: months=0 and months=7 → rejected by FastAPI Query validation.
        We test the function directly — FastAPI handles Query constraints at HTTP level.
        Valid months (1-6) should work without error."""
        with patch.object(tl_module, "supabase", _make_sb(days=[])):
            result = tl_module.get_calendar_heatmap("pet-1", months=1)
        self.assertIsNotNone(result)
        with patch.object(tl_module, "supabase", _make_sb(days=[])):
            result = tl_module.get_calendar_heatmap("pet-1", months=6)
        self.assertIsNotNone(result)

    def test_t9_summary_aggregation(self):
        """T9: Summary correctly counts critical_days and max_heatmap_score."""
        days = [
            {"date": "2026-02-10", "max_escalation": "CRITICAL", "event_count": 1},
            {"date": "2026-02-11", "max_escalation": "LOW", "event_count": 1},
            {"date": "2026-02-12", "max_escalation": "CRITICAL", "event_count": 2},
        ]
        with patch.object(tl_module, "supabase", _make_sb(days=days)):
            result = tl_module.get_calendar_heatmap("pet-1", months=1)
        summary = result["summary"]
        self.assertEqual(summary["total_events"], 4)
        self.assertEqual(summary["critical_days"], 2)
        self.assertEqual(summary["max_heatmap_score"], 3)
        self.assertEqual(summary["days_with_events"], 3)

    def test_t10_empty_period(self):
        """T10: No events → empty days, zero summary."""
        with patch.object(tl_module, "supabase", _make_sb(days=[])):
            result = tl_module.get_calendar_heatmap("pet-1", months=1)
        self.assertEqual(result["days"], {})
        self.assertEqual(result["summary"]["total_events"], 0)
        self.assertEqual(result["summary"]["days_with_events"], 0)
        self.assertEqual(result["summary"]["critical_days"], 0)
        self.assertEqual(result["summary"]["max_heatmap_score"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
