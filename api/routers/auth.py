import secrets
import asyncio
from fastapi import APIRouter, Depends, Request
from fastapi import HTTPException, status
import database as db
from api.dependencies import verify_token
from api.models import APIResponse
from api.utils import log_api_action

router = APIRouter(prefix="/token", tags=["Users"])


@router.post("/regenerate", response_model=APIResponse)
async def regenerate_token(request: Request, current_user: dict = Depends(verify_token)):
    user_id = current_user['tg_user_id']
    username = current_user.get('username') or f"user{user_id}"
    new_token = f"{username}:{user_id}:{secrets.token_urlsafe(32)}"
    if await db.regenerate_user_token(user_id, new_token):

        return APIResponse(data={"new_token": new_token})
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update token in the database.")
