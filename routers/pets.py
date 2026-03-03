from fastapi import APIRouter, HTTPException
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from schemas.pet import PetCreate

router = APIRouter()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


@router.post("/pets")
def create_pet(pet: PetCreate):
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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pets/{user_id}")
def get_pets(user_id: str):
    try:
        response = supabase.table("pets").select("*").eq("user_id", user_id).order("created_at", desc=False).execute()
        return response.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
