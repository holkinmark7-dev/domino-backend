"""
test_monotonic_lock.py — Unit tests for DAY 3.1 Monotonic Final Escalation Lock
Tests: apply_monotonic_lock()
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from routers.services.chat_helpers import apply_monotonic_lock


# ─── Helpers ─────────────────────────────────────────────────────────────────

EPISODE_ID = "ep-test-001"


def _make_decision(escalation="MODERATE"):
    return {
        "escalation": escalation,
        "symptom": "vomiting",
        "stats": {"today": 2, "last_hour": 1},
    }


def _make_event(episode_id, urgency_score):
    """Simulate a medical_events row with content dict."""
    return {
        "content": {
            "episode_id": episode_id,
            "urgency_score": urgency_score,
        }
    }


# ═════════════════════════════════════════════════════════════════════════════
# Section 1 — Core correctness (TZ requirements)
# ═════════════════════════════════════════════════════════════════════════════

class TestMonotonicLock(unittest.TestCase):

    # T1: Escalation cannot drop — previous HIGH(2), current MODERATE → corrected to HIGH
    def test_escalation_cannot_drop(self):
        decision = _make_decision(escalation="MODERATE")
        events = [_make_event(EPISODE_ID, urgency_score=2)]  # 2 = HIGH
        apply_monotonic_lock(decision, EPISODE_ID, events)
        self.assertEqual(decision["escalation"], "HIGH")
        self.assertTrue(decision["monotonic_corrected"])

    # T2: Escalation increases normally — previous MODERATE(1), current HIGH → stays HIGH
    def test_escalation_increases_normally(self):
        decision = _make_decision(escalation="HIGH")
        events = [_make_event(EPISODE_ID, urgency_score=1)]  # 1 = MODERATE
        apply_monotonic_lock(decision, EPISODE_ID, events)
        self.assertEqual(decision["escalation"], "HIGH")
        self.assertFalse(decision["monotonic_corrected"])

    # T3: New episode — no previous events → no correction, monotonic_corrected=False
    def test_new_episode_no_correction(self):
        decision = _make_decision(escalation="MODERATE")
        apply_monotonic_lock(decision, EPISODE_ID, [])
        self.assertEqual(decision["escalation"], "MODERATE")
        self.assertFalse(decision["monotonic_corrected"])

    # T4: Absolute critical — previous HIGH(2), current CRITICAL(3) → stays CRITICAL
    def test_critical_not_downgraded(self):
        decision = _make_decision(escalation="CRITICAL")
        events = [_make_event(EPISODE_ID, urgency_score=2)]  # 2 = HIGH
        apply_monotonic_lock(decision, EPISODE_ID, events)
        self.assertEqual(decision["escalation"], "CRITICAL")
        self.assertFalse(decision["monotonic_corrected"])


# ═════════════════════════════════════════════════════════════════════════════
# Section 2 — Edge cases
# ═════════════════════════════════════════════════════════════════════════════

class TestMonotonicLockEdgeCases(unittest.TestCase):

    # T5: Only events matching episode_id contribute to previous_max
    def test_only_matching_episode_id_counts(self):
        decision = _make_decision(escalation="MODERATE")
        events = [
            _make_event("other-ep-xyz", urgency_score=3),  # CRITICAL — wrong episode
            _make_event(EPISODE_ID, urgency_score=1),       # MODERATE — correct episode
        ]
        apply_monotonic_lock(decision, EPISODE_ID, events)
        # previous_max for EPISODE_ID = 1 (MODERATE), current = MODERATE(1) → no correction
        self.assertEqual(decision["escalation"], "MODERATE")
        self.assertFalse(decision["monotonic_corrected"])

    # T6: Non-dict content rows are skipped without error
    def test_non_dict_content_skipped(self):
        decision = _make_decision(escalation="MODERATE")
        events = [
            {"content": None},
            {"content": "plain string"},
            {"content": 42},
            _make_event(EPISODE_ID, urgency_score=2),  # HIGH
        ]
        apply_monotonic_lock(decision, EPISODE_ID, events)
        self.assertEqual(decision["escalation"], "HIGH")
        self.assertTrue(decision["monotonic_corrected"])

    # T7: Multiple events — highest urgency_score wins
    def test_max_urgency_from_multiple_events(self):
        decision = _make_decision(escalation="MODERATE")
        events = [
            _make_event(EPISODE_ID, urgency_score=1),  # MODERATE
            _make_event(EPISODE_ID, urgency_score=2),  # HIGH
            _make_event(EPISODE_ID, urgency_score=1),  # MODERATE again
        ]
        apply_monotonic_lock(decision, EPISODE_ID, events)
        self.assertEqual(decision["escalation"], "HIGH")
        self.assertTrue(decision["monotonic_corrected"])

    # T8: LOW stays LOW when previous also LOW — no false correction
    def test_low_stays_low_no_correction(self):
        decision = _make_decision(escalation="LOW")
        events = [_make_event(EPISODE_ID, urgency_score=0)]  # 0 = LOW
        apply_monotonic_lock(decision, EPISODE_ID, events)
        self.assertEqual(decision["escalation"], "LOW")
        self.assertFalse(decision["monotonic_corrected"])

    # T9: monotonic_corrected always set as bool regardless of path
    def test_monotonic_corrected_always_bool(self):
        for esc in ["LOW", "MODERATE", "HIGH", "CRITICAL"]:
            decision = _make_decision(escalation=esc)
            apply_monotonic_lock(decision, EPISODE_ID, [])
            self.assertIn("monotonic_corrected", decision)
            self.assertIsInstance(decision["monotonic_corrected"], bool)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestMonotonicLock))
    suite.addTests(loader.loadTestsFromTestCase(TestMonotonicLockEdgeCases))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-'*60}")
    print(f"TOTAL: {passed}/{total} PASS")
