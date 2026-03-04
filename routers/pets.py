import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from schemas.pet import PetCreate
from dependencies.auth import get_current_user, verify_pet_owner
from dependencies.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


@router.post("/pets")
def create_pet(pet: PetCreate, current_user: dict = Depends(get_current_user)):
    if isinstance(current_user, dict) and str(pet.user_id) != current_user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        response = supabase.table("pets").insert({
            "user_id": str(pet.user_id),
            "name": pet.name,
            "species": pet.species,
            "breed": pet.breed,
            "birth_date": pet.birth_date,
        }).execute()

        return response.data

    except Exception as e:
        logger.error("Database error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/pets/{user_id}")
@limiter.limit("30/minute")
def get_pets(user_id: str, request: Request = None, current_user: dict = Depends(get_current_user)):
    if isinstance(current_user, dict) and user_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        response = supabase.table("pets").select("*").eq("user_id", user_id).order("created_at", desc=False).execute()
        return response.data or []
    except Exception as e:
        logger.error("Database error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/pet/{pet_id}")
@limiter.limit("30/minute")
def get_pet_by_id(pet_id: str, request: Request = None, current_user: dict = Depends(get_current_user)):
    try:
        UUID(pet_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "invalid pet_id"})

    verify_pet_owner(pet_id, current_user, supabase)

    result = (
        supabase.table("pets")
        .select("*")
        .eq("id", pet_id)
        .single()
        .execute()
    )

    if not result.data:
        return JSONResponse(status_code=404, content={"error": "pet not found"})

    return result.data
