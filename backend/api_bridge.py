import json
import logging
from datetime import datetime
from typing import Optional, Any
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc

from backend.config import settings
from backend.database import get_db, DB_KIND
from backend.models import RawSMS

logger = logging.getLogger("resq.api_bridge")

bridge_router = APIRouter(prefix="/api", tags=["Online MAS Bridge"])


# ──────────────────────────────────────────────────────────────
# Security: Authentication for Online MAS Orchestrator
# ──────────────────────────────────────────────────────────────
def verify_bridge_auth(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> bool:
    """Verifies that the request from the online agent framework includes

    a valid bearer token or X-API-Key header.
    """
    token: Optional[str] = None
    if x_api_key:
        token = x_api_key.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    valid_keys = {settings.MAS_API_KEY, settings.SECRET_TOKEN}
    if not token or token not in valid_keys:
        logger.warning(f"Unauthorized bridge request. Provided token: '{token}'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "success": False,
                "error": "Unauthorized: Missing or invalid API key for offline bridge",
                "message": "Please provide 'Authorization: Bearer <API_KEY>' or 'X-API-Key: <API_KEY>'",
            },
        )
    return True


# ──────────────────────────────────────────────────────────────
# Pydantic Schemas for Structured Agent Queries
# ──────────────────────────────────────────────────────────────
class OfflineQueryRequest(BaseModel):
    """Structured query filter payload sent by the Online MAS Orchestrator."""
    emergency_type: Optional[str] = Field(
        default=None,
        description="Filter by emergency type (FLOOD, FIRE, MEDICAL, COLLAPSE, OTHER)",
    )
    victim_status: Optional[str] = Field(
        default=None,
        description="Filter by victim status (TRAPPED, INJURED, UNCONSCIOUS, NEED_EVACUATION, SAFE_BUT_NEED_HELP)",
    )
    db_status: Optional[str] = Field(
        default=None,
        description="Filter by database processing status ('parsed', 'needs_review', 'received', 'duplicate')",
    )
    sender: Optional[str] = Field(
        default=None,
        description="Filter by sender phone number or pattern",
    )
    min_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Filter records with confidence score >= min_confidence",
    )
    needs_review: Optional[bool] = Field(
        default=None,
        description="Filter records that specifically need human operator review",
    )
    since: Optional[str] = Field(
        default=None,
        description="Filter records received at or after this ISO datetime string (e.g. 2026-11-01T00:00:00)",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of records to return (1-200)",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Pagination offset",
    )
    order: str = Field(
        default="desc",
        description="Sort order by received_at ('desc' or 'asc')",
    )


class RecordItem(BaseModel):
    id: int
    provider_message_id: Optional[str] = None
    sender: str
    raw_body: str
    received_at: Optional[str] = None
    status: str
    confidence: Optional[float] = None
    parsed_data: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None


class OfflineQueryResponse(BaseModel):
    """Structured JSON response returned across the secure tunnel to the online agent."""
    success: bool
    count: int
    total: int
    query_params: dict[str, Any]
    records: list[RecordItem]
    message: Optional[str] = None
    error: Optional[str] = None


class BridgeStatusResponse(BaseModel):
    bridge_status: str
    database: str
    total_records: int
    latest_received_at: Optional[str] = None
    auth_configured: bool


# ──────────────────────────────────────────────────────────────
# Helper: Format Database Record to Dictionary
# ──────────────────────────────────────────────────────────────
def format_record(r: RawSMS) -> RecordItem:
    parsed_dict: Optional[dict[str, Any]] = None
    if r.parsed_data:
        try:
            parsed_dict = json.loads(r.parsed_data)
        except Exception:
            parsed_dict = {"raw": r.parsed_data}

    return RecordItem(
        id=r.id,
        provider_message_id=r.provider_message_id,
        sender=r.sender,
        raw_body=r.raw_body,
        received_at=r.received_at.isoformat() if r.received_at else None,
        status=r.status,
        confidence=r.confidence,
        parsed_data=parsed_dict,
        error_message=r.error_message,
    )


