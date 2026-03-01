from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional
from uuid import UUID


class ChatMessage(BaseModel):
    user_id: Optional[str] = None
    pet_id: str = Field(..., min_length=1)
    message: str = Field(..., max_length=5000)
    anonymous_id: Optional[str] = None
    client_time: Optional[str] = None

    @field_validator("pet_id")
    @classmethod
    def validate_pet_id_uuid(cls, v):
        try:
            UUID(v)
        except ValueError:
            raise ValueError("pet_id must be a valid UUID")
        return v

    @field_validator("user_id", "anonymous_id")
    @classmethod
    def validate_optional_uuid(cls, v, info):
        if v is not None:
            try:
                UUID(v)
            except ValueError:
                raise ValueError(f"{info.field_name} must be a valid UUID")
        return v

    @model_validator(mode="after")
    def check_identity(self):
        if not self.user_id and not self.anonymous_id:
            raise ValueError("Either user_id or anonymous_id must be provided")
        if self.user_id is None and self.anonymous_id is not None:
            self.user_id = self.anonymous_id
        return self


class MigrateUser(BaseModel):
    anonymous_id: str = Field(..., min_length=1)
    new_user_id: str = Field(..., min_length=1)

    @field_validator("anonymous_id", "new_user_id")
    @classmethod
    def validate_uuid(cls, v, info):
        try:
            UUID(v)
        except ValueError:
            raise ValueError(f"{info.field_name} must be a valid UUID")
        return v
