import pytest
from backend.parser import parse_sms_message
from backend.schemas import EmergencyType, VictimStatus

# 32 diverse messy, edge-case, and malformed samples
MESSY_SAMPLES = [
    # 1. Exact standard message
    {
        "sms": "FLOOD | TRAPPED | 12.97160,77.59460",
        "expected_type": EmergencyType.FLOOD,
        "expected_status": VictimStatus.TRAPPED,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 2. Standard message with unknown location
    {
        "sms": "FIRE | INJURED | LOC:UNKNOWN",
        "expected_type": EmergencyType.FIRE,
        "expected_status": VictimStatus.INJURED,
        "location_unknown": True,
        "needs_review": False,
    },
    # 3. All lowercase
    {
        "sms": "medical | unconscious | 12.97160,77.59460",
        "expected_type": EmergencyType.MEDICAL,
        "expected_status": VictimStatus.UNCONSCIOUS,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 4. Mixed casing
    {
        "sms": "Collapse | Safe_But_Need_Help | 12.97160,77.59460",
        "expected_type": EmergencyType.COLLAPSE,
        "expected_status": VictimStatus.SAFE_BUT_NEED_HELP,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 5. No spaces around delimiters
    {
        "sms": "OTHER|NEED_EVACUATION|13.08270,80.27070",
        "expected_type": EmergencyType.OTHER,
        "expected_status": VictimStatus.NEED_EVACUATION,
        "lat": 13.0827,
        "lon": 80.2707,
        "needs_review": False,
    },
    # 6. Excessive spaces and tabs
    {
        "sms": "  FLOOD   |   TRAPPED   |   12.97160 ,  77.59460  ",
        "expected_type": EmergencyType.FLOOD,
        "expected_status": VictimStatus.TRAPPED,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 7. Short decimal format (2 decimals)
    {
        "sms": "FIRE | INJURED | 12.97,77.59",
        "expected_type": EmergencyType.FIRE,
        "expected_status": VictimStatus.INJURED,
        "lat": 12.97,
        "lon": 77.59,
        "needs_review": False,
    },
    # 8. High precision decimals (7 decimals)
    {
        "sms": "MEDICAL | TRAPPED | 12.9715982,77.5945821",
        "expected_type": EmergencyType.MEDICAL,
        "expected_status": VictimStatus.TRAPPED,
        "lat": 12.9715982,
        "lon": 77.5945821,
        "needs_review": False,
    },
    # 9. Negative coordinates (Southern & Western Hemisphere)
    {
        "sms": "FLOOD | TRAPPED | -23.55052,-46.63331",
        "expected_type": EmergencyType.FLOOD,
        "expected_status": VictimStatus.TRAPPED,
        "lat": -23.55052,
        "lon": -46.63331,
        "needs_review": False,
    },
    # 10. Origin coordinates (0.0, 0.0)
    {
        "sms": "OTHER | SAFE_BUT_NEED_HELP | 0.00000,0.00000",
        "expected_type": EmergencyType.OTHER,
        "expected_status": VictimStatus.SAFE_BUT_NEED_HELP,
        "lat": 0.0,
        "lon": 0.0,
        "needs_review": False,
    },
    # 11. Type abbreviation 'MED' -> MEDICAL
    {
        "sms": "MED | INJURED | 12.9716,77.5946",
        "expected_type": EmergencyType.MEDICAL,
        "expected_status": VictimStatus.INJURED,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 12. Type alias 'MEDIC' -> MEDICAL
    {
        "sms": "MEDIC | UNCONSCIOUS | 12.9716,77.5946",
        "expected_type": EmergencyType.MEDICAL,
        "expected_status": VictimStatus.UNCONSCIOUS,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 13. Type alias 'BUILDING_COLLAPSE' -> COLLAPSE
    {
        "sms": "BUILDING_COLLAPSE | TRAPPED | 12.9716,77.5946",
        "expected_type": EmergencyType.COLLAPSE,
        "expected_status": VictimStatus.TRAPPED,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 14. Status typo 'TRAPD' -> TRAPPED
    {
        "sms": "FLOOD | TRAPD | 12.9716,77.5946",
        "expected_type": EmergencyType.FLOOD,
        "expected_status": VictimStatus.TRAPPED,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 15. Status synonym 'HURT' -> INJURED
    {
        "sms": "FIRE | HURT | 12.9716,77.5946",
        "expected_type": EmergencyType.FIRE,
        "expected_status": VictimStatus.INJURED,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 16. Status typo 'UNCONCIOUS' -> UNCONSCIOUS
    {
        "sms": "MEDICAL | UNCONCIOUS | 12.9716,77.5946",
        "expected_type": EmergencyType.MEDICAL,
        "expected_status": VictimStatus.UNCONSCIOUS,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 17. Status alias 'EVAC' -> NEED_EVACUATION
    {
        "sms": "FLOOD | EVAC | 12.9716,77.5946",
        "expected_type": EmergencyType.FLOOD,
        "expected_status": VictimStatus.NEED_EVACUATION,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 18. Status alias 'SAFE' -> SAFE_BUT_NEED_HELP
    {
        "sms": "OTHER | SAFE | 12.9716,77.5946",
        "expected_type": EmergencyType.OTHER,
        "expected_status": VictimStatus.SAFE_BUT_NEED_HELP,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 19. Semicolon delimiters
    {
        "sms": "FLOOD; TRAPPED; 12.9716,77.5946",
        "expected_type": EmergencyType.FLOOD,
        "expected_status": VictimStatus.TRAPPED,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 20. Forward slash delimiters
    {
        "sms": "FIRE / INJURED / 12.9716,77.5946",
        "expected_type": EmergencyType.FIRE,
        "expected_status": VictimStatus.INJURED,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 21. Android forwarder prefix: "[SMS] ..."
    {
        "sms": "[SMS] FLOOD | TRAPPED | 12.9716,77.5946",
        "expected_type": EmergencyType.FLOOD,
        "expected_status": VictimStatus.TRAPPED,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 22. Android forwarder prefix: "Forwarded SMS: ..."
    {
        "sms": "Forwarded SMS: MEDICAL | UNCONSCIOUS | 12.9716,77.5946",
        "expected_type": EmergencyType.MEDICAL,
        "expected_status": VictimStatus.UNCONSCIOUS,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 23. Coordinates with spaces around comma
    {
        "sms": "COLLAPSE | TRAPPED | 12.97160 , 77.59460",
        "expected_type": EmergencyType.COLLAPSE,
        "expected_status": VictimStatus.TRAPPED,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # 24. Location Unknown variation: LOCATION_UNKNOWN
    {
        "sms": "FIRE | NEED_EVACUATION | LOCATION_UNKNOWN",
        "expected_type": EmergencyType.FIRE,
        "expected_status": VictimStatus.NEED_EVACUATION,
        "location_unknown": True,
        "needs_review": False,
    },
    # 25. Location Unknown variation: NO_GPS
    {
        "sms": "OTHER | SAFE_BUT_NEED_HELP | NO_GPS",
        "expected_type": EmergencyType.OTHER,
        "expected_status": VictimStatus.SAFE_BUT_NEED_HELP,
        "location_unknown": True,
        "needs_review": False,
    },
    # 26. Embedded SOS surrounded by phone alerts
    {
        "sms": "[EMERGENCY ALERT] FLOOD | TRAPPED | 12.9716,77.5946 [BATTERY 10%]",
        "expected_type": EmergencyType.FLOOD,
        "expected_status": VictimStatus.TRAPPED,
        "lat": 12.9716,
        "lon": 77.5946,
        "needs_review": False,
    },
    # --- MALFORMED SAMPLES (MUST give clean needs_review=True) ---
    # 27. Latitude out of range (> 90)
    {
        "sms": "FLOOD | TRAPPED | 95.1234,77.5946",
        "needs_review": True,
    },
    # 28. Longitude out of range (> 180)
    {
        "sms": "FIRE | INJURED | 12.9716,195.5946",
        "needs_review": True,
    },
    # 29. Missing coordinates / incomplete 2-part message
    {
        "sms": "FLOOD | TRAPPED",
        "needs_review": True,
    },
    # 30. Completely malformed casual text / spam
    {
        "sms": "Hey are we still meeting for lunch today at 1pm?",
        "needs_review": True,
    },
    # 31. Empty string or whitespace
    {
        "sms": "   ",
        "needs_review": True,
    },
    # 32. Garbage symbols
    {
        "sms": "@!#$%^&*() | ????? | !!!",
        "needs_review": True,
    },
]


@pytest.mark.parametrize("sample", MESSY_SAMPLES)
def test_messy_sms_parser(sample):
    sms = sample["sms"]
    result = parse_sms_message(sms)

    if sample["needs_review"]:
        assert result.needs_review is True, f"Expected needs_review for '{sms}', but got {result}"
    else:
        assert result.needs_review is False, f"Unexpected needs_review for '{sms}': {result.error}"
        assert result.type == sample["expected_type"]
        assert result.status == sample["expected_status"]
        if sample.get("location_unknown"):
            assert result.location_unknown is True
            assert result.location is None
        else:
            assert result.location is not None
            assert pytest.approx(result.location.lat, abs=1e-4) == sample["lat"]
            assert pytest.approx(result.location.lon, abs=1e-4) == sample["lon"]
            assert result.confidence >= 0.70

