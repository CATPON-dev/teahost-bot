import logging
import time
import os
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi import APIRouter
import database as db

from api.models import APIErrorResponse
from api.routers import users, userbots, auth, servers

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SharkHost API",
    version="1.0.0",
    redoc_url=None,
    responses={
        403: {"model": APIErrorResponse},
        404: {"model": APIErrorResponse},
        409: {"model": APIErrorResponse},
        429: {"model": APIErrorResponse},
        500: {"model": APIErrorResponse},
    }
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
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "success": False,
                "error": {
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": "Too many requests."}})

    recent_timestamps.append(now)
    REQUESTS[ip] = recent_timestamps

    if MAINTENANCE_MODE:
        path = request.url.path
        main_paths = [
            "/",
            "/index.html",
            "/profile",
            "/profile.html",
            "/servers",
            "/servers.html"]
        if path in main_paths:
            tech_path = os.path.join("static", "tech.html")
            return FileResponse(tech_path, media_type="text/html")

    response = await call_next(request)
    return response


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


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
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
        content={
            "success": False,
            "error": {
                "code": error_code,
                "message": exc.detail}},
    )

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(users.router)
api_v1_router.include_router(userbots.router)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(servers.router)

app.include_router(api_v1_router)
