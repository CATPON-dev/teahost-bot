import logging
import asyncio
import secrets
import time
import os
from fastapi import FastAPI, APIRouter, Depends, HTTPException, status, Header, Query, Path, Request
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, constr
from typing import Literal, List, Optional, Any
from datetime import datetime, date

from aiogram import Bot, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database as db
import server_config
from config_manager import config
from channel_logger import log_event
from api_manager import api_manager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SharkHost API",
    version="1.0.0",
    redoc_url=None
)

REQUEST_LIMIT = 20
TIME_WINDOW = 60
REQUESTS = {}

MAINTENANCE_MODE = False

@app.middleware("http")
async def combined_middleware(request: Request, call_next):
    ip = request.client.host
    now = time.time()
    
    timestamps = REQUESTS.get(ip, [])
    recent_timestamps = [t for t in timestamps if now - t < TIME_WINDOW]

    if len(recent_timestamps) >= REQUEST_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Flood."
        )
    
    recent_timestamps.append(now)
    REQUESTS[ip] = recent_timestamps

    if MAINTENANCE_MODE:
        path = request.url.path
        main_paths = ["/", "/index.html", "/profile", "/profile.html", "/servers", "/servers.html"]
        if path in main_paths:
            tech_path = os.path.join("static", "tech.html")
            return FileResponse(tech_path, media_type="text/html")

    response = await call_next(request)
    return response

def create_bot_instance():
    return Bot(
        token=config.BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI application startup...")
    await db.init_pool()
    logger.info("Database pool initialized for FastAPI.")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI application shutdown...")
    if db.pool:
        db.pool.close()
        await db.pool.wait_closed()
        logger.info("Database pool closed.")

class APIError(BaseModel):
    code: str
    message: str

class APIErrorResponse(BaseModel):
    success: bool = False
    error: APIError

class APIResponse(BaseModel):
    success: bool = True
    data: Optional[Any] = None

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    error_message = exc.detail
    error_code = "CLIENT_ERROR"
    if status.HTTP_500_INTERNAL_SERVER_ERROR <= exc.status_code:
        error_code = "SERVER_ERROR"
    elif exc.status_code == status.HTTP_404_NOT_FOUND:
        error_code = "NOT_FOUND"
    elif exc.status_code == status.HTTP_403_FORBIDDEN:
        error_code = "FORBIDDEN"
    elif exc.status_code == status.HTTP_409_CONFLICT:
        error_code = "CONFLICT"
    elif exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        error_code = "RATE_LIMIT_EXCEEDED"
    
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": {"code": error_code, "message": error_message}},
    )

class UserbotCreateRequest(BaseModel):
    server_code: constr(strip_whitespace=True, min_length=1)
    ub_type: Literal['hikka', 'heroku', 'fox', 'legacy']

class UserbotManageRequest(BaseModel):
    action: Literal['start', 'stop', 'restart']

class UserbotTransferRequest(BaseModel):
    new_owner_identifier: str

class UserbotExecRequest(BaseModel):
    ub_username: str
    command: str

