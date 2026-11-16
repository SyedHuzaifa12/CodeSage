/**
 * Cloudflare Turnstile (bot protection on guest creation).
 *
 * Enabled only when NEXT_PUBLIC_TURNSTILE_SITE_KEY is set; without it (local
 * development) no token is sent and the backend — which only skips the check
 * in development — accepts the guest. The widget runs in "interaction-only"
 * mode: invisible unless Cloudflare decides the visitor needs a challenge.
 */

const SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
const SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
const TIMEOUT_MS = 60_000;

interface TurnstileApi {
  render(
    container: HTMLElement,
    options: {
      sitekey: string;
      appearance?: "always" | "execute" | "interaction-only";
      callback: (token: string) => void;
      "error-callback": () => void;
      "expired-callback"?: () => void;
    },
  ): string;
  remove(widgetId: string): void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

let scriptPromise: Promise<TurnstileApi> | undefined;

function loadScript(): Promise<TurnstileApi> {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (!scriptPromise) {
    scriptPromise = new Promise<TurnstileApi>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = SCRIPT_SRC;
      script.async = true;
      script.onload = () =>
        window.turnstile ? resolve(window.turnstile) : reject(new Error("The bot-protection widget failed to load."));
      script.onerror = () => {
        scriptPromise = undefined; // allow a retry on the next attempt
        reject(new Error("Couldn't load the bot-protection widget. Check your connection and try again."));
      };
      document.head.appendChild(script);
    });
  }
  return scriptPromise;
}

export const turnstileEnabled = Boolean(SITE_KEY);

/** Resolves with a single-use challenge token, or `undefined` when Turnstile is not configured. */
export async function getTurnstileToken(): Promise<string | undefined> {
  if (!SITE_KEY || typeof window === "undefined") return undefined;
  const turnstile = await loadScript();

  return new Promise<string>((resolve, reject) => {
    const host = document.createElement("div");
    host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:60";
    document.body.appendChild(host);

    let widgetId: string | undefined;
    const finish = (settle: () => void) => {
      clearTimeout(timer);
      if (widgetId) turnstile.remove(widgetId);
      host.remove();
      settle();
    };
    const timer = setTimeout(
      () => finish(() => reject(new Error("The bot-protection check timed out. Please reload and try again."))),
      TIMEOUT_MS,
    );

    widgetId = turnstile.render(host, {
      sitekey: SITE_KEY,
      appearance: "interaction-only",
      callback: (token) => finish(() => resolve(token)),
      "error-callback": () => finish(() => reject(new Error("The bot-protection check failed. Please reload and try again."))),
    });
  });
}
