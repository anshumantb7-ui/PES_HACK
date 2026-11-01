"""MAS (Multi-Agent System) Tool Wrapper Example.

This script demonstrates how an online cloud agent (e.g., LangGraph, CrewAI,
or custom Orchestrator) queries the offline disaster database through a secure
tunnel (Cloudflare Tunnel, Tailscale, or direct IP).

Loop Architecture:
  Orchestrator Agent (Online)
  -> query_offline_database() [Tool Call]
  -> HTTPS Request with Bearer Auth
  -> Secure Tunnel (Cloudflare/Tailscale)
  -> Offline FastAPI Server (/api/query-offline)
  -> SQLite/PostgreSQL Database Query Execution
  -> Clean JSON Response Generation
  -> Tool Deserialization & Context Window Injection
"""

import os
import json
import requests
from typing import Optional, Any


class OfflineDatabaseTool:
    """Tool wrapper for the Online Orchestrator to query the offline RESQ database."""

    def __init__(
        self,
        bridge_base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        # When deployed online, set BRIDGE_BASE_URL to your Cloudflare Tunnel URL
        # e.g., 'https://resq-offline-bridge.your-domain.com'
        self.base_url = (
            bridge_base_url
            or os.getenv("RESQ_OFFLINE_BRIDGE_URL", "http://127.0.0.1:8000")
        ).rstrip("/")

        self.api_key = api_key or os.getenv(
            "RESQ_MAS_API_KEY", "resq-mas-bridge-secret-2026"
        )

    def _get_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def check_connection(self) -> dict[str, Any]:
        """Pings the offline bridge to ensure the tunnel and database are active."""
        url = f"{self.base_url}/api/bridge/status"
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=5)
            return resp.json()
        except requests.RequestException as e:
            return {"bridge_status": "offline", "error": str(e)}

    def query_incidents(
        self,
        emergency_type: Optional[str] = None,
        victim_status: Optional[str] = None,
        needs_review: Optional[bool] = None,
        min_confidence: Optional[float] = None,
        since: Optional[str] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Queries the offline database with structured filter parameters.

        Args:
            emergency_type: 'FLOOD', 'FIRE', 'MEDICAL', 'COLLAPSE', 'OTHER'
            victim_status: 'TRAPPED', 'INJURED', 'UNCONSCIOUS', 'NEED_EVACUATION', 'SAFE_BUT_NEED_HELP'
            needs_review: True to retrieve records requiring manual human triage
            min_confidence: Minimum parsing confidence score (0.0 to 1.0)
            since: ISO timestamp string (e.g. '2026-11-01T00:00:00')
            limit: Maximum records to return (1-200)

        Returns:
            Structured dictionary with 'success', 'count', 'records', etc.
        """
        url = f"{self.base_url}/api/query-offline"
        payload = {
            "emergency_type": emergency_type,
            "victim_status": victim_status,
            "needs_review": needs_review,
            "min_confidence": min_confidence,
            "since": since,
            "limit": limit,
        }

        # Filter out None values
        clean_payload = {k: v for k, v in payload.items() if v is not None}

        try:
            resp = requests.post(
                url,
                json=clean_payload,
                headers=self._get_headers(),
                timeout=10,
            )
            data = resp.json()

            # Format human/agent-readable summary for the context window
            records = data.get("records", [])
            summary_lines = [
                f"=== OFFLINE DATABASE QUERY RESULTS (Count: {len(records)}) ==="
            ]
            for r in records:
                loc = "None"
                pd = r.get("parsed_data") or {}
                if pd.get("location"):
                    loc = f"({pd['location']['lat']:.5f}, {pd['location']['lon']:.5f})"
                elif pd.get("location_unknown"):
                    loc = "LOC:UNKNOWN"

                summary_lines.append(
                    f"- [ID #{r['id']}] From: {r['sender']} | "
                    f"Type: {pd.get('type')} | Status: {pd.get('status')} | "
                    f"Loc: {loc} | Confidence: {r.get('confidence')} | "
                    f"DB Status: {r.get('status')}"
                )

            data["agent_context_summary"] = "\n".join(summary_lines)
            return data

        except requests.RequestException as e:
            return {
                "success": False,
                "count": 0,
                "records": [],
                "error": f"Failed to connect to offline bridge: {e}",
            }


if __name__ == "__main__":
    # Self-test demonstration
    tool = OfflineDatabaseTool()
    print("Testing connection to offline bridge...")
    status_info = tool.check_connection()
    print("Bridge Status:", json.dumps(status_info, indent=2))

    print("\nQuerying offline incidents...")
    results = tool.query_incidents(limit=5)
    print("Query Summary:\n", results.get("agent_context_summary", results))