async def verify_token(x_api_token: str = Header(...)):
    user_data = await db.get_user_by_api_token(x_api_token)
    if not user_data:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired API token.")
    user_id = user_data['tg_user_id']
    if not await db.has_user_accepted_agreement(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has not accepted the agreement.")
    if await db.is_user_banned(user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This user is banned.")
    return user_data

async def api_create_and_notify(tg_user_id: int, server_ip: str, webui_port: int):
    bot = create_bot_instance()
    try:
        login_url = f"http://{server_ip}:{webui_port}"
        builder = InlineKeyboardBuilder()
        builder.button(text="➡️ Войти в WEB-UI", url=login_url)
        text = f"✅ <b>Ваш юзербот, созданный через API, готов!</b>\n\nИспользуйте кнопку ниже для авторизации."
        await bot.send_message(tg_user_id, text, reply_markup=builder.as_markup(), disable_web_page_preview=True)
    finally:
        await bot.session.close()

async def api_delete_and_notify(tg_user_id: int, ub_username: str, server_ip: str, request_ip: str):
    bot = create_bot_instance()
    try:
        ub_data = await db.get_userbot_data(ub_username)
        ub_type = ub_data.get('ub_type', 'Userbot').capitalize() if ub_data else 'Userbot'
        
        server_details = server_config.get_servers().get(server_ip, {})
        server_code = server_details.get('code', 'Unknown')
        server_flag = server_details.get('flag', '🏳️')

        text = (
            f"🗑️ <b>Ваш юзербот {html.quote(ub_type)} был удален по API запросу.</b>\n\n"
            "<blockquote>"
            f"<b>Сервер:</b> {server_flag} {server_code}\n"
            f"<b>IP-адрес запроса:</b> <code>{request_ip}</code>"
            "</blockquote>"
        )
        
        await bot.send_message(tg_user_id, text)
    finally:
        await bot.session.close()

router = APIRouter(prefix="/api/v1")

@router.get("/users/{identifier}", response_model=APIResponse, tags=["Users"])
async def get_user_info(identifier: str = Path(...), current_user: dict = Depends(verify_token)):
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
    return APIResponse(data=response_data)

@router.get("/userbots/{ub_username}/logs", response_model=APIResponse, tags=["Userbots"])
async def get_my_userbot_logs(ub_username: str, lines: int = Query(200, ge=1, le=1000), current_user: dict = Depends(verify_token)):
    tg_user_id = current_user['tg_user_id']
    userbot_data = await db.get_userbot_data(ub_username)
    if not userbot_data or userbot_data.get('tg_user_id') != tg_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Userbot not found or permission denied.")
    
    logs_result = await api_manager.get_container_logs(ub_username, userbot_data['server_ip'])
    
    if not logs_result.get("success"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=logs_result.get("error", "Failed to fetch logs."))

    logs_text = logs_result.get("data", {}).get("logs", "")
    log_lines = logs_text.strip().split('\n')
    
    return APIResponse(data={
        "logs": log_lines[-lines:], 
        "total_lines": len(log_lines)
    })

@router.post("/userbots/create", response_model=APIResponse, tags=["Userbots"])
async def create_userbot(request_data: UserbotCreateRequest, current_user: dict = Depends(verify_token)):
    tg_user_id = current_user['tg_user_id']
    if await db.get_userbots_by_tg_id(tg_user_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You already have a userbot.")
    
    server_ip = next((ip for ip, d in server_config.get_servers().items() if d.get("code") == request_data.server_code), None)
    if not server_ip or not server_config.is_install_allowed(server_ip, tg_user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found or not available for installation.")
    
    ub_username = f"ub{tg_user_id}"
    webui_port = await db.generate_random_port()
    if not webui_port:
        raise HTTPException(status_code=status.HTTP_507_INSUFFICIENT_STORAGE, detail="No free ports available on the server.")

    creation_result = await api_manager.create_container(ub_username, webui_port, request_data.ub_type, server_ip)
    if not creation_result.get("success"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=creation_result.get("error", "Failed to create container."))

    await db.add_userbot_record(tg_user_id, ub_username, request_data.ub_type, server_ip, webui_port)
    await db.update_userbot_status(ub_username, "running")
    
    asyncio.create_task(api_create_and_notify(tg_user_id, server_ip, webui_port))
    
    return APIResponse(data={"ub_username": ub_username, "webui_port": webui_port, "message": "Userbot installation initiated."})

@router.delete("/userbots/{ub_username}", response_model=APIResponse, tags=["Userbots"])
async def delete_userbot(ub_username: str, request: Request, current_user: dict = Depends(verify_token)):
    tg_user_id = current_user['tg_user_id']
    userbot_data = await db.get_userbot_data(ub_username)
    if not userbot_data or userbot_data.get('tg_user_id') != tg_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Userbot not found or permission denied.")
    
    server_ip = userbot_data['server_ip']
    deletion_result = await api_manager.delete_container(ub_username, server_ip)
    if not deletion_result.get("success"):
        logger.warning(f"Container deletion failed for {ub_username} but proceeding with DB cleanup. Error: {deletion_result.get('error')}")

    await db.delete_userbot_record(ub_username)
    
    request_ip = request.client.host
    asyncio.create_task(api_delete_and_notify(tg_user_id, ub_username, server_ip, request_ip))
    return APIResponse(data={"message": "Userbot has been successfully deleted."})

@router.post("/userbots/{ub_username}/manage", response_model=APIResponse, tags=["Userbots"])
async def manage_userbot(ub_username: str, request_data: UserbotManageRequest, current_user: dict = Depends(verify_token)):
    tg_user_id = current_user['tg_user_id']
    userbot_data = await db.get_userbot_data(ub_username)
    if not userbot_data or userbot_data.get('tg_user_id') != tg_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Userbot not found or permission denied.")

    server_ip = userbot_data['server_ip']
    action = request_data.action
    result = {}

    if action == "start":
        result = await api_manager.start_container(ub_username, server_ip)
    elif action == "stop":
        result = await api_manager.stop_container(ub_username, server_ip)
    elif action == "restart":
        result = await api_manager.restart_container(ub_username, server_ip)
    
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result.get("error", "Action failed on the host server."))

    await asyncio.sleep(1.5)
    status_res = await api_manager.get_container_status(ub_username, server_ip)
    new_status = status_res.get("data", {}).get("status", "unknown") if status_res.get("success") else "error"
    await db.update_userbot_status(ub_username, new_status)

    return APIResponse(data={"new_status": new_status})

@router.post("/userbots/{ub_username}/transfer", response_model=APIResponse, tags=["Userbots"])
async def transfer_userbot(ub_username: str, request_data: UserbotTransferRequest, current_user: dict = Depends(verify_token)):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="This feature is temporarily disabled.")

@router.post("/userbots/exec", response_model=APIResponse, tags=["Userbots"])
async def exec_command(request_data: UserbotExecRequest, current_user: dict = Depends(verify_token)):
    tg_user_id = current_user['tg_user_id']
    ub_username = request_data.ub_username
    userbot_data = await db.get_userbot_data(ub_username)
    if not userbot_data or userbot_data.get('tg_user_id') != tg_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Userbot not found or permission denied.")
    
    server_ip = userbot_data['server_ip']
    result = await api_manager.exec_in_container(ub_username, request_data.command, server_ip)
    
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result.get("error", "Execution failed on the host server."))

    return APIResponse(data=result.get("data", {}).get("exec"))
    
@router.post("/token/regenerate", response_model=APIResponse, tags=["Users"])
async def regenerate_token(current_user: dict = Depends(verify_token)):
    user_id = current_user['tg_user_id']
    username = current_user.get('username') or f"user{user_id}"
    new_token = f"{username}:{user_id}:{secrets.token_urlsafe(32)}"
    if await db.regenerate_user_token(user_id, new_token):
        return APIResponse(data={"new_token": new_token})
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update token in the database.")

app.include_router(router)