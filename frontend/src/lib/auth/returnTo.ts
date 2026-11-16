const KEY = "codesage.oauth.returnTo";

/** Only same-site absolute paths: anything else (`//evil.example`, `https://…`) would be an open redirect. */
export function isSafeReturnPath(path: string | null | undefined): path is string {
  return typeof path === "string" && path.startsWith("/") && !path.startsWith("//") && !path.includes("\\");
}

/** Remember where to send the user after GitHub login completes. */
export function saveReturnTo(path: string): void {
  try {
    if (isSafeReturnPath(path)) window.sessionStorage.setItem(KEY, path);
  } catch {
    /* storage blocked: fall back to the home page */
  }
}

/** Read and clear the remembered path; `/` if there is none or it is unsafe. */
export function consumeReturnTo(): string {
  try {
    const path = window.sessionStorage.getItem(KEY);
    window.sessionStorage.removeItem(KEY);
    return isSafeReturnPath(path) ? path : "/";
  } catch {
    return "/";
  }
}
