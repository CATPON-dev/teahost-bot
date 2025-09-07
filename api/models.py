from pydantic import BaseModel
from typing import Optional, Any

class APIError(BaseModel):
    code: str
    message: str

class APIErrorResponse(BaseModel):
    success: bool = False
    error: APIError

class APIResponse(BaseModel):
    success: bool = True
    data: Optional[Any] = None