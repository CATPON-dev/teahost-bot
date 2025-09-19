import asyncio
from fastapi import APIRouter, Depends, Query, Request, Header
from fastapi import HTTPException, status
from typing import Literal
import database as db
import server_config
from api_manager import api_manager
from api.dependencies import verify_token
from api.models import APIResponse
from api.utils import api_create_and_notify, api_delete_and_notify, log_api_action

router = APIRouter(prefix="/userbots", tags=["Userbots"])


@router.get("/{ub_username}/logs", response_model=APIResponse)
async def get_my_userbot_logs(
    request: Request,
    ub_username: str,
    lines: int = Query(200, ge=1, le=1000),
    current_user: dict = Depends(verify_token)
):
    tg_user_id = current_user['tg_user_id']
    userbot_data = await db.get_userbot_data(ub_username)
    if not userbot_data or userbot_data.get('tg_user_id') != tg_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Userbot not found or permission denied.")

    logs_result = await api_manager.get_container_logs(ub_username, userbot_data['server_ip'])

    if not logs_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=logs_result.get(
                "error",
                "Failed to fetch logs."))

    server_details = server_config.get_servers().get(
        userbot_data['server_ip'], {})

    logs_text = logs_result.get("data", {}).get("logs", "")
    log_lines = logs_text.strip().split('\n')

    return APIResponse(
        data={"logs": log_lines[-lines:], "total_lines": len(log_lines)})


@router.post("/create", response_model=APIResponse)
async def create_userbot(
    current_user: dict = Depends(verify_token),
    server_code: str = Header(..., alias="Server-Code"),
    ub_type: Literal['hikka', 'heroku', 'fox', 'legacy'] = Header(..., alias="Ub-Type")
):
    tg_user_id = current_user['tg_user_id']
    if await db.get_userbots_by_tg_id(tg_user_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a userbot.")

    server_ip = next((ip for ip, d in server_config.get_servers(
    ).items() if d.get("code") == server_code), None)
    if not server_ip or not await server_config.is_install_allowed(server_ip, tg_user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found or not available for installation.")

    ub_username = f"ub{tg_user_id}"
    webui_port = await db.generate_random_port()
    if not webui_port:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="No free ports available on the server.")

    creation_result = await api_manager.create_container(ub_username, webui_port, ub_type, server_ip)
    if not creation_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=creation_result.get(
                "error",
                "Failed to create container."))

    await db.add_userbot_record(tg_user_id, ub_username, ub_type, server_ip, webui_port)
    await db.update_userbot_status(ub_username, "running")

    asyncio.create_task(
        log_api_action(
            "installation_via_api", {
                "user_data": {
                    "id": tg_user_id, "full_name": current_user.get(
                        'full_name', str(tg_user_id))}, "ub_info": {
                    "name": ub_username, "type": ub_type}, "server_info": {
                            "ip": server_ip, "code": server_config.get_servers().get(
                                server_ip, {}).get(
                                    "code", "N/A")}}))

    asyncio.create_task(
        api_create_and_notify(
            tg_user_id,
            server_ip,
            webui_port))

    return APIResponse(
        data={
            "ub_username": ub_username,
            "webui_port": webui_port,
            "message": "Userbot installation initiated."})


@router.delete("/{ub_username}", response_model=APIResponse)
async def delete_userbot(request: Request, ub_username: str, current_user: dict = Depends(verify_token)):
    tg_user_id = current_user['tg_user_id']
    userbot_data = await db.get_userbot_data(ub_username)
    if not userbot_data or userbot_data.get('tg_user_id') != tg_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Userbot not found or permission denied.")

    server_ip = userbot_data['server_ip']
    deletion_result = await api_manager.delete_container(ub_username, server_ip)
    if not deletion_result.get("success"):
        logging.warning(
            f"Container deletion failed for {ub_username} but proceeding with DB cleanup. Error: {deletion_result.get('error')}")

    await db.delete_userbot_record(ub_username)

    asyncio.create_task(
        log_api_action(
            "api_delete_userbot", {
                "user_data": {
                    "id": tg_user_id, "full_name": current_user.get('full_name')}, "ub_info": {
                    "name": ub_username}, "server_info": {
                        "ip": server_ip, "code": server_config.get_servers().get(
                            server_ip, {}).get("code")}, "details": request.client.host}))

    asyncio.create_task(
        api_delete_and_notify(
            tg_user_id,
            ub_username,
            server_ip,
            request.client.host))
    return APIResponse(
        data={"message": "Userbot has been successfully deleted."})


@router.post("/{ub_username}/manage", response_model=APIResponse)
async def manage_userbot(
    request: Request,
    ub_username: str,
    current_user: dict = Depends(verify_token),
    action: Literal['start', 'stop', 'restart'] = Header(..., alias="Action")
):
    tg_user_id = current_user['tg_user_id']
    userbot_data = await db.get_userbot_data(ub_username)
    if not userbot_data or userbot_data.get('tg_user_id') != tg_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Userbot not found or permission denied.")

    server_ip = userbot_data['server_ip']
    result = {}

    if action == "start":
        result = await api_manager.start_container(ub_username, server_ip)
    elif action == "stop":
        result = await api_manager.stop_container(ub_username, server_ip)
    elif action == "restart":
        result = await api_manager.restart_container(ub_username, server_ip)

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get(
                "error",
                "Action failed on the host server."))

    await asyncio.sleep(1.5)
    status_res = await api_manager.get_container_status(ub_username, server_ip)
    new_status = status_res.get(
        "data",
        {}).get(
        "status",
        "unknown") if status_res.get("success") else "error"
    await db.update_userbot_status(ub_username, new_status)

    return APIResponse(data={"new_status": new_status})


@router.post("/exec", response_model=APIResponse)
async def exec_command(
    request: Request,
    current_user: dict = Depends(verify_token),
    ub_username: str = Header(..., alias="Ub-Username"),
    command: str = Header(..., alias="Command")
):
    tg_user_id = current_user['tg_user_id']
    userbot_data = await db.get_userbot_data(ub_username)
    if not userbot_data or userbot_data.get('tg_user_id') != tg_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Userbot not found or permission denied.")

    server_ip = userbot_data['server_ip']
    result = await api_manager.exec_in_container(ub_username, command, server_ip)

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get(
                "error",
                "Execution failed on the host server."))

    return APIResponse(data=result.get("data", {}).get("exec"))
