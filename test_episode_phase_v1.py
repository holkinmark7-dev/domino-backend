"""
test_episode_phase_v1.py — Unit tests for compute_episode_phase_v1()

6 scenarios:
  1. initial          — no prior escalation data
  2. worsening        — escalation increased vs previous
  3. stable           — same escalation, no new drivers
  4. improving        — monotonic lock held the level (raw would be lower)
  5. cross-class worsening — escalation raised by cross_class_override
  6. systemic worsening   — escalation raised by systemic_adjusted

compute_episode_phase_v1 is a pure function — no Supabase, no HTTP.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from routers.chat import compute_episode_phase_v1


class TestEpisodePhaseV1(unittest.TestCase):

    # ── T1: initial ──────────────────────────────────────────────────────────
    def test_initial_when_no_previous_data(self):
        """
        No prior events in this episode (previous_max_urgency=None).
        Regardless of current escalation, phase must be "initial".
        """
        phase = compute_episode_phase_v1(
            current_escalation="LOW",
            previous_max_urgency=None,
            monotonic_corrected=False,
            systemic_adjusted=False,
            cross_class_override=False,
        )
        self.assertEqual(phase, "initial")

    # ── T2: worsening ────────────────────────────────────────────────────────
    def test_worsening_when_escalation_increased(self):
        """
        Previous max = LOW (0), current = HIGH (2).
        No monotonic correction, no systemic, no cross_class.
        Phase must be "worsening".
        """
        phase = compute_episode_phase_v1(
            current_escalation="HIGH",
            previous_max_urgency=0,   # LOW
            monotonic_corrected=False,
            systemic_adjusted=False,
            cross_class_override=False,
        )
        self.assertEqual(phase, "worsening")

    # ── T3: stable ───────────────────────────────────────────────────────────
    def test_stable_when_same_escalation_no_drivers(self):
        """
        Previous max = MODERATE (1), current = MODERATE (1).
        No systemic_adjusted, no cross_class_override.
        Phase must be "stable".
        """
        phase = compute_episode_phase_v1(
            current_escalation="MODERATE",
            previous_max_urgency=1,   # MODERATE
            monotonic_corrected=False,
            systemic_adjusted=False,
            cross_class_override=False,
        )
        self.assertEqual(phase, "stable")

    # ── T4: improving (monotonic lock held) ──────────────────────────────────
    def test_improving_when_monotonic_corrected(self):
        """
        Previous max = HIGH (2).  Current raw escalation would be MODERATE (1),
        but monotonic lock raised it back to HIGH.
        monotonic_corrected=True → phase must be "improving".
        """
        phase = compute_episode_phase_v1(
            current_escalation="HIGH",      # after lock correction
            previous_max_urgency=2,         # HIGH
            monotonic_corrected=True,       # lock triggered
            systemic_adjusted=False,
            cross_class_override=False,
        )
        self.assertEqual(phase, "improving")

    # ── T5: cross-class worsening ────────────────────────────────────────────
    def test_worsening_driven_by_cross_class_override(self):
        """
        Previous max = LOW (0).  Cross-class override raised escalation to
        CRITICAL (3).  Even though cross_class_override=True, the escalation
        level itself jumped → primary result is "worsening".
        """
        phase = compute_episode_phase_v1(
            current_escalation="CRITICAL",
            previous_max_urgency=0,         # LOW
            monotonic_corrected=False,
            systemic_adjusted=False,
            cross_class_override=True,
        )
        self.assertEqual(phase, "worsening")

    # ── T6: systemic worsening ───────────────────────────────────────────────
    def test_worsening_driven_by_systemic_adjusted(self):
        """
        Previous max = LOW (0).  Systemic state layer raised escalation to
        HIGH (2) via systemic_adjusted=True.  Escalation went up → "worsening".
        """
        phase = compute_episode_phase_v1(
            current_escalation="HIGH",
            previous_max_urgency=0,         # LOW
            monotonic_corrected=False,
            systemic_adjusted=True,
            cross_class_override=False,
        )
        self.assertEqual(phase, "worsening")

    # ── Bonus: progressing (same level, but new driver present) ──────────────
    def test_progressing_when_same_level_with_systemic_driver(self):
        """
        Previous max = HIGH (2), current = HIGH (2).
        systemic_adjusted=True → phase must be "progressing", not "stable".
        Demonstrates that same-level + active driver → progressing, not stable.
        """
        phase = compute_episode_phase_v1(
            current_escalation="HIGH",
            previous_max_urgency=2,         # HIGH
            monotonic_corrected=False,
            systemic_adjusted=True,
            cross_class_override=False,
        )
        self.assertEqual(phase, "progressing")

    def test_progressing_when_same_level_with_cross_class_driver(self):
        """
        Previous max = MODERATE (1), current = MODERATE (1).
        cross_class_override=True → phase must be "progressing".
        """
        phase = compute_episode_phase_v1(
            current_escalation="MODERATE",
            previous_max_urgency=1,
            monotonic_corrected=False,
            systemic_adjusted=False,
            cross_class_override=True,
        )
        self.assertEqual(phase, "progressing")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestEpisodePhaseV1)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
