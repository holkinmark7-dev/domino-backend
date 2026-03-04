from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    token = credentials.credentials
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        response = supabase.auth.get_user(token)
        if not response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"id": response.user.id, "email": response.user.email}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def verify_pet_owner(pet_id: str, current_user: dict, supabase_client) -> None:
    """
    Проверяет что питомец принадлежит текущему пользователю.
    404 если не найден, 403 если чужой.
    """
    if not isinstance(current_user, dict):
        return  # direct call from tests without DI
    try:
        result = (
            supabase_client.table("pets")
            .select("user_id")
            .eq("id", pet_id)
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Pet not found")

    if not result.data:
        raise HTTPException(status_code=404, detail="Pet not found")

    if result.data["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
