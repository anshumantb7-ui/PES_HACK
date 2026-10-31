from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator, model_validator

class EmergencyType(str, Enum):
    FLOOD = "FLOOD"
    FIRE = "FIRE"
    MEDICAL = "MEDICAL"
    COLLAPSE = "COLLAPSE"
    OTHER = "OTHER"

class VictimStatus(str, Enum):
    TRAPPED = "TRAPPED"
    INJURED = "INJURED"
    UNCONSCIOUS = "UNCONSCIOUS"
    NEED_EVACUATION = "NEED_EVACUATION"
    SAFE_BUT_NEED_HELP = "SAFE_BUT_NEED_HELP"

class Coordinates(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude between -90 and 90")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude between -180 and 180")

class ParsedSMS(BaseModel):
    type: Optional[EmergencyType] = None
    status: Optional[VictimStatus] = None
    location: Optional[Coordinates] = None
    location_unknown: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_review: bool = False
    parse_method: str = "regex"  # "regex", "gemini", "unparsed"
    raw_text: str = ""
    error: Optional[str] = None

class SMSForwarderPayload(BaseModel):
    """Flexible payload adapter accepting various Android SMS forwarder app formats.

    Supports fields: from/sender/phone, message/text/body/content, id/message_id.
    """
    sender: str = Field(default="UNKNOWN_SENDER")
    message: str = Field(default="")
    message_id: Optional[str] = None
    timestamp: Optional[Any] = None
    raw_extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        
        # Resolve sender / phone
        sender = (
            data.get("sender")
            or data.get("from")
            or data.get("phone")
            or data.get("address")
            or data.get("originatingAddress")
            or "UNKNOWN_SENDER"
        )
        
        # Resolve message body / text
        message = (
            data.get("message")
            or data.get("text")
            or data.get("body")
            or data.get("content")
            or data.get("msg")
            or ""
        )
        
        # Resolve message ID
        message_id = (
            data.get("id")
            or data.get("message_id")
            or data.get("sms_id")
            or data.get("_id")
        )

        return {
            "sender": str(sender).strip(),
            "message": str(message).strip(),
            "message_id": str(message_id).strip() if message_id else None,
            "timestamp": data.get("timestamp") or data.get("date"),
            "raw_extra": data,
        }

class IngestResponse(BaseModel):
    status: str
    sms_id: Optional[int] = None
    message: str

class HealthResponse(BaseModel):
    status: str
    service: str
    time: str
    database: str

