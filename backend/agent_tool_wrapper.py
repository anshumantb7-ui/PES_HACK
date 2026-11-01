"""Client-Side Python Tool Wrapper for Online MAS Orchestrators.

This module acts as the "Hands and Ears" of the Online Main Agent (Orchestrator).
It translates the Orchestrator's natural language tool invocations into authenticated
HTTP requests across the secure tunnel (Cloudflare Tunnel, Tailscale, or LAN IP),
queries the offline database (SQLite/PostgreSQL) via the server-side API bridge,
and converts the response back into structured text for agent context injection.

Compatible with:
- LangChain / LangGraph (@tool)
- CrewAI / AutoGen
- OpenAI / Gemini Function Calling
- Custom Multi-Agent Systems
"""

import os
import sys
import json
import logging
from typing import Optional, Any, Dict
import requests

# Ensure UTF-8 console output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logger = logging.getLogger("resq.agent_tool")

# ──────────────────────────────────────────────────────────────
# Default Configuration (Override via Environment Variables)
# ──────────────────────────────────────────────────────────────
# In production, set RESQ_OFFLINE_BRIDGE_URL to your secure tunnel URL
# e.g., "https://resq-offline.your-domain.com" or "http://192.168.137.1:8000"
DEFAULT_BRIDGE_URL = os.getenv("RESQ_OFFLINE_BRIDGE_URL", "http://127.0.0.1:8000")
DEFAULT_API_KEY = os.getenv("RESQ_MAS_API_KEY", "resq-mas-bridge-secret-2026")
DEFAULT_TIMEOUT = int(os.getenv("RESQ_BRIDGE_TIMEOUT", "10"))


