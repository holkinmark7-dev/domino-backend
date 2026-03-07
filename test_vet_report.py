"""
Vet Report API Unit Tests — Day 21
9 scenarios verifying report fields, aggregation, and read-only invariants.
Uses unittest.mock to isolate from database.
"""
import sys
import io
import unittest
from unittest.mock import MagicMock, patch

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import routers.vet_report as vr


# ─────────────────────────────────────────────────────────────────────────────
# Helper: mock supabase returning given rows
# Chain: .table().select().eq().order().execute().data
# ─────────────────────────────────────────────────────────────────────────────
def _mock_sb(rows: list) -> MagicMock:
    mock_sb = MagicMock()
    mock_sb.table.return_value \
        .select.return_value \
        .eq.return_value \
        .order.return_value \
        .execute.return_value \
        .data = rows
    return mock_sb


def _ep(
    ep_id: str,
    key: str = "vomiting",
    escalation_level: str = "LOW",
    status: str = "active",
    started_at: str = "2026-02-20T10:00:00+00:00",
    resolved_at=None,
    updated_at: str = "2026-02-20T10:00:00+00:00",
) -> dict:
    return {
        "id": ep_id,
        "normalized_key": key,
        "escalation_level": escalation_level,
        "status": status,
        "started_at": started_at,
        "resolved_at": resolved_at,
        "updated_at": updated_at,
    }


