import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GuestBanner } from "@/components/auth/GuestBanner";
import { SignInModal } from "@/components/auth/SignInModal";
import { ApiError } from "@/lib/api/client";
import { demoQuestions } from "@/lib/demo";
import type { QuotaStatus } from "@/lib/types/auth";

const auth = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));
vi.mock("@/context/AuthContext", () => ({ useAuth: () => auth.current }));

const quota = (overrides: Partial<QuotaStatus> = {}): QuotaStatus => ({
  repositories_used: 0,
  repositories_limit: 1,
  questions_used_today: 3,
  questions_limit_daily: 15,
  ...overrides,
});

afterEach(cleanup);

describe("GuestBanner", () => {
  it("tells a guest what is left and how to get more", () => {
    const openSignIn = vi.fn();
    auth.current = { status: "ready", isGuest: true, quota: quota(), openSignIn };
    render(<GuestBanner />);

    expect(screen.getByRole("status").textContent).toContain("1 of 1");
    expect(screen.getByRole("status").textContent).toContain("12"); // 15 - 3 questions left
    fireEvent.click(screen.getByRole("button", { name: /sign in with github/i }));
    expect(openSignIn).toHaveBeenCalledOnce();
  });

  it("shows zero repositories left once the free one is used, never a negative number", () => {
    auth.current = { status: "ready", isGuest: true, quota: quota({ repositories_used: 2, questions_used_today: 99 }), openSignIn: vi.fn() };
    render(<GuestBanner />);
    expect(screen.getByRole("status").textContent).toContain("0 of 1");
    expect(screen.getByRole("status").textContent).not.toContain("-");
  });

  it.each([
    ["a signed-in member", { status: "ready", isGuest: false, quota: quota() }],
    ["while the session is still loading", { status: "loading", isGuest: false, quota: undefined }],
    ["when the session failed", { status: "error", isGuest: false, quota: undefined }],
  ])("is hidden for %s", (_label, state) => {
    auth.current = { ...state, openSignIn: vi.fn() };
    const { container } = render(<GuestBanner />);
    expect(container.firstChild).toBeNull();
  });
});

describe("SignInModal", () => {
  const baseProps = { open: true, onClose: vi.fn() };

  it("explains why the user is being asked, using the backend's own message", () => {
    render(<SignInModal {...baseProps} reason="Guests can index one repository." onSignIn={vi.fn()} />);
    expect(screen.getByText("Guests can index one repository.")).toBeTruthy();
  });

  it("starts the GitHub flow when the button is pressed", async () => {
    const onSignIn = vi.fn().mockResolvedValue(undefined);
    render(<SignInModal {...baseProps} onSignIn={onSignIn} />);
    fireEvent.click(screen.getByRole("button", { name: /continue with github/i }));
    await waitFor(() => expect(onSignIn).toHaveBeenCalledOnce());
  });

  it("says plainly when GitHub sign-in isn't configured, and lets the user try again", async () => {
    const unavailable = new ApiError("Login is not configured.", { status: 503, errors: [{ code: "SERVICE_UNAVAILABLE" }] });
    const onSignIn = vi.fn().mockRejectedValue(unavailable);
    render(<SignInModal {...baseProps} onSignIn={onSignIn} />);

    fireEvent.click(screen.getByRole("button", { name: /continue with github/i }));

    expect((await screen.findByRole("alert")).textContent).toContain("isn't available");
    // The button is usable again rather than stuck in a spinner.
    await waitFor(() => expect(screen.getByRole("button", { name: /continue with github/i }).hasAttribute("disabled")).toBe(false));
  });

  it("closes without signing in when the user says not now", () => {
    const onClose = vi.fn();
    render(<SignInModal open onClose={onClose} onSignIn={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /not now/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("promises not to read repositories (the OAuth scope is identity-only)", () => {
    render(<SignInModal {...baseProps} onSignIn={vi.fn()} />);
    expect(screen.getByText(/never reads your repositories/i)).toBeTruthy();
  });
});

describe("demoQuestions", () => {
  it("uses Express-specific questions only for the Express demo", () => {
    expect(demoQuestions("https://github.com/expressjs/express")[0]).toMatch(/Express/);
    expect(demoQuestions("https://github.com/expressjs/express/")[0]).toMatch(/Express/);
  });

  it("falls back to generic questions for any other repository, never wrong ones", () => {
    for (const url of ["https://github.com/expressjs/cors", "https://github.com/pallets/flask", null, undefined]) {
      expect(demoQuestions(url).some((q) => /Express|app\.listen/.test(q))).toBe(false);
    }
  });
});
