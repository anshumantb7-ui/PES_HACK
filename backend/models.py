from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float
from sqlalchemy.sql import func
from backend.database import Base

class RawSMS(Base):
    __tablename__ = "raw_sms"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    provider_message_id = Column(String(128), index=True, nullable=True)
    sender = Column(String(64), index=True, nullable=False)
    raw_payload = Column(Text, nullable=False)
    raw_body = Column(Text, nullable=False)
    # Store as naive UTC (SQLite has no timezone column support).
    # server_default=func.now() keeps inserts in sync even without a Python default.
    received_at = Column(DateTime, server_default=func.now(), default=datetime.utcnow, nullable=False)
    status = Column(String(32), default="received", nullable=False)  # received, parsed, needs_review, duplicate
    dedup_hash = Column(String(64), index=True, nullable=True)
    confidence = Column(Float, nullable=True)
    parsed_data = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "provider_message_id": self.provider_message_id,
            "sender": self.sender,
            "raw_body": self.raw_body,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "status": self.status,
            "confidence": self.confidence,
            "parsed_data": self.parsed_data,
            "error_message": self.error_message,
        }

