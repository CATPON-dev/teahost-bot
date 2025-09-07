from fastapi import Header, HTTPException, status
import database as db

async def verify_token(x_api_token: str = Header(..., alias="X-API-Token")):
    if not x_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API token is missing.")

    user_data = await db.get_user_by_api_token(x_api_token)
    if not user_data:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired API token.")

    user_id = user_data['tg_user_id']
    
    if not await db.has_user_accepted_agreement(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has not accepted the agreement.")
        
    if await db.is_user_banned(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This user is banned.")
        
    return user_data