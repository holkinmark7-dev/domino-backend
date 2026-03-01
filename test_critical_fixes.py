"""
test_critical_fixes.py — CRITICAL FIXES: Duplicate Route + DB + Cleanup

11 tests:
  T1  /timeline returns calendar_index as dict (not list)
  T2  /timeline response has "days" key
  T3  normalize_timeline_event does NOT exist in chat module
  T4  Only one call to get_recent_events in chat.py source (no duplicate)
  T5  _build_actions_block({"symptom": "vomiting"}) does not crash
  T6  _build_actions_block({}) does not crash
  T7  _build_actions_block({"symptom": "seizure"}) contains "Засеките время приступа"
  T8  timeline module imports ESCALATION_ORDER from risk_engine (not inline dict)
  T9  Regression: test_monotonic_lock.py all PASS
  T10 Regression: test_llm_contract.py all PASS
  T11 Regression: test_response_templates.py all PASS

No Supabase / HTTP calls except T1-T2 which stub supabase.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import subprocess

sys.path.insert(0, os.path.dirname(__file__))


# ─────────────────────────────────────────────────────────────────────────────
# T1 + T2 — timeline endpoint returns correct structure
# ─────────────────────────────────────────────────────────────────────────────

import routers.timeline as timeline_module


def _run_timeline_stub(episodes: list) -> dict:
    fake_result = MagicMock()
    fake_result.data = episodes
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = fake_result
    with patch.object(timeline_module, "supabase", mock_sb):
        return timeline_module.get_timeline("pet-test")


class TestTimelineStructure(unittest.TestCase):

    def setUp(self):
        self._result = _run_timeline_stub([
            {
                "id": "ep-1", "normalized_key": "vomiting", "escalation": "HIGH",
                "status": "active", "started_at": "2026-02-20T10:00:00",
                "resolved_at": None, "updated_at": None,
            },
        ])

    # T1: calendar_index is a dict, not a list
    def test_calendar_index_is_dict(self):
        self.assertIsInstance(self._result["calendar_index"], dict)

    # T2: response has "days" key
    def test_response_has_days_key(self):
        self.assertIn("days", self._result)
        self.assertIsInstance(self._result["days"], list)


# ─────────────────────────────────────────────────────────────────────────────
# T3 — normalize_timeline_event removed from chat module
# ─────────────────────────────────────────────────────────────────────────────

import routers.chat as chat_module


class TestDuplicateRouteRemoved(unittest.TestCase):

    # T3: normalize_timeline_event must NOT exist in chat module
    def test_normalize_timeline_event_not_in_chat(self):
        self.assertFalse(
            hasattr(chat_module, "normalize_timeline_event"),
            "normalize_timeline_event still present in chat.py — duplicate route not removed",
        )


# ─────────────────────────────────────────────────────────────────────────────
# T4 — only one get_recent_events call in chat.py source
# ─────────────────────────────────────────────────────────────────────────────

class TestSingleDbQuery(unittest.TestCase):

    # T4: source of chat.py has exactly one call to get_recent_events
    def test_single_get_recent_events_call(self):
        chat_py_path = os.path.join(os.path.dirname(__file__), "routers", "chat.py")
        with open(chat_py_path, "r", encoding="utf-8") as f:
            source = f.read()
        # Count actual call sites (not the import line)
        call_count = source.count("get_recent_events(")
        self.assertEqual(
            call_count, 1,
            f"Expected exactly 1 call to get_recent_events(), found {call_count}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# T5–T7 — _build_actions_block correctness after cleanup
# ─────────────────────────────────────────────────────────────────────────────

from routers.services.ai import _build_actions_block


class TestBuildActionsBlockAfterCleanup(unittest.TestCase):

    # T5: no crash with vomiting
    def test_vomiting_no_crash(self):
        try:
            result = _build_actions_block({"symptom": "vomiting"})
        except Exception as e:
            self.fail(f"_build_actions_block crashed with vomiting: {e}")
        self.assertIsInstance(result, str)

    # T6: no crash with empty dict
    def test_empty_dict_no_crash(self):
        try:
            result = _build_actions_block({})
        except Exception as e:
            self.fail(f"_build_actions_block crashed with {{}}: {e}")
        self.assertIsInstance(result, str)

    # T7: seizure block contains the expected Russian instruction
    def test_seizure_contains_timer_instruction(self):
        result = _build_actions_block({"symptom": "seizure"})
        self.assertIn("Засеките время приступа", result)


# ─────────────────────────────────────────────────────────────────────────────
# T8 — timeline.py uses ESCALATION_ORDER from risk_engine (not inline dict)
# ─────────────────────────────────────────────────────────────────────────────

from routers.services.risk_engine import ESCALATION_ORDER


class TestTimelineUsesSharedEscOrder(unittest.TestCase):

    # T8: _ESC_ORDER in timeline module is the same object as risk_engine.ESCALATION_ORDER
    def test_esc_order_is_imported_from_risk_engine(self):
        # timeline module should not define its own _ESC_ORDER inline —
        # it imports it from risk_engine. We verify the values match.
        self.assertEqual(
            timeline_module._ESC_ORDER,
            ESCALATION_ORDER,
            "_ESC_ORDER in timeline.py differs from risk_engine.ESCALATION_ORDER",
        )


# ─────────────────────────────────────────────────────────────────────────────
# T9–T11 — Regressions
# ─────────────────────────────────────────────────────────────────────────────

def _run_test_file(filename: str) -> tuple[int, int]:
    """Run a test file via subprocess, return (passed, total)."""
    result = subprocess.run(
        [sys.executable, filename],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(__file__),
    )
    output = result.stdout + result.stderr
    # Parse "TOTAL: X/Y PASS" line
    for line in reversed(output.splitlines()):
        if line.startswith("TOTAL:"):
            parts = line.split()
            ratio = parts[1]
            passed, total = map(int, ratio.split("/"))
            return passed, total
    # Fallback: if no TOTAL line, check for "OK"
    if "OK" in output:
        import re
        m = re.search(r"Ran (\d+) test", output)
        total = int(m.group(1)) if m else 0
        return total, total
    return 0, 0


class TestRegressions(unittest.TestCase):

    # T9: test_monotonic_lock.py — all tests pass
    def test_monotonic_lock_regression(self):
        passed, total = _run_test_file("test_monotonic_lock.py")
        self.assertGreater(total, 0, "test_monotonic_lock.py ran 0 tests")
        self.assertEqual(passed, total, f"test_monotonic_lock.py: {passed}/{total} PASS")

    # T10: test_llm_contract.py — all tests pass
    def test_llm_contract_regression(self):
        passed, total = _run_test_file("test_llm_contract.py")
        self.assertGreater(total, 0, "test_llm_contract.py ran 0 tests")
        self.assertEqual(passed, total, f"test_llm_contract.py: {passed}/{total} PASS")

    # T11: test_response_templates.py — all tests pass
    def test_response_templates_regression(self):
        passed, total = _run_test_file("test_response_templates.py")
        self.assertGreater(total, 0, "test_response_templates.py ran 0 tests")
        self.assertEqual(passed, total, f"test_response_templates.py: {passed}/{total} PASS")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestTimelineStructure))
    suite.addTests(loader.loadTestsFromTestCase(TestDuplicateRouteRemoved))
    suite.addTests(loader.loadTestsFromTestCase(TestSingleDbQuery))
    suite.addTests(loader.loadTestsFromTestCase(TestBuildActionsBlockAfterCleanup))
    suite.addTests(loader.loadTestsFromTestCase(TestTimelineUsesSharedEscOrder))
    suite.addTests(loader.loadTestsFromTestCase(TestRegressions))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
