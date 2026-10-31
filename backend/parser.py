import re
import json
import logging
from typing import Optional
from backend.schemas import (
    EmergencyType,
    VictimStatus,
    Coordinates,
    ParsedSMS,
)
from backend.config import settings

logger = logging.getLogger("resq.parser")

# Canonical Enums
TYPE_MAP = {
    "FLOOD": EmergencyType.FLOOD,
    "FIRE": EmergencyType.FIRE,
    "MEDICAL": EmergencyType.MEDICAL,
    "MED": EmergencyType.MEDICAL,
    "MEDIC": EmergencyType.MEDICAL,
    "COLLAPSE": EmergencyType.COLLAPSE,
    "BUILDING_COLLAPSE": EmergencyType.COLLAPSE,
    "OTHER": EmergencyType.OTHER,
}

STATUS_MAP = {
    "TRAPPED": VictimStatus.TRAPPED,
    "TRAPD": VictimStatus.TRAPPED,
    "INJURED": VictimStatus.INJURED,
    "HURT": VictimStatus.INJURED,
    "WOUNDED": VictimStatus.INJURED,
    "UNCONSCIOUS": VictimStatus.UNCONSCIOUS,
    "UNCONCIOUS": VictimStatus.UNCONSCIOUS,
    "PASSED_OUT": VictimStatus.UNCONSCIOUS,
    "NEED_EVACUATION": VictimStatus.NEED_EVACUATION,
    "NEED_EVAC": VictimStatus.NEED_EVACUATION,
    "EVAC": VictimStatus.NEED_EVACUATION,
    "EVACUATION": VictimStatus.NEED_EVACUATION,
    "EVACUATE": VictimStatus.NEED_EVACUATION,
    "SAFE_BUT_NEED_HELP": VictimStatus.SAFE_BUT_NEED_HELP,
    "SAFE_NEED_HELP": VictimStatus.SAFE_BUT_NEED_HELP,
    "SAFE_HELP": VictimStatus.SAFE_BUT_NEED_HELP,
    "SAFE": VictimStatus.SAFE_BUT_NEED_HELP,
}

UNKNOWN_LOC_PATTERNS = [
    r"LOC\s*:\s*UNKNOWN",
    r"LOCATION_UNKNOWN",
    r"NO[-_\s]?GPS",
    r"UNKNOWN",
]

# Coordinate regex: lat, lon with optional signs and decimals
COORD_REGEX = re.compile(
    r"(?P<lat>-?\d{1,3}(?:\.\d+)?)\s*,\s*(?P<lon>-?\d{1,3}(?:\.\d+)?)"
)

