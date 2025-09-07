import asyncio
from fastapi import APIRouter, Depends, Path, Request
from fastapi import HTTPException, status
import database as db
import server_config
from api_manager import api_manager
from api.dependencies import verify_token
from api.models import APIResponse
from api.utils import log_api_action

router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/{identifier}", response_model=APIResponse)
async def get_user_info(request: Request, identifier: str = Path(...), current_user: dict = Depends(verify_token)):
    target_user_data = await db.get_user_by_username_or_id(identifier)
    if not target_user_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    target_id = target_user_data['tg_user_id']
    user_bots = await db.get_userbots_by_tg_id(target_id)
    userbot_info_obj = None

    if user_bots:
        ub = user_bots[0]
        status_res = await api_manager.get_container_status(ub['ub_username'], ub['server_ip'])
        status_str = status_res.get("data", {}).get("status", "unknown") if status_res.get("success") else "error"
        
        server_details = server_config.get_servers().get(ub['server_ip'], {})
        userbot_info_obj = {
            "ub_username": ub['ub_username'],
            "ub_type": ub.get('ub_type'),
            "status": status_str,
            "server_code": server_details.get('code', 'N/A'),
            "created_at": ub.get('created_at')
        }

    response_data = {
        "owner": {
            "id": target_id,
            "username": target_user_data.get('username'),
            "full_name": target_user_data.get('full_name'),
            "registered_at": target_user_data.get('registered_at')
        },
        "userbot": userbot_info_obj
    }

    log_data = {
        "admin_data": {"id": current_user['tg_user_id'], "full_name": current_user.get('full_name')},
        "user_data": {"id": target_user_data['tg_user_id'], "full_name": target_user_data.get('full_name')},
        "details": request.client.host
    }
    asyncio.create_task(log_api_action("api_get_user_info", log_data))

    return APIResponse(data=response_data)