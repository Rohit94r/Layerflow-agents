"use client";

import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { get } from "./api";
import { JOB_LABEL } from "./format";
import { useToast } from "./toast";
import type { Job, JobEvent } from "./types";

interface Watched {
  id: string;
  label: string;
  invalidate: QueryKey[];
  successMessage?: (job: Job) => string | undefined;
}

interface JobsApi {
  watch: (job: Job | null | undefined, opts?: { label?: string; invalidate?: QueryKey[]; success?: (job: Job) => string | undefined }) => void;
  active: Watched[];
}

const Ctx = createContext<JobsApi | null>(null);

function WatchedJob({ w, onFinished }: { w: Watched; onFinished: (id: string) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const fired = useRef(false);
  const { data } = useQuery({
    queryKey: ["job", w.id],
    queryFn: () => get<{ job: Job; events: JobEvent[] }>(`/jobs/${w.id}`),
    refetchInterval: (q) => {
      const s = q.state.data?.job.status;
      return s === "done" || s === "failed" || s === "dead" ? false : 2000;
    },
  });
  const job = data?.job;
  useEffect(() => {
    if (!job || fired.current) return;
    if (job.status === "done" || job.status === "failed" || job.status === "dead") {
      fired.current = true;
      for (const key of w.invalidate) qc.invalidateQueries({ queryKey: key });
      if (job.status === "done") {
        const outcome = (job.result as { outcome?: string; reason?: string } | null) ?? null;
        if (outcome?.outcome === "needs_sources") toast.info(`${w.label}: needs more sources`, outcome.reason);
        else toast.success(`${w.label} finished`, w.successMessage?.(job));
      } else {
        toast.error(`${w.label} failed`, job.last_error ?? undefined);
      }
      setTimeout(() => onFinished(w.id), 1500);
    }
  }, [job, w, qc, toast, onFinished]);
  const last = data?.events?.[data.events.length - 1];
  return (
    <li className="flex items-center gap-2 text-xs">
      <Loader2 className={`size-3.5 ${job?.status === "running" || job?.status === "queued" || !job ? "animate-spin" : ""} text-accent`} aria-hidden />
      <span className="font-medium text-ink">{w.label}</span>
      <span className="truncate text-muted">{job ? (last?.message ?? job.status) : "starting…"}</span>
    </li>
  );
}

export function JobsProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<Watched[]>([]);
  const finish = useCallback((id: string) => setActive((a) => a.filter((w) => w.id !== id)), []);
  const watch = useCallback<JobsApi["watch"]>((job, opts) => {
    if (!job) return;
    setActive((a) =>
      a.some((w) => w.id === job.id)
        ? a
        : [...a, { id: job.id, label: opts?.label ?? JOB_LABEL[job.type] ?? job.type, invalidate: opts?.invalidate ?? [], successMessage: opts?.success }],
    );
  }, []);
  const value = useMemo(() => ({ watch, active }), [watch, active]);
  return (
    <Ctx.Provider value={value}>
      {children}
      {active.length ? (
        <div className="fixed bottom-4 left-4 z-[90] w-[340px] max-w-[calc(100vw-2rem)] rounded-md border border-line bg-surface px-3 py-2.5 shadow-lg" aria-live="polite">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">Running jobs</p>
          <ul className="space-y-1.5">
            {active.map((w) => (
              <WatchedJob key={w.id} w={w} onFinished={finish} />
            ))}
          </ul>
        </div>
      ) : null}
    </Ctx.Provider>
  );
}

export function useJobs(): JobsApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useJobs must be used inside JobsProvider");
  return ctx;
}