def validate_coordinates(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0

def parse_with_regex(raw_text: str) -> ParsedSMS:
    """Regex-based parser for 'TYPE | STATUS | LAT,LON' (or LOC:UNKNOWN).

    Handles variations in casing, spacing, delimiters (|, ;, /), and coordinate precision.
    """
    clean_text = raw_text.strip()
    if not clean_text:
        return ParsedSMS(
            raw_text=raw_text,
            needs_review=True,
            confidence=0.0,
            parse_method="regex",
            error="Empty message",
        )

    # Remove typical forwarder envelope headers if present, e.g. "[SMS] ", "Forwarded: "
    text_to_parse = re.sub(
        r"^(?:(?:\[SMS\]|Forwarded\s*(?:SMS)?|From\s*[\w\+\-\s]+:)\s*)",
        "",
        clean_text,
        flags=re.IGNORECASE,
    ).strip()

    # Match 3 segments separated by '|', ';', or '/'
    # Example: FLOOD | TRAPPED | 12.97160,77.59460
    # Also tolerate comma separation if coordinates are last
    delimiters_pattern = re.compile(r"\s*[|;/]\s*")
    segments = [s.strip() for s in delimiters_pattern.split(text_to_parse) if s.strip()]

    # If not split into 3 segments, check if there's an embedded match inside text
    if len(segments) != 3:
        embedded_match = re.search(
            r"([A-Za-z_]+)\s*[|;/]\s*([A-Za-z_]+)\s*[|;/]\s*([^|;/]+)",
            text_to_parse,
        )
        if embedded_match:
            segments = [
                embedded_match.group(1).strip(),
                embedded_match.group(2).strip(),
                embedded_match.group(3).strip(),
            ]

    if len(segments) < 3:
        return ParsedSMS(
            raw_text=raw_text,
            needs_review=True,
            confidence=0.2,
            parse_method="regex",
            error=f"Expected 3 segments (TYPE | STATUS | LOC), found {len(segments)}",
        )

    raw_type, raw_status, raw_loc = segments[0], segments[1], segments[2]
    
    # 1. Match Emergency Type (extract exact keyword if surrounded by prefix/noise)
    matched_type = None
    type_exact = False
    
    # Try direct match first
    direct_type_key = re.sub(r"[^A-Za-z_]", "", raw_type).upper()
    if direct_type_key in TYPE_MAP:
        matched_type = TYPE_MAP[direct_type_key]
        type_exact = (direct_type_key in [t.value for t in EmergencyType])
    else:
        # Check words in segment for a recognized type
        words = re.findall(r"\b[A-Za-z_]+\b", raw_type)
        for w in reversed(words):  # prioritize word closest to delimiter
            wk = w.upper()
            if wk in TYPE_MAP:
                matched_type = TYPE_MAP[wk]
                type_exact = (wk in [t.value for t in EmergencyType])
                break

    # 2. Match Victim Status (extract exact keyword if surrounded by noise)
    matched_status = None
    status_exact = False
    
    direct_status_key = re.sub(r"[^A-Za-z_]", "", raw_status).upper()
    if direct_status_key in STATUS_MAP:
        matched_status = STATUS_MAP[direct_status_key]
        status_exact = (direct_status_key in [s.value for s in VictimStatus])
    else:
        words = re.findall(r"\b[A-Za-z_]+\b", raw_status)
        for w in reversed(words):
            wk = w.upper()
            if wk in STATUS_MAP:
                matched_status = STATUS_MAP[wk]
                status_exact = (wk in [s.value for s in VictimStatus])
                break

    if not matched_type or not matched_status:
        return ParsedSMS(
            raw_text=raw_text,
            needs_review=True,
            confidence=0.3,
            parse_method="regex",
            error=f"Unrecognized type '{raw_type}' or status '{raw_status}'",
        )

    # 3. Match Location (Coordinates or Unknown)
    is_unknown_loc = any(
        re.search(pat, raw_loc, re.IGNORECASE) for pat in UNKNOWN_LOC_PATTERNS
    )

    location: Optional[Coordinates] = None
    coord_valid = False

    if is_unknown_loc:
        coord_valid = True
    else:
        coord_match = COORD_REGEX.search(raw_loc)
        if coord_match:
            try:
                lat = float(coord_match.group("lat"))
                lon = float(coord_match.group("lon"))
                if validate_coordinates(lat, lon):
                    location = Coordinates(lat=lat, lon=lon)
                    coord_valid = True
                else:
                    return ParsedSMS(
                        type=matched_type,
                        status=matched_status,
                        raw_text=raw_text,
                        needs_review=True,
                        confidence=0.4,
                        parse_method="regex",
                        error=f"Coordinates out of valid range: lat={lat}, lon={lon}",
                    )
            except ValueError:
                coord_valid = False

    if not coord_valid:
        return ParsedSMS(
            type=matched_type,
            status=matched_status,
            raw_text=raw_text,
            needs_review=True,
            confidence=0.35,
            parse_method="regex",
            error=f"Could not parse valid coordinates from '{raw_loc}'",
        )

    # Compute Confidence Score
    confidence = 1.0
    if not (type_exact and status_exact):
        confidence -= 0.15  # Alias or normalized mapping
    if "|" not in text_to_parse:
        confidence -= 0.10  # Used alternative delimiter
    if len(text_to_parse) != len(clean_text):
        confidence -= 0.05  # Had extra wrappers

    confidence = max(0.0, min(1.0, round(confidence, 2)))

    return ParsedSMS(
        type=matched_type,
        status=matched_status,
        location=location,
        location_unknown=is_unknown_loc,
        confidence=confidence,
        needs_review=(confidence < 0.7),
        parse_method="regex",
        raw_text=raw_text,
        error=None,
    )


def parse_with_gemini_fallback(raw_text: str) -> Optional[ParsedSMS]:
    """Fallback parser using Gemini LLM with strict JSON schema and grounding checks.

    Ensures values are genuinely grounded in raw_text.
    """
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        logger.debug("GEMINI_API_KEY not configured, skipping LLM fallback.")
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        prompt = f"""You are an emergency SMS parser for disaster response.
Parse the following raw SMS into the specified fields.
Valid Types: FLOOD, FIRE, MEDICAL, COLLAPSE, OTHER
Valid Statuses: TRAPPED, INJURED, UNCONSCIOUS, NEED_EVACUATION, SAFE_BUT_NEED_HELP

SMS:
\"\"\"{raw_text}\"\"\"

CRITICAL GROUNDING RULES:
1. ONLY extract coordinates if numbers representing latitude and longitude actually appear in the SMS text.
2. DO NOT make up or hallucinate coordinates. If none appear, set location_unknown to true.
3. If the SMS is not an emergency message or is completely unreadable/spam, set is_valid_emergency to false.

Return JSON adhering to this schema:
{{
  "type": "FLOOD" | "FIRE" | "MEDICAL" | "COLLAPSE" | "OTHER" | null,
  "status": "TRAPPED" | "INJURED" | "UNCONSCIOUS" | "NEED_EVACUATION" | "SAFE_BUT_NEED_HELP" | null,
  "latitude": float or null,
  "longitude": float or null,
  "location_unknown": boolean,
  "is_valid_emergency": boolean,
  "explanation": "brief reason"
}}
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )

        data = json.loads(response.text)
        if not data.get("is_valid_emergency", False):
            return ParsedSMS(
                raw_text=raw_text,
                needs_review=True,
                confidence=0.0,
                parse_method="gemini",
                error=f"LLM classified as non-emergency/spam: {data.get('explanation')}",
            )

        extracted_type = data.get("type")
        extracted_status = data.get("status")
        extracted_lat = data.get("latitude")
        extracted_lon = data.get("longitude")
        loc_unknown = data.get("location_unknown", False)

        # GROUNDING CHECK:
        # Verify that latitude & longitude numbers actually exist in the raw text
        if extracted_lat is not None and extracted_lon is not None:
            lat_str = f"{extracted_lat:.2f}"
            lon_str = f"{extracted_lon:.2f}"
            # Check basic prefix in text
            lat_prefix = str(extracted_lat).split(".")[0]
            lon_prefix = str(extracted_lon).split(".")[0]
            if lat_prefix not in raw_text or lon_prefix not in raw_text:
                logger.warning(
                    f"Grounding check failed: LLM coordinates ({extracted_lat}, {extracted_lon}) "
                    f"not found in raw text: '{raw_text}'"
                )
                return ParsedSMS(
                    raw_text=raw_text,
                    needs_review=True,
                    confidence=0.2,
                    parse_method="gemini",
                    error="Grounding check failed: coordinates not present in raw SMS",
                )

            if not validate_coordinates(extracted_lat, extracted_lon):
                return ParsedSMS(
                    raw_text=raw_text,
                    needs_review=True,
                    confidence=0.2,
                    parse_method="gemini",
                    error="LLM extracted coordinates out of valid range",
                )
            location = Coordinates(lat=extracted_lat, lon=extracted_lon)
        else:
            location = None
            loc_unknown = True

        return ParsedSMS(
            type=EmergencyType(extracted_type) if extracted_type in [t.value for t in EmergencyType] else None,
            status=VictimStatus(extracted_status) if extracted_status in [s.value for s in VictimStatus] else None,
            location=location,
            location_unknown=loc_unknown,
            confidence=0.75,
            needs_review=(extracted_type is None or extracted_status is None),
            parse_method="gemini",
            raw_text=raw_text,
            error=None,
        )

    except Exception as e:
        logger.error(f"Gemini fallback failed: {e}")
        return None


def parse_sms_message(raw_text: str) -> ParsedSMS:
    """Master parser: tries regex first, falls back to Gemini on low-confidence/malformed messages."""
    result = parse_with_regex(raw_text)

    # Fallback to Gemini if low confidence or needs review
    if result.needs_review and settings.GEMINI_API_KEY:
        gemini_result = parse_with_gemini_fallback(raw_text)
        if gemini_result:
            return gemini_result

    return result
