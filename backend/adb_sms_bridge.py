import os
import re
import sys
import time
import subprocess
import requests
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Paths & Settings
BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_ADB = BASE_DIR / "tools" / "platform-tools" / "adb.exe"
ADB_PATH = str(LOCAL_ADB) if LOCAL_ADB.exists() else "adb"

BACKEND_URL = os.getenv("RESQ_BACKEND_URL", "http://127.0.0.1:8000/sms")
SECRET_TOKEN = os.getenv("RESQ_SECRET_TOKEN", "resq-secret-key-2026")
POLL_INTERVAL = float(os.getenv("ADB_POLL_INTERVAL", "2.0"))


def run_adb_command(args: list[str]) -> subprocess.CompletedProcess:
    """Executes an ADB command and returns output."""
    cmd = [ADB_PATH] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def wait_for_device():
    """Waits until an authorized Android device is plugged in."""
    print("======================================================================")
    print("🔌 [RESQ ADB BRIDGE] Waiting for Phone B via USB...")
    print("======================================================================")
    while True:
        res = run_adb_command(["devices"])
        lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
        # Skip header 'List of devices attached'
        devices = [l for l in lines[1:] if not l.startswith("*")]

        if not devices:
            print("  ⏳ No phone detected. Please connect Phone B via USB...", end="\r")
            time.sleep(2)
            continue

        device_line = devices[0]
        serial, status = device_line.split()[0], device_line.split()[1]

        if status == "unauthorized":
            print(f"\n[!] Phone B ({serial}) is UNAUTHORIZED!")
            print("   -> Check Phone B's screen and tap 'Always allow from this computer' -> OK.")
            time.sleep(3)
            continue
        elif status == "device":
            print(f"\n[OK] Phone B connected & authorized! (Serial: {serial})\n")
            return serial
        else:
            print(f"\n[!] Phone B in state: {status}. Waiting...")
            time.sleep(3)


def parse_content_query_rows(output: str) -> list[dict]:
    """Parses Android 'content query' output rows into dictionary records."""
    records = []
    # Android output format:
    # Row: 0 _id=14, address=+911234567890, body=FLOOD | TRAPPED | ..., date=1730000000000
    row_pattern = re.compile(
        r"Row:\s*\d+\s+_id=(?P<id>[^,]+),\s*address=(?P<address>[^,]+),\s*body=(?P<body>.*?),\s*date=(?P<date>\d+)",
        re.DOTALL,
    )

    for match in row_pattern.finditer(output):
        records.append({
            "id": match.group("id").strip(),
            "address": match.group("address").strip(),
            "body": match.group("body").strip(),
            "date": match.group("date").strip(),
        })

    # If regex missed due to newline in body, try line-by-line fallback
    if not records and "Row:" in output:
        for line in output.split("Row:"):
            line = line.strip()
            if not line:
                continue
            id_m = re.search(r"_id=([^,]+)", line)
            addr_m = re.search(r"address=([^,]+)", line)
            body_m = re.search(r"body=(.*?)(?:,\s*date=|$)", line, re.DOTALL)
            date_m = re.search(r"date=(\d+)", line)
            if id_m and addr_m and body_m:
                records.append({
                    "id": id_m.group(1).strip(),
                    "address": addr_m.group(1).strip(),
                    "body": body_m.group(1).strip(),
                    "date": date_m.group(1).strip() if date_m else str(int(time.time() * 1000)),
                })

    return records


def fetch_latest_sms_from_phone(limit: int = 5) -> list[dict]:
    """Queries Phone B's SMS inbox via ADB content provider."""
    # Projection must be colon-separated for Android content query
    # Sort order must be quoted or formatted as 'date DESC'
    args = [
        "shell",
        "content",
        "query",
        "--uri",
        "content://sms/inbox",
        "--projection",
        "_id:address:body:date",
        "--sort",
        "'date DESC'",
    ]
    res = run_adb_command(args)
    if res.returncode != 0:
        if "Permission Denial" in res.stderr:
            print("[ERROR] Permission denied by Phone B to read SMS!")
            print("   -> If using Xiaomi/Redmi/Poco: Enable 'USB debugging (Security settings)' in Developer Options.")
            print("   -> On standard Android: Ensure USB debugging is granted.")
        return []
    # Return top N messages
    records = parse_content_query_rows(res.stdout)
    return records[:limit]


def forward_to_fastapi(record: dict) -> bool:
    """Sends the extracted SMS to the RESQ FastAPI /sms endpoint."""
    payload = {
        "from": record["address"],
        "message": record["body"],
        "id": f"adb-sms-{record['id']}",
        "timestamp": record.get("date"),
    }
    headers = {
        "Content-Type": "application/json",
        "X-RESQ-Secret": SECRET_TOKEN,
    }

    try:
        resp = requests.post(BACKEND_URL, json=payload, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            status_text = data.get("status", "ok")
            print(f"[FORWARDED] SMS #{record['id']} from {record['address']} -> Backend: {status_text.upper()}")
            return True
        else:
            print(f"[ERROR] Backend returned status {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to reach backend at {BACKEND_URL}: {e}")
        return False


def main():
    print("======================================================================")
    print("📱 RESQ Phone B USB SMS Forwarder Bridge")
    print(f"   Target Backend : {BACKEND_URL}")
    print(f"   ADB Path       : {ADB_PATH}")
    print("======================================================================")

    # 1. Wait for Phone B connection
    wait_for_device()

    # 2. Pre-seed existing SMS IDs so we don't spam historical old messages on startup
    print("📥 Scanning current inbox on Phone B...")
    initial_messages = fetch_latest_sms_from_phone()
    seen_ids = set()

    if initial_messages:
        print(f"   Found {len(initial_messages)} existing messages in Phone B's inbox.")
        for msg in initial_messages:
            seen_ids.add(msg["id"])
        print(f"   Initialized seen ID list. Now waiting for NEW incoming SMS from Phone A...")
    else:
        print("   Inbox currently empty or no messages found. Waiting for incoming SMS...")

    print("\n[ACTIVE] LISTENER ACTIVE: Send an SMS from Phone A to Phone B now!")
    print("----------------------------------------------------------------------")

    # 3. Continuous Polling Loop
    while True:
        try:
            current_messages = fetch_latest_sms_from_phone()
            for msg in reversed(current_messages):  # Process oldest to newest
                msg_id = msg["id"]
                if msg_id not in seen_ids:
                    seen_ids.add(msg_id)
                    print(f"\n[NEW SMS DETECTED ON PHONE B]")
                    print(f"   Sender : {msg['address']}")
                    print(f"   Body   : {msg['body']}")
                    forward_to_fastapi(msg)

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\n[STOP] Stopping ADB Bridge listener.")
            break
        except Exception as e:
            print(f"[WARN] Listener error: {e}")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
