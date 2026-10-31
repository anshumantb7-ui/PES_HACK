import { describe, expect, it } from "vitest";
import { EMERGENCY_TYPES, SMS_SEGMENT_LIMIT, STATUSES } from "./constants";
import {
  buildMessage,
  buildMessageWithoutLocation,
  buildSmsLink,
  detectPlatform,
  formatCoordinate,
  gsm7Length,
} from "./message";

const NUMBER = "+15551234567";
const MESSAGE = "FLOOD | TRAPPED | 12.93450,77.61230";
const ENCODED = "FLOOD%20%7C%20TRAPPED%20%7C%2012.93450%2C77.61230";

const combos = EMERGENCY_TYPES.flatMap((t) =>
  STATUSES.map((s) => [t, s] as const),
);

describe("formatCoordinate", () => {
  it("pads to 5 decimals", () => {
    expect(formatCoordinate(12.9345)).toBe("12.93450");
  });
  it("rounds down past 5 decimals", () => {
    expect(formatCoordinate(77.612304999)).toBe("77.61230");
  });
  it("rounds up past 5 decimals", () => {
    expect(formatCoordinate(77.612306)).toBe("77.61231");
  });
  it("formats integers", () => {
    expect(formatCoordinate(13)).toBe("13.00000");
  });
  it("never emits negative zero", () => {
    expect(formatCoordinate(-0.000001)).toBe("0.00000");
  });
});

describe("buildMessage", () => {
  it("matches the spec example exactly", () => {
    expect(buildMessage("FLOOD", "TRAPPED", 12.9345, 77.6123)).toBe(MESSAGE);
  });
  it("handles negative coordinates", () => {
    expect(buildMessage("FIRE", "INJURED", -33.86882, 151.20929)).toBe(
      "FIRE | INJURED | -33.86882,151.20929",
    );
  });
  it("rejects latitude out of range", () => {
    expect(() => buildMessage("FLOOD", "TRAPPED", 91, 0)).toThrow();
  });
  it("rejects longitude out of range", () => {
    expect(() => buildMessage("FLOOD", "TRAPPED", 0, 181)).toThrow();
  });
  it("rejects NaN coordinates", () => {
    expect(() => buildMessage("FLOOD", "TRAPPED", NaN, 77)).toThrow();
  });
  it("rejects an unknown type", () => {
    expect(() => buildMessage("TSUNAMI" as never, "TRAPPED", 1, 1)).toThrow();
  });
  it("rejects an unknown status", () => {
    expect(() => buildMessage("FLOOD", "LOST" as never, 1, 1)).toThrow();
  });
});

describe("message length", () => {
  it("every type/status combo fits in one SMS even at extreme coordinates", () => {
    for (const [t, s] of combos) {
      const m = buildMessage(t, s, -90, -180);
      expect(gsm7Length(m)).toBeLessThanOrEqual(SMS_SEGMENT_LIMIT);
    }
  });
  it("worst case is 54 GSM-7 units (52 chars + 2 extra for the two pipes)", () => {
    const m = buildMessage("COLLAPSE", "SAFE_BUT_NEED_HELP", -90, -180);
    expect(m.length).toBe(52);
    expect(gsm7Length(m)).toBe(54);
  });
  it("uses only characters that exist in the GSM-7 alphabet", () => {
    for (const [t, s] of combos) {
      expect(buildMessage(t, s, 12.9, 77.6)).toMatch(/^[A-Z0-9_ |,.-]+$/);
    }
  });
});

describe("buildSmsLink", () => {
  it("builds the Android link with ?body=", () => {
    expect(buildSmsLink(NUMBER, MESSAGE, "android")).toBe(
      `sms:${NUMBER}?body=${ENCODED}`,
    );
  });
  it("builds the iOS link with &body=", () => {
    expect(buildSmsLink(NUMBER, MESSAGE, "ios")).toBe(
      `sms:${NUMBER}&body=${ENCODED}`,
    );
  });
  it("round-trips: decoding the body gives back the original message", () => {
    const link = buildSmsLink(NUMBER, MESSAGE, "android");
    expect(decodeURIComponent(link.split("body=")[1])).toBe(MESSAGE);
  });
  it("rejects an invalid gateway number", () => {
    expect(() => buildSmsLink("12ab", MESSAGE, "android")).toThrow();
    expect(() => buildSmsLink("", MESSAGE, "android")).toThrow();
  });
});

describe("detectPlatform", () => {
  it("detects iPhone as ios", () => {
    expect(
      detectPlatform("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"),
    ).toBe("ios");
  });
  it("detects Android", () => {
    expect(detectPlatform("Mozilla/5.0 (Linux; Android 14; Pixel 8)")).toBe(
      "android",
    );
  });
});
describe("buildMessageWithoutLocation", () => {
  it("uses the LOC:UNKNOWN marker in place of coordinates", () => {
    expect(buildMessageWithoutLocation("FLOOD", "TRAPPED")).toBe("FLOOD | TRAPPED | LOC:UNKNOWN");
  });
  it("stays within one SMS segment for every type and status", () => {
    for (const [t, s] of combos) {
      expect(gsm7Length(buildMessageWithoutLocation(t, s))).toBeLessThanOrEqual(SMS_SEGMENT_LIMIT);
    }
  });
  it("rejects an unknown type or status", () => {
    expect(() => buildMessageWithoutLocation("TSUNAMI" as never, "TRAPPED")).toThrow();
    expect(() => buildMessageWithoutLocation("FLOOD", "LOST" as never)).toThrow();
  });
});
