import sys
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    BackgroundTasks,
    Depends,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db, init_db, DB_KIND
from backend.models import RawSMS
from backend.schemas import (
    SMSForwarderPayload,
    IngestResponse,
    HealthResponse,
)
from backend.parser import parse_sms_message

# ──────────────────────────────────────────────────────────────
# Logging — must be configured BEFORE lifespan or any function
# that calls logger.*
# ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("resq.backend")


# ──────────────────────────────────────────────────────────────
# App lifespan (replaces deprecated on_event("startup"))
# ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info(f"RESQ backend initialized with {DB_KIND} database.")
    yield
    # (shutdown logic can go here later)


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Emergency SOS SMS ingestion and multi-agent coordination gateway",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins so Phone B on the hotspot can reach the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────
# Online MAS Orchestrator API Bridge Router
# Exposes POST /api/query-offline, GET /api/records, GET /api/bridge/status
# ──────────────────────────────────────────────────────────────
from backend.api_bridge import bridge_router
app.include_router(bridge_router)


# ──────────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        service="resq-backend",
        time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        database=DB_KIND,
    )


# ──────────────────────────────────────────────────────────────
# Auth helper
# ──────────────────────────────────────────────────────────────
def verify_auth_header(
    x_resq_secret: Optional[str] = Header(None, alias="X-RESQ-Secret"),
    authorization: Optional[str] = Header(None),
) -> bool:
    """Accepts 'X-RESQ-Secret: <token>' or 'Authorization: Bearer <token>'."""
    token: Optional[str] = None
    if x_resq_secret:
        token = x_resq_secret.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if not token or token != settings.SECRET_TOKEN:
        logger.warning(f"Unauthorized /sms attempt. Token: '{token}'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing authentication secret",
        )
    return True


# ──────────────────────────────────────────────────────────────
# Deduplication helper
# ──────────────────────────────────────────────────────────────
def compute_dedup_hash(sender: str, body: str) -> str:
    normalized = f"{sender.strip()}:{body.strip()}".lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────
