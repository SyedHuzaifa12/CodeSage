/**
 * Mirrors backend/app/schemas/envelope.py's SuccessResponse and
 * backend/app/exceptions/handlers.py's error envelope exactly.
 * Every backend response is one of these two shapes — never anything else.
 */
export interface SuccessEnvelope<T> {
  success: true;
  message: string;
  data: T;
}

export interface ErrorDetail {
  field?: string;
  message?: string;
  type?: string;
  detail?: string;
  [key: string]: unknown;
}

export interface ErrorEnvelope {
  success: false;
  message: string;
  errors: ErrorDetail[];
}

export type ApiEnvelope<T> = SuccessEnvelope<T> | ErrorEnvelope;
