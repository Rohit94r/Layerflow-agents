"use client";

import type { ReactNode } from "react";
import { AppShell } from "@/components/shell";
import { ErrorState, Skeleton } from "@/components/ui";
import { useMe } from "@/lib/hooks";

export default function AppLayout({ children }: { children: ReactNode }) {
  const me = useMe();
  if (me.isPending) {
    return (
      <div className="flex min-h-screen" aria-busy="true">
        <div className="hidden w-[220px] border-r border-line bg-surface md:block" />
        <div className="flex-1 space-y-4 p-8">
          <Skeleton className="h-9 w-64" />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-72" />
        </div>
      </div>
    );
  }
  if (me.isError) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <ErrorState error={me.error} onRetry={() => me.refetch()} />
      </div>
    );
  }
  return <AppShell me={me.data}>{children}</AppShell>;
}
