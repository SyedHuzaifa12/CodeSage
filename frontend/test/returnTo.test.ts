import { beforeEach, describe, expect, it } from "vitest";
import { consumeReturnTo, isSafeReturnPath, saveReturnTo } from "@/lib/auth/returnTo";

describe("post-login redirect safety (open-redirect guard)", () => {
  beforeEach(() => window.sessionStorage.clear());

  it("accepts same-site paths", () => {
    for (const path of ["/", "/r/abc/ask?q=hello", "/about#top"]) expect(isSafeReturnPath(path)).toBe(true);
  });

  it("rejects anything that could leave the site", () => {
    for (const path of ["//evil.example", "https://evil.example", "javascript:alert(1)", "/\\evil.example", "evil", "", null, undefined]) {
      expect(isSafeReturnPath(path)).toBe(false);
    }
  });

  it("round-trips a safe path once, then forgets it", () => {
    saveReturnTo("/r/abc/ask");
    expect(consumeReturnTo()).toBe("/r/abc/ask");
    expect(consumeReturnTo()).toBe("/");
  });

  it("never stores or returns an unsafe target", () => {
    saveReturnTo("//evil.example");
    expect(consumeReturnTo()).toBe("/");
    window.sessionStorage.setItem("codesage.oauth.returnTo", "https://evil.example");
    expect(consumeReturnTo()).toBe("/");
  });
});
