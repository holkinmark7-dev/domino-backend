from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID


class PetCreate(BaseModel):
    user_id: UUID
    name: str = Field(..., min_length=2, max_length=50)
    species: str
    breed: Optional[str] = None
    birth_date: Optional[str] = None