# Background parse task
# ──────────────────────────────────────────────────────────────
def process_sms_async(sms_id: int) -> None:
    """Parses the raw SMS body and updates the DB record.

    Runs in a FastAPI BackgroundTask thread after the HTTP response is sent.
    Uses its own DB session — BackgroundTasks run outside the request context.
    """
    from backend.database import SessionLocal  # local import avoids circular ref

    db = SessionLocal()
    try:
        sms_record = db.query(RawSMS).filter(RawSMS.id == sms_id).first()
        if not sms_record:
            logger.warning(f"process_sms_async: SMS #{sms_id} not found in DB.")
            return

        parsed = parse_sms_message(sms_record.raw_body)
        sms_record.confidence = parsed.confidence
        sms_record.parsed_data = parsed.model_dump_json()

        if parsed.needs_review:
            sms_record.status = "needs_review"
            sms_record.error_message = parsed.error or "Low confidence / malformed message"
        else:
            sms_record.status = "parsed"
            sms_record.error_message = None

        db.commit()

        # ASCII-safe terminal banner (avoids cp1252 UnicodeEncodeError on Windows)
        border = "=" * 70
        loc_str = (
            f"({parsed.location.lat:.5f}, {parsed.location.lon:.5f})"
            if parsed.location
            else ("LOC:UNKNOWN" if parsed.location_unknown else "None")
        )
        print(f"\n{border}", flush=True)
        print(f"[RESQ GATEWAY] SMS #{sms_record.id} INGESTED & PROCESSED")
        print(f"  Sender    : {sms_record.sender}")
        print(f"  Raw Body  : {sms_record.raw_body}")
        print(f"  Type      : {parsed.type.value if parsed.type else 'UNKNOWN'}")
        print(f"  Status    : {parsed.status.value if parsed.status else 'UNKNOWN'}")
        print(f"  Location  : {loc_str}")
        print(f"  Confidence: {parsed.confidence:.2f}  [{parsed.parse_method}]")
        print(f"  DB Status : {sms_record.status.upper()}")
        print(f"{border}\n", flush=True)

    except Exception as exc:
        logger.error(
            f"Background parse error for SMS #{sms_id}: {exc}", exc_info=True
        )
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────
# SMS ingestion endpoint
# ──────────────────────────────────────────────────────────────
@app.post("/sms", response_model=IngestResponse)
def ingest_sms(
    payload: SMSForwarderPayload,
    background_tasks: BackgroundTasks,
    _auth: bool = Depends(verify_auth_header),
    db: Session = Depends(get_db),
):
    """Ingest SMS from Phone B forwarder app:

    1. Authenticate via secret header
    2. Store raw payload in DB immediately (before any parsing)
    3. Deduplicate (provider message-id; or sender+body within time window)
    4. Return 200 instantly
    5. Parse in a background task
    """
    sender = payload.sender
    body = payload.message
    message_id = payload.message_id
    dedup_hash = compute_dedup_hash(sender, body)
    raw_payload_json = json.dumps(payload.raw_extra)

    # ── Dedup check 1: provider message ID ──
    if message_id:
        existing = (
            db.query(RawSMS)
            .filter(RawSMS.provider_message_id == message_id)
            .first()
        )
        if existing:
            logger.info(f"Duplicate (provider ID {message_id}) -> SMS #{existing.id}")
            return IngestResponse(
                status="duplicate",
                sms_id=existing.id,
                message="Duplicate SMS ignored (same provider message ID)",
            )

    # ── Dedup check 2: same sender + body within window ──
    # Use datetime.utcnow() (naive UTC) to match how SQLite stores the received_at column.
    # Both sides are naive UTC so the comparison is safe and correct.
    cutoff_time = datetime.utcnow() - timedelta(seconds=settings.DEDUP_WINDOW_SECONDS)
    existing_dup = (
        db.query(RawSMS)
        .filter(
            RawSMS.sender == sender,
            RawSMS.dedup_hash == dedup_hash,
            RawSMS.received_at >= cutoff_time,
        )
        .first()
    )
    if existing_dup:
        logger.info(
            f"Duplicate (sender {sender}, within {settings.DEDUP_WINDOW_SECONDS}s) "
            f"-> SMS #{existing_dup.id}"
        )
        return IngestResponse(
            status="duplicate",
            sms_id=existing_dup.id,
            message="Duplicate SMS ignored (received within deduplication window)",
        )

    # ── Store raw record BEFORE parsing ──
    raw_record = RawSMS(
        provider_message_id=message_id,
        sender=sender,
        raw_payload=raw_payload_json,
        raw_body=body,
        status="received",
        dedup_hash=dedup_hash,
    )
    db.add(raw_record)
    db.commit()
    db.refresh(raw_record)
    sms_id = raw_record.id

    logger.info(f"SMS #{sms_id} stored (sender={sender}). Queuing parser.")

    # ── Dispatch background parser ──
    background_tasks.add_task(process_sms_async, sms_id)

    return IngestResponse(
        status="ok",
        sms_id=sms_id,
        message="SMS received and queued for processing",
    )


# ──────────────────────────────────────────────────────────────
# SMS list (dashboard / debug)
# ──────────────────────────────────────────────────────────────
@app.get("/sms")
def list_sms(limit: int = 20, db: Session = Depends(get_db)):
    """Return the most-recent ingested SMS records."""
    records = (
        db.query(RawSMS)
        .order_by(RawSMS.id.desc())
        .limit(min(limit, 200))
        .all()
    )
    return [r.to_dict() for r in records]


# ──────────────────────────────────────────────────────────────
# Test-fire endpoint (no secret required — for Swagger / curl)
# ──────────────────────────────────────────────────────────────
@app.post("/sms/test", response_model=IngestResponse)
def test_sms(
    sender: str = "+919876543210",
    message: str = "FLOOD | TRAPPED | 12.97160,77.59460",
    background_tasks: BackgroundTasks = BackgroundTasks(),  # noqa: B008
    db: Session = Depends(get_db),
):
    """Fire a test SMS without needing the auth header. Only for dev/demo use."""
    payload = SMSForwarderPayload(sender=sender, message=message)
    return ingest_sms(
        payload=payload,
        background_tasks=background_tasks,
        _auth=True,
        db=db,
    )
