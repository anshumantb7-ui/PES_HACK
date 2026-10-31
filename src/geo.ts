export type GeoFix = { lat: number; lon: number; accuracy: number; timestamp: number };

export type GeoErrorKind = "insecure" | "unsupported" | "denied" | "unavailable" | "timeout";

export type GeoProblem = { kind: GeoErrorKind; message: string };

export type GeoHandlers = {
  onFix: (fix: GeoFix) => void;
  onProblem: (problem: GeoProblem) => void;
};

/** Maps a GeolocationPositionError code (1, 2, 3) to a message a stressed person can act on. */
export function describeGeoError(code: number): GeoProblem {
  switch (code) {
    case 1:
      return {
        kind: "denied",
        message:
          "Location permission is off. Allow Location for this site in your browser settings, then tap Update.",
      };
    case 3:
      return { kind: "timeout", message: "Still looking for GPS. Move to open sky or near a window." };
    default:
      return {
        kind: "unavailable",
        message: "No GPS signal yet. Turn Location ON and move near a window or outdoors.",
      };
  }
}

/**
 * Starts reading the phone's GPS continuously and reports every fix, so the
 * coordinates improve as the GPS settles. Returns a function that stops it.
 * Needs HTTPS (or localhost) and the user's permission.
 */
export function startLocationWatch(handlers: GeoHandlers): () => void {
  if (!window.isSecureContext) {
    handlers.onProblem({
      kind: "insecure",
      message: "GPS is blocked: this page is not HTTPS. Open the https:// link, not http://192.168.x.x.",
    });
    return () => {};
  }
  if (!("geolocation" in navigator)) {
    handlers.onProblem({ kind: "unsupported", message: "This browser has no GPS support." });
    return () => {};
  }
  const id = navigator.geolocation.watchPosition(
    (pos) =>
      handlers.onFix({
        lat: pos.coords.latitude,
        lon: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
        timestamp: pos.timestamp,
      }),
    (err) => handlers.onProblem(describeGeoError(err.code)),
    { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 },
  );
  return () => navigator.geolocation.clearWatch(id);
}
