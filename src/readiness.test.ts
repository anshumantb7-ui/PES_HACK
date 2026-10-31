import { describe, expect, it } from "vitest";
import { computeReadiness } from "./readiness";

const ready = { kind: "ready", version: "abc" } as const;

describe("computeReadiness", () => {
  it("is ready when saved offline and location is granted, even in a browser tab", () => {
    const r = computeReadiness({ offline: ready, permission: "granted", hasFix: true, standalone: false });
    expect(r.ready).toBe(true);
    expect(r.items.find((i) => i.label.includes("home screen"))?.ok).toBe(false);
  });
  it("is not ready while the offline copy is still being saved", () => {
    const r = computeReadiness({ offline: { kind: "preparing" }, permission: "granted", hasFix: true, standalone: true });
    expect(r.ready).toBe(false);
    expect(r.items[0]?.hint).toContain("internet");
  });
  it("is not ready when location is denied, and says how to fix it", () => {
    const r = computeReadiness({ offline: ready, permission: "denied", hasFix: false, standalone: true });
    expect(r.ready).toBe(false);
    expect(r.items[1]?.hint).toContain("settings");
  });
  it("accepts a received GPS fix as proof of permission when the Permissions API is unavailable", () => {
    const r = computeReadiness({ offline: ready, permission: "unknown", hasFix: true, standalone: false });
    expect(r.ready).toBe(true);
  });
  it("is never ready in dev mode or on an insecure page", () => {
    expect(computeReadiness({ offline: { kind: "dev" }, permission: "granted", hasFix: true, standalone: true }).ready).toBe(false);
    expect(computeReadiness({ offline: { kind: "unsupported" }, permission: "granted", hasFix: true, standalone: true }).ready).toBe(false);
  });
});
