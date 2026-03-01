"""
test_phase_followup_engine.py — DAY 4 Phase-Driven Follow-Up Engine v1

6 tests:
  T1  worsening → follow_up_required=True (window = escalation-based)
  T2  progressing → follow_up_required=True
  T3  stable + HIGH → follow_up_required=True, window=3
  T4  stable + LOW → follow_up_required=False, window=None
  T5  improving → follow_up_required=False (positive trend, no reminder needed)
  T6  initial → follow_up_required=False, window=None

Pure-logic tests — no Supabase / HTTP calls.
The helper _follow_up() mirrors the FOLLOW-UP ENGINE v1 block in chat.py exactly.
Any divergence between the helper and chat.py is a bug.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))


# ─────────────────────────────────────────────────────────────────────────────
# Mirror of FOLLOW-UP ENGINE v1 logic from chat.py
# Kept intentionally inline so a diff between this and chat.py is immediately
# visible in code review.
# ─────────────────────────────────────────────────────────────────────────────

_FOLLOW_UP_WINDOWS = {"CRITICAL": 1, "HIGH": 3, "MODERATE": 8, "LOW": None}


def _follow_up(episode_phase: str, escalation: str) -> tuple[bool, int | None]:
    """
    Pure mirror of FOLLOW-UP ENGINE v1 in chat.py.
    Returns (follow_up_required, follow_up_window_hours).
    """
    if episode_phase == "worsening":
        required = True
    elif episode_phase == "progressing":
        required = True
    elif episode_phase == "stable" and escalation in ["HIGH", "CRITICAL"]:
        required = True
    else:
        required = False

    window = _FOLLOW_UP_WINDOWS.get(escalation) if required else None
    return required, window


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFollowUpEngine(unittest.TestCase):

    # T1: worsening → follow_up_required=True; window driven by escalation level
    def test_worsening_requires_followup(self):
        """
        Worsening episode with CRITICAL escalation:
        follow_up_required=True, window=1 hour (CRITICAL urgency).
        """
        required, window = _follow_up("worsening", "CRITICAL")
        self.assertTrue(required)
        self.assertEqual(window, 1)

    # T2: progressing → follow_up_required=True
    def test_progressing_requires_followup(self):
        """
        Progressing episode (same level but new systemic driver) with HIGH:
        follow_up_required=True, window=3 hours.
        """
        required, window = _follow_up("progressing", "HIGH")
        self.assertTrue(required)
        self.assertEqual(window, 3)

    # T3: stable + HIGH → follow_up_required=True, window=3
    def test_stable_high_requires_followup(self):
        """
        Stable but at HIGH escalation — patient still at elevated risk.
        follow_up_required=True, window=3 hours.
        """
        required, window = _follow_up("stable", "HIGH")
        self.assertTrue(required)
        self.assertEqual(window, 3)

    # T4: stable + LOW → follow_up_required=False, window=None
    def test_stable_low_no_followup(self):
        """
        Stable at LOW escalation — no urgent follow-up needed.
        follow_up_required=False, window=None.
        """
        required, window = _follow_up("stable", "LOW")
        self.assertFalse(required)
        self.assertIsNone(window)

    # T5: improving → follow_up_required=False
    def test_improving_no_followup(self):
        """
        Improving phase means the monotonic lock held at a higher level but
        the underlying clinical picture is better. No follow-up required.
        """
        required, window = _follow_up("improving", "HIGH")
        self.assertFalse(required)
        self.assertIsNone(window)

    # T6: initial → follow_up_required=False, window=None
    def test_initial_no_followup(self):
        """
        First event in episode — no history to compare against.
        follow_up_required=False, window=None.
        """
        required, window = _follow_up("initial", "MODERATE")
        self.assertFalse(required)
        self.assertIsNone(window)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestFollowUpEngine))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
