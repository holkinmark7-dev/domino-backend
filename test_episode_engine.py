"""
Episode Engine Unit Tests — Day 16 Deep Fix
Tests 10+ scenarios covering all invariants specified in the TZ.
Uses unittest.mock to isolate from database.
"""
import sys
import io
import unittest
from unittest.mock import MagicMock, patch, call

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ── Import module under test ──────────────────────────────────────────────────
# Import works because .env provides SUPABASE_URL/KEY; we replace supabase
# immediately after import so no real DB calls occur in tests.
import routers.services.episode_manager as em


def _mock_supabase():
    """Return a fresh MagicMock to replace em.supabase."""
    return MagicMock()


# ─────────────────────────────────────────────────────────────────────────────
# Helper: build a fake active episode row
# ─────────────────────────────────────────────────────────────────────────────
def _active_ep(episode_id="ep-1", escalation="LOW", normalized_key="vomiting"):
    return {
        "id": episode_id,
        "pet_id": "pet-1",
        "episode_type": "symptom",
        "normalized_key": normalized_key,
        "status": "active",
        "escalation": escalation,
        "started_at": "2024-01-01T00:00:00+00:00",
        "last_event_at": "2024-01-01T00:00:00+00:00",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tests for _max_escalation
# ─────────────────────────────────────────────────────────────────────────────
class TestMaxEscalation(unittest.TestCase):

    def test_higher_wins(self):
        self.assertEqual(em._max_escalation("LOW", "HIGH"), "HIGH")

    def test_same_returns_current(self):
        self.assertEqual(em._max_escalation("HIGH", "HIGH"), "HIGH")

    def test_lower_does_not_downgrade(self):
        self.assertEqual(em._max_escalation("CRITICAL", "LOW"), "CRITICAL")

    def test_full_order(self):
        levels = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
        for i, a in enumerate(levels):
            for j, b in enumerate(levels):
                expected = b if j > i else a
                self.assertEqual(em._max_escalation(a, b), expected)


# ─────────────────────────────────────────────────────────────────────────────
# Tests for _is_resolution
# ─────────────────────────────────────────────────────────────────────────────
class TestIsResolution(unittest.TestCase):

    def test_resolution_phrase(self):
        self.assertTrue(em._is_resolution("рвота прекратилась"))
        self.assertTrue(em._is_resolution("всё прошло, питомец в норме"))
        self.assertTrue(em._is_resolution("уже нормально"))

    def test_non_resolution(self):
        self.assertFalse(em._is_resolution("собака рвёт"))
        self.assertFalse(em._is_resolution("рвота продолжается"))


# ─────────────────────────────────────────────────────────────────────────────
# Tests for _handle_key (core engine logic)
# ─────────────────────────────────────────────────────────────────────────────
class TestHandleKey(unittest.TestCase):

    # T1: First event → new episode created
    def test_new_episode_created(self):
        with patch.object(em, "_get_active_episode", return_value=None), \
             patch.object(em, "_create_episode", return_value=_active_ep("ep-new")) as mock_create:
            result = em._handle_key("pet-1", "symptom", "vomiting", False, None, "LOW")
        self.assertEqual(result["action"], "created")
        self.assertEqual(result["episode_id"], "ep-new")
        mock_create.assert_called_once_with("pet-1", "symptom", "vomiting", None, "LOW")

    # T2: Same symptom again → continuation
    def test_continuation_on_existing_episode(self):
        active = _active_ep("ep-1", escalation="MODERATE")
        with patch.object(em, "_get_active_episode", return_value=active), \
             patch.object(em, "_update_episode") as mock_update:
            result = em._handle_key("pet-1", "symptom", "vomiting", False, None, "MODERATE")
        self.assertEqual(result["action"], "continued")
        self.assertEqual(result["episode_id"], "ep-1")
        mock_update.assert_called_once()

    # T3: vomiting HIGH → vomiting LOW → escalation stays HIGH
    def test_escalation_never_decreases(self):
        active = _active_ep("ep-1", escalation="HIGH")
        with patch.object(em, "_get_active_episode", return_value=active), \
             patch.object(em, "_update_episode") as mock_update:
            em._handle_key("pet-1", "symptom", "vomiting", False, None, "LOW")
        # Third arg of _update_episode call is the new escalation
        call_args = mock_update.call_args
        passed_escalation = call_args[0][2]  # positional arg index 2
        self.assertEqual(passed_escalation, "HIGH")  # must stay HIGH, not drop to LOW

    # T4: Resolution → episode closed, action=resolved
    def test_resolution_closes_episode(self):
        active = _active_ep("ep-1")
        with patch.object(em, "_get_active_episode", return_value=active), \
             patch.object(em, "_resolve_episode") as mock_resolve:
            result = em._handle_key("pet-1", "symptom", "vomiting", True, None)
        self.assertEqual(result["action"], "resolved")
        self.assertEqual(result["episode_id"], "ep-1")
        mock_resolve.assert_called_once_with("ep-1")

    # T5: Resolution with no active episode → standalone
    def test_resolution_without_active_episode(self):
        with patch.object(em, "_get_active_episode", return_value=None):
            result = em._handle_key("pet-1", "symptom", "vomiting", True, None)
        self.assertEqual(result["action"], "standalone")
        self.assertIsNone(result["episode_id"])

    # T6: After resolution, same symptom → NEW episode created
    def test_new_episode_after_resolution(self):
        # No active episode (was resolved), create fresh one
        with patch.object(em, "_get_active_episode", return_value=None), \
             patch.object(em, "_create_episode", return_value=_active_ep("ep-2")) as mock_create:
            result = em._handle_key("pet-1", "symptom", "vomiting", False, None, "LOW")
        self.assertEqual(result["action"], "created")
        self.assertEqual(result["episode_id"], "ep-2")
        mock_create.assert_called_once()

    # T7: Race condition — create fails, fallback to found episode
    def test_race_condition_fallback_to_continuation(self):
        active = _active_ep("ep-1", escalation="LOW")
        # First call: no active. _create_episode returns None (DB conflict).
        # Second call (fallback): finds the concurrently-created episode.
        get_side_effects = [None, active]
        with patch.object(em, "_get_active_episode", side_effect=get_side_effects), \
             patch.object(em, "_create_episode", return_value=None), \
             patch.object(em, "_update_episode") as mock_update:
            result = em._handle_key("pet-1", "symptom", "vomiting", False, None, "MODERATE")
        self.assertEqual(result["action"], "continued")
        self.assertEqual(result["episode_id"], "ep-1")
        mock_update.assert_called_once()

    # T8: Escalation is upgraded when new event is higher
    def test_escalation_upgraded(self):
        active = _active_ep("ep-1", escalation="LOW")
        with patch.object(em, "_get_active_episode", return_value=active), \
             patch.object(em, "_update_episode") as mock_update:
            em._handle_key("pet-1", "symptom", "vomiting", False, None, "CRITICAL")
        passed_escalation = mock_update.call_args[0][2]
        self.assertEqual(passed_escalation, "CRITICAL")


# ─────────────────────────────────────────────────────────────────────────────
# Tests for update_episode_escalation
# ─────────────────────────────────────────────────────────────────────────────
class TestUpdateEpisodeEscalation(unittest.TestCase):

    def _setup_mock(self, current_escalation: str):
        mock_sb = _mock_supabase()
        mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "escalation": current_escalation
        }
        em.supabase = mock_sb
        return mock_sb

    # T9: update_episode_escalation raises escalation when new is higher
    def test_escalation_raised(self):
        mock_sb = self._setup_mock("LOW")
        em.update_episode_escalation("ep-1", "HIGH")
        # update should have been called with "HIGH"
        update_chain = mock_sb.table.return_value.update.return_value.eq.return_value.execute
        update_chain.assert_called_once()
        update_data = mock_sb.table.return_value.update.call_args[0][0]
        self.assertEqual(update_data["escalation"], "HIGH")

    # T10: update_episode_escalation never lowers escalation
    def test_escalation_not_lowered(self):
        mock_sb = self._setup_mock("CRITICAL")
        em.update_episode_escalation("ep-1", "LOW")
        # update should NOT have been called (escalation unchanged)
        update_chain = mock_sb.table.return_value.update.return_value.eq.return_value.execute
        update_chain.assert_not_called()

    # T11: update_episode_escalation is no-op when same level
    def test_escalation_no_op_same_level(self):
        mock_sb = self._setup_mock("HIGH")
        em.update_episode_escalation("ep-1", "HIGH")
        update_chain = mock_sb.table.return_value.update.return_value.eq.return_value.execute
        update_chain.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Tests for process_event (top-level API)
