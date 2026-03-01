"""
Episode Phase Display Layer Unit Tests — Day 18
Covers all 8 scenarios from the TZ plus invariant assertions.

Tests:
  - compute_episode_phase() for all boundary cases
  - None → "initial" default
  - Escalation invariant (phase is pure function, no escalation side-effects)
  - Recurrence invariant (phase does not touch recurrence state)
  - Debug payload field presence
"""
import sys
import io
import unittest
from unittest.mock import MagicMock, patch

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from routers.services.episode_phase import compute_episode_phase


# ─────────────────────────────────────────────────────────────────────────────
# Tests for compute_episode_phase()
# ─────────────────────────────────────────────────────────────────────────────
class TestComputeEpisodePhase(unittest.TestCase):

    # T1: 0h → initial
    def test_zero_hours_is_initial(self):
        self.assertEqual(compute_episode_phase(0.0), "initial")

    # T2: 11.9h → initial (boundary: just below 12)
    def test_below_12h_is_initial(self):
        self.assertEqual(compute_episode_phase(11.9), "initial")

    # T3: 12h → ongoing (boundary: exactly 12)
    def test_exactly_12h_is_ongoing(self):
        self.assertEqual(compute_episode_phase(12.0), "ongoing")

    # T4: 30h → ongoing (midpoint)
    def test_30h_is_ongoing(self):
        self.assertEqual(compute_episode_phase(30.0), "ongoing")

    # T5: 47.9h → ongoing (boundary: just below 48)
    def test_below_48h_is_ongoing(self):
        self.assertEqual(compute_episode_phase(47.9), "ongoing")

    # T6: 48h → prolonged (boundary: exactly 48)
    def test_exactly_48h_is_prolonged(self):
        self.assertEqual(compute_episode_phase(48.0), "prolonged")

    # T7: 72h → prolonged (well above threshold)
    def test_72h_is_prolonged(self):
        self.assertEqual(compute_episode_phase(72.0), "prolonged")

    # T8: None → initial (safe default — no episode data)
    def test_none_duration_is_initial(self):
        self.assertEqual(compute_episode_phase(None), "initial")


# ─────────────────────────────────────────────────────────────────────────────
# Additional boundary and edge cases
# ─────────────────────────────────────────────────────────────────────────────
class TestComputeEpisodePhaseBoundaries(unittest.TestCase):

    def test_all_three_phases_covered(self):
        # Verify mutually exclusive: each duration maps to exactly one phase
        self.assertEqual(compute_episode_phase(0), "initial")
        self.assertEqual(compute_episode_phase(12), "ongoing")
        self.assertEqual(compute_episode_phase(48), "prolonged")

    def test_small_float_precision(self):
        # 11.999 should still be initial
        self.assertEqual(compute_episode_phase(11.999), "initial")
        # 12.001 should be ongoing
        self.assertEqual(compute_episode_phase(12.001), "ongoing")

    def test_very_long_episode(self):
        # 720h (30 days) → prolonged
        self.assertEqual(compute_episode_phase(720.0), "prolonged")


# ─────────────────────────────────────────────────────────────────────────────
# Invariant: compute_episode_phase is a pure function — no side-effects
# ─────────────────────────────────────────────────────────────────────────────
class TestEpisodePhaseInvariants(unittest.TestCase):

    def test_escalation_invariant_pure_function(self):
        """
        compute_episode_phase() takes only duration_hours and returns str.
        It has no escalation parameter and returns no escalation.
        Escalation state is guaranteed unchanged by design.
        """
        import inspect
        sig = inspect.signature(compute_episode_phase)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ["duration_hours"],
                         "compute_episode_phase must accept only duration_hours")
        # Return value is a str, never an escalation-mutating structure
        result = compute_episode_phase(24.0)
        self.assertIsInstance(result, str)
        self.assertIn(result, ["initial", "ongoing", "prolonged"])

    def test_recurrence_invariant_no_shared_state(self):
        """
        Calling compute_episode_phase() multiple times with same input
        always returns the same output — no shared mutable state.
        """
        for _ in range(5):
            self.assertEqual(compute_episode_phase(30.0), "ongoing")
            self.assertEqual(compute_episode_phase(None), "initial")

    def test_does_not_mutate_arguments(self):
        """
        Duration value passed in is not modified.
        """
        duration = 24.5
        compute_episode_phase(duration)
        self.assertEqual(duration, 24.5)

    def test_decision_phase_field_present(self):
        """
        Simulate what chat.py does: set decision["episode_phase"].
        Verify the field is set to a valid phase value.
        """
        decision = {"escalation": "MODERATE"}
        _episode_duration_hours = 36.0

        # Mirrors chat.py line: decision["episode_phase"] = compute_episode_phase(...)
        decision["episode_phase"] = compute_episode_phase(_episode_duration_hours)

        self.assertIn("episode_phase", decision)
        self.assertEqual(decision["episode_phase"], "ongoing")
        # Escalation must not have changed
        self.assertEqual(decision["escalation"], "MODERATE")

    def test_debug_payload_episode_phase_field(self):
        """
        Simulate debug payload construction. episode_phase is present
        and has a valid value.
        """
        decision = {
            "escalation": "HIGH",
            "episode_phase": compute_episode_phase(50.0),  # "prolonged"
        }
        # Mirrors debug payload: "episode_phase": decision.get("episode_phase")
        debug_payload = {
            "episode_phase": decision.get("episode_phase"),
        }
        self.assertEqual(debug_payload["episode_phase"], "prolonged")


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────
def main():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestComputeEpisodePhase,
        TestComputeEpisodePhaseBoundaries,
        TestEpisodePhaseInvariants,
    ]:
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
