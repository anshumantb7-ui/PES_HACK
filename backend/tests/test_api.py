import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings
from backend.database import init_db, engine
from backend.models import RawSMS
from sqlalchemy.orm import sessionmaker

@pytest.fixture(autouse=True)
def clean_database():
    """Wipe the raw_sms table before each test to avoid cross-test dedup collisions."""
    init_db()
    Session = sessionmaker(bind=engine)
    db = Session()
    db.query(RawSMS).delete()
    db.commit()
    db.close()

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "resq-backend"
    assert "database" in data
    assert "time" in data

def test_sms_unauthorized():
    response = client.post(
        "/sms",
        json={"from": "+919876543210", "message": "FLOOD | TRAPPED | 12.9716,77.5946"},
        headers={"X-RESQ-Secret": "wrong-secret"},
    )
    assert response.status_code == 401

def test_sms_ingest_and_deduplicate():
    secret_headers = {"X-RESQ-Secret": settings.SECRET_TOKEN}
    payload = {
        "from": "+919999988888",
        "message": "FIRE | INJURED | 12.97160,77.59460",
        "id": "msg-unique-001",
    }
    
    # 1. First ingestion -> Should succeed
    resp1 = client.post("/sms", json=payload, headers=secret_headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["status"] == "ok"
    assert data1["sms_id"] is not None

    # 2. Duplicate with same provider ID -> Should be flagged as duplicate
    resp2 = client.post("/sms", json=payload, headers=secret_headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "duplicate"
    assert data2["sms_id"] == data1["sms_id"]

    # 3. Duplicate without provider ID but within time window
    payload_no_id = {
        "from": "+918888877777",
        "message": "COLLAPSE | TRAPPED | 12.97160,77.59460",
    }
    resp3 = client.post("/sms", json=payload_no_id, headers=secret_headers)
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3["status"] == "ok"

    # Same sender + message right away
    resp4 = client.post("/sms", json=payload_no_id, headers=secret_headers)
    assert resp4.status_code == 200
    data4 = resp4.json()
    assert data4["status"] == "duplicate"
    assert data4["sms_id"] == data3["sms_id"]

def test_sms_list_endpoint():
    response = client.get("/sms")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
