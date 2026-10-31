import "./style.css";
import {
  EMERGENCY_TYPES,
  SMS_SEGMENT_LIMIT,
  STATUSES,
  type EmergencyType,
  type VictimStatus,
} from "./constants";
import { startLocationWatch, type GeoFix } from "./geo";
import {
  buildMessage,
  buildMessageWithoutLocation,
  buildSmsLink,
  detectPlatform,
  formatCoordinate,
  gsm7Length,
  type SmsPlatform,
} from "./message";
import { computeReadiness, type LocationPermission } from "./readiness";
import {
  isStandalone,
  promptInstall,
  registerServiceWorker,
  requestPersistentStorage,
  watchInstallPrompt,
  watchOfflineState,
  type OfflineState,
} from "./pwa";

const GATEWAY_NUMBER: string = (import.meta.env.VITE_GATEWAY_NUMBER ?? "").trim();

function el<T extends HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing element #${id}`);
  return node as T;
}

/** Elements that only exist in the dev panel (removed from production builds). */
function optional<T extends HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

const typeSelect = el<HTMLSelectElement>("type");
const statusSelect = el<HTMLSelectElement>("status");
const coordsEl = el<HTMLElement>("coords");
const previewEl = el<HTMLElement>("preview");
const metaEl = el<HTMLElement>("meta");
const sosButton = el<HTMLButtonElement>("sos");
const locateButton = el<HTMLButtonElement>("locate");
const noGpsButton = el<HTMLButtonElement>("nogps");
const networkEl = el<HTMLElement>("st-network");
const cacheEl = el<HTMLElement>("st-cache");
const appEl = el<HTMLElement>("st-app");
const installButton = el<HTMLButtonElement>("install");
const iosHint = el<HTMLElement>("ios-hint");
const readyEl = el<HTMLElement>("ready");
const checklistEl = el<HTMLElement>("checklist");

const devOn = import.meta.env.DEV;
const platformSelect = devOn ? optional<HTMLSelectElement>("platform") : null;
const latInput = devOn ? optional<HTMLInputElement>("lat") : null;
const lonInput = devOn ? optional<HTMLInputElement>("lon") : null;
const useTestInput = devOn ? optional<HTMLInputElement>("useTest") : null;
const linkEl = devOn ? optional<HTMLElement>("link") : null;

// ---------- location state ----------
let fix: GeoFix | null = null;
let geoProblem = "";
let searching = true;
let sendWithoutLocation = false;
let stopWatch: () => void = () => {};

function fillSelect(select: HTMLSelectElement, values: readonly string[]): void {
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value.replace(/_/g, " ");
    select.append(option);
  }
}

function currentCoords(): { lat: number; lon: number; label: string } | null {
  if (useTestInput?.checked && latInput && lonInput) {
    return { lat: parseFloat(latInput.value), lon: parseFloat(lonInput.value), label: "test values" };
  }
  if (fix) {
    const accuracy = Math.round(fix.accuracy);
    const warn = accuracy > 50 ? ", low accuracy: move near a window or outdoors" : "";
    return { lat: fix.lat, lon: fix.lon, label: `GPS ±${accuracy} m${warn}` };
  }
  return null;
}

function currentPlatform(): SmsPlatform {
  return (platformSelect?.value as SmsPlatform | undefined) ?? detectPlatform(navigator.userAgent);
}

function refresh(): void {
  sosButton.disabled = true;
  delete sosButton.dataset.link;
  if (linkEl) linkEl.textContent = "";

  const type = typeSelect.value as EmergencyType;
  const status = statusSelect.value as VictimStatus;
  const coords = currentCoords();

  // The "send without location" option only appears once GPS has failed.
  noGpsButton.hidden = !(!coords && !searching && !sendWithoutLocation);

  let message: string;
  try {
    if (coords) {
      message = buildMessage(type, status, coords.lat, coords.lon);
      coordsEl.textContent = `Location: ${formatCoordinate(coords.lat)}, ${formatCoordinate(coords.lon)} (${coords.label})`;
    } else if (sendWithoutLocation) {
      message = buildMessageWithoutLocation(type, status);
      coordsEl.textContent = "Location: not included (no GPS). Responders will call you back.";
    } else {
      previewEl.classList.remove("error");
      previewEl.textContent = "Waiting for GPS location…";
      metaEl.textContent = "";
      coordsEl.textContent = searching && !geoProblem ? "Location: getting GPS fix…" : geoProblem;
      return;
    }
  } catch (error) {
    previewEl.textContent = (error as Error).message;
    previewEl.classList.add("error");
    metaEl.textContent = "";
    coordsEl.textContent = "Location: unavailable";
    return;
  }

  previewEl.classList.remove("error");
  previewEl.textContent = message;
  metaEl.textContent = `${message.length} characters · ${gsm7Length(message)} GSM-7 units (limit ${SMS_SEGMENT_LIMIT})`;

  try {
    const link = buildSmsLink(GATEWAY_NUMBER, message, currentPlatform());
    if (linkEl) linkEl.textContent = link;
    sosButton.dataset.link = link;
    sosButton.disabled = false;
  } catch (error) {
    previewEl.textContent = (error as Error).message;
    previewEl.classList.add("error");
  }
}

