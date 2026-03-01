"""
Chat History Endpoint Unit Tests
GET /chat/history/{pet_id}
"""
import sys
import io
import json
import unittest
from unittest.mock import MagicMock, patch

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import routers.chat_history as ch


def _mock_sb(chat_rows: list, event_rows: list) -> MagicMock:
    """Mock supabase for two sequential queries (chat, then events)."""
    mock_sb = MagicMock()

    # chat query chain
    chat_chain = (
        mock_sb.table.return_value
        .select.return_value
        .eq.return_value
        .order.return_value
        .execute.return_value
    )
    chat_chain.data = chat_rows

    # events query chain (different .eq chain)
    events_chain = MagicMock()
    events_chain.execute.return_value.data = event_rows

    # Route by table name
    def _table(name):
        tbl = MagicMock()
        if name == "chat":
            tbl.select.return_value.eq.return_value.order.return_value.execute.return_value.data = chat_rows
        else:  # events
            tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = event_rows
        return tbl

    mock_sb.table.side_effect = _table
    return mock_sb


def _med_event(chat_id: str, urgency: int = 1, symptom: str = "vomiting") -> dict:
    content = json.dumps({
        "symptom": symptom,
        "urgency_score": urgency,
        "source_chat_id": chat_id,
    })
    return {"content": content}