# ──────────────────────────────────────────────────────────────
# Endpoint 1: POST /api/query-offline (Primary Orchestrator Tool)
# ──────────────────────────────────────────────────────────────
@app_post := bridge_router.post(
    "/query-offline",
    response_model=OfflineQueryResponse,
    summary="Query offline disaster records using structured agent filters",
)
def query_offline(
    query_body: OfflineQueryRequest,
    _auth: bool = Depends(verify_bridge_auth),
    db: Session = Depends(get_db),
):
    """Executes a structured query against the offline SQLite/PostgreSQL database

    and returns a clean JSON payload for the online MAS Orchestrator.
    """
    try:
        q = db.query(RawSMS)

        # 1. Filter by DB status
        if query_body.db_status:
            q = q.filter(RawSMS.status == query_body.db_status.lower().strip())

        # 2. Filter by sender phone
        if query_body.sender:
            q = q.filter(RawSMS.sender.contains(query_body.sender.strip()))

        # 3. Filter by min confidence
        if query_body.min_confidence is not None:
            q = q.filter(RawSMS.confidence >= query_body.min_confidence)

        # 4. Filter by datetime 'since'
        if query_body.since:
            try:
                # Accept ISO string or YYYY-MM-DD
                clean_since = query_body.since.replace("Z", "+00:00")
                since_dt = datetime.fromisoformat(clean_since).replace(tzinfo=None)
                q = q.filter(RawSMS.received_at >= since_dt)
            except Exception as e:
                logger.warning(f"Invalid 'since' datetime filter '{query_body.since}': {e}")
                return OfflineQueryResponse(
                    success=False,
                    count=0,
                    total=0,
                    query_params=query_body.model_dump(),
                    records=[],
                    error=f"Invalid 'since' datetime format: {query_body.since}. Use ISO format (YYYY-MM-DDTHH:MM:SS)",
                )

        # Sorting
        if query_body.order.lower() == "asc":
            q = q.order_by(asc(RawSMS.id))
        else:
            q = q.order_by(desc(RawSMS.id))

        all_matches = q.all()
        total_matched = len(all_matches)

        # In-memory filtering for JSON parsed fields (emergency_type, victim_status, needs_review)
        filtered_items: list[RecordItem] = []
        for r in all_matches:
            item = format_record(r)
            pd = item.parsed_data or {}

            # Filter emergency_type
            if query_body.emergency_type:
                t = (pd.get("type") or "").upper()
                if t != query_body.emergency_type.upper().strip():
                    continue

            # Filter victim_status
            if query_body.victim_status:
                s = (pd.get("status") or "").upper()
                if s != query_body.victim_status.upper().strip():
                    continue

            # Filter needs_review
            if query_body.needs_review is not None:
                nr = pd.get("needs_review", False)
                if nr != query_body.needs_review:
                    continue

            filtered_items.append(item)

        # Apply pagination after in-memory filters
        paged_records = filtered_items[query_body.offset : query_body.offset + query_body.limit]
        final_count = len(paged_records)

        msg = None
        if final_count == 0:
            msg = "No matching offline records found for the given criteria."

        return OfflineQueryResponse(
            success=True,
            count=final_count,
            total=len(filtered_items),
            query_params=query_body.model_dump(),
            records=paged_records,
            message=msg,
            error=None,
        )

    except Exception as exc:
        logger.error(f"Error executing offline query: {exc}", exc_info=True)
        return OfflineQueryResponse(
            success=False,
            count=0,
            total=0,
            query_params=query_body.model_dump(),
            records=[],
            error=f"Internal database query error: {str(exc)}",
        )


# ──────────────────────────────────────────────────────────────
# Endpoint 2: GET /api/records (Simple Query via URL Params)
# ──────────────────────────────────────────────────────────────
@bridge_router.get(
    "/records",
    response_model=OfflineQueryResponse,
    summary="List offline records with optional URL query filters",
)
def list_records(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    sender: Optional[str] = Query(default=None),
    type_filter: Optional[str] = Query(default=None, alias="type"),
    since: Optional[str] = Query(default=None),
    _auth: bool = Depends(verify_bridge_auth),
    db: Session = Depends(get_db),
):
    """Simple GET interface for retrieving records from the offline database."""
    query_req = OfflineQueryRequest(
        emergency_type=type_filter,
        db_status=status_filter,
        sender=sender,
        since=since,
        limit=limit,
        offset=offset,
    )
    return query_offline(query_body=query_req, _auth=_auth, db=db)


# ──────────────────────────────────────────────────────────────
# Endpoint 3: GET /api/records/{record_id} (Fetch Single Record)
# ──────────────────────────────────────────────────────────────
@bridge_router.get(
    "/records/{record_id}",
    summary="Retrieve single offline record by ID",
)
def get_record_by_id(
    record_id: int,
    _auth: bool = Depends(verify_bridge_auth),
    db: Session = Depends(get_db),
):
    """Retrieve full details of a specific record by primary key."""
    record = db.query(RawSMS).filter(RawSMS.id == record_id).first()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "success": False,
                "error": f"Record #{record_id} not found in offline database",
            },
        )
    return {
        "success": True,
        "record": format_record(record).model_dump(),
    }


# ──────────────────────────────────────────────────────────────
# Endpoint 4: GET /api/bridge/status (Health / Ping for Tunnel)
# ──────────────────────────────────────────────────────────────
@bridge_router.get(
    "/bridge/status",
    response_model=BridgeStatusResponse,
    summary="Health check for the offline API bridge and secure tunnel",
)
def bridge_status(
    _auth: bool = Depends(verify_bridge_auth),
    db: Session = Depends(get_db),
):
    """Quick ping endpoint for the online Orchestrator to confirm the tunnel

    and offline database are actively reachable.
    """
    total = db.query(RawSMS).count()
    latest = db.query(RawSMS).order_by(desc(RawSMS.id)).first()
    latest_time = latest.received_at.isoformat() if latest and latest.received_at else None

    return BridgeStatusResponse(
        bridge_status="online",
        database=DB_KIND,
        total_records=total,
        latest_received_at=latest_time,
        auth_configured=bool(settings.MAS_API_KEY),
    )

