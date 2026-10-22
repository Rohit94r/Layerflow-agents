"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, RefreshCw, RotateCcw } from "lucide-react";
import Link from "next/link";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Banner, Button, Card, CardHeader, EmptyState, ErrorState, JobBadge, PageHeader, Skeleton, Stat, StatusDot, td, th } from "@/components/ui";
import { get, post } from "@/lib/api";
import { JOB_LABEL, STATE_LABEL, ago, ms, num, titleCase } from "@/lib/format";
import { useAction, useMe } from "@/lib/hooks";
import { useJobs } from "@/lib/jobs";
import type { AuditEntry, DashboardSummary, Job, Paginated } from "@/lib/types";

function describe(e: AuditEntry): string {
  const d = (e.detail ?? {}) as Record<string, unknown>;
  switch (e.action) {
    case "article.transition":
      return `${e.entity_label ? `“${e.entity_label}” ` : ""}moved ${STATE_LABEL[String(d.from)] ?? d.from} → ${STATE_LABEL[String(d.to)] ?? d.to}${d.reason ? ` (${d.reason})` : ""}`;
    case "discovery.run":
      return `Discovery stored ${d.new_items ?? 0} new item(s) from ${d.sources_ok ?? 0}/${d.sources ?? 0} sources`;
    case "feed.promote":
      return `Promoted a story to the studio as ${titleCase(String(d.category ?? ""))}`;
    case "review.approve":
      return `Approved ${e.entity_label ? `“${e.entity_label}”` : "an article"}`;
    case "review.reject":
      return `Rejected ${e.entity_label ? `“${e.entity_label}”` : "an article"}: ${d.reason ?? ""}`;
    case "review.request_revision":
      return `Requested a revision: ${d.reason ?? ""}`;
    case "publication.published":
      return `Published to ${d.target}: ${d.live_url ?? ""}`;
    case "publication.failed":
      return `Publish failed: ${d.error ?? ""}`;
    case "job.failed":
      return `${JOB_LABEL[String(d.type)] ?? d.type} job ${d.status}: ${String(d.error ?? "").slice(0, 120)}`;
    case "job.done":
      return `${JOB_LABEL[String(d.type)] ?? d.type} job finished`;
    default:
      return `${titleCase(e.action.replace(".", " "))}${e.entity_label ? ` · ${e.entity_label}` : ""}`;
  }
}

