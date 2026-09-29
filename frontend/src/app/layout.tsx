import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

/**
 * Loaded via a Google Fonts <link> rather than next/font/google (Design
 * System §14.4 names this as an "equally valid Sprint 7 implementation
 * choice"). Switched from next/font after next/font's Google-fonts-metrics
 * fetch for `Newsreader` failed to resolve in this environment (Next
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

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,500;0,600;0,700;1,500;1,600;1,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap"
        />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
