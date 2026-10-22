"use client";

import { useQuery } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Skeleton, td, th } from "@/components/ui";
import { get, post } from "@/lib/api";
import { ago, titleCase } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import { useJobs } from "@/lib/jobs";
import type { EvalCaseRow, EvalRun, Job } from "@/lib/types";

const SUITES = [
  { suite: "deterministic", label: "Deterministic gates", hint: "Seconds, no model: seeded hallucinations must be caught, good articles not blocked." },
  { suite: "critic", label: "Critic (model)", hint: "Same cases with the critic model rubric on top." },
  { suite: "pipeline", label: "Full pipeline (model)", hint: "Golden cases through research → write → edit → critic. Slow on CPU." },
] as const;

export function EvalsSettings({ canContent }: { canContent: boolean }) {
  const jobs = useJobs();
  const q = useQuery({ queryKey: ["evals"], queryFn: () => get<{ cases: EvalCaseRow[]; runs: EvalRun[]; latest: EvalRun | null }>("/settings/evals") });
  const [openRun, setOpenRun] = useState<string | null>(null);
  const detail = useQuery({ queryKey: ["evalRun", openRun], queryFn: () => get<EvalRun>(`/settings/evals/${openRun}`), enabled: Boolean(openRun) });
  const run = useAction((suite: string) => post<{ job: Job }>("/settings/evals/run", { suite }), {
    success: "Evaluation queued",
    onSuccess: (r, suite) => jobs.watch(r.job, { label: `Eval: ${suite}`, invalidate: [["evals"]], success: (j) => {
      const res = j.result as { passed?: number; total?: number } | null;
      return res ? `${res.passed}/${res.total} passed` : undefined;
    } }),
  });
  if (q.isPending) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const shown = openRun ? detail.data : q.data.latest;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        {SUITES.map((s) => (
          <Card key={s.suite} className="flex flex-col justify-between p-4">
            <div>
              <p className="font-medium text-ink">{s.label}</p>
              <p className="mt-1 text-xs text-ink-2">{s.hint}</p>
            </div>
            <Button className="mt-3 self-start" icon={<FlaskConical className="size-3.5" />} loading={run.isPending && run.variables === s.suite} onClick={() => run.mutate(s.suite)} disabledReason={!canContent ? "Your role cannot run evaluations" : null}>
              Run
            </Button>
          </Card>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="overflow-hidden">
          <CardHeader title={`Runs (${q.data.runs.length})`} />
          {q.data.runs.length === 0 ? (
            <EmptyState title="No evaluation runs yet" body="Run the deterministic suite first — it needs no model." className="py-8" />
          ) : (
            <table className="w-full text-[13px]">
              <thead className="border-b border-line">
                <tr>
                  <th className={th}>Suite</th>
                  <th className={th}>Model</th>
                  <th className={th}>Result</th>
                  <th className={th}>When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {q.data.runs.map((r) => (
                  <tr key={r.id} className="cursor-pointer hover:bg-surface-2/50" onClick={() => setOpenRun(r.id)}>
                    <td className={td}>{titleCase(r.agent)}</td>
                    <td className={`${td} text-xs text-ink-2`}>{r.model}</td>
                    <td className={td}>
                      <Badge tone={r.passed === r.total ? "ok" : r.passed / Math.max(1, r.total) >= 0.8 ? "warn" : "bad"}>
                        {r.passed}/{r.total}
                      </Badge>
                    </td>
                    <td className={`${td} text-xs text-ink-2`}>{ago(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card>
          <CardHeader title={shown ? `${titleCase(shown.agent)} · ${shown.passed}/${shown.total}` : "Run details"} subtitle={shown ? `${shown.model} · ${ago(shown.created_at)}` : undefined} />
          {shown ? (
            <div className="space-y-3 p-4">
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(shown.scores).map(([k, v]) => (
                  <Badge key={k}>
                    {k.replace(/_/g, " ")}: {v ?? "—"}
                  </Badge>
                ))}
              </div>
              {shown.details?.length ? (
                <pre className="max-h-80 overflow-auto font-mono text-[11px] text-ink-2">{JSON.stringify(shown.details, null, 1)}</pre>
              ) : (
                <p className="text-xs text-muted">Select a run to see per-case details.</p>
              )}
            </div>
          ) : (
            <p className="p-4 text-xs text-muted">No runs yet.</p>
          )}
        </Card>
      </div>
      <Card className="overflow-hidden">
        <CardHeader title={`Golden set (${q.data.cases.length} cases)`} subtitle="evals/cases/*.json — fictional companies, so any unsupported figure is unambiguously invented" />
        <table className="w-full text-[13px]">
          <thead className="border-b border-line">
            <tr>
              <th className={th}>Case</th>
              <th className={th}>Category</th>
              <th className={th}>Label</th>
              <th className={th}>Expected</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {q.data.cases.map((c) => (
              <tr key={c.id}>
                <td className={`${td} max-w-xl`}>
                  <p className="font-mono text-xs text-ink">{c.id}</p>
                  <p className="text-xs text-ink-2">{c.description}</p>
                </td>
                <td className={td}>{titleCase(c.category)}</td>
                <td className={td}>
                  <Badge tone={c.label === "good" ? "ok" : c.label === "adversarial" ? "bad" : "warn"}>{c.label}</Badge>
                </td>
                <td className={`${td} text-xs`}>{c.expected}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
