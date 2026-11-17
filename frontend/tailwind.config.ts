import type { Config } from "tailwindcss";

/**
 * Tailwind configured entirely from CodeSage's design tokens (Sprint 7
 * Design System §7), expressed as CSS custom properties in
 * src/app/globals.css — never hardcoded Tailwind defaults. Light is the
 * default theme; dark is opt-in via <html data-theme="dark">.
 */
const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--cs-bg)",
        "surface-1": "var(--cs-surface-1)",
        "surface-2": "var(--cs-surface-2)",
        "surface-3": "var(--cs-surface-3)",
        "border-subtle": "var(--cs-border-subtle)",
        "border-strong": "var(--cs-border-strong)",
        "text-primary": "var(--cs-text-primary)",
        "text-secondary": "var(--cs-text-secondary)",
        "text-tertiary": "var(--cs-text-tertiary)",
        violet: "var(--cs-accent-violet)",
        cyan: "var(--cs-accent-cyan)",
        success: "var(--cs-success)",
        warning: "var(--cs-warning)",
        danger: "var(--cs-danger)",
        info: "var(--cs-info)",
      },
      fontFamily: {
        display: ["var(--font-display)", "system-ui", "sans-serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      fontSize: {
        masthead: ["38px", { lineHeight: "1.15", letterSpacing: "-0.022em" }],
        "masthead-lg": ["44px", { lineHeight: "1.12", letterSpacing: "-0.024em" }],
        display: ["28px", { lineHeight: "1.2", letterSpacing: "-0.018em" }],
        h1: ["22px", { lineHeight: "1.25" }],
        h2: ["17px", { lineHeight: "1.3" }],
        lede: ["16px", { lineHeight: "1.6" }],
        body: ["14px", { lineHeight: "1.55" }],
        small: ["12px", { lineHeight: "1.5" }],
        micro: ["11px", { lineHeight: "1.4" }],
      },
      borderRadius: {
        sm: "6px",
        md: "10px",
        lg: "14px",
        pill: "999px",
      },
      spacing: {
        "4.5": "18px",
      },
      transitionTimingFunction: {
        cs: "cubic-bezier(0.2,0,0,1)",
      },
      transitionDuration: {
        micro: "120ms",
        standard: "200ms",
        panel: "280ms",
      },
      keyframes: {
        "cs-shimmer": {
          "0%": { backgroundPosition: "-200px 0" },
          "100%": { backgroundPosition: "200px 0" },
        },
        "cs-fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
      },
      animation: {
        "cs-shimmer": "cs-shimmer 1.6s ease-in-out infinite",
        "cs-fade-in": "cs-fade-in 200ms cubic-bezier(0.2,0,0,1)",
      },
    },
  },
  plugins: [],
};

export default config;
