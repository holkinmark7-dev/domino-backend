"""
Timeline API Unit Tests — Day 19–20
Day 19: grouping, sorting, read-only invariants (11 tests).
Day 20: last_escalation, active/resolved counts, calendar_index (8 tests).
Uses unittest.mock to isolate from database.
"""
import sys
import io
import unittest
from unittest.mock import MagicMock, patch

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import routers.timeline as tl


# ─────────────────────────────────────────────────────────────────────────────
# Helper: build a mock supabase that returns the given episode rows
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
    escalation: str = "LOW",
    status: str = "active",
    started_at: str = "2026-02-25T10:00:00+00:00",
    resolved_at=None,
    updated_at: str = "2026-02-25T10:00:00+00:00",
) -> dict:
    return {
        "id": ep_id,
        "normalized_key": key,
        "escalation": escalation,
        "status": status,
        "started_at": started_at,
        "resolved_at": resolved_at,
        "updated_at": updated_at,
    }


# ─────────────────────────────────────────────────────────────────────────────
class TestTimeline(unittest.TestCase):

    # T1: No episodes → empty days list, total_episodes = 0
    def test_no_episodes(self):
        with patch.object(tl, "supabase", _mock_sb([])):
            result = tl.get_timeline("pet-1")
        self.assertEqual(result["pet_id"], "pet-1")
        self.assertEqual(result["total_episodes"], 0)
        self.assertEqual(result["days"], [])

    # T2: One episode → one day, one episode in list
    def test_one_episode(self):
        rows = [_ep("ep-1", started_at="2026-02-25T09:00:00+00:00")]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        self.assertEqual(result["total_episodes"], 1)
        self.assertEqual(len(result["days"]), 1)
        self.assertEqual(result["days"][0]["date"], "2026-02-25")
        self.assertEqual(len(result["days"][0]["episodes"]), 1)
        self.assertEqual(result["days"][0]["episodes"][0]["episode_id"], "ep-1")

    # T3: 2 episodes on the same day → one day entry, two episodes
    def test_two_episodes_same_day(self):
        rows = [
            _ep("ep-2", started_at="2026-02-25T15:00:00+00:00"),
            _ep("ep-1", started_at="2026-02-25T09:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        self.assertEqual(result["total_episodes"], 2)
        self.assertEqual(len(result["days"]), 1)
        self.assertEqual(result["days"][0]["date"], "2026-02-25")
        self.assertEqual(len(result["days"][0]["episodes"]), 2)

    # T4: 3 episodes on 3 different days → 3 day entries
    def test_three_episodes_different_days(self):
        rows = [
            _ep("ep-3", started_at="2026-02-25T10:00:00+00:00"),
            _ep("ep-2", started_at="2026-02-23T10:00:00+00:00"),
            _ep("ep-1", started_at="2026-02-20T10:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        self.assertEqual(result["total_episodes"], 3)
        self.assertEqual(len(result["days"]), 3)

    # T5: Days sorted newest first
    def test_days_sorted_newest_first(self):
        # DB returns in DESC order; grouping must preserve newest day first
        rows = [
            _ep("ep-3", started_at="2026-02-25T10:00:00+00:00"),
            _ep("ep-2", started_at="2026-02-23T10:00:00+00:00"),
            _ep("ep-1", started_at="2026-02-20T10:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        dates = [d["date"] for d in result["days"]]
        self.assertEqual(dates, ["2026-02-25", "2026-02-23", "2026-02-20"])
        # Each subsequent date must be less than the previous
        for i in range(len(dates) - 1):
            self.assertGreater(dates[i], dates[i + 1])

    # T6: Episodes within a day sorted newest first
    # (DB returns started_at DESC; order must be preserved in grouped output)
    def test_episodes_within_day_newest_first(self):
        rows = [
            # Both same date, different times — DB returns newest first
            _ep("ep-b", started_at="2026-02-25T18:00:00+00:00"),
            _ep("ep-a", started_at="2026-02-25T06:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        episodes = result["days"][0]["episodes"]
        self.assertEqual(episodes[0]["episode_id"], "ep-b")  # 18:00 first
        self.assertEqual(episodes[1]["episode_id"], "ep-a")  # 06:00 second

    # T7: total_episodes matches actual count regardless of grouping
    def test_total_episodes_count(self):
        rows = [
            _ep("ep-1", started_at="2026-02-25T10:00:00+00:00"),
            _ep("ep-2", started_at="2026-02-25T12:00:00+00:00"),
            _ep("ep-3", started_at="2026-02-24T08:00:00+00:00"),
            _ep("ep-4", started_at="2026-02-22T08:00:00+00:00"),
            _ep("ep-5", started_at="2026-02-22T09:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        self.assertEqual(result["total_episodes"], 5)
        # Verify total equals sum of all episodes across all days
        total_from_days = sum(len(d["episodes"]) for d in result["days"])
        self.assertEqual(total_from_days, 5)

    # T8: Escalation returned as-is — never mutated by the endpoint
    def test_escalation_not_mutated(self):
        rows = [
            _ep("ep-1", escalation="HIGH", status="active"),
            _ep("ep-2", escalation="CRITICAL", status="resolved",
                resolved_at="2026-02-24T10:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        # Flatten all returned episodes
        returned_eps = [
            ep
            for day in result["days"]
            for ep in day["episodes"]
        ]
        escalations = {ep["episode_id"]: ep["escalation"] for ep in returned_eps}
        self.assertEqual(escalations["ep-1"], "HIGH")
        self.assertEqual(escalations["ep-2"], "CRITICAL")

    # Extra T9: Response contains correct episode fields
    def test_episode_fields_present(self):
        rows = [_ep(
            "ep-x",
            key="diarrhea",
            escalation="MODERATE",
            status="resolved",
            started_at="2026-02-25T10:00:00+00:00",
            resolved_at="2026-02-25T14:00:00+00:00",
            updated_at="2026-02-25T14:00:00+00:00",
        )]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-x")
        ep = result["days"][0]["episodes"][0]
        self.assertEqual(ep["episode_id"], "ep-x")
        self.assertEqual(ep["normalized_key"], "diarrhea")
        self.assertEqual(ep["escalation"], "MODERATE")
        self.assertEqual(ep["status"], "resolved")
        self.assertIsNotNone(ep["resolved_at"])
        self.assertIsNotNone(ep["started_at"])
        self.assertIsNotNone(ep["updated_at"])

    # Extra T10: pet_id in response matches request
    def test_pet_id_echoed_in_response(self):
        with patch.object(tl, "supabase", _mock_sb([])):
            result = tl.get_timeline("pet-unique-123")
        self.assertEqual(result["pet_id"], "pet-unique-123")

    # Extra T11: Only SELECT — verify no update/insert calls on mock
    def test_read_only_no_writes(self):
        mock_sb = _mock_sb([])
        with patch.object(tl, "supabase", mock_sb):
            tl.get_timeline("pet-1")
        # update and insert should NOT have been called
        mock_sb.table.return_value.update.assert_not_called()
        mock_sb.table.return_value.insert.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Day 20: new aggregate fields
# ─────────────────────────────────────────────────────────────────────────────
class TestTimelinePart2(unittest.TestCase):

    # T1-D20: last_escalation is the escalation of the newest episode
    def test_last_escalation_correct(self):
        # DB returns newest first (DESC); first row is the most recent
        rows = [
            _ep("ep-2", escalation="HIGH",     started_at="2026-02-25T15:00:00+00:00"),
            _ep("ep-1", escalation="LOW",      started_at="2026-02-24T09:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        self.assertEqual(result["last_escalation"], "HIGH")

    # T2-D20: active_episode_count correct
    def test_active_episode_count(self):
        rows = [
            _ep("ep-1", status="active",   started_at="2026-02-25T10:00:00+00:00"),
            _ep("ep-2", status="active",   started_at="2026-02-24T10:00:00+00:00"),
            _ep("ep-3", status="resolved", started_at="2026-02-23T10:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        self.assertEqual(result["active_episode_count"], 2)

    # T3-D20: resolved_episode_count correct
    def test_resolved_episode_count(self):
        rows = [
            _ep("ep-1", status="active",   started_at="2026-02-25T10:00:00+00:00"),
            _ep("ep-2", status="resolved", started_at="2026-02-24T10:00:00+00:00"),
            _ep("ep-3", status="resolved", started_at="2026-02-23T10:00:00+00:00"),
            _ep("ep-4", status="resolved", started_at="2026-02-22T10:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        self.assertEqual(result["resolved_episode_count"], 3)

    # T4-D20: calendar_index contains unique dates only
    def test_calendar_index_unique_dates(self):
        rows = [
            # Two episodes on the same day — should produce only one date entry
            _ep("ep-2", started_at="2026-02-25T15:00:00+00:00"),
            _ep("ep-1", started_at="2026-02-25T09:00:00+00:00"),
            _ep("ep-3", started_at="2026-02-23T10:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        ci = result["calendar_index"]
        self.assertEqual(len(ci), len(set(ci)), "calendar_index must have no duplicates")
        self.assertEqual(sorted(set(ci), reverse=True), ci)

    # T5-D20: calendar_index sorted newest first
    def test_calendar_index_sorted_newest_first(self):
        rows = [
            _ep("ep-3", started_at="2026-02-25T10:00:00+00:00"),
            _ep("ep-2", started_at="2026-02-23T10:00:00+00:00"),
            _ep("ep-1", started_at="2026-02-20T10:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        ci = result["calendar_index"]
        self.assertEqual(ci, ["2026-02-25", "2026-02-23", "2026-02-20"])
        for i in range(len(ci) - 1):
            self.assertGreater(ci[i], ci[i + 1])

    # T6-D20: no episodes → all zeros/null
    def test_no_episodes_all_zeros(self):
        with patch.object(tl, "supabase", _mock_sb([])):
            result = tl.get_timeline("pet-empty")
        self.assertEqual(result["total_episodes"], 0)
        self.assertEqual(result["active_episode_count"], 0)
        self.assertEqual(result["resolved_episode_count"], 0)
        self.assertIsNone(result["last_escalation"])
        self.assertEqual(result["calendar_index"], [])
        self.assertEqual(result["days"], [])

    # T7-D20: escalation values are not mutated by aggregation
    def test_escalation_not_mutated_in_aggregates(self):
        rows = [
            _ep("ep-1", escalation="CRITICAL", status="active",
                started_at="2026-02-25T10:00:00+00:00"),
            _ep("ep-2", escalation="LOW",      status="resolved",
                started_at="2026-02-24T10:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        # last_escalation comes from the raw DB value — must be "CRITICAL" (newest)
        self.assertEqual(result["last_escalation"], "CRITICAL")
        # Per-episode escalation also unchanged
        flat = [ep for day in result["days"] for ep in day["episodes"]]
        by_id = {ep["episode_id"]: ep["escalation"] for ep in flat}
        self.assertEqual(by_id["ep-1"], "CRITICAL")
        self.assertEqual(by_id["ep-2"], "LOW")

    # T8-D20: no write operations
    def test_read_only_no_writes_part2(self):
        mock_sb = _mock_sb([_ep("ep-1")])
        with patch.object(tl, "supabase", mock_sb):
            tl.get_timeline("pet-1")
        mock_sb.table.return_value.update.assert_not_called()
        mock_sb.table.return_value.insert.assert_not_called()

    # Extra: active + resolved counts sum to total (no other statuses in fixture)
    def test_counts_sum_to_total(self):
        rows = [
            _ep("ep-1", status="active",   started_at="2026-02-25T10:00:00+00:00"),
            _ep("ep-2", status="resolved", started_at="2026-02-24T10:00:00+00:00"),
            _ep("ep-3", status="active",   started_at="2026-02-23T10:00:00+00:00"),
            _ep("ep-4", status="resolved", started_at="2026-02-22T10:00:00+00:00"),
        ]
        with patch.object(tl, "supabase", _mock_sb(rows)):
            result = tl.get_timeline("pet-1")
        self.assertEqual(
            result["active_episode_count"] + result["resolved_episode_count"],
            result["total_episodes"],
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────
def main():
    tl.supabase = MagicMock()  # baseline mock

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestTimeline, TestTimelinePart2]:
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