function startLocating(): void {
  stopWatch();
  fix = null;
  geoProblem = "";
  searching = true;
  sendWithoutLocation = false;
  refresh();
  stopWatch = startLocationWatch({
    onFix: (next) => {
      fix = next;
      geoProblem = "";
      searching = false;
      sendWithoutLocation = false;
      refresh();
      renderReadiness();
    },
    onProblem: (problem) => {
      searching = false;
      // Keep the last good fix on a temporary problem; clear it only if permission is gone.
      if (problem.kind === "denied" || problem.kind === "insecure" || problem.kind === "unsupported") {
        fix = null;
      }
      geoProblem = problem.message;
      refresh();
      renderReadiness();
    },
  });
}

// ---------- phone status (network, offline cache, install, readiness) ----------
let offlineState: OfflineState = { kind: "preparing" };
let permission: LocationPermission = "unknown";

function renderReadiness(): void {
  const result = computeReadiness({
    offline: offlineState,
    permission,
    hasFix: fix !== null,
    standalone: isStandalone(),
  });
  readyEl.textContent = result.ready
    ? "Ready: this phone can send an SOS with no internet."
    : "Not ready yet. Finish these while you still have internet:";
  readyEl.className = `ready ${result.ready ? "good" : "warn"}`;
  checklistEl.replaceChildren(
    ...result.items.map((item) => {
      const li = document.createElement("li");
      li.className = item.ok ? "good" : item.required ? "warn" : "";
      li.textContent = `${item.ok ? "✓" : "○"} ${item.label}${item.required ? "" : " (optional)"}`;
      if (!item.ok && item.hint) {
        const hint = document.createElement("span");
        hint.className = "hint";
        hint.textContent = item.hint;
        li.append(hint);
      }
      return li;
    }),
  );
}

async function watchPermission(): Promise<void> {
  try {
    const status = await navigator.permissions.query({ name: "geolocation" });
    const sync = (): void => {
      permission = status.state;
      renderReadiness();
    };
    sync();
    status.addEventListener("change", sync);
  } catch {
    // Permissions API missing (some iOS versions): a received GPS fix proves permission instead.
  }
}

function renderNetwork(): void {
  const online = navigator.onLine;
  networkEl.textContent = online ? "Connected" : "No internet (SMS still works)";
  networkEl.className = online ? "" : "warn";
}

function renderOffline(state: OfflineState): void {
  offlineState = state;
  renderReadiness();
  switch (state.kind) {
    case "ready":
      cacheEl.textContent = `Yes, saved on this phone (v${state.version})`;
      cacheEl.className = "good";
      break;
    case "preparing":
      cacheEl.textContent = "Saving… keep internet on for a moment";
      cacheEl.className = "warn";
      break;
    case "unsupported":
      cacheEl.textContent = "No (needs the https:// link)";
      cacheEl.className = "warn";
      break;
    case "dev":
      cacheEl.textContent = "Off in dev mode";
      cacheEl.className = "";
      break;
  }
}

function renderApp(): void {
  const standalone = isStandalone();
  appEl.textContent = standalone ? "Installed app" : "Browser tab";
  iosHint.hidden = standalone || detectPlatform(navigator.userAgent) !== "ios";
}

// ---------- wiring ----------
fillSelect(typeSelect, EMERGENCY_TYPES);
fillSelect(statusSelect, STATUSES);
if (platformSelect) platformSelect.value = detectPlatform(navigator.userAgent);

for (const control of [typeSelect, statusSelect, platformSelect, latInput, lonInput, useTestInput]) {
  control?.addEventListener("input", refresh);
}
locateButton.addEventListener("click", startLocating);
noGpsButton.addEventListener("click", () => {
  sendWithoutLocation = true;
  refresh();
});

sosButton.addEventListener("click", () => {
  const link = sosButton.dataset.link ?? "";
  if (link.startsWith("sms:")) {
    window.location.href = link; // opens the SMS app; the victim presses Send
  }
});

installButton.addEventListener("click", () => {
  installButton.hidden = true; // the browser offers it again if the person dismisses the prompt
  void promptInstall();
});
watchInstallPrompt((available) => {
  installButton.hidden = !available;
});

window.addEventListener("online", renderNetwork);
window.addEventListener("offline", renderNetwork);
renderNetwork();
renderApp();
renderOffline(offlineState);
void watchPermission();
watchOfflineState(renderOffline);
void registerServiceWorker().then(requestPersistentStorage);

refresh();
startLocating();
