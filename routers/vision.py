import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from supabase import create_client

from config import SUPABASE_URL, SUPABASE_KEY
from schemas.vision import (
    VisionRequest, PassportResponse, BreedResponse, SymptomResponse,
    AvatarResponse, PassportConfirmRequest,
)
from dependencies.auth import get_current_user, verify_pet_owner
from dependencies.limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Passport OCR ─────────────────────────────────────────────────────────────

@router.post("/vision/passport", response_model=PassportResponse)
@limiter.limit("20/minute")
async def vision_passport(
    body: VisionRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    OCR ветеринарного паспорта.
    Returns structured fields + confidence. Does NOT auto-save.
    Frontend shows PASSPORT_REVIEW → user confirms → POST /vision/passport/confirm.
    """
    # pet_id optional during onboarding (pet not yet created)
    if body.pet_id:
        try:
            UUID(body.pet_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid pet_id")
        verify_pet_owner(body.pet_id, current_user, supabase)

    from routers.services.vision_service import process_passport_ocr
    try:
        result = await process_passport_ocr(body.image_base64)
        return result
    except Exception as e:
        logger.error("Passport OCR error: %s", e)
        from schemas.vision import PassportFields, FieldConfidence
        return PassportResponse(
            success=False,
            fields=PassportFields(),
            field_confidence=FieldConfidence(),
            overall_confidence=0.0,
            low_confidence_fields=[],
            error="parse_error",
        )


# ── Passport Confirm ─────────────────────────────────────────────────────────

@router.post("/vision/passport/confirm")
@limiter.limit("20/minute")
async def vision_passport_confirm(
    body: PassportConfirmRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Save confirmed passport data to pet profile + vaccines.
    Called ONLY after user confirms on PASSPORT_REVIEW screen.
    """
    try:
        UUID(body.pet_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pet_id")

    verify_pet_owner(body.pet_id, current_user, supabase)

    from routers.services.vision_service import save_passport_data
    await save_passport_data(body.pet_id, body.fields)
    return {"success": True}


# ── Breed Detection ──────────────────────────────────────────────────────────

@router.post("/vision/breed", response_model=BreedResponse)
@limiter.limit("20/minute")
async def vision_breed(
    body: VisionRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Detect breed and color from pet photo."""
    from routers.services.vision_service import process_breed_detection
    try:
        result = await process_breed_detection(body.image_base64)
        return result
    except Exception as e:
        logger.error("Breed detection error: %s", e)
        return BreedResponse(success=False, breeds=[], confidence=0.0, error="parse_error")


# ── Symptom Vision ───────────────────────────────────────────────────────────

@router.post("/vision/symptom", response_model=SymptomResponse)
@limiter.limit("20/minute")
async def vision_symptom(
    body: VisionRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Analyze symptom photo from chat.
    Returns text description → frontend appends to user message → sends to POST /chat.
    """
    from routers.services.vision_service import process_symptom_vision
    try:
        result = await process_symptom_vision(body.image_base64, pet_context=body.pet_context)
        return result
    except Exception as e:
        logger.error("Symptom vision error: %s", e)
        return SymptomResponse(success=False, description="", error="parse_error")


# ── Avatar Upload (preserved from previous version) ──────────────────────────

@router.post("/pets/{pet_id}/avatar", response_model=AvatarResponse)
@limiter.limit("5/minute")
async def upload_avatar(
    pet_id: str,
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    try:
        UUID(pet_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid pet_id")

    verify_pet_owner(pet_id, current_user, supabase)

    content = await file.read()
    ext = file.filename.rsplit(".", 1)[-1] if file.filename else "jpg"
    storage_path = f"{pet_id}/avatar.{ext}"

    try:
        supabase.storage.from_("pet-photos").upload(
            storage_path,
            content,
            file_options={"content-type": file.content_type or "image/jpeg", "upsert": "true"},
        )
    except Exception as e:
        logger.error("Storage upload error: %s", e)
        raise HTTPException(status_code=500, detail="Avatar upload failed")

    public_url = f"{SUPABASE_URL}/storage/v1/object/public/pet-photos/{storage_path}"
    supabase.table("pets").update({"avatar_url": public_url}).eq("id", pet_id).execute()

    return AvatarResponse(avatar_url=public_url)
