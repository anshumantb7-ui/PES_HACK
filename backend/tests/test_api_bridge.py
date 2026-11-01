import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings
from backend.database import init_db, SessionLocal
from backend.models import RawSMS

client = TestClient(app)

AUTH_HEADER = {"Authorization": f"Bearer {settings.MAS_API_KEY}"}
API_KEY_HEADER = {"X-API-Key": settings.MAS_API_KEY}


@pytest.fixture(autouse=True)
def setup_test_records():
    """Ensure database has controlled test records for the bridge tests."""
    init_db()
    db = SessionLocal()
    try:
        # Clear existing
        db.query(RawSMS).delete()
        # Add sample records
        r1 = RawSMS(
            sender="+919986898914",
            raw_payload="{}",
            raw_body="FLOOD | TRAPPED | 12.93473,77.53482",
            status="parsed",
            confidence=1.0,
            parsed_data='{"type":"FLOOD","status":"TRAPPED","location":{"lat":12.93473,"lon":77.53482},"needs_review":false}',
        )
        r2 = RawSMS(
            sender="+919123456789",
            raw_payload="{}",
            raw_body="FIRE | INJURED | 13.08270,80.27070",
            status="parsed",
            confidence=0.85,
            parsed_data='{"type":"FIRE","status":"INJURED","location":{"lat":13.08270,"lon":80.27070},"needs_review":false}',
        )
        r3 = RawSMS(
            sender="+918888877777",
            raw_payload="{}",
            raw_body="Help me please near bridge",
            status="needs_review",
            confidence=0.2,
            parsed_data='{"type":null,"status":null,"location":null,"needs_review":true}',
            error_message="Could not parse coordinates",
        )
        db.add_all([r1, r2, r3])
        db.commit()
    finally:
        db.close()


def test_bridge_status_unauthorized():
    res = client.get("/api/bridge/status")
    assert res.status_code == 401


def test_bridge_status_authorized_bearer():
    res = client.get("/api/bridge/status", headers=AUTH_HEADER)
    assert res.status_code == 200
    data = res.json()
    assert data["bridge_status"] == "online"
    assert data["total_records"] == 3
    assert data["auth_configured"] is True


def test_bridge_status_authorized_api_key():
    res = client.get("/api/bridge/status", headers=API_KEY_HEADER)
    assert res.status_code == 200
    assert res.json()["bridge_status"] == "online"


def test_query_offline_all():
    res = client.post("/api/query-offline", json={}, headers=AUTH_HEADER)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["count"] == 3
    assert len(data["records"]) == 3


def test_query_offline_filter_by_type():
    res = client.post(
        "/api/query-offline",
        json={"emergency_type": "FLOOD"},
        headers=AUTH_HEADER,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["count"] == 1
    assert data["records"][0]["sender"] == "+919986898914"
    assert data["records"][0]["parsed_data"]["type"] == "FLOOD"


def test_query_offline_filter_by_needs_review():
    res = client.post(
        "/api/query-offline",
        json={"needs_review": True},
        headers=AUTH_HEADER,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["count"] == 1
    assert data["records"][0]["status"] == "needs_review"


def test_query_offline_empty_results():
    res = client.post(
        "/api/query-offline",
        json={"emergency_type": "COLLAPSE"},
        headers=AUTH_HEADER,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["count"] == 0
    assert "No matching offline records" in data["message"]


def test_list_records_get():
    res = client.get("/api/records?limit=2", headers=AUTH_HEADER)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["count"] == 2


def test_get_single_record():
    res = client.get("/api/records/1", headers=AUTH_HEADER)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "record" in data
    assert data["record"]["id"] == 1


def test_get_single_record_not_found():
    res = client.get("/api/records/9999", headers=AUTH_HEADER)
    assert res.status_code == 404

