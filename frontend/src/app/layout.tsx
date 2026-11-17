import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

/**
 * Loaded via a Google Fonts <link> rather than next/font/google (Design
 * System §14.4 names this as an "equally valid Sprint 7 implementation
 * choice"). Switched from next/font after next/font's Google-fonts-metrics
 * fetch for the display font failed to resolve in this environment (Next
 * 14.2.35 + Node 24) and, instead of failing gracefully, retried in a loop
 * that leaked memory until the dev server crashed with an OOM. A <link>
 * tag has no such fetch-at-compile-time step, so it can't hit that failure
 * mode. The CSS variables below are consumed identically by
 * tailwind.config.ts / globals.css either way — no other file changed.
 */
export const metadata: Metadata = {
  title: "CodeSage — Repository Intelligence",
  description: "AI-powered repository intelligence and grounded Q&A for engineering teams.",
};

// ?theme=dark|light overrides the saved choice for that visit only (handy for sharing a link or checking both themes).
const THEME_INIT = `try{var q=new URLSearchParams(location.search).get("theme");var t=q||localStorage.getItem("cs-theme");document.documentElement.setAttribute("data-theme",t==="dark"?"dark":"light")}catch(e){document.documentElement.setAttribute("data-theme","light")}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Sets the theme before first paint so there is no light/dark flash. Light unless the user chose dark. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
        />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
