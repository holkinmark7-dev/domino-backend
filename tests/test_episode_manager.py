"""
Part B — Episode manager unit tests.

Tests process_event, update_episode_escalation, and internal helpers.
All supabase calls are mocked.
"""
import sys
import os
import pytest
from freezegun import freeze_time
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.services.episode_manager import (
    process_event,
    update_episode_escalation,
    _is_resolution,
    _max_escalation,
)

PET_ID = "00000000-0000-0000-0000-000000000002"


# ══════════════════════════════════════════════════════════════════════════════
# Pure helpers
# ══════════════════════════════════════════════════════════════════════════════
class TestMaxEscalation:

    def test_same_level(self):
        assert _max_escalation("LOW", "LOW") == "LOW"

    def test_second_higher(self):
        assert _max_escalation("LOW", "HIGH") == "HIGH"

    def test_first_higher(self):
        assert _max_escalation("CRITICAL", "MODERATE") == "CRITICAL"

    def test_unknown_treated_as_zero(self):
        assert _max_escalation("HIGH", "UNKNOWN") == "HIGH"


class TestIsResolution:

    def test_resolution_phrase(self):
        assert _is_resolution("всё прошло, рвоты нет") is True

    def test_no_resolution(self):
        assert _is_resolution("vomiting again today") is False

    def test_case_insensitive(self):
        assert _is_resolution("Уже Нормально") is True


# ══════════════════════════════════════════════════════════════════════════════
# process_event — creates new episode
# ══════════════════════════════════════════════════════════════════════════════
class TestProcessEventCreate:

    @freeze_time("2024-06-15 12:00:00", tz_offset=0)
    def test_new_symptom_creates_episode(self):
        """First vomiting event → creates new episode."""
        active_resp = MagicMock()
        active_resp.data = []  # no active episode

        insert_resp = MagicMock()
        insert_resp.data = [{"id": "ep-new-1", "status": "active"}]

        with patch("routers.services.episode_manager.supabase") as sb:
            tbl = MagicMock()
            # _get_active_episode → empty
            sel = MagicMock()
            sel.eq.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = active_resp
            tbl.select.return_value = sel
            # _create_episode → success
            tbl.insert.return_value.execute.return_value = insert_resp
            sb.table.return_value = tbl

            result = process_event(
                pet_id=PET_ID, symptom="vomiting", medication=None,
                message_text="Кот рвёт", event_id="ev-1",
            )

        assert result["symptom_episode"]["action"] == "created"
        assert result["symptom_episode"]["episode_id"] == "ep-new-1"

    @freeze_time("2024-06-15 12:00:00", tz_offset=0)
    def test_existing_episode_continues(self):
        """Second vomiting event → continues existing episode."""
        active_resp = MagicMock()
        active_resp.data = [{"id": "ep-exist", "escalation": "LOW", "status": "active"}]

        update_resp = MagicMock()

        with patch("routers.services.episode_manager.supabase") as sb:
            tbl = MagicMock()
            sel = MagicMock()
            sel.eq.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = active_resp
            tbl.select.return_value = sel
            tbl.update.return_value.eq.return_value.execute.return_value = update_resp
            sb.table.return_value = tbl

            result = process_event(
                pet_id=PET_ID, symptom="vomiting", medication=None,
                message_text="Опять рвёт", event_id="ev-2",
            )

        assert result["symptom_episode"]["action"] == "continued"
        assert result["symptom_episode"]["episode_id"] == "ep-exist"


# ══════════════════════════════════════════════════════════════════════════════
# process_event — resolution
# ══════════════════════════════════════════════════════════════════════════════
class TestProcessEventResolution:

    @freeze_time("2024-06-15 12:00:00", tz_offset=0)
    def test_resolution_resolves_active_episode(self):
        """Resolution phrase → resolves active episode."""
        active_resp = MagicMock()
        active_resp.data = [{"id": "ep-resolve", "status": "active"}]

        with patch("routers.services.episode_manager.supabase") as sb:
            tbl = MagicMock()
            sel = MagicMock()
            sel.eq.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = active_resp
            tbl.select.return_value = sel
            tbl.update.return_value.eq.return_value.execute.return_value = MagicMock()
            sb.table.return_value = tbl

            result = process_event(
                pet_id=PET_ID, symptom="vomiting", medication=None,
                message_text="Всё прошло", event_id="ev-3",
            )

        assert result["symptom_episode"]["action"] == "resolved"

    @freeze_time("2024-06-15 12:00:00", tz_offset=0)
    def test_resolution_no_active_returns_standalone(self):
        """Resolution phrase but no active episode → standalone."""
        empty_resp = MagicMock()
        empty_resp.data = []

        with patch("routers.services.episode_manager.supabase") as sb:
            tbl = MagicMock()
            sel = MagicMock()
            sel.eq.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = empty_resp
            tbl.select.return_value = sel
            sb.table.return_value = tbl

            result = process_event(
                pet_id=PET_ID, symptom="vomiting", medication=None,
                message_text="Всё прошло", event_id="ev-4",
            )

        assert result["symptom_episode"]["action"] == "standalone"


# ══════════════════════════════════════════════════════════════════════════════
# update_episode_escalation — monotonic invariant
# ══════════════════════════════════════════════════════════════════════════════
class TestUpdateEpisodeEscalation:

    def test_escalation_goes_up(self):
        """LOW → HIGH: should update."""
        row_resp = MagicMock()
        row_resp.data = {"escalation": "LOW"}

        with patch("routers.services.episode_manager.supabase") as sb:
            tbl = MagicMock()
            tbl.select.return_value.eq.return_value.single.return_value.execute.return_value = row_resp
            tbl.update.return_value.eq.return_value.execute.return_value = MagicMock()
            sb.table.return_value = tbl

            update_episode_escalation("ep-1", "HIGH")

        tbl.update.assert_called_once()

    def test_escalation_stays_same_no_update(self):
        """HIGH → HIGH: no update needed."""
        row_resp = MagicMock()
        row_resp.data = {"escalation": "HIGH"}

        with patch("routers.services.episode_manager.supabase") as sb:
            tbl = MagicMock()
            tbl.select.return_value.eq.return_value.single.return_value.execute.return_value = row_resp
            sb.table.return_value = tbl

            update_episode_escalation("ep-1", "HIGH")

        tbl.update.assert_not_called()

    def test_escalation_never_lowers(self):
        """CRITICAL → LOW: should NOT update (monotonic invariant)."""
        row_resp = MagicMock()
        row_resp.data = {"escalation": "CRITICAL"}

        with patch("routers.services.episode_manager.supabase") as sb:
            tbl = MagicMock()
            tbl.select.return_value.eq.return_value.single.return_value.execute.return_value = row_resp
            sb.table.return_value = tbl

            update_episode_escalation("ep-1", "LOW")

        tbl.update.assert_not_called()

    def test_db_error_does_not_raise(self):
        """Supabase failure → swallowed, no crash."""
        with patch("routers.services.episode_manager.supabase") as sb:
            sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = Exception("db down")

            # Should not raise
            update_episode_escalation("ep-1", "HIGH")
