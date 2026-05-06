from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ErrorLogCreate(BaseModel):
    entity_name: str
    error_category: str
    original_error: str

class ErrorLogResponse(ErrorLogCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class SystemSettingsUpdate(BaseModel):
    evo_url: str
    evo_token: str
    evo_instance: str
    evo_number: str
    summary_interval_hours: float

class SystemSettingsResponse(SystemSettingsUpdate):
    id: int

    class Config:
        from_attributes = True

class AgentHeartbeatCreate(BaseModel):
    entity_name: str
