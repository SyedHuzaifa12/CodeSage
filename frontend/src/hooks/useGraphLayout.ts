"use client";

import { useEffect, useRef, useState } from "react";
import { computeLayout, type LayoutResult } from "@/lib/graph/layout";
import type { GraphView } from "@/lib/graph/model";

/**
 * `view` and `result` always belong together: they are the last view that was fully laid out. The page draws those, not
 * the newest view, so positions never come from a different picture than the boxes they are applied to.
 */
export interface LayoutState {
  status: "idle" | "working" | "ready" | "error";
  view: GraphView | null;
  result: LayoutResult | null;
  error: string | null;
}

/**
 * Lays a view out in a web worker. Each request carries an id, and an answer for an older request is thrown away, so
 * quickly expanding two folders never lets the first (slower) answer overwrite the second. The previous layout stays
 * on screen while a new one is worked out, which stops the picture flashing blank on every click.
 *
 * If workers are unavailable, or the worker fails, it falls back to computing on the main thread.
 */
export function useGraphLayout(view: GraphView | null): LayoutState {
  const [state, setState] = useState<LayoutState>({ status: "idle", view: null, result: null, error: null });
  const worker = useRef<Worker | null>(null);
  const latest = useRef(0);
  const pending = useRef(new Map<number, (r: { ok: true; result: LayoutResult } | { ok: false; error: string }) => void>());

  useEffect(() => {
    const waiting = pending.current;
    if (typeof Worker === "undefined") return;
    try {
      const w = new Worker(new URL("../lib/graph/layout.worker.ts", import.meta.url));
      w.onmessage = (e: MessageEvent<{ id: number } & ({ ok: true; result: LayoutResult } | { ok: false; error: string })>) => {
        const done = pending.current.get(e.data.id);
        pending.current.delete(e.data.id);
        done?.(e.data);
      };
      w.onerror = () => {
        // A crashed worker answers nothing: fail every waiting request so each falls back to the main thread.
        for (const done of pending.current.values()) done({ ok: false, error: "The layout worker stopped." });
        pending.current.clear();
        w.terminate();
        worker.current = null;
      };
      worker.current = w;
    } catch {
      worker.current = null;
    }
    return () => {
      worker.current?.terminate();
      worker.current = null;
      waiting.clear();
    };
  }, []);

  useEffect(() => {
    if (!view) return;
    const id = ++latest.current;
    setState((s) => ({ ...s, status: "working", error: null }));

    const viaMainThread = async () => {
      const { default: ELK } = await import("elkjs/lib/elk.bundled.js");
      return computeLayout(new ELK(), view);
    };
    const viaWorker = () =>
      new Promise<LayoutResult>((resolve, reject) => {
        const w = worker.current;
        if (!w) return reject(new Error("no worker"));
        pending.current.set(id, (r) => (r.ok ? resolve(r.result) : reject(new Error(r.error))));
        w.postMessage({ id, view });
      });

    viaWorker()
      .catch(viaMainThread)
      .then((result) => {
        if (id === latest.current) setState({ status: "ready", view, result, error: null });
      })
      .catch((error: unknown) => {
        if (id === latest.current) setState((s) => ({ ...s, status: "error", error: error instanceof Error ? error.message : "The layout failed." }));
      });
  }, [view]);

  return state;
}
