"""
tests/test_timeline.py — 8 тестов для Timeline backend
Все тесты используют только моки. Никаких subprocess. Никаких реальных DB вызовов.
"""
import sys, os, unittest
from unittest.mock import MagicMock, patch
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import routers.timeline as tl_module


def _make_sb(days=None, episodes=None, events=None, medical=None):
    """Возвращает мок supabase с заданными данными."""
    sb = MagicMock()
    _cache: dict = {}  # cache mocks by table name so repeated table() calls return same object

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
            sel.order.return_value = sel
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
            sel.lte.return_value = sel
            sel.or_.return_value = sel
            sel.execute.return_value = result
            m.select.return_value = sel

        elif name == "events":
            result = MagicMock()
            result.data = events if events is not None else []
            sel.eq.return_value = sel
            sel.gte.return_value = sel
            sel.lte.return_value = sel
            sel.order.return_value = sel
            sel.execute.return_value = result
            m.select.return_value = sel

        _cache[name] = m
        return m

    sb.table.side_effect = _table
    return sb


class TestTimelineMonth(unittest.TestCase):

    def test_t1_month_returns_required_fields(self):
        """T1: GET month → содержит year/month/days/active_episodes/has_events"""
        with patch.object(tl_module, "supabase", _make_sb(days=[], episodes=[])):
            result = tl_module.get_timeline_month("pet-1")
        self.assertIn("year", result)
        self.assertIn("month", result)
        self.assertIn("days", result)
        self.assertIn("active_episodes", result)
        self.assertIn("has_events", result)

    def test_t2_month_specific_year_month(self):
        """T2: year=2026 month=3 → year и month в ответе совпадают"""
        with patch.object(tl_module, "supabase", _make_sb(days=[], episodes=[])):
            result = tl_module.get_timeline_month("pet-1", year=2026, month=3)
        self.assertEqual(result["year"], 2026)
        self.assertEqual(result["month"], 3)

    def test_t7_empty_month(self):
        """T7: нет событий → days==[], has_events==False"""
        with patch.object(tl_module, "supabase", _make_sb(days=[], episodes=[])):
            result = tl_module.get_timeline_month("pet-1")
        self.assertEqual(result["days"], [])
        self.assertFalse(result["has_events"])

    def test_t8_active_episodes_moderate_plus(self):
        """T8: active_episodes возвращает данные из supabase (фильтрация на стороне DB)"""
        _ep = [{"id": "ep-1", "current_escalation": "HIGH", "status": "active"}]
        with patch.object(tl_module, "supabase", _make_sb(days=[], episodes=_ep)):
            result = tl_module.get_timeline_month("pet-1")
        self.assertEqual(len(result["active_episodes"]), 1)


class TestTimelineDay(unittest.TestCase):

    def test_t3_day_returns_required_fields(self):
        """T3: GET day → содержит date/summary/events/episodes"""
        with patch.object(tl_module, "supabase", _make_sb(days=None, episodes=[], events=[])):
            result = tl_module.get_timeline_day("pet-1", "2026-03-12")
        self.assertIn("date", result)
        self.assertIn("summary", result)
        self.assertIn("events", result)
        self.assertIn("episodes", result)
        self.assertEqual(result["date"], "2026-03-12")


class TestRecalculate(unittest.TestCase):

    def test_t4_recalculate_returns_status(self):
        """T4: recalculate → status=='recalculated'"""
        _sb = _make_sb(events=[], medical=[])
        with patch.object(tl_module, "supabase", _sb):
            result = tl_module.recalculate_day("pet-1", "2026-03-12")
        self.assertEqual(result["status"], "recalculated")
        self.assertEqual(result["date"], "2026-03-12")

    def test_t5_recalculate_calls_upsert(self):
        """T5: recalculate вызывает upsert в timeline_days"""
        _sb = _make_sb(events=[], medical=[])
        with patch.object(tl_module, "supabase", _sb):
            tl_module.recalculate_day("pet-1", "2026-03-12")
        _sb.table("timeline_days").upsert.assert_called_once()

    def test_t6_max_escalation_logic(self):
        """T6: CRITICAL > HIGH > MODERATE > LOW — берётся максимальный"""
        _medical = [
            {"event_type": "medical", "content": {"escalation": "HIGH", "episode_id": None}},
            {"event_type": "medical", "content": {"escalation": "CRITICAL", "episode_id": None}},
            {"event_type": "medical", "content": {"escalation": "MODERATE", "episode_id": None}},
        ]

        sb = MagicMock()
        _t6_cache: dict = {}
        def _table(name):
            if name in _t6_cache:
                return _t6_cache[name]
            m = MagicMock()
            sel = MagicMock()
            r = MagicMock()
            # both events queries (all events + medical events) return _medical
            # so max_escalation logic can process them; all_types won't trigger flags
            r.data = _medical if name == "events" else []
            sel.eq.return_value = sel
            sel.gte.return_value = sel
            sel.lte.return_value = sel
            sel.execute.return_value = r
            m.select.return_value = sel
            ups = MagicMock()
            ups.execute.return_value = MagicMock()
            m.upsert.return_value = ups
            _t6_cache[name] = m
            return m
        sb.table.side_effect = _table

        with patch.object(tl_module, "supabase", sb):
            result = tl_module.recalculate_day("pet-1", "2026-03-12")
        self.assertEqual(result["max_escalation"], "CRITICAL")


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestTimelineMonth, TestTimelineDay, TestRecalculate]:
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'─'*40}")
    print(f"ИТОГ: {passed}/{total} PASS")
