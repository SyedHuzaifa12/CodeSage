"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

const KEY = "cs-theme";
type Theme = "light" | "dark";

/** Light/dark switch. The initial theme is applied before paint by a script in layout.tsx; this only flips and remembers it. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light");
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* private mode: the choice just won't be remembered */
    }
    setTheme(next);
  }

  const dark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Switch to light theme" : "Switch to dark theme"}
      className="grid h-9 w-9 place-items-center rounded-[8px] text-text-secondary transition-colors hover:bg-surface-2 hover:text-text-primary"
    >
      {dark ? <Sun size={17} strokeWidth={1.6} aria-hidden="true" /> : <Moon size={17} strokeWidth={1.6} aria-hidden="true" />}
    </button>
  );
}