export default function DashboardPage() {
  const me = useMe();
  const jobs = useJobs();
  const summary = useQuery({ queryKey: ["summary"], queryFn: () => get<DashboardSummary>("/dashboard/summary"), refetchInterval: 15_000 });
  const activity = useQuery({ queryKey: ["activity"], queryFn: () => get<{ items: AuditEntry[] }>("/dashboard/activity", { limit: 25 }), refetchInterval: 15_000 });
  const failed = useQuery({
    queryKey: ["jobs", { status: "failed,dead" }],
    queryFn: () => get<Paginated<Job>>("/jobs", { status: "failed,dead", page_size: 8 }),
    refetchInterval: 30_000,
  });
  const canContent = me.data?.user.role !== "reviewer";
  const refresh = useAction(() => post<{ job: Job }>("/feed/refresh"), {
    success: "Discovery queued",
    onSuccess: (r) => jobs.watch(r.job, { label: "Discovery", invalidate: [["summary"], ["feed"], ["activity"]], success: (j) => {
      const res = j.result as { new_items?: number; unique_stories?: number } | null;
      return res ? `${res.new_items ?? 0} new items, ${res.unique_stories ?? 0} unique stories` : undefined;
    } }),
  });
  const retry = useAction((id: string) => post<{ job: Job }>(`/jobs/${id}/retry`), {
    success: "Job re-queued",
    invalidate: [["jobs"], ["summary"]],
    onSuccess: (r) => jobs.watch(r.job, { invalidate: [["jobs"], ["summary"], ["articles"]] }),
  });

  const s = summary.data;
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader
        title="Dashboard"
        subtitle={s ? `Live pipeline state · updated ${ago(s.generated_at)}` : "Live pipeline state"}
        actions={
          <Button
            variant="primary"
            icon={<RefreshCw className="size-3.5" />}
            loading={refresh.isPending}
            onClick={() => refresh.mutate(undefined)}
            disabledReason={!canContent ? "Reviewers cannot start discovery" : null}
          >
            Refresh discovery
          </Button>
        }
      />

      {summary.isError ? (
        <Card>
          <ErrorState error={summary.error} onRetry={() => summary.refetch()} />
        </Card>
      ) : (
        <>
          {s && s.model.status !== "ok" ? (
            <Banner tone={s.model.status === "down" ? "bad" : "warn"} title={`Model ${s.model.status}: ${s.model.provider} at ${s.model.base_url ?? "?"}`} className="mb-4">
              {s.model.detail ?? "Generation jobs will retry with backoff until the model is reachable."}
            </Banner>
          ) : null}
          {s && s.worker.status !== "ok" ? (
            <Banner tone="bad" title={`Worker ${s.worker.status}`} className="mb-4">
              {s.worker.detail ?? `Last heartbeat ${ago(s.worker.last_seen)}. Jobs will wait in the queue until a worker runs.`}
            </Banner>
          ) : null}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {s ? (
              <>
                <Stat label="Candidates today" value={num(s.cards.candidates_today)} hint="Unique stories, last 24h" href="/news" />
                <Stat label="Drafts in progress" value={num(s.cards.drafts_in_progress)} hint="Queued → QA" href="/studio" />
                <Stat label="Awaiting review" value={num(s.cards.awaiting_review)} hint="Human approval" href="/review" />
                <Stat label="Scheduled" value={num(s.cards.scheduled)} hint="Upcoming publications" href="/calendar" />
                <Stat label="Published (7d)" value={num(s.cards.published_7d)} tone={s.cards.published_7d ? "ok" : undefined} href="/calendar" />
                <Stat label="Failed jobs" value={num(s.cards.failed_jobs)} tone={s.cards.failed_jobs ? "bad" : undefined} hint="Visible and retryable" />
              </>
            ) : (
              Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[104px]" />)
            )}
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title="Last 7 days" subtitle="Discovered stories, drafts written, articles published (UTC days)" />
              <div className="h-[240px] px-2 py-3">
                {s ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={s.daily.map((d) => ({ ...d, day: d.date.slice(5) }))} barGap={2}>
                      <CartesianGrid strokeDasharray="2 4" stroke="var(--line)" vertical={false} />
                      <XAxis dataKey="day" tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={{ stroke: "var(--line)" }} tickLine={false} />
                      <YAxis allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} width={32} />
                      <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 6, fontSize: 12 }} cursor={{ fill: "var(--surface-2)" }} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar dataKey="discovered" name="Discovered" fill="var(--line-strong)" radius={[2, 2, 0, 0]} />
                      <Bar dataKey="drafted" name="Drafted" fill="var(--info)" radius={[2, 2, 0, 0]} />
                      <Bar dataKey="published" name="Published" fill="var(--accent)" radius={[2, 2, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <Skeleton className="h-full w-full" />
                )}
              </div>
            </Card>
            <Card>
              <CardHeader title="Pipeline funnel" subtitle="Last 7 days" />
              <div className="space-y-2.5 px-4 py-4">
                {s
                  ? s.funnel.map((f) => {
                      const max = Math.max(1, ...s.funnel.map((x) => x.count));
                      return (
                        <div key={f.stage}>
                          <div className="mb-1 flex justify-between text-xs">
                            <span className="text-ink-2">{f.label}</span>
                            <span className="font-medium text-ink tabular">{num(f.count)}</span>
                          </div>
                          <div className="h-2 overflow-hidden rounded bg-surface-2">
                            <div className="h-full rounded bg-accent/80" style={{ width: `${(f.count / max) * 100}%` }} />
                          </div>
                        </div>
                      );
                    })
                  : Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-7" />)}
              </div>
            </Card>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title="Agent health" subtitle="Last 24 hours · real job and model-run records" />
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead className="border-b border-line">
                    <tr>
                      <th className={th}>Agent</th>
                      <th className={th}>Jobs</th>
                      <th className={th}>Model calls</th>
                      <th className={th}>Errors</th>
                      <th className={th}>p50 / p95</th>
                      <th className={th}>Last run</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {s
                      ? s.agents.map((a) => (
                          <tr key={a.agent}>
                            <td className={td}>
                              <span className="mr-2 font-mono text-[11px] text-muted">{a.code}</span>
                              <span className="font-medium text-ink">{a.label}</span>
                              {a.last_error ? (
                                <p className="mt-0.5 max-w-md truncate text-xs text-bad" title={a.last_error}>
                                  {a.last_error}
                                </p>
                              ) : null}
                            </td>
                            <td className={`${td} tabular`}>{a.jobs_24h}</td>
                            <td className={`${td} tabular`}>{a.model_calls_24h}</td>
                            <td className={td}>{a.errors_24h ? <Badge tone="bad">{a.errors_24h}</Badge> : <span className="text-muted">0</span>}</td>
                            <td className={`${td} tabular text-ink-2`}>
                              {ms(a.p50_latency_ms)} / {ms(a.p95_latency_ms)}
                            </td>
                            <td className={`${td} text-ink-2`}>{ago(a.last_run_at, "never")}</td>
                          </tr>
                        ))
                      : Array.from({ length: 8 }).map((_, i) => (
                          <tr key={i}>
                            <td colSpan={6} className="px-3 py-2">
                              <Skeleton className="h-5" />
                            </td>
                          </tr>
                        ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card>
              <CardHeader title="System" />
              {s ? (
                <dl className="divide-y divide-line text-[13px]">
                  {[
                    ["Model", <span key="m" className="flex items-center gap-1.5"><StatusDot status={s.model.status} />{s.model.provider} · {s.model.status}{s.model.latency_ms != null ? ` · ${ms(s.model.latency_ms)}` : ""}</span>],
                    ["Models loaded", s.model.models.length ? s.model.models.slice(0, 4).join(", ") + (s.model.models.length > 4 ? "…" : "") : "—"],
                    ["Missing models", s.model.missing.length ? <span key="mm" className="text-warn">{s.model.missing.join(", ")}</span> : "none"],
                    ["Worker", <span key="w" className="flex items-center gap-1.5"><StatusDot status={s.worker.status} />{s.worker.status} · {ago(s.worker.last_seen, "never")}</span>],
                    ["Queue depth", `${s.queue.queued} queued · ${s.queue.running} running`],
                    ["Retrying", String(s.queue.retrying)],
                    ["Failures (24h)", String(s.queue.failed_24h)],
                    ["Oldest waiting", s.queue.oldest_queued_age_s != null ? ms(s.queue.oldest_queued_age_s * 1000) : "—"],
                  ].map(([k, v]) => (
                    <div key={String(k)} className="flex items-start justify-between gap-3 px-4 py-2">
                      <dt className="text-ink-2">{k}</dt>
                      <dd className="text-right text-ink">{v}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <div className="space-y-2 p-4">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <Skeleton key={i} className="h-5" />
                  ))}
                </div>
              )}
            </Card>
          </div>
        </>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title="Recent activity" subtitle="Audit log: every transition and action" actions={<Activity className="size-4 text-muted" />} />
          {activity.isPending ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-6" />
              ))}
            </div>
          ) : activity.isError ? (
            <ErrorState error={activity.error} onRetry={() => activity.refetch()} />
          ) : activity.data.items.length === 0 ? (
            <EmptyState title="No activity yet" body="Refresh discovery to pull today's stories." />
          ) : (
            <ul className="max-h-[420px] divide-y divide-line overflow-y-auto">
              {activity.data.items.map((e) => (
                <li key={e.id} className="flex items-start gap-3 px-4 py-2 text-[13px]">
                  <Badge tone={e.actor_type === "user" ? "accent" : e.actor_type === "agent" ? "info" : "neutral"}>{e.actor_type === "user" ? (e.actor_label ?? "user") : (e.actor_id ?? e.actor_type)}</Badge>
                  <span className="min-w-0 flex-1 text-ink-2">
                    {e.entity === "article" && e.entity_id ? (
                      <Link href={`/studio/${e.entity_id}`} className="hover:text-accent">
                        {describe(e)}
                      </Link>
                    ) : (
                      describe(e)
                    )}
                  </span>
                  <span className="shrink-0 text-xs text-muted">{ago(e.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <CardHeader title="Failed jobs" subtitle="Never silently lost" />
          {failed.isPending ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          ) : failed.isError ? (
            <ErrorState error={failed.error} onRetry={() => failed.refetch()} />
          ) : failed.data.items.length === 0 ? (
            <EmptyState title="No failed jobs" body="Failures appear here with their error and a retry button." />
          ) : (
            <ul className="divide-y divide-line">
              {failed.data.items.map((j) => (
                <li key={j.id} className="px-4 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2 text-[13px] font-medium text-ink">
                      {JOB_LABEL[j.type] ?? j.type} <JobBadge status={j.status} />
                    </span>
                    <Button size="xs" icon={<RotateCcw className="size-3" />} loading={retry.isPending && retry.variables === j.id} onClick={() => retry.mutate(j.id)} disabledReason={!canContent ? "Reviewers cannot retry jobs" : null}>
                      Retry
                    </Button>
                  </div>
                  {j.article_title ? (
                    <Link href={`/studio/${j.article_id}`} className="mt-0.5 block truncate text-xs text-ink-2 hover:text-accent">
                      {j.article_title}
                    </Link>
                  ) : null}
                  <p className="mt-1 line-clamp-2 text-xs text-bad" title={j.last_error ?? ""}>
                    {j.last_error}
                  </p>
                  <p className="mt-0.5 text-[11px] text-muted">
                    {j.attempts}/{j.max_attempts} attempts · {ago(j.finished_at ?? j.created_at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
