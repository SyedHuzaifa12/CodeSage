import type { GraphEdge } from "@/lib/types/workspace";

export interface Point {
  x: number;
  y: number;
}

function seeded(str: string) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619);
  return () => {
    h ^= h << 13;
    h ^= h >>> 17;
    h ^= h << 5;
    return ((h >>> 0) % 10000) / 10000;
  };
}

const cache = new Map<string, Point[]>();

/**
 * Deterministic force-directed layout (Fruchterman–Reingold with
 * degree-weighted gravity, so more-connected nodes sit more centrally —
 * the "sized/placed by connectivity" composition from the design canvas).
 * Seeded from the node set, never Math.random(), so server and client
 * renders agree and the same repository always draws the same map.
 * Intended for the capped (≤ ~40 node) views only.
 */
export function forceLayout(
  nodes: string[],
  edges: GraphEdge[],
  opts: { width?: number; height?: number; iterations?: number; key?: string } = {},
): Point[] {
  const w = opts.width ?? 1000;
  const h = opts.height ?? 760;
  const iterations = opts.iterations ?? 360;
  const cacheKey = `${opts.key ?? ""}:${nodes.join("|")}:${edges.length}:${w}x${h}`;
  const hit = cache.get(cacheKey);
  if (hit) return hit;

  const n = nodes.length;
  const index = new Map(nodes.map((id, i) => [id, i]));
  const degree = new Array<number>(n).fill(0);
  const E: [number, number][] = [];
  for (const e of edges) {
    const a = index.get(e.source);
    const b = index.get(e.target);
    if (a === undefined || b === undefined || a === b) continue;
    E.push([a, b]);
    degree[a]++;
    degree[b]++;
  }
  const maxDegree = Math.max(1, ...degree);
  const rnd = seeded(cacheKey);
  const order = nodes.map((_, i) => i).sort((a, b) => degree[b] - degree[a] || nodes[a].localeCompare(nodes[b]));
  const P: Point[] = new Array(n);
  order.forEach((i, k) => {
    const angle = k * 2.39996;
    const r = 20 + 34 * Math.sqrt(k);
    P[i] = { x: w / 2 + r * Math.cos(angle) + rnd() * 4, y: h / 2 + r * Math.sin(angle) * 0.9 + rnd() * 4 };
  });
  if (n <= 1) {
    if (n === 1) P[0] = { x: w / 2, y: h / 2 };
    cache.set(cacheKey, P);
    return P;
  }

  const K = Math.sqrt((w * h) / n) * 0.58;
  let t = w / 9;
  for (let it = 0; it < iterations; it++) {
    const D = P.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = P[i].x - P[j].x;
        let dy = P[i].y - P[j].y;
        const d = Math.hypot(dx, dy) || 0.01;
        const f = (K * K) / d;
        dx /= d;
        dy /= d;
        D[i].x += dx * f;
        D[i].y += dy * f;
        D[j].x -= dx * f;
        D[j].y -= dy * f;
      }
    }
    for (const [a, b] of E) {
      let dx = P[a].x - P[b].x;
      let dy = P[a].y - P[b].y;
      const d = Math.hypot(dx, dy) || 0.01;
      const f = (d * d) / K;
      dx /= d;
      dy /= d;
      D[a].x -= dx * f;
      D[a].y -= dy * f;
      D[b].x += dx * f;
      D[b].y += dy * f;
    }
    for (let i = 0; i < n; i++) {
      const g = 0.035 + 0.22 * (degree[i] / maxDegree);
      D[i].x += (w / 2 - P[i].x) * g * K * 0.05;
      D[i].y += (h / 2 - P[i].y) * g * K * 0.06;
      const len = Math.hypot(D[i].x, D[i].y) || 1;
      const step = Math.min(len, t);
      P[i].x = Math.min(w - 30, Math.max(30, P[i].x + (D[i].x / len) * step));
      P[i].y = Math.min(h - 30, Math.max(30, P[i].y + (D[i].y / len) * step));
    }
    t = Math.max(1.2, t * 0.985);
  }

  // Compress the radius a little so hubs don't leave an empty centre.
  const cx = P.reduce((a, p) => a + p.x, 0) / n;
  const cy = P.reduce((a, p) => a + p.y, 0) / n;
  const rMax = Math.max(...P.map((p) => Math.hypot(p.x - cx, p.y - cy))) || 1;
  for (const p of P) {
    const dx = p.x - cx;
    const dy = p.y - cy;
    const r0 = Math.hypot(dx, dy);
    if (r0 > 0) {
      const r1 = rMax * Math.pow(r0 / rMax, 0.62);
      p.x = cx + (dx / r0) * r1;
      p.y = cy + (dy / r0) * r1;
    }
  }

  const xs = P.map((p) => p.x);
  const ys = P.map((p) => p.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pad = 70;
  const s = Math.min((w - pad * 2) / (x1 - x0 || 1), (h - pad * 2) / (y1 - y0 || 1));
  const out = P.map((p) => ({
    x: pad + (p.x - x0) * s + (w - pad * 2 - (x1 - x0) * s) / 2,
    y: pad + (p.y - y0) * s + (h - pad * 2 - (y1 - y0) * s) / 2,
  }));
  cache.set(cacheKey, out);
  return out;
}

export const nodeRadius = (degree: number, maxDegree: number) => 5 + Math.sqrt(degree / Math.max(1, maxDegree)) * 13;
