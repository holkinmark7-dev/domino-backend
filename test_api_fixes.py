"""
test_api_fixes.py — Tests for CHAT HISTORY + TIMELINE + VET REPORT fixes

Section 1 — chat_history.py  (3 tests)
Section 2 — timeline.py      (2 tests)
Section 3 — vet_report.py    (4 tests: JSON fields + PDF bytes)

No Supabase / HTTP calls. All DB interactions are stubbed.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))


# ═════════════════════════════════════════════════════════════════════════════
# Section 1 — chat_history.py
# ═════════════════════════════════════════════════════════════════════════════

import routers.chat_history as chat_history_module
from routers.chat_history import _FOLLOWUP_MSG


class TestChatHistoryFixes(unittest.TestCase):

    # T1: _FOLLOWUP_MSG contains "Следите", not "Monitor"
    def test_followup_msg_is_russian(self):
        self.assertIn("Следите", _FOLLOWUP_MSG)
        self.assertNotIn("Monitor", _FOLLOWUP_MSG)

    # T2: user message object contains the "escalation" key
    def test_user_message_has_escalation_key(self):
        """
        Stub the supabase calls and verify the returned message object
        contains an "escalation" field.
        """
        fake_chat = MagicMock()
        fake_chat.data = [
            {"id": "chat-001", "role": "user", "message": "Рвота", "created_at": "2026-01-01T10:00:00"}
        ]

        fake_events = MagicMock()
        fake_events.data = [
            {
                "content": {
                    "source_chat_id": "chat-001",
                    "symptom": "vomiting",
                    "urgency_score": 2,
                    "escalation": "HIGH",
                }
            }
        ]

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = fake_chat
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = fake_events

        with patch.object(chat_history_module, "supabase", mock_sb):
            result = chat_history_module.get_chat_history("pet-001")

        self.assertTrue(len(result) > 0)
        user_msg = next((m for m in result if m["role"] == "user"), None)
        self.assertIsNotNone(user_msg)
        self.assertIn("escalation", user_msg)

    # T3: escalation value from med is exposed in message
    def test_user_message_escalation_value(self):
        """
        When the medical event has escalation="CRITICAL", the message
        object must carry escalation="CRITICAL".
        """
        fake_chat = MagicMock()
        fake_chat.data = [
            {"id": "chat-002", "role": "user", "message": "Критично", "created_at": "2026-01-01T11:00:00"}
        ]

        fake_events = MagicMock()
        fake_events.data = [
            {
                "content": {
                    "source_chat_id": "chat-002",
                    "symptom": "vomiting",
                    "urgency_score": 3,
                    "escalation": "CRITICAL",
                }
            }
        ]

        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = fake_chat
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = fake_events

        with patch.object(chat_history_module, "supabase", mock_sb):
            result = chat_history_module.get_chat_history("pet-002")

        user_msg = next((m for m in result if m["role"] == "user"), None)
        self.assertIsNotNone(user_msg)
        self.assertEqual(user_msg["escalation"], "CRITICAL")


# ═════════════════════════════════════════════════════════════════════════════
# Section 2 — timeline.py
# ═════════════════════════════════════════════════════════════════════════════

import routers.timeline as timeline_module


def _run_timeline(episodes: list) -> dict:
    """Run get_timeline() with stubbed supabase returning the given episodes."""
    fake_result = MagicMock()
    fake_result.data = episodes

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = fake_result

    with patch.object(timeline_module, "supabase", mock_sb):
        return timeline_module.get_timeline("pet-test")


class TestTimelineCalendarIndex(unittest.TestCase):

    # T4: calendar_index values are dicts with "has_events" and "max_escalation"
    def test_calendar_index_is_dict_with_correct_keys(self):
        result = _run_timeline([
            {"id": "ep-1", "normalized_key": "vomiting", "escalation": "LOW",
             "status": "active", "started_at": "2026-02-01T10:00:00", "resolved_at": None, "updated_at": None},
        ])
        idx = result["calendar_index"]
        self.assertIsInstance(idx, dict)
        date_entry = idx.get("2026-02-01")
        self.assertIsNotNone(date_entry)
        self.assertIn("has_events", date_entry)
        self.assertIn("max_escalation", date_entry)
        self.assertTrue(date_entry["has_events"])

    # T5: max_escalation selects the highest from mixed escalation levels
    def test_calendar_index_max_escalation_correct(self):
        """
        Three episodes on same day with LOW, CRITICAL, MODERATE.
        max_escalation must be "CRITICAL".
        """
        result = _run_timeline([
            {"id": "ep-1", "normalized_key": "vomiting", "escalation": "LOW",
             "status": "active", "started_at": "2026-02-10T08:00:00", "resolved_at": None, "updated_at": None},
            {"id": "ep-2", "normalized_key": "diarrhea", "escalation": "CRITICAL",
             "status": "active", "started_at": "2026-02-10T09:00:00", "resolved_at": None, "updated_at": None},
            {"id": "ep-3", "normalized_key": "fever", "escalation": "MODERATE",
             "status": "resolved", "started_at": "2026-02-10T10:00:00", "resolved_at": None, "updated_at": None},
        ])
        idx = result["calendar_index"]
        self.assertEqual(idx["2026-02-10"]["max_escalation"], "CRITICAL")


# ═════════════════════════════════════════════════════════════════════════════
# Section 3 — vet_report.py
# ═════════════════════════════════════════════════════════════════════════════

import routers.vet_report as vet_report_module
from routers.vet_report import get_vet_report, _build_pdf


def _run_vet_report(episodes: list, pet: dict) -> dict:
    """Run get_vet_report() with stubbed supabase."""
    fake_ep_result = MagicMock()
    fake_ep_result.data = episodes

    fake_pet_result = MagicMock()
    fake_pet_result.data = pet

    mock_sb = MagicMock()

    # episodes query
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = fake_ep_result
    # pet profile query (.single() chain)
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = fake_pet_result

    with patch.object(vet_report_module, "supabase", mock_sb):
        return get_vet_report("pet-xyz")


class TestVetReportFixes(unittest.TestCase):

    def setUp(self):
        self.pet = {"name": "Бони", "species": "dog", "breed": "beagle", "birth_date": "2020-03-15"}
        self.episodes = [
            {"id": "ep-1", "normalized_key": "vomiting", "escalation": "HIGH",
             "status": "resolved", "started_at": "2026-01-10T08:00:00", "resolved_at": "2026-01-10T10:00:00"},
        ]

    # T6: get_vet_report returns all four pet profile fields
    def test_vet_report_has_pet_profile_fields(self):
        report = _run_vet_report(self.episodes, self.pet)
        self.assertIn("pet_name", report)
        self.assertIn("pet_species", report)
        self.assertIn("pet_breed", report)
        self.assertIn("pet_birth_date", report)

    # T7: pet profile values are correctly forwarded
    def test_vet_report_pet_profile_values(self):
        report = _run_vet_report(self.episodes, self.pet)
        self.assertEqual(report["pet_name"], "Бони")
        self.assertEqual(report["pet_species"], "dog")
        self.assertEqual(report["pet_breed"], "beagle")
        self.assertEqual(report["pet_birth_date"], "2020-03-15")

    # T8: PDF bytes contain "Patsient"
    def test_pdf_contains_patsient(self):
        report = _run_vet_report(self.episodes, self.pet)
        pdf_bytes = _build_pdf(report, _compress=False)  # uncompressed for literal search
        self.assertIn(b"Patsient", pdf_bytes)

    # T9: PDF bytes contain "Domino"
    def test_pdf_contains_domino(self):
        report = _run_vet_report(self.episodes, self.pet)
        pdf_bytes = _build_pdf(report, _compress=False)  # uncompressed for literal search
        self.assertIn(b"Domino", pdf_bytes)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestChatHistoryFixes))
    suite.addTests(loader.loadTestsFromTestCase(TestTimelineCalendarIndex))
    suite.addTests(loader.loadTestsFromTestCase(TestVetReportFixes))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
