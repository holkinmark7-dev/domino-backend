"""
Vet Report PDF Export Unit Tests — Day 22
Verifies the PDF endpoint contract:
  - Calls get_vet_report() for data (no duplicated logic)
  - Returns application/pdf Response
  - Content-Disposition header present
  - No additional DB queries (supabase untouched by PDF layer)
  - Content is valid PDF bytes
"""
import sys
import io
import unittest
from unittest.mock import MagicMock, patch

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import routers.vet_report as vr
from fastapi.responses import Response

# ─────────────────────────────────────────────────────────────────────────────
# Fixture: a typical report dict (mirrors get_vet_report output)
# ─────────────────────────────────────────────────────────────────────────────
_SAMPLE_REPORT = {
    "pet_id": "pet-test-1",
    "report_generated_at": "2026-02-25T12:00:00+00:00",
    "total_episodes": 3,
    "active_episode_count": 1,
    "resolved_episode_count": 2,
    "first_episode_at": "2026-02-01T08:00:00+00:00",
    "last_episode_at": "2026-02-25T08:00:00+00:00",
    "highest_escalation_ever": "HIGH",
    "episodes": [
        {
            "episode_id": "ep-1",
            "normalized_key": "vomiting",
            "escalation": "LOW",
            "status": "resolved",
            "started_at": "2026-02-01T08:00:00+00:00",
            "resolved_at": "2026-02-02T09:00:00+00:00",
        },
        {
            "episode_id": "ep-2",
            "normalized_key": "diarrhea",
            "escalation": "HIGH",
            "status": "resolved",
            "started_at": "2026-02-15T08:00:00+00:00",
            "resolved_at": "2026-02-16T09:00:00+00:00",
        },
        {
            "episode_id": "ep-3",
            "normalized_key": "vomiting",
            "escalation": "MODERATE",
            "status": "active",
            "started_at": "2026-02-25T08:00:00+00:00",
            "resolved_at": None,
        },
    ],
}

_EMPTY_REPORT = {
    "pet_id": "pet-empty",
    "report_generated_at": "2026-02-25T12:00:00+00:00",
    "total_episodes": 0,
    "active_episode_count": 0,
    "resolved_episode_count": 0,
    "first_episode_at": None,
    "last_episode_at": None,
    "highest_escalation_ever": None,
    "episodes": [],
}


class TestVetReportPdf(unittest.TestCase):

    # T1: Response returns HTTP 200 (status_code on fastapi Response)
    def test_returns_200(self):
        with patch.object(vr, "get_vet_report", return_value=_SAMPLE_REPORT):
            response = vr.get_vet_report_pdf("pet-test-1")
        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, 200)

    # T2: media_type is application/pdf
    def test_media_type_is_pdf(self):
        with patch.object(vr, "get_vet_report", return_value=_SAMPLE_REPORT):
            response = vr.get_vet_report_pdf("pet-test-1")
        self.assertEqual(response.media_type, "application/pdf")

    # T3: Content-Disposition header is present and contains filename
    def test_content_disposition_present(self):
        with patch.object(vr, "get_vet_report", return_value=_SAMPLE_REPORT):
            response = vr.get_vet_report_pdf("pet-test-1")
        cd = response.headers.get("content-disposition", "")
        self.assertIn("attachment", cd)
        self.assertIn("vet-report-pet-test-1.pdf", cd)

    # T4: get_vet_report is called exactly once with the correct pet_id
    def test_get_vet_report_called_once(self):
        with patch.object(vr, "get_vet_report", return_value=_SAMPLE_REPORT) as mock_fn:
            vr.get_vet_report_pdf("pet-test-1")
        mock_fn.assert_called_once_with("pet-test-1")

    # T5: No additional supabase calls from the PDF layer itself
    # (get_vet_report is mocked → supabase must not be touched by PDF endpoint)
    def test_no_additional_db_queries(self):
        mock_sb = MagicMock()
        with patch.object(vr, "get_vet_report", return_value=_SAMPLE_REPORT), \
             patch.object(vr, "supabase", mock_sb):
            vr.get_vet_report_pdf("pet-test-1")
        # The PDF endpoint itself must not touch supabase — only get_vet_report does
        mock_sb.table.assert_not_called()

    # T6: Content is non-empty bytes starting with PDF magic bytes (%PDF)
    def test_content_is_valid_pdf_bytes(self):
        with patch.object(vr, "get_vet_report", return_value=_SAMPLE_REPORT):
            response = vr.get_vet_report_pdf("pet-test-1")
        content = response.body
        self.assertIsInstance(content, bytes)
        self.assertGreater(len(content), 100)
        self.assertTrue(content.startswith(b"%PDF"), "Content must start with %PDF")

    # T7: PDF generated for empty report (no episodes) — must not crash
    def test_empty_report_generates_pdf(self):
        with patch.object(vr, "get_vet_report", return_value=_EMPTY_REPORT):
            response = vr.get_vet_report_pdf("pet-empty")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "application/pdf")
        self.assertTrue(response.body.startswith(b"%PDF"))

    # T8: _build_pdf is pure — calling it with the same report twice gives valid PDF both times
    def test_build_pdf_idempotent(self):
        pdf1 = vr._build_pdf(_SAMPLE_REPORT)
        pdf2 = vr._build_pdf(_SAMPLE_REPORT)
        self.assertTrue(pdf1.startswith(b"%PDF"))
        self.assertTrue(pdf2.startswith(b"%PDF"))
        # Both PDFs should be non-trivially sized
        self.assertGreater(len(pdf1), 500)
        self.assertGreater(len(pdf2), 500)

    # Extra: filename in Content-Disposition changes with pet_id
    def test_filename_uses_pet_id(self):
        with patch.object(vr, "get_vet_report", return_value={**_SAMPLE_REPORT, "pet_id": "xyz-999"}):
            response = vr.get_vet_report_pdf("xyz-999")
        cd = response.headers.get("content-disposition", "")
        self.assertIn("vet-report-xyz-999.pdf", cd)

    # Extra: JSON endpoint unchanged — get_vet_report still returns a dict (not a Response)
    def test_json_endpoint_not_modified(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value \
            .select.return_value \
            .eq.return_value \
            .order.return_value \
            .execute.return_value \
            .data = []
        with patch.object(vr, "supabase", mock_sb):
            result = vr.get_vet_report("pet-check")
        self.assertIsInstance(result, dict)
        self.assertIn("total_episodes", result)
        self.assertIn("episodes", result)


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────
def main():
    vr.supabase = MagicMock()  # baseline mock

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestVetReportPdf)

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
