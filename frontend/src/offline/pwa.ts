import { setUpdateReady } from "./appUpdate";

// PR25E S6: service-worker registration (registerType "prompt"). Kept out of
// appUpdate.ts so tests never import the plugin's virtual module.
export async function registerServiceWorker(): Promise<void> {
  if (!("serviceWorker" in navigator)) return;
  const { registerSW } = await import("virtual:pwa-register");
  const update = registerSW({
    onNeedRefresh() {
      // updateSW(true) activates the waiting worker and reloads the page.
      setUpdateReady(() => update(true));
    },
  });
}

/** Ask the browser not to evict IndexedDB (design 13.1). Best effort. */
export async function requestPersistentStorage(): Promise<boolean> {
  try {
    if (!navigator.storage?.persist) return false;
    if (await navigator.storage.persisted?.()) return true;
    return await navigator.storage.persist();
  } catch {
    return false;
  }
}

// ---- install prompt (Chromium; iOS has no event, operators use Share > Add) --
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}
let deferred: BeforeInstallPromptEvent | null = null;
const installListeners = new Set<() => void>();

export function captureInstallPrompt(): () => void {
  const onPrompt = (e: Event) => {
    e.preventDefault();
    deferred = e as BeforeInstallPromptEvent;
    installListeners.forEach((l) => l());
  };
  const onInstalled = () => {
    deferred = null;
    installListeners.forEach((l) => l());
  };
  window.addEventListener("beforeinstallprompt", onPrompt);
  window.addEventListener("appinstalled", onInstalled);
  return () => {
    window.removeEventListener("beforeinstallprompt", onPrompt);
    window.removeEventListener("appinstalled", onInstalled);
  };
}
export function canInstall(): boolean {
  return deferred !== null;
}
export function subscribeInstall(l: () => void): () => void {
  installListeners.add(l);
  return () => installListeners.delete(l);
}
export async function promptInstall(): Promise<void> {
  const e = deferred;
  if (!e) return;
  deferred = null;
  await e.prompt();
  await e.userChoice.catch(() => undefined);
  installListeners.forEach((l) => l());
}
