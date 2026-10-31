import type { OfflineState } from "./pwa";

export type LocationPermission = "granted" | "prompt" | "denied" | "unknown";

export type ReadinessItem = { label: string; ok: boolean; required: boolean; hint: string };
export type Readiness = { ready: boolean; items: ReadinessItem[] };

type Input = {
  offline: OfflineState;
  permission: LocationPermission;
  hasFix: boolean; // a GPS fix has arrived in this session (proves permission even if the Permissions API is missing)
  standalone: boolean;
};

function offlineHint(offline: OfflineState): string {
  switch (offline.kind) {
    case "ready":
      return "";
    case "preparing":
      return "Keep internet on until this says saved.";
    case "unsupported":
      return "Open the https:// link in Chrome or Safari.";
    case "dev":
      return "Only works in the deployed app.";
  }
}

function locationHint(permission: LocationPermission): string {
  switch (permission) {
    case "denied":
      return "Turn Location on for this site in the browser settings.";
    case "prompt":
      return "Tap Allow when the phone asks for location.";
    default:
      return "Tap Update my location and allow it.";
  }
}

/** Decides whether this phone is set up to send an SOS with no internet. */
export function computeReadiness(input: Input): Readiness {
  const locationOk = input.permission === "granted" || input.hasFix;
  const items: ReadinessItem[] = [
    {
      label: "Saved for offline use",
      ok: input.offline.kind === "ready",
      required: true,
      hint: offlineHint(input.offline),
    },
    {
      label: "Location allowed",
      ok: locationOk,
      required: true,
      hint: locationOk ? "" : locationHint(input.permission),
    },
    {
      label: "Added to home screen",
      ok: input.standalone,
      required: false,
      hint: input.standalone ? "" : "Recommended: use Install app or Share > Add to Home Screen.",
    },
  ];
  return { ready: items.filter((item) => item.required).every((item) => item.ok), items };
}
