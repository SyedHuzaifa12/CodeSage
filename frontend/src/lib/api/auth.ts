import { api } from "@/lib/api/client";
import type { GitHubAuthorizeData, GitHubLoginData, MeData } from "@/lib/types/auth";

/** Mirrors backend/app/auth/api.py. Guest creation and token refresh live in lib/auth/authFlow.ts. */
export const authApi = {
  me: () => api.get<MeData>("/auth/me"),
  /** Public: starting GitHub login needs no session. */
  githubAuthorize: () => api.get<GitHubAuthorizeData>("/auth/github/authorize", { auth: false }),
  /**
   * `withSession`: send the caller's current (guest) session so the backend can upgrade it in place and keep
   * their repository. Pass false when there is no session — it would otherwise be created just to be replaced.
   */
  githubLogin: (code: string, state: string, withSession: boolean) =>
    api.post<GitHubLoginData>("/auth/github", { code, state }, { auth: withSession }),
};