# ──────────────────────────────────────────────────────────────
# Core Tool Function (Agent Context Injection Format)
# ──────────────────────────────────────────────────────────────
def query_offline_database(
    emergency_type: Optional[str] = None,
    victim_status: Optional[str] = None,
    sender: Optional[str] = None,
    needs_review: Optional[bool] = None,
    min_confidence: Optional[float] = None,
    since: Optional[str] = None,
    limit: int = 20,
    bridge_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> str:
    """Queries the offline RESQ disaster database via the secure API bridge.

    Use this tool whenever you need real-time ground reports, victim locations,
    or emergency SMS messages collected by offline field gateways.

    Args:
        emergency_type: Filter by category ('FLOOD', 'FIRE', 'MEDICAL', 'COLLAPSE', 'OTHER').
        victim_status: Filter by status ('TRAPPED', 'INJURED', 'UNCONSCIOUS', 'NEED_EVACUATION', 'SAFE_BUT_NEED_HELP').
        sender: Filter by sender phone number (e.g. '+919986898914').
        needs_review: Set to True to retrieve messages requiring manual human verification.
        min_confidence: Minimum parsing confidence score (0.0 to 1.0).
        since: ISO datetime string to retrieve records after a specific time (e.g. '2026-11-01T00:00:00').
        limit: Maximum number of incidents to return (1-100, default 20).
        bridge_url: Optional override URL for the offline bridge / tunnel.
        api_key: Optional override for Bearer auth API key.

    Returns:
        Structured text summary formatted with Markdown, ready to be injected
        directly into the active context memory of the Orchestrator agent.
    """
    base_url = (bridge_url or DEFAULT_BRIDGE_URL).rstrip("/")
    token = api_key or DEFAULT_API_KEY
    endpoint = f"{base_url}/api/query-offline"

    # Step 1: Serialize Agent Arguments into Structured JSON Payload
    payload: Dict[str, Any] = {
        "emergency_type": emergency_type.upper().strip() if emergency_type else None,
        "victim_status": victim_status.upper().strip() if victim_status else None,
        "sender": sender.strip() if sender else None,
        "needs_review": needs_review,
        "min_confidence": min_confidence,
        "since": since,
        "limit": min(max(1, limit), 100),
    }
    # Clean nulls
    request_data = {k: v for k, v in payload.items() if v is not None}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    # Step 2: Transmit HTTP Request across Secure Tunnel to Offline Host
    try:
        response = requests.post(
            endpoint,
            json=request_data,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        error_msg = (
            f"[OFFLINE DATABASE ERROR]: Unable to connect to offline bridge at '{base_url}'. "
            "The offline host or secure tunnel (Cloudflare/Tailscale) appears to be unreachable."
        )
        logger.error(error_msg)
        return error_msg
    except requests.exceptions.Timeout:
        error_msg = (
            f"[OFFLINE DATABASE ERROR]: Query to '{endpoint}' timed out after {DEFAULT_TIMEOUT}s. "
            "The offline machine or network tunnel may be under heavy load."
        )
        logger.error(error_msg)
        return error_msg
    except Exception as exc:
        error_msg = f"[OFFLINE DATABASE ERROR]: Unexpected client error during request: {str(exc)}"
        logger.error(error_msg)
        return error_msg

    # Step 3: Handle HTTP Status Codes & Error Responses
    if response.status_code == 401:
        return (
            "[OFFLINE DATABASE AUTH ERROR]: 401 Unauthorized. "
            "Invalid or missing Bearer API key for the offline bridge."
        )
    elif response.status_code != 200:
        return (
            f"[OFFLINE DATABASE HTTP ERROR]: Received status {response.status_code} "
            f"from bridge: {response.text}"
        )

    # Step 4: Deserialize JSON & Format into Agent Context Summary
    try:
        data = response.json()
    except Exception as exc:
        return f"[OFFLINE DATABASE PARSE ERROR]: Bridge returned invalid JSON: {exc}"

    if not data.get("success", False):
        error_desc = data.get("error") or "Unknown database error"
        return f"[OFFLINE DATABASE QUERY FAILED]: {error_desc}"

    records = data.get("records", [])
    total_found = data.get("total", len(records))

    if not records:
        filter_str = ", ".join(f"{k}={v}" for k, v in request_data.items()) or "all"
        return (
            f"### Offline Disaster Database Query Results\n"
            f"- Status: Success (0 matching incidents found)\n"
            f"- Applied Filters: {filter_str}\n"
            f"- Note: No emergency records currently match the specified criteria in the offline database."
        )

    # Build clear, high-density Markdown summary for the LLM context window
    lines = [
        f"### Offline Disaster Database Query Results",
        f"- **Found**: {len(records)} incidents displayed (Total matching: {total_found})",
        "",
        "| ID | Sender | Type | Status | Location (Lat, Lon) | Confidence | Review Needed? |",
        "|---|---|---|---|---|---|---|",
    ]

    for rec in records:
        rec_id = rec.get("id")
        sndr = rec.get("sender", "Unknown")
        parsed = rec.get("parsed_data") or {}

        e_type = parsed.get("type") or "UNKNOWN"
        v_status = parsed.get("status") or "UNKNOWN"

        loc_data = parsed.get("location")
        if loc_data and isinstance(loc_data, dict):
            lat = loc_data.get("lat")
            lon = loc_data.get("lon")
            loc_str = f"{lat:.5f}, {lon:.5f}" if lat is not None and lon is not None else "Unknown"
        elif parsed.get("location_unknown"):
            loc_str = "LOC:UNKNOWN (No GPS)"
        else:
            loc_str = "None"

        conf = rec.get("confidence")
        conf_str = f"{conf:.2f}" if conf is not None else "N/A"
        needs_rev = "[!] YES" if parsed.get("needs_review") or rec.get("status") == "needs_review" else "No"

        lines.append(
            f"| #{rec_id} | {sndr} | {e_type} | {v_status} | {loc_str} | {conf_str} | {needs_rev} |"
        )

    lines.append("")
    lines.append("**Raw Messages & Details:**")
    for rec in records:
        lines.append(
            f"- Incident #{rec.get('id')} ({rec.get('sender')}): \"{rec.get('raw_body')}\" "
            f"[Received: {rec.get('received_at')}]"
        )

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# Helper: Verify Tunnel & Bridge Connection
# ──────────────────────────────────────────────────────────────
def check_offline_bridge_health(
    bridge_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Pings the offline bridge /api/bridge/status to verify connectivity."""
    base_url = (bridge_url or DEFAULT_BRIDGE_URL).rstrip("/")
    token = api_key or DEFAULT_API_KEY
    url = f"{base_url}/api/bridge/status"

    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
        return {"bridge_status": "error", "http_status": resp.status_code, "detail": resp.text}
    except Exception as exc:
        return {"bridge_status": "offline", "error": str(exc)}


# ──────────────────────────────────────────────────────────────
# Tool Definition Schema (for OpenAI / Gemini / Anthropic Function Calling)
# ──────────────────────────────────────────────────────────────
OFFLINE_DB_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "query_offline_database",
        "description": (
            "Queries the offline RESQ database for emergency reports, victim coordinates, "
            "and disaster SMS messages collected on the ground by field gateway nodes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "emergency_type": {
                    "type": "string",
                    "enum": ["FLOOD", "FIRE", "MEDICAL", "COLLAPSE", "OTHER"],
                    "description": "Category of disaster incident to filter for.",
                },
                "victim_status": {
                    "type": "string",
                    "enum": ["TRAPPED", "INJURED", "UNCONSCIOUS", "NEED_EVACUATION", "SAFE_BUT_NEED_HELP"],
                    "description": "Current status of victims involved.",
                },
                "sender": {
                    "type": "string",
                    "description": "Filter by sender phone number (e.g. '+919986898914').",
                },
                "needs_review": {
                    "type": "boolean",
                    "description": "Set to true to inspect low-confidence or malformed messages needing review.",
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum parsing confidence threshold between 0.0 and 1.0.",
                },
                "since": {
                    "type": "string",
                    "description": "ISO format timestamp to filter messages received after this time.",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Max records to retrieve (1-100).",
                },
            },
            "required": [],
        },
    },
}


# ──────────────────────────────────────────────────────────────
# LangChain / LangGraph Adapter (Conditional Import)
# ──────────────────────────────────────────────────────────────
try:
    from langchain_core.tools import tool

    @tool
    def offline_database_tool(
        emergency_type: Optional[str] = None,
        victim_status: Optional[str] = None,
        sender: Optional[str] = None,
        needs_review: Optional[bool] = None,
        min_confidence: Optional[float] = None,
        since: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """Query the offline disaster database for real-time field reports and victim coordinates."""
        return query_offline_database(
            emergency_type=emergency_type,
            victim_status=victim_status,
            sender=sender,
            needs_review=needs_review,
            min_confidence=min_confidence,
            since=since,
            limit=limit,
        )

except ImportError:
    # LangChain not installed in local environment; core function is directly callable
    offline_database_tool = query_offline_database  # type: ignore


# ──────────────────────────────────────────────────────────────
# Interactive Verification when Executed Directly
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("[TEST] Checking connection to Offline API Bridge...")
    print(f"   Target URL: {DEFAULT_BRIDGE_URL}")
    print("=" * 70)

    health = check_offline_bridge_health()
    print(f"Bridge Health: {json.dumps(health, indent=2)}")

    print("\nExecuting sample agent query: query_offline_database(limit=5)...")
    result_text = query_offline_database(limit=5)
    print("\n--- INJECTED AGENT CONTEXT OUTPUT ---")
    print(result_text)
    print("=" * 70)
