import { describe, expect, it } from "vitest";
import { describeGeoError } from "./geo";

describe("describeGeoError", () => {
  it("maps code 1 to denied", () => {
    expect(describeGeoError(1).kind).toBe("denied");
  });
  it("maps code 2 to unavailable", () => {
    expect(describeGeoError(2).kind).toBe("unavailable");
  });
  it("maps code 3 to timeout", () => {
    expect(describeGeoError(3).kind).toBe("timeout");
  });
  it("falls back to unavailable for unknown codes", () => {
    expect(describeGeoError(99).kind).toBe("unavailable");
  });
  it("always gives a non-empty message", () => {
    for (const code of [1, 2, 3, 99]) {
      expect(describeGeoError(code).message.length).toBeGreaterThan(10);
    }
  });
});
