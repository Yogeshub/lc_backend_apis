from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str
    full_name: Optional[str] = None
    role: str = Field(default="read")  # new: "read" | "write" | "admin"
    is_admin: bool = Field(default=False)

class LC(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lc_no: str = Field(index=True)
    extracted_json: Optional[str] = None
    status: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Attachment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lc_id: Optional[int] = Field(default=None, foreign_key="lc.id")
    filename: str
    filepath: str
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

class UCPDocument(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: Optional[str] = None
    filepath: str
    active: bool = Field(default=False)
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

class ValidationResult(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lc_id: int = Field(foreign_key="lc.id")
    valid: bool
    summary: str
    raw: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
