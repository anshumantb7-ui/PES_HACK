import {
  EMERGENCY_TYPES,
  LOCATION_UNKNOWN,
  STATUSES,
  type EmergencyType,
  type VictimStatus,
} from "./constants";

export type SmsPlatform = "android" | "ios";

/** Characters that cost 2 units in the GSM-7 alphabet (extension table). */
const GSM7_EXTENDED = new Set(["^", "{", "}", "\\", "[", "]", "~", "|", "€", "\f"]);

/** Fixed 5-decimal formatting (~1.1 m precision). Never returns "-0.00000". */
export function formatCoordinate(value: number): string {
  const text = value.toFixed(5);
  return text === "-0.00000" ? "0.00000" : text;
}

/** Builds exactly: TYPE | STATUS | LAT,LON */
export function buildMessage(
  type: EmergencyType,
  status: VictimStatus,
  lat: number,
  lon: number,
): string {
  if (!(EMERGENCY_TYPES as readonly string[]).includes(type)) {
    throw new Error(`Unknown emergency type: ${String(type)}`);
  }
  if (!(STATUSES as readonly string[]).includes(status)) {
    throw new Error(`Unknown status: ${String(status)}`);
  }
  if (!Number.isFinite(lat) || lat < -90 || lat > 90) {
    throw new Error("Latitude must be a number between -90 and 90");
  }
  if (!Number.isFinite(lon) || lon < -180 || lon > 180) {
    throw new Error("Longitude must be a number between -180 and 180");
  }
  return `${type} | ${status} | ${formatCoordinate(lat)},${formatCoordinate(lon)}`;
}

/** Builds exactly: TYPE | STATUS | LOC:UNKNOWN (used when there is no GPS fix). */
export function buildMessageWithoutLocation(type: EmergencyType, status: VictimStatus): string {
  if (!(EMERGENCY_TYPES as readonly string[]).includes(type)) {
    throw new Error(`Unknown emergency type: ${String(type)}`);
  }
  if (!(STATUSES as readonly string[]).includes(status)) {
    throw new Error(`Unknown status: ${String(status)}`);
  }
  return `${type} | ${status} | ${LOCATION_UNKNOWN}`;
}

/** Length in GSM-7 units: '|' counts as 2. Assumes the text is GSM-7 safe. */
export function gsm7Length(text: string): number {
  let units = 0;
  for (const ch of text) {
    units += GSM7_EXTENDED.has(ch) ? 2 : 1;
  }
  return units;
}

/**
 * Builds the sms: link. Android uses "?body=", iOS has historically used
 * "&body=". The '+' of the phone number must NOT be encoded.
 */
export function buildSmsLink(
  gatewayNumber: string,
  body: string,
  platform: SmsPlatform,
): string {
  const number = gatewayNumber.trim();
  if (!/^\+?[0-9]{5,15}$/.test(number)) {
    throw new Error(
      "Gateway number is missing or invalid. Set VITE_GATEWAY_NUMBER in .env.local (digits, optional leading +).",
    );
  }
  const separator = platform === "ios" ? "&" : "?";
  return `sms:${number}${separator}body=${encodeURIComponent(body)}`;
}

export function detectPlatform(userAgent: string): SmsPlatform {
  return /iPhone|iPad|iPod/.test(userAgent) ? "ios" : "android";
}