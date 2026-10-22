"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { JobsProvider } from "@/lib/jobs";
import { ToastProvider } from "@/lib/toast";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 10_000,
            refetchOnWindowFocus: true,
            retry: (count, err) => {
              if (err instanceof ApiError && [401, 403, 404, 409, 422].includes(err.status)) return false;
              return count < 2;
            },
          },
          mutations: { retry: false },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <JobsProvider>{children}</JobsProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
