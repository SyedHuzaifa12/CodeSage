import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeToggle } from "@/components/nav/ThemeToggle";
import { NAV_ICONS } from "@/components/nav/NavRail";
import { NAV_ITEMS } from "@/lib/nav";

const root = () => document.documentElement;

beforeEach(() => {
  localStorage.clear();
  root().removeAttribute("data-theme");
});
afterEach(cleanup);

describe("ThemeToggle", () => {
  it("offers dark when the page is light, and switches to it", () => {
    root().setAttribute("data-theme", "light");
    render(<ThemeToggle />);

    fireEvent.click(screen.getByRole("button", { name: /switch to dark theme/i }));

    expect(root().getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("cs-theme")).toBe("dark");
    expect(screen.getByRole("button", { name: /switch to light theme/i })).toBeTruthy();
  });

  it("starts from whatever theme the page already applied before paint", () => {
    root().setAttribute("data-theme", "dark");
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: /switch to light theme/i })).toBeTruthy();
  });

  it("switches back to light and remembers it", () => {
    root().setAttribute("data-theme", "dark");
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: /switch to light theme/i }));
    expect(root().getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem("cs-theme")).toBe("light");
  });

  it("still switches when the browser blocks storage (private mode)", () => {
    root().setAttribute("data-theme", "light");
    const blocked = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<ThemeToggle />);

    fireEvent.click(screen.getByRole("button", { name: /switch to dark theme/i }));

    expect(root().getAttribute("data-theme")).toBe("dark"); // the choice applies for this visit; it just isn't remembered
    blocked.mockRestore();
  });
});

describe("navigation", () => {
  it("has an icon for every section, so no item renders as a bare label", () => {
    for (const item of NAV_ITEMS) expect(NAV_ICONS[item.label], `missing icon for ${item.label}`).toBeTruthy();
  });
});
