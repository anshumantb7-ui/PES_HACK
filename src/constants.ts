export const EMERGENCY_TYPES = [
  "FLOOD",
  "FIRE",
  "MEDICAL",
  "COLLAPSE",
  "OTHER",
] as const;

export const STATUSES = [
  "TRAPPED",
  "INJURED",
  "UNCONSCIOUS",
  "NEED_EVACUATION",
  "SAFE_BUT_NEED_HELP",
] as const;

export type EmergencyType = (typeof EMERGENCY_TYPES)[number];
export type VictimStatus = (typeof STATUSES)[number];

// One SMS segment holds 160 GSM-7 units.
export const SMS_SEGMENT_LIMIT = 160;
// Sent in place of coordinates when the phone has no GPS fix.
export const LOCATION_UNKNOWN = "LOC:UNKNOWN";
