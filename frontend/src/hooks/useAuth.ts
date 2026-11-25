"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { authService } from "@/lib/api/auth.service";
import type { User } from "@/types/api";

/**
 * Current signed-in user, resolved from the session cookie via GET /auth/me/.
 * Anonymous visitors get a 204 (no body), which surfaces here simply as
 * `user = null` — a 2xx by design, so the console shows no failed request on
 * every storefront page. The catch covers real failures (network, 5xx).
 */
export function useAuth() {
  const { data, isLoading } = useQuery<User | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return (await authService.me()) ?? null;
      } catch {
        return null;
      }
    },
    retry: false,
    staleTime: 60_000,
  });

  return { user: data ?? null, isLoading };
}

/** Invalidate the cached user after login/register/logout. */
export function useRefreshAuth() {
  const qc = useQueryClient();
  return async () => {
    qc.removeQueries({ queryKey: ["my-bookings"] });
    qc.removeQueries({ queryKey: ["my-cards"] });
    await qc.invalidateQueries({ queryKey: ["me"] });
  };
}
