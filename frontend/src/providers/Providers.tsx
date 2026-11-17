"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Feedback from "@/components/ui/Feedback";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 60 * 1000, retry: 1 },
        },
      })
  );

  return <QueryClientProvider client={queryClient}>{children}<Feedback /></QueryClientProvider>;
}
