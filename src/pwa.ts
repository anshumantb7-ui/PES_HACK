/** Offline support: service worker registration, install prompt and status checks. */

const CACHE_PREFIX = "resq-sos-";

export type OfflineState =
  | { kind: "dev" } // the service worker is only used in production builds
  | { kind: "unsupported" } // no service worker / Cache API (not HTTPS, or an old browser)
  | { kind: "preparing" }
  | { kind: "ready"; version: string };

export async function registerServiceWorker(): Promise<void> {
  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("./sw.js");
  } catch (error) {
    console.error("Service worker registration failed", error);
  }
}

async function readOfflineState(): Promise<OfflineState> {
  if (!import.meta.env.PROD) return { kind: "dev" };
  if (!("serviceWorker" in navigator) || !("caches" in window)) return { kind: "unsupported" };
  const registration = await navigator.serviceWorker.getRegistration();
  if (!registration?.active) return { kind: "preparing" };
  const names = (await caches.keys()).filter((name) => name.startsWith(CACHE_PREFIX));
  const newest = names[names.length - 1];
  if (!newest) return { kind: "preparing" };
  // A cache can exist but be empty (storage was cleared). Ready means the page itself is saved.
  const cache = await caches.open(newest);
  const page = await cache.match(new URL("./", registration.scope).href, { ignoreSearch: true });
  if (!page) return { kind: "preparing" };
  return { kind: "ready", version: newest.slice(CACHE_PREFIX.length) };
}

/** Calls back now and again whenever the offline state may have changed. */
export function watchOfflineState(callback: (state: OfflineState) => void): void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let rechecks = 0;
  const update = (): void => {
    clearTimeout(timer);
    void readOfflineState().then((state) => {
      callback(state);
      // While the copy is still being saved (or being repaired), look again shortly.
      if (state.kind === "preparing" && rechecks++ < 20) timer = setTimeout(update, 1500);
    });
  };
  update();
  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;
  void navigator.serviceWorker.ready.then(update);
  navigator.serviceWorker.addEventListener("controllerchange", update);
}

export function isStandalone(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

type InstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: string }>;
};

let deferredPrompt: InstallPromptEvent | null = null;

/** Android/Chrome only: tells you when the browser allows a one-tap install. */
export function watchInstallPrompt(callback: (available: boolean) => void): void {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event as InstallPromptEvent;
    callback(true);
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    callback(false);
  });
}

export async function promptInstall(): Promise<void> {
  const prompt = deferredPrompt;
  if (!prompt) return;
  deferredPrompt = null;
  await prompt.prompt();
  await prompt.userChoice;
}

/** Asks the browser not to delete the saved copy when storage is low. Best effort. */
export async function requestPersistentStorage(): Promise<void> {
  try {
    await navigator.storage?.persist?.();
  } catch {
    // not supported; ignore
  }
}
