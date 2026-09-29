import { API_BASE_URL } from "@/lib/api/client";

export interface HealthData {
  app_name: string;
  version: string;
  environment: string;
  uptime_seconds: number;
  dependencies: Record<string, boolean>;
}

/**
 * GET /health — unversioned (outside /api/v1) and returns its envelope
 * with HTTP 503 when any dependency is down, so it bypasses apiRequest's
 * success-only unwrapping and reports the degraded payload as data.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<{ healthy: boolean; data: HealthData | null }> {
  const res = await fetch(`${API_BASE_URL}/health`, { cache: "no-store", signal });
  const json = (await res.json().catch(() => null)) as { success?: boolean; data?: HealthData } | null;
  return { healthy: res.ok && Boolean(json?.success), data: json?.data ?? null };
}
