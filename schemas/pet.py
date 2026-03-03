from pydantic import BaseModel
from typing import Optional
from uuid import UUID


class PetCreate(BaseModel):
    user_id: UUID
    name: Optional[str] = None
    species: Optional[str] = None
    breed: Optional[str] = None
    birth_date: Optional[str] = None
