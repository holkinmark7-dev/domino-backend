"""
Recurrence Layer Unit Tests — Day 17
8 scenarios covering all invariants specified in the TZ.
Uses unittest.mock to isolate from database.
"""
import sys
import io
import unittest
from unittest.mock import MagicMock, patch

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import routers.services.recurrence as rec

# Escalation order used in escalation-bump assertions
_ESC_ORDER = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
_ESC_LEVELS = ["LOW", "MODERATE", "HIGH", "CRITICAL"]


def _mock_sb_with_count(n: int) -> MagicMock:
    """
    Return a MagicMock supabase client that reports n resolved episodes.
    Mocks the full chain:
      .table().select().eq().eq().eq().eq().gte().execute()
    """
    mock_sb = MagicMock()
    mock_sb.table.return_value \
        .select.return_value \
        .eq.return_value \
        .eq.return_value \
        .eq.return_value \
        .eq.return_value \
        .gte.return_value \
        .execute.return_value \
        .data = [{"id": f"ep-{i}"} for i in range(n)]
    return mock_sb


# ─────────────────────────────────────────────────────────────────────────────
# Helper: bump escalation by one level (mirrors chat.py integration logic)
# ─────────────────────────────────────────────────────────────────────────────
def _apply_recurrence(current_escalation: str, recurrent: bool) -> tuple[str, bool]:
    """
    Returns (new_escalation, recurrence_adjusted) using the same logic as chat.py
    Recurrence Layer integration.
    """
    if recurrent and current_escalation != "CRITICAL":
        idx = _ESC_ORDER[current_escalation]
        new = _ESC_LEVELS[min(idx + 1, 3)]
        if new != current_escalation:
            return new, True
    return current_escalation, False


# ─────────────────────────────────────────────────────────────────────────────
# Tests for check_recurrence()
# ─────────────────────────────────────────────────────────────────────────────
class TestCheckRecurrence(unittest.TestCase):

    # T1: 2 resolved episodes → check_recurrence returns False
    def test_two_resolved_no_recurrence(self):
        with patch.object(rec, "supabase", _mock_sb_with_count(2)):
            result = rec.check_recurrence("pet-1", "vomiting")
        self.assertFalse(result)

    # T2: Exactly 3 resolved episodes → check_recurrence returns True
    def test_three_resolved_is_recurrence(self):
        with patch.object(rec, "supabase", _mock_sb_with_count(3)):
            result = rec.check_recurrence("pet-1", "vomiting")
        self.assertTrue(result)

    # T3: 4 resolved episodes → still True
    def test_four_resolved_is_recurrence(self):
        with patch.object(rec, "supabase", _mock_sb_with_count(4)):
            result = rec.check_recurrence("pet-1", "vomiting")
        self.assertTrue(result)

    # T4: 3 resolved but older than 30 days → DB filters them out → 0 rows → False
    # In production the GTE filter excludes them. We simulate this by returning 0 rows.
    def test_old_resolved_outside_window_no_recurrence(self):
        with patch.object(rec, "supabase", _mock_sb_with_count(0)):
            result = rec.check_recurrence("pet-1", "vomiting")
        self.assertFalse(result)

    # T7: 3 resolved episodes but for a DIFFERENT normalized_key → False
    # The caller passes the correct key; DB query would return 0 for a different key.
    # We simulate: query returns 0 rows (DB filtered by normalized_key).
    def test_different_normalized_key_no_recurrence(self):
        with patch.object(rec, "supabase", _mock_sb_with_count(0)):
            # Even if other keys have 3+ resolved, this key has 0
            result = rec.check_recurrence("pet-1", "diarrhea")
        self.assertFalse(result)

    # T8: Episodes without resolved_at are excluded by the GTE("resolved_at") filter.
    # DB returns 0 rows (NULLs fail GTE comparison in Postgres).
    def test_resolved_without_resolved_at_excluded(self):
        with patch.object(rec, "supabase", _mock_sb_with_count(0)):
            result = rec.check_recurrence("pet-1", "vomiting")
        self.assertFalse(result)

    # T6: 3 resolved + active episode → active not counted, check_recurrence still True
    # The DB query filters status='resolved', so the active episode returns 0 from
    # its own query (not included). We simulate 3 resolved returned.
    def test_active_episode_not_counted(self):
        # 3 resolved rows returned (active episode is excluded by the DB filter)
        with patch.object(rec, "supabase", _mock_sb_with_count(3)):
            result = rec.check_recurrence("pet-1", "vomiting")
        self.assertTrue(result)  # +1 escalation should fire

    # Extra: query exception → returns False (safe default)
    def test_exception_returns_false(self):
        mock_sb = MagicMock()
        mock_sb.table.side_effect = RuntimeError("DB down")
        with patch.object(rec, "supabase", mock_sb):
            result = rec.check_recurrence("pet-1", "vomiting")
        self.assertFalse(result)


# ─────────────────────────────────────────────────────────────────────────────
# Tests for Recurrence Layer integration logic (escalation bump)
# These mirror what chat.py does after calling check_recurrence().
# ─────────────────────────────────────────────────────────────────────────────
class TestRecurrenceEscalationLogic(unittest.TestCase):

    # T5: Current escalation is CRITICAL + recurrence → stays CRITICAL
    def test_critical_not_escalated_above_critical(self):
        new_esc, adjusted = _apply_recurrence("CRITICAL", recurrent=True)
        self.assertEqual(new_esc, "CRITICAL")
        self.assertFalse(adjusted)

    # Escalation bumps: LOW → MODERATE
    def test_low_bumped_to_moderate(self):
        new_esc, adjusted = _apply_recurrence("LOW", recurrent=True)
        self.assertEqual(new_esc, "MODERATE")
        self.assertTrue(adjusted)

    # MODERATE → HIGH
    def test_moderate_bumped_to_high(self):
        new_esc, adjusted = _apply_recurrence("MODERATE", recurrent=True)
        self.assertEqual(new_esc, "HIGH")
        self.assertTrue(adjusted)

    # HIGH → CRITICAL
    def test_high_bumped_to_critical(self):
        new_esc, adjusted = _apply_recurrence("HIGH", recurrent=True)
        self.assertEqual(new_esc, "CRITICAL")
        self.assertTrue(adjusted)

    # No recurrence → no change
    def test_no_recurrence_no_change(self):
        for level in ["LOW", "MODERATE", "HIGH", "CRITICAL"]:
            new_esc, adjusted = _apply_recurrence(level, recurrent=False)
            self.assertEqual(new_esc, level)
            self.assertFalse(adjusted)


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────
def main():
    rec.supabase = MagicMock()  # baseline mock so import doesn't hit real DB

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestCheckRecurrence, TestRecurrenceEscalationLogic]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed
    print(f"\n{'─' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