# ─────────────────────────────────────────────────────────────────────────────
class TestProcessEvent(unittest.TestCase):

    # T12: process_event with symptom → episode lifecycle
    def test_process_event_new_symptom(self):
        with patch.object(em, "_handle_key",
                          return_value={"episode_id": "ep-1", "action": "created"}) as mock_hk:
            result = em.process_event("pet-1", "vomiting", None, "собака рвёт", None, "LOW")
        self.assertEqual(result["episode_id"], "ep-1")
        self.assertEqual(result["action"], "created")
        mock_hk.assert_called_once_with(
            pet_id="pet-1",
            episode_type="symptom",
            normalized_key="vomiting",
            is_resolution=False,
            event_id=None,
            escalation="LOW",
        )

    # T13: Resolution phrase closes most recent active symptom (no symptom extracted)
    def test_process_event_resolution_no_symptom(self):
        mock_sb = _mock_supabase()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            _active_ep("ep-resolved")
        ]
        em.supabase = mock_sb
        with patch.object(em, "_resolve_episode") as mock_resolve:
            result = em.process_event("pet-1", None, None, "рвота прекратилась", None)
        mock_resolve.assert_called_once_with("ep-resolved")
        self.assertEqual(result["action"], "resolved")

    # T14: No symptom, no resolution → standalone
    def test_process_event_no_symptom_no_resolution(self):
        result = em.process_event("pet-1", None, None, "как дела?", None)
        self.assertEqual(result["action"], "standalone")
        self.assertIsNone(result["episode_id"])

    # T15: Medication episode is tracked independently
    def test_process_event_medication(self):
        with patch.object(em, "_handle_key",
                          return_value={"episode_id": "ep-med", "action": "created"}) as mock_hk:
            result = em.process_event("pet-1", None, "смекта", "дали смекту", None)
        mock_hk.assert_called_once_with(
            pet_id="pet-1",
            episode_type="medication",
            normalized_key="смекта",
            is_resolution=False,
            event_id=None,
            escalation=None,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────
def main():
    # Reset em.supabase to a mock before running tests
    em.supabase = _mock_supabase()

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestMaxEscalation,
        TestIsResolution,
        TestHandleKey,
        TestUpdateEpisodeEscalation,
        TestProcessEvent,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed
    print(f"\n{'─'*60}")
    print(f"TOTAL: {passed}/{total} PASS")
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
