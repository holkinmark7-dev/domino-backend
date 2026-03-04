from pydantic import BaseModel
from typing import Optional
from uuid import UUID


class PetCreate(BaseModel):
    user_id: UUID
    name: Optional[str] = None
    species: Optional[str] = None
    breed: Optional[str] = None
    birth_date: Optional[str] = None


class PetUpdate(BaseModel):
    name: Optional[str] = None
    species: Optional[str] = None
    breed: Optional[str] = None
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    neutered: Optional[bool] = None
    color: Optional[str] = None
    features: Optional[str] = None
    chip_id: Optional[str] = None
    stamp_id: Optional[str] = None
    age_years: Optional[float] = None
    # skipped flags
    breed_skipped: Optional[bool] = None
    color_skipped: Optional[bool] = None
    features_skipped: Optional[bool] = None
    chip_id_skipped: Optional[bool] = None
    stamp_id_skipped: Optional[bool] = None
