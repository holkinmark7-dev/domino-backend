"""
Part C — Recurrence detection tests.

Tests check_recurrence from routers/services/recurrence.py.
All supabase calls are mocked.
"""
import sys
import os
import pytest
from freezegun import freeze_time
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.services.recurrence import check_recurrence

PET_ID = "00000000-0000-0000-0000-000000000002"


class TestCheckRecurrence:

    def test_no_history_not_recurrent(self):
        """No past episodes → False."""
        mock_resp = MagicMock()
        mock_resp.data = []

        with patch("routers.services.recurrence.supabase") as sb:
            sb.table.return_value.select.return_value.eq.return_value \
                .eq.return_value.eq.return_value.eq.return_value \
                .gte.return_value.execute.return_value = mock_resp

            result = check_recurrence(PET_ID, "vomiting")

        assert result is False

    def test_one_episode_not_recurrent(self):
        """1 resolved episode → False (threshold is 3)."""
        mock_resp = MagicMock()
        mock_resp.data = [{"id": "ep-1"}]

        with patch("routers.services.recurrence.supabase") as sb:
            sb.table.return_value.select.return_value.eq.return_value \
                .eq.return_value.eq.return_value.eq.return_value \
                .gte.return_value.execute.return_value = mock_resp

            result = check_recurrence(PET_ID, "vomiting")

        assert result is False

    def test_two_episodes_not_recurrent(self):
        """2 resolved episodes → False (threshold is 3)."""
        mock_resp = MagicMock()
        mock_resp.data = [{"id": "ep-1"}, {"id": "ep-2"}]

        with patch("routers.services.recurrence.supabase") as sb:
            sb.table.return_value.select.return_value.eq.return_value \
                .eq.return_value.eq.return_value.eq.return_value \
                .gte.return_value.execute.return_value = mock_resp

            result = check_recurrence(PET_ID, "vomiting")

        assert result is False

    def test_three_episodes_is_recurrent(self):
        """3 resolved episodes → True."""
        mock_resp = MagicMock()
        mock_resp.data = [{"id": "ep-1"}, {"id": "ep-2"}, {"id": "ep-3"}]

        with patch("routers.services.recurrence.supabase") as sb:
            sb.table.return_value.select.return_value.eq.return_value \
                .eq.return_value.eq.return_value.eq.return_value \
                .gte.return_value.execute.return_value = mock_resp

            result = check_recurrence(PET_ID, "vomiting")

        assert result is True

    def test_five_episodes_is_recurrent(self):
        """5 resolved episodes → True."""
        mock_resp = MagicMock()
        mock_resp.data = [{"id": f"ep-{i}"} for i in range(5)]

        with patch("routers.services.recurrence.supabase") as sb:
            sb.table.return_value.select.return_value.eq.return_value \
                .eq.return_value.eq.return_value.eq.return_value \
                .gte.return_value.execute.return_value = mock_resp

            result = check_recurrence(PET_ID, "vomiting")

        assert result is True

    def test_db_error_returns_false(self):
        """Supabase failure → False (safe fallback)."""
        with patch("routers.services.recurrence.supabase") as sb:
            sb.table.return_value.select.return_value.eq.return_value \
                .eq.return_value.eq.return_value.eq.return_value \
                .gte.return_value.execute.side_effect = Exception("timeout")

            result = check_recurrence(PET_ID, "vomiting")

        assert result is False

    def test_none_data_returns_false(self):
        """result.data is None → treated as 0 episodes, False."""
        mock_resp = MagicMock()
        mock_resp.data = None

        with patch("routers.services.recurrence.supabase") as sb:
            sb.table.return_value.select.return_value.eq.return_value \
                .eq.return_value.eq.return_value.eq.return_value \
                .gte.return_value.execute.return_value = mock_resp

            result = check_recurrence(PET_ID, "vomiting")

        assert result is False
