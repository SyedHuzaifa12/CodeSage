"use client";

import { useEffect, useState } from "react";

/** Design System §11 breakpoints: >=1280 desktop, 900-1279 tablet, <900 mobile. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia(query);
    setMatches(mql.matches);
    const listener = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener("change", listener);
    return () => mql.removeEventListener("change", listener);
  }, [query]);

  return matches;
}

export function useBreakpoint(): "desktop" | "tablet" | "mobile" {
  const isTablet = useMediaQuery("(min-width: 900px) and (max-width: 1279px)");
  const isMobile = useMediaQuery("(max-width: 899px)");
  if (isMobile) return "mobile";
  if (isTablet) return "tablet";
  return "desktop";
}

export function usePrefersReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}
