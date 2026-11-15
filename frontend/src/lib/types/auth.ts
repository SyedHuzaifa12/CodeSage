/** Mirrors backend/app/auth/schemas.py. */

export type UserKind = "guest" | "user";

export interface AuthUser {
  id: string;
  kind: UserKind;
  github_login: string | null;
  display_name: string | null;
  avatar_url: string | null;
  is_admin: boolean;
  guest_expires_at: string | null;
}

export interface QuotaStatus {
  repositories_used: number;
  repositories_limit: number;
  questions_used_today: number;
  questions_limit_daily: number;
}

export interface TokenPair {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token: string;
}

export interface AuthSessionData {
  tokens: TokenPair;
  user: AuthUser;
  quota: QuotaStatus;
}

export interface GitHubLoginData extends AuthSessionData {
  repositories_transferred: number;
}

export interface GitHubAuthorizeData {
  authorize_url: string;
  state: string;
}

export interface MeData {
  user: AuthUser;
  quota: QuotaStatus;
}
