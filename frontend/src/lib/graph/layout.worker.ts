/// <reference lib="webworker" />
// Runs the layout off the main thread: a graph of a few hundred boxes takes long enough to freeze scrolling and typing.
import ELK from "elkjs/lib/elk.bundled.js";
import { computeLayout } from "./layout";
import type { GraphView } from "./model";

const elk = new ELK();

self.onmessage = async (event: MessageEvent<{ id: number; view: GraphView }>) => {
  const { id, view } = event.data;
  try {
    self.postMessage({ id, ok: true, result: await computeLayout(elk, view) });
  } catch (error) {
    self.postMessage({ id, ok: false, error: error instanceof Error ? error.message : String(error) });
  }
};
