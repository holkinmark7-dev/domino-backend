import sys, os, unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import routers.timeline as tl_module


def _make_sb(days=None):
    sb = MagicMock()
    def _table(name):
        m = MagicMock()
        sel = MagicMock()
        r = MagicMock()
        r.data = days if days is not None else []
        sel.eq.return_value = sel
        sel.gte.return_value = sel
        sel.lte.return_value = sel
        sel.order.return_value = sel
        sel.execute.return_value = r
        m.select.return_value = sel
        return m
    sb.table.side_effect = _table
    return sb


class TestTimelineFilter(unittest.TestCase):

    def test_t1_filter_all_returns_fields(self):
        with patch.object(tl_module, "supabase", _make_sb(days=[])):
            result = tl_module.get_timeline_filtered("pet-1", event_type="all")
        self.assertEqual(result["filter"], "all")
        self.assertIn("days", result)
        self.assertIn("has_events", result)

    def test_t2_filter_episodes(self):
        with patch.object(tl_module, "supabase", _make_sb(days=[])):
            result = tl_module.get_timeline_filtered("pet-1", event_type="episodes")
        self.assertEqual(result["filter"], "episodes")

    def test_t3_filter_vet_visit(self):
        with patch.object(tl_module, "supabase", _make_sb(days=[])):
            result = tl_module.get_timeline_filtered("pet-1", event_type="vet_visit")
        self.assertEqual(result["filter"], "vet_visit")

    def test_t4_empty_result(self):
        with patch.object(tl_module, "supabase", _make_sb(days=[])):
            result = tl_module.get_timeline_filtered("pet-1")
        self.assertFalse(result["has_events"])

    def test_t5_year_month_passed(self):
        with patch.object(tl_module, "supabase", _make_sb(days=[])):
            result = tl_module.get_timeline_filtered("pet-1", year=2026, month=3)
        self.assertEqual(result["year"], 2026)
        self.assertEqual(result["month"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
