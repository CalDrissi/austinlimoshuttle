import { apiGet, apiPost, apiPatch } from "./client";
import type { User, LoginRequest, RegisterRequest } from "@/types/api";

/**
 * Cookie-session auth. The session cookie is httpOnly and set by Django; there
 * is no token in JS. `me()` resolves the current user (403 when anonymous).
 */
export const authService = {
  login: (body: LoginRequest) => apiPost<User>("/auth/login/", body),
  sendCode: (email: string) => apiPost<{ detail: string }>("/auth/send-code/", { email }),
  verifyCode: (body: { email: string; code: string }) => apiPost<User>("/auth/verify-code/", body),
  register: (body: RegisterRequest) => apiPost<User>("/auth/register/", body),
  logout: () => apiPost<void>("/auth/logout/", {}),
  me: () => apiGet<User>("/auth/me/"),
  updateProfile: (body: { first_name?: string; last_name?: string; phone?: string }) =>
    apiPatch<User>("/auth/me/", body),
  requestPasswordReset: (email: string) =>
    apiPost<{ detail: string }>("/auth/password-reset/", { email }),
};