# ─────────────────────────────────────────────────────────────────────────────
class TestVetReport(unittest.TestCase):

    # T1: No episodes → all null/zero, empty list
    def test_no_episodes(self):
        with patch.object(vr, "supabase", _mock_sb([])):
            result = vr.get_vet_report("pet-1")
        self.assertEqual(result["pet_id"], "pet-1")
        self.assertEqual(result["total_episodes"], 0)
        self.assertEqual(result["active_episode_count"], 0)
        self.assertEqual(result["resolved_episode_count"], 0)
        self.assertIsNone(result["first_episode_at"])
        self.assertIsNone(result["last_episode_at"])
        self.assertIsNone(result["highest_escalation_ever"])
        self.assertEqual(result["episodes"], [])
        self.assertIn("report_generated_at", result)

    # T2: One episode → first = last, all fields populated
    def test_one_episode(self):
        rows = [_ep("ep-1", escalation_level="MODERATE", status="active",
                    started_at="2026-02-22T10:00:00+00:00")]
        with patch.object(vr, "supabase", _mock_sb(rows)):
            result = vr.get_vet_report("pet-1")
        self.assertEqual(result["total_episodes"], 1)
        self.assertEqual(result["first_episode_at"], "2026-02-22T10:00:00+00:00")
        self.assertEqual(result["last_episode_at"], "2026-02-22T10:00:00+00:00")
        self.assertEqual(result["highest_escalation_ever"], "MODERATE")
        self.assertEqual(len(result["episodes"]), 1)
        self.assertEqual(result["episodes"][0]["episode_id"], "ep-1")

    # T3: Multiple episodes → all counts correct
    def test_multiple_episodes(self):
        # DB returns ASC (chronological); earliest first
        rows = [
            _ep("ep-1", status="resolved", started_at="2026-02-20T08:00:00+00:00",
                resolved_at="2026-02-21T09:00:00+00:00"),
            _ep("ep-2", status="resolved", started_at="2026-02-22T10:00:00+00:00",
                resolved_at="2026-02-23T11:00:00+00:00"),
            _ep("ep-3", status="active",   started_at="2026-02-25T12:00:00+00:00"),
        ]
        with patch.object(vr, "supabase", _mock_sb(rows)):
            result = vr.get_vet_report("pet-1")
        self.assertEqual(result["total_episodes"], 3)
        self.assertEqual(result["active_episode_count"], 1)
        self.assertEqual(result["resolved_episode_count"], 2)
        self.assertEqual(len(result["episodes"]), 3)

    # T4: highest_escalation_ever picks the true maximum
    def test_highest_escalation_ever(self):
        rows = [
            _ep("ep-1", escalation_level="LOW",      started_at="2026-02-20T08:00:00+00:00"),
            _ep("ep-2", escalation_level="MODERATE",  started_at="2026-02-21T08:00:00+00:00"),
            _ep("ep-3", escalation_level="HIGH",      started_at="2026-02-22T08:00:00+00:00"),
            _ep("ep-4", escalation_level="MODERATE",  started_at="2026-02-23T08:00:00+00:00"),
        ]
        with patch.object(vr, "supabase", _mock_sb(rows)):
            result = vr.get_vet_report("pet-1")
        self.assertEqual(result["highest_escalation_ever"], "HIGH")

    def test_highest_escalation_ever_critical(self):
        rows = [
            _ep("ep-1", escalation_level="HIGH",     started_at="2026-02-20T08:00:00+00:00"),
            _ep("ep-2", escalation_level="CRITICAL", started_at="2026-02-21T08:00:00+00:00"),
            _ep("ep-3", escalation_level="LOW",      started_at="2026-02-22T08:00:00+00:00"),
        ]
        with patch.object(vr, "supabase", _mock_sb(rows)):
            result = vr.get_vet_report("pet-1")
        self.assertEqual(result["highest_escalation_ever"], "CRITICAL")

    # T5: first_episode_at is the earliest started_at (DB returns ASC → first row)
    def test_first_episode_at(self):
        rows = [
            _ep("ep-1", started_at="2026-02-01T08:00:00+00:00"),  # earliest
            _ep("ep-2", started_at="2026-02-10T08:00:00+00:00"),
            _ep("ep-3", started_at="2026-02-20T08:00:00+00:00"),
        ]
        with patch.object(vr, "supabase", _mock_sb(rows)):
            result = vr.get_vet_report("pet-1")
        self.assertEqual(result["first_episode_at"], "2026-02-01T08:00:00+00:00")

    # T6: last_episode_at is the latest started_at (DB returns ASC → last row)
    def test_last_episode_at(self):
        rows = [
            _ep("ep-1", started_at="2026-02-01T08:00:00+00:00"),
            _ep("ep-2", started_at="2026-02-10T08:00:00+00:00"),
            _ep("ep-3", started_at="2026-02-20T08:00:00+00:00"),  # latest
        ]
        with patch.object(vr, "supabase", _mock_sb(rows)):
            result = vr.get_vet_report("pet-1")
        self.assertEqual(result["last_episode_at"], "2026-02-20T08:00:00+00:00")

    # T7: active/resolved counts correct
    def test_active_resolved_counts(self):
        rows = [
            _ep("ep-1", status="active",   started_at="2026-02-20T08:00:00+00:00"),
            _ep("ep-2", status="active",   started_at="2026-02-21T08:00:00+00:00"),
            _ep("ep-3", status="resolved", started_at="2026-02-22T08:00:00+00:00"),
        ]
        with patch.object(vr, "supabase", _mock_sb(rows)):
            result = vr.get_vet_report("pet-1")
        self.assertEqual(result["active_episode_count"], 2)
        self.assertEqual(result["resolved_episode_count"], 1)

    # T8: escalation values not mutated — passed through as-is
    def test_escalation_not_mutated(self):
        rows = [
            _ep("ep-1", escalation_level="HIGH",     started_at="2026-02-20T08:00:00+00:00"),
            _ep("ep-2", escalation_level="CRITICAL", started_at="2026-02-21T08:00:00+00:00"),
        ]
        with patch.object(vr, "supabase", _mock_sb(rows)):
            result = vr.get_vet_report("pet-1")
        by_id = {ep["episode_id"]: ep["escalation_level"] for ep in result["episodes"]}
        self.assertEqual(by_id["ep-1"], "HIGH")
        self.assertEqual(by_id["ep-2"], "CRITICAL")
        # highest_escalation_ever is read from the DB values, not recalculated
        self.assertEqual(result["highest_escalation_ever"], "CRITICAL")

    # T9: Only SELECT — no update/insert calls
    def test_read_only_no_writes(self):
        mock_sb = _mock_sb([])
        with patch.object(vr, "supabase", mock_sb):
            vr.get_vet_report("pet-1")
        mock_sb.table.return_value.update.assert_not_called()
        mock_sb.table.return_value.insert.assert_not_called()

    # Extra: report_generated_at is present and is a valid ISO string
    def test_report_generated_at_present(self):
        with patch.object(vr, "supabase", _mock_sb([])):
            result = vr.get_vet_report("pet-x")
        ts = result.get("report_generated_at")
        self.assertIsNotNone(ts)
        # Should be parseable as ISO datetime
        from datetime import datetime
        try:
            datetime.fromisoformat(ts)
        except ValueError:
            self.fail(f"report_generated_at is not a valid ISO timestamp: {ts}")

    # Extra: episode fields correct in report list
    def test_episode_fields_in_list(self):
        rows = [_ep(
            "ep-x", key="diarrhea", escalation_level="MODERATE", status="resolved",
            started_at="2026-02-20T08:00:00+00:00",
            resolved_at="2026-02-20T18:00:00+00:00",
        )]
        with patch.object(vr, "supabase", _mock_sb(rows)):
            result = vr.get_vet_report("pet-1")
        ep = result["episodes"][0]
        self.assertEqual(ep["episode_id"], "ep-x")
        self.assertEqual(ep["normalized_key"], "diarrhea")
        self.assertEqual(ep["escalation_level"], "MODERATE")
        self.assertEqual(ep["status"], "resolved")
        self.assertEqual(ep["started_at"], "2026-02-20T08:00:00+00:00")
        self.assertEqual(ep["resolved_at"], "2026-02-20T18:00:00+00:00")


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────
def main():
    vr.supabase = MagicMock()  # baseline mock

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestVetReport)

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
