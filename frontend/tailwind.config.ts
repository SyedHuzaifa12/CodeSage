import type { Config } from "tailwindcss";

/**
 * Tailwind configured entirely from CodeSage's design tokens (Sprint 7
 * Design System §7), expressed as CSS custom properties in
 * src/app/globals.css — never hardcoded Tailwind defaults. Editorial
 * Graph is a single, permanent dark visual language (no light mode).
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
        display: ["var(--font-newsreader)", "Georgia", "serif"],
        sans: ["var(--font-plex-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "monospace"],
      },
      fontSize: {
        masthead: ["52px", { lineHeight: "0.98", letterSpacing: "-0.02em" }],
        "masthead-lg": ["58px", { lineHeight: "0.98", letterSpacing: "-0.02em" }],
        display: ["34px", { lineHeight: "1.05", letterSpacing: "-0.012em" }],
        h1: ["22px", { lineHeight: "1.2" }],
        h2: ["17px", { lineHeight: "1.3" }],
        lede: ["19px", { lineHeight: "1.6" }],
        body: ["13.5px", { lineHeight: "1.6" }],
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
