from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class VisionMode(str, Enum):
    passport = "passport"
    breed = "breed"
    symptom = "symptom"


class VisionRequest(BaseModel):
    mode: VisionMode
    image_base64: str = Field(..., description="Base64-encoded image, without data:image/... prefix")
    pet_id: Optional[str] = Field(None, description="Required for passport and breed modes")
    pet_context: Optional[dict] = Field(None, description="Pet profile context for symptom mode")


# --- PASSPORT MODE ---

class VaccineEntry(BaseModel):
    name: str
    date: Optional[str] = None
    next_date: Optional[str] = None
    batch_number: Optional[str] = None


class PassportFields(BaseModel):
    pet_name_ru: Optional[str] = None
    pet_name_lat: Optional[str] = None
    species: Optional[str] = None
    breed_ru: Optional[str] = None
    breed_lat: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[str] = None
    color: Optional[str] = None
    chip_id: Optional[str] = None
    chip_install_date: Optional[str] = None
    stamp_id: Optional[str] = None
    vaccines: List[VaccineEntry] = []
    owner_name: Optional[str] = None
    vet_clinic: Optional[str] = None


class FieldConfidence(BaseModel):
    pet_name_ru: float = 1.0
    pet_name_lat: float = 1.0
    species: float = 1.0
    breed_ru: float = 1.0
    birth_date: float = 1.0
    gender: float = 1.0
    color: float = 1.0
    chip_id: float = 1.0
    chip_install_date: float = 1.0
    stamp_id: float = 1.0
    vaccines: float = 1.0


class PassportResponse(BaseModel):
    success: bool
    fields: PassportFields
    field_confidence: FieldConfidence
    overall_confidence: float
    low_confidence_fields: List[str]
    error: Optional[str] = None


# --- BREED MODE ---

class BreedCandidate(BaseModel):
    name_ru: str
    name_lat: str
    probability: float


class BreedResponse(BaseModel):
    success: bool
    breeds: List[BreedCandidate]
    color: Optional[str] = None
    age_estimate: Optional[str] = None
    confidence: float
    error: Optional[str] = None


# --- SYMPTOM MODE ---

class SymptomResponse(BaseModel):
    success: bool
    description: str
    severity_hint: Optional[str] = None
    error: Optional[str] = None


# --- AVATAR (kept from previous version) ---

class AvatarResponse(BaseModel):
    avatar_url: str


# --- PASSPORT CONFIRM ---

class PassportConfirmRequest(BaseModel):
    pet_id: str
    fields: dict
