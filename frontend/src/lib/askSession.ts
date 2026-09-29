import type { AskResponseData } from "@/lib/types/ai";
import type { ApiError } from "@/lib/api/client";

/**
 * Session-only Ask history, one list per repository.
 *
 * Lives outside React so turns survive navigating between pages (and an
 * in-flight answer keeps resolving while the user is on another page),
 * but is intentionally NOT persisted: the backend writes conversation
 * rows but exposes no read API, and does not use earlier turns as
 * context, so the UI never pretends otherwise.
 */
export type TurnStatus = "thinking" | "revealing" | "done" | "error";

export interface AskTurn {
  id: string;
  question: string;
  /** Client-paced stage index while waiting (0 retrieve · 1 evidence · 2 reason · 3 verify). */
  stage: number;
  status: TurnStatus;
  /** Answer text revealed so far by the AnswerStream (progressive reveal). */
  partial: string;
  response: AskResponseData | null;
  error: ApiError | Error | null;
  askedAt: number;
}

type Listener = () => void;

const sessions = new Map<string, AskTurn[]>();
const listeners = new Set<Listener>();
const EMPTY: AskTurn[] = [];

export const askSession = {
  get(repositoryId: string): AskTurn[] {
    return sessions.get(repositoryId) ?? EMPTY;
  },
  set(repositoryId: string, turns: AskTurn[]) {
    sessions.set(repositoryId, turns);
    listeners.forEach((l) => l());
  },
  update(repositoryId: string, id: string, patch: Partial<AskTurn>) {
    const turns = askSession.get(repositoryId);
    askSession.set(
      repositoryId,
      turns.map((t) => (t.id === id ? { ...t, ...patch } : t)),
    );
  },
  clear(repositoryId: string) {
    askSession.set(repositoryId, []);
  },
  subscribe(listener: Listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};
