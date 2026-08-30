/**
 * The numbered-index nav (Design System §16/§17): "01 Overview ... 06
 * Reports". Rail order is fixed — Ask sits second, directly under
 * Overview, the one deliberate IA decision that makes Ask the flagship.
 */
export interface NavItem {
  num: string;
  label: string;
  path: (id: string) => string;
  /** Reachable even before indexing finishes (§1: raw tree, no intelligence overlay). */
  reachableBeforeReady: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { num: "01", label: "Overview", path: (id) => `/r/${id}`, reachableBeforeReady: true },
  { num: "02", label: "Ask", path: (id) => `/r/${id}/ask`, reachableBeforeReady: false },
  { num: "03", label: "Explorer", path: (id) => `/r/${id}/explorer`, reachableBeforeReady: true },
  { num: "04", label: "Search", path: (id) => `/r/${id}/search`, reachableBeforeReady: false },
  { num: "05", label: "Graph", path: (id) => `/r/${id}/graph`, reachableBeforeReady: false },
  { num: "06", label: "Reports", path: (id) => `/r/${id}/reports`, reachableBeforeReady: false },
];

export const SETTINGS_PATH = (id: string) => `/r/${id}/settings`;