class TestChatHistory(unittest.TestCase):

    # T1: No messages → returns empty list (not 404 / 500)
    def test_no_messages_returns_empty_list(self):
        with patch.object(ch, "supabase", _mock_sb([], [])):
            result = ch.get_chat_history("pet-1")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    # T2: Single user message without medical event → role "user", risk "normal"
    def test_single_message_no_event(self):
        rows = [{"id": "chat-1", "message": "Кошка рвёт", "created_at": "2026-02-25T10:00:00"}]
        with patch.object(ch, "supabase", _mock_sb(rows, [])):
            result = ch.get_chat_history("pet-1")
        self.assertEqual(len(result), 1)
        msg = result[0]
        self.assertEqual(msg["id"], "chat-1")
        self.assertEqual(msg["role"], "user")
        self.assertEqual(msg["content"], "Кошка рвёт")
        self.assertEqual(msg["risk_level"], "normal")
        self.assertIsNone(msg["structured_data"])
        self.assertIsNone(msg["followup_instructions"])

    # T3: Message linked to medical event → structured_data and risk_level populated
    def test_message_with_medical_event(self):
        rows = [{"id": "chat-2", "message": "Рвота 3 раза", "created_at": "2026-02-25T11:00:00"}]
        events = [_med_event("chat-2", urgency=2, symptom="vomiting")]
        with patch.object(ch, "supabase", _mock_sb(rows, events)):
            result = ch.get_chat_history("pet-1")
        msg = result[0]
        self.assertEqual(msg["risk_level"], "moderate")
        self.assertIsNotNone(msg["structured_data"])
        self.assertEqual(msg["structured_data"]["symptom"], "vomiting")
        # source_chat_id stripped from structured_data
        self.assertNotIn("source_chat_id", msg["structured_data"])

    # T4: urgency_score 0 → risk "normal", no followup
    def test_urgency_0_risk_normal(self):
        rows = [{"id": "c1", "message": "Всё хорошо", "created_at": "2026-02-25T10:00:00"}]
        events = [_med_event("c1", urgency=0)]
        with patch.object(ch, "supabase", _mock_sb(rows, events)):
            result = ch.get_chat_history("pet-1")
        self.assertEqual(result[0]["risk_level"], "normal")
        self.assertIsNone(result[0]["followup_instructions"])

    # T5: urgency_score 3 → risk "high", followup present
    def test_urgency_3_risk_high_with_followup(self):
        rows = [{"id": "c2", "message": "Не дышит", "created_at": "2026-02-25T10:00:00"}]
        events = [_med_event("c2", urgency=3)]
        with patch.object(ch, "supabase", _mock_sb(rows, events)):
            result = ch.get_chat_history("pet-1")
        self.assertEqual(result[0]["risk_level"], "high")
        self.assertIsNotNone(result[0]["followup_instructions"])

    # T6: Multiple messages in correct order
    def test_multiple_messages_order(self):
        rows = [
            {"id": "c1", "message": "msg1", "created_at": "2026-02-25T10:00:00"},
            {"id": "c2", "message": "msg2", "created_at": "2026-02-25T11:00:00"},
            {"id": "c3", "message": "msg3", "created_at": "2026-02-25T12:00:00"},
        ]
        with patch.object(ch, "supabase", _mock_sb(rows, [])):
            result = ch.get_chat_history("pet-1")
        self.assertEqual(len(result), 3)
        self.assertEqual([m["id"] for m in result], ["c1", "c2", "c3"])

    # T7: Response fields complete — all required keys present
    def test_all_required_fields_present(self):
        rows = [{"id": "cx", "message": "test", "created_at": "2026-02-25T10:00:00"}]
        with patch.object(ch, "supabase", _mock_sb(rows, [])):
            result = ch.get_chat_history("pet-x")
        msg = result[0]
        for field in ["id", "role", "content", "structured_data", "risk_level", "followup_instructions"]:
            self.assertIn(field, msg, f"Missing field: {field}")

    # T8: Read-only — no update/insert calls
    def test_read_only_no_writes(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = []
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        with patch.object(ch, "supabase", mock_sb):
            ch.get_chat_history("pet-1")
        mock_sb.table.return_value.update.assert_not_called()
        mock_sb.table.return_value.insert.assert_not_called()

    # T9: AI role message — no triage enrichment, correct fields
    def test_ai_role_message_no_enrichment(self):
        rows = [
            {"id": "c1", "role": "user", "message": "Кошка рвёт", "created_at": "2026-02-25T10:00:00"},
            {"id": "c2", "role": "ai",   "message": "Следите за состоянием.", "created_at": "2026-02-25T10:00:01"},
        ]
        with patch.object(ch, "supabase", _mock_sb(rows, [])):
            result = ch.get_chat_history("pet-1")
        self.assertEqual(len(result), 2)

        user_msg = result[0]
        self.assertEqual(user_msg["role"], "user")
        self.assertEqual(user_msg["risk_level"], "normal")

        ai_msg = result[1]
        self.assertEqual(ai_msg["role"], "ai")
        self.assertEqual(ai_msg["content"], "Следите за состоянием.")
        self.assertIsNone(ai_msg["structured_data"])
        self.assertEqual(ai_msg["risk_level"], "normal")
        self.assertIsNone(ai_msg["followup_instructions"])

    # T10: Legacy rows with NULL role default to "user"
    def test_null_role_defaults_to_user(self):
        rows = [{"id": "cx", "role": None, "message": "test", "created_at": "2026-02-25T10:00:00"}]
        with patch.object(ch, "supabase", _mock_sb(rows, [])):
            result = ch.get_chat_history("pet-1")
        self.assertEqual(result[0]["role"], "user")

    # T11: AI message is not enriched even when a medical event with matching id exists
    def test_ai_message_not_enriched_by_medical_event(self):
        rows = [
            {"id": "c1", "role": "ai", "message": "AI says hi", "created_at": "2026-02-25T10:00:00"},
        ]
        # Even if an event has the same source_chat_id — AI messages skip enrichment
        events = [_med_event("c1", urgency=3, symptom="vomiting")]
        with patch.object(ch, "supabase", _mock_sb(rows, events)):
            result = ch.get_chat_history("pet-1")
        ai_msg = result[0]
        self.assertEqual(ai_msg["role"], "ai")
        self.assertIsNone(ai_msg["structured_data"])
        self.assertEqual(ai_msg["risk_level"], "normal")


def main():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestChatHistory)
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
