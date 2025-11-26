from pydantic import BaseModel
from typing import Optional, List

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    username: Optional[str] = None

class UserCreate(BaseModel):
    username: str
    password: str
    role: str
    full_name: Optional[str] = None

class UserRead(BaseModel):
    id: int
    username: str
    full_name: Optional[str]
    is_admin: bool
    role: Optional[str]


class LCCreate(BaseModel):
    lc_no: str

class LCRead(BaseModel):
    id: int
    lc_no: str
    status: Optional[str]
    extracted_json: Optional[str]
