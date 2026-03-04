"""
Vet Report API — Day 21–22

GET /vet-report/{pet_id}       → JSON report
GET /vet-report/{pet_id}/pdf   → PDF download (Day 22)

Read-only aggregation over the episodes table.
The PDF endpoint delegates entirely to get_vet_report() — no duplicated logic,
no additional DB queries.
"""
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from dependencies.auth import get_current_user, verify_pet_owner
from dependencies.limiter import limiter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from supabase import create_client

from config import SUPABASE_URL, SUPABASE_KEY
from routers.services.risk_engine import ESCALATION_ORDER

router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

_EPISODE_FIELDS = "id, normalized_key, escalation, status, started_at, resolved_at, updated_at"


@router.get("/vet-report/{pet_id}")
@limiter.limit("30/minute")
def get_vet_report(pet_id: str, request: Request = None, current_user: dict = Depends(get_current_user)):
    """
    Return a structured clinical history report for a pet.

    - Episodes listed in chronological order (started_at ASC).
    - highest_escalation_ever: max escalation across all episodes by ESCALATION_ORDER.
    - Escalation values passed through as-is — never recalculated.
    - report_generated_at: UTC timestamp of this request.
    """
    verify_pet_owner(pet_id, current_user, supabase)
    result = (
        supabase.table("episodes")
        .select(_EPISODE_FIELDS)
        .eq("pet_id", pet_id)
        .order("started_at", desc=False)   # ASC — chronological for clinical history
        .execute()
    )

    episodes = result.data if result.data else []

    # Pet profile
    pet_result = (
        supabase.table("pets")
        .select("name, species, breed, birth_date")
        .eq("id", pet_id)
        .single()
        .execute()
    )
    pet_profile = pet_result.data if pet_result.data else {}

    # Status counts
    active_episode_count = sum(1 for ep in episodes if ep.get("status") == "active")
    resolved_episode_count = sum(1 for ep in episodes if ep.get("status") == "resolved")

    # first / last episode timestamps (episodes sorted ASC)
    first_episode_at = episodes[0].get("started_at") if episodes else None
    last_episode_at = episodes[-1].get("started_at") if episodes else None

    # highest escalation ever seen (read-only aggregation, no mutation)
    if episodes:
        highest_escalation_ever = max(
            (ep.get("escalation") or "LOW" for ep in episodes),
            key=lambda e: ESCALATION_ORDER.get(e, 0),
        )
    else:
        highest_escalation_ever = None

    # Episode list for report
    episode_list = [
        {
            "episode_id": ep.get("id"),
            "normalized_key": ep.get("normalized_key"),
            "escalation": ep.get("escalation"),
            "status": ep.get("status"),
            "started_at": ep.get("started_at"),
            "resolved_at": ep.get("resolved_at"),
        }
        for ep in episodes
    ]

    return {
        "pet_id": pet_id,
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
        "pet_name": pet_profile.get("name"),
        "pet_species": pet_profile.get("species"),
        "pet_breed": pet_profile.get("breed"),
        "pet_birth_date": pet_profile.get("birth_date"),
        "total_episodes": len(episodes),
        "active_episode_count": active_episode_count,
        "resolved_episode_count": resolved_episode_count,
        "first_episode_at": first_episode_at,
        "last_episode_at": last_episode_at,
        "highest_escalation_ever": highest_escalation_ever,
        "episodes": episode_list,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Day 22: PDF export
# ─────────────────────────────────────────────────────────────────────────────

def _build_pdf(report: dict, _compress: bool = True) -> bytes:
    """
    Render a vet report dict (from get_vet_report) as a PDF byte string.
    MVP layout: title, patient block, summary block, episodes table.

    _compress=False disables page compression (used in tests to allow
    literal byte-level assertions on the content stream).
    """
    _dash = "\u2014"  # em-dash — can't use \u inside f-string on Python < 3.12
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4, pageCompression=int(_compress))
    page_w, page_h = A4
    margin = 50
    y = page_h - margin

    def _next_line(step: int = 15):
        nonlocal y
        y -= step
        if y < margin + 30:          # near bottom → new page
            c.showPage()
            y = page_h - margin
            c.setFont("Helvetica", 10)

    # ── Title ────────────────────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, "Domino Pets - Veterinarnyi otchet")
    _next_line(22)

    c.setFont("Helvetica", 11)
    c.drawString(margin, y, f"Pet ID: {report.get('pet_id') or _dash}")
    _next_line()
    c.drawString(margin, y, f"Generated at: {report.get('report_generated_at') or _dash}")
    _next_line(22)

    # ── Patient block ─────────────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Patsient")
    _next_line(18)

    c.setFont("Helvetica", 11)
    pet_lines = [
        f"Imya:    {report.get('pet_name') or _dash}",
        f"Vid:     {report.get('pet_species') or _dash}",
        f"Poroda:  {report.get('pet_breed') or _dash}",
        f"D.r.:    {report.get('pet_birth_date') or _dash}",
    ]
    for line in pet_lines:
        c.drawString(margin, y, line)
        _next_line()
    _next_line(12)

    # ── Summary ───────────────────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Svodka")
    _next_line(18)

    c.setFont("Helvetica", 11)
    summary_lines = [
        f"Vsego epizodov:     {report.get('total_episodes', 0)}",
        f"Aktivnykh:          {report.get('active_episode_count', 0)}",
        f"Zavershennykh:      {report.get('resolved_episode_count', 0)}",
        f"Pervyi epizod:      {report.get('first_episode_at') or _dash}",
        f"Posledniy epizod:   {report.get('last_episode_at') or _dash}",
        f"Maks. eskalatsiya:  {report.get('highest_escalation_ever') or _dash}",
    ]
    for line in summary_lines:
        c.drawString(margin, y, line)
        _next_line()
    _next_line(12)

    # ── Episodes table ────────────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y, "Epizody")
    _next_line(18)

    # Column header
    col_x = [margin, margin + 90, margin + 240, margin + 330, margin + 430]
    headers = ["Data", "Simptom", "Eskalatsiya", "Status"]
    c.setFont("Helvetica-Bold", 10)
    for hdr, x in zip(headers, col_x):
        c.drawString(x, y, hdr)
    _next_line(5)
    c.line(margin, y, page_w - margin, y)
    _next_line(12)

    # Rows
    c.setFont("Helvetica", 10)
    for ep in report.get("episodes", []):
        started = (ep.get("started_at") or "")[:10]
        key = (ep.get("normalized_key") or "\u2014")[:22]
        esc = ep.get("escalation") or "\u2014"
        status = ep.get("status") or "\u2014"
        for text, x in zip([started, key, esc, status], col_x):
            c.drawString(x, y, text)
        _next_line()

    c.save()
    return buffer.getvalue()


@router.get("/vet-report/{pet_id}/pdf")
@limiter.limit("30/minute")
def get_vet_report_pdf(pet_id: str, request: Request = None, current_user: dict = Depends(get_current_user)):
    """
    Return a PDF version of the vet report.
    Delegates entirely to get_vet_report() — no additional DB queries.
    """
    report = get_vet_report(pet_id, current_user)
    pdf_bytes = _build_pdf(report)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=vet-report-{pet_id}.pdf",
        },
    )
