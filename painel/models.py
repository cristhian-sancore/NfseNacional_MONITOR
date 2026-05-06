from sqlalchemy import Column, Integer, String, Text, DateTime, Float
from sqlalchemy.sql import func
from database import Base

class ErrorLog(Base):
    __tablename__ = "error_logs"

    id = Column(Integer, primary_key=True, index=True)
    entity_name = Column(String(100), index=True)
    error_category = Column(String(100), index=True)
    original_error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SystemSettings(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    evo_url = Column(String(200), default="")
    evo_token = Column(String(200), default="")
    evo_instance = Column(String(100), default="")
    evo_number = Column(String(50), default="")
    summary_interval_hours = Column(Float, default=12.0)
    last_summary_sent = Column(DateTime(timezone=True), nullable=True)

class AgentHeartbeat(Base):
    __tablename__ = "agent_heartbeats"

    id = Column(Integer, primary_key=True, index=True)
    entity_name = Column(String(100), unique=True, index=True)
    last_ping = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    is_offline = Column(Integer, default=0) # 0 = Online, 1 = Offline (para evitar múltiplos avisos)
