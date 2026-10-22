"use client";

import { useQuery } from "@tanstack/react-query";
import { addDays, addMonths, addWeeks, endOfMonth, endOfWeek, format, startOfMonth, startOfWeek } from "date-fns";
import { AlertTriangle, ChevronLeft, ChevronRight, Download, ExternalLink, Rocket, RotateCcw, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type DragEvent } from "react";
import { ScheduleModal } from "@/components/schedule-modal";
import { Badge, Banner, Button, Card, CardHeader, CategoryChip, EmptyState, ErrorState, PageHeader, Skeleton, Tabs, cn } from "@/components/ui";
import { apiUrl, get, patch, post } from "@/lib/api";
import { ago } from "@/lib/format";
import { useAction, useMe, usePlaybookMap } from "@/lib/hooks";
import { useJobs } from "@/lib/jobs";
import { useToast } from "@/lib/toast";
import { dayKey, formatIn, hourIn, moveTo, timeIn } from "@/lib/tz";
import type { ArticleSummary, CalendarConflict, Cadence, Job, Paginated, Publication } from "@/lib/types";

const HOURS = Array.from({ length: 17 }, (_, i) => i + 6); // 06:00–22:00
const statusTone = { scheduled: "info", publishing: "accent", published: "ok", failed: "bad", cancelled: "neutral", rolled_back: "neutral" } as const;

function when(p: Publication): string | null {
  return p.status === "published" ? (p.published_at ?? p.scheduled_at) : (p.scheduled_at ?? p.published_at);
}

function Chip({ p, color, onOpen, compact }: { p: Publication; color?: string; onOpen: () => void; compact?: boolean }) {
  const draggable = p.status === "scheduled" || p.status === "failed";
  return (
    <button
      type="button"
      draggable={draggable}
      onDragStart={(e) => {
        e.dataTransfer.setData("text/publication", p.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      onClick={onOpen}
      title={`${p.article?.title ?? "Article"} — ${p.status}${draggable ? " (drag to reschedule)" : ""}`}
      className={cn(
        "flex w-full items-center gap-1.5 truncate rounded border-l-[3px] bg-surface px-1.5 py-1 text-left text-[11px] shadow-sm hover:bg-surface-2",
        draggable ? "cursor-grab" : "cursor-pointer",
        p.status === "failed" && "ring-1 ring-bad",
        p.status === "cancelled" && "opacity-50 line-through",
      )}
      style={{ borderLeftColor: color ?? "var(--muted)" }}
    >
      <span className="truncate text-ink">{p.article?.title ?? "Untitled"}</span>
      {!compact ? <span className="ml-auto shrink-0 text-muted">{p.status === "published" ? "✓" : p.status === "failed" ? "!" : ""}</span> : null}
    </button>
  );
}

function SidePanel({ p, tz, onClose }: { p: Publication; tz: string; onClose: () => void }) {
  const jobs = useJobs();
  const me = useMe();
  const canPublish = Boolean(me.data);
  const publishNow = useAction(() => post<{ publication: Publication; job: Job | null }>(`/publications/${p.id}/publish-now`), {
    success: (r) => (r.job ? "Publishing now" : "Already published — nothing duplicated"),
    invalidate: [["publications"]],
    onSuccess: (r) => r.job && jobs.watch(r.job, { label: "Publish", invalidate: [["publications"], ["summary"], ["articles"]], success: () => "Live — see the publication panel" }),
  });
  const cancel = useAction(() => patch<Publication>(`/publications/${p.id}`, { status: "cancelled" }), { success: "Publication cancelled", invalidate: [["publications"], ["articles"]], onSuccess: onClose });
  const rollback = useAction(() => post<Publication>(`/publications/${p.id}/rollback`), { success: "Rolled back to the previous version", invalidate: [["publications"], ["articles"]] });
  const editable = p.status === "scheduled" || p.status === "failed";
  return (
    <Card className="sticky top-20 p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <Badge tone={statusTone[p.status]}>{p.status}</Badge>
          {p.late ? (
            <Badge tone="warn" className="ml-1">
              late
            </Badge>
          ) : null}
          <p className="mt-1.5 font-display text-[16px] leading-snug font-semibold text-ink">{p.article?.title}</p>
        </div>
        <button type="button" onClick={onClose} className="rounded p-1 text-muted hover:bg-surface-2" aria-label="Close panel">
          <X className="size-4" />
        </button>
      </div>
      <dl className="grid grid-cols-[90px_1fr] gap-x-2 gap-y-1.5 text-xs">
        <dt className="text-muted">Target</dt>
        <dd className="text-ink">{p.target}</dd>
        <dt className="text-muted">Scheduled</dt>
        <dd className="text-ink">{formatIn(p.scheduled_at, tz, { weekday: "short" })}</dd>
        <dt className="text-muted">Published</dt>
        <dd className="text-ink">{p.published_at ? formatIn(p.published_at, tz) : "—"}</dd>
        {p.live_url ? (
          <>
            <dt className="text-muted">Live URL</dt>
            <dd>
              <a href={p.live_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-start gap-1 break-all text-accent hover:underline">
                {p.live_url} <ExternalLink className="mt-0.5 size-3 shrink-0" />
              </a>
            </dd>
          </>
        ) : null}
      </dl>
      {p.last_error ? <p className="mt-3 rounded bg-bad-soft px-2.5 py-2 text-xs text-bad">{p.last_error}</p> : null}
      {p.warnings.length ? (
        <ul className="mt-3 space-y-1 text-xs text-warn">
          {p.warnings.map((w) => (
            <li key={w} className="flex gap-1.5">
              <AlertTriangle className="mt-0.5 size-3 shrink-0" /> {w}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button size="sm" variant="primary" icon={<Rocket className="size-3.5" />} loading={publishNow.isPending} onClick={() => publishNow.mutate(undefined)} disabledReason={!canPublish ? "Sign in" : !editable ? `Publication is ${p.status}` : null}>
          Publish now
        </Button>
        <Button size="sm" icon={<X className="size-3.5" />} loading={cancel.isPending} onClick={() => cancel.mutate(undefined)} disabledReason={!editable ? `Publication is ${p.status}` : null}>
          Cancel
        </Button>
        <Button size="sm" icon={<RotateCcw className="size-3.5" />} loading={rollback.isPending} onClick={() => rollback.mutate(undefined)} disabledReason={p.status !== "published" ? "Only published pages can be rolled back" : p.target === "export" ? "Export bundles are uploaded by hand; remove the page on the server" : null}>
          Roll back
        </Button>
        {p.has_artifact ? (
          <a href={apiUrl(`/publications/${p.id}/artifact`)} download>
            <Button size="sm" icon={<Download className="size-3.5" />}>
              Bundle
            </Button>
          </a>
        ) : null}
        <Link href={`/studio/${p.article_id}`}>
          <Button size="sm" variant="ghost">
            Studio
          </Button>
        </Link>
      </div>
      {editable ? <p className="mt-3 text-[11px] text-muted">Drag the item to another day or hour to reschedule.</p> : null}
    </Card>
  );
}

export default function CalendarPage() {
  const me = useMe();
  const pbs = usePlaybookMap();
  const tz = me.data?.tenant.timezone ?? "UTC";
  const [view, setView] = useState<"month" | "week">("month");
  const [anchor, setAnchor] = useState(() => new Date());
  const [selected, setSelected] = useState<string | null>(null);
  const [scheduling, setScheduling] = useState<ArticleSummary | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const toast = useToast();

  const range = useMemo(() => {
    if (view === "month") {
      const start = startOfWeek(startOfMonth(anchor), { weekStartsOn: 1 });
      const end = endOfWeek(endOfMonth(anchor), { weekStartsOn: 1 });
      return { start, end };
    }
    return { start: startOfWeek(anchor, { weekStartsOn: 1 }), end: endOfWeek(anchor, { weekStartsOn: 1 }) };
  }, [view, anchor]);
  const days = useMemo(() => {
    const out: Date[] = [];
    for (let d = range.start; d <= range.end; d = addDays(d, 1)) out.push(d);
    return out;
  }, [range]);

  const pubs = useQuery({
    queryKey: ["publications", range.start.toISOString(), range.end.toISOString()],
    queryFn: () =>
      get<{ items: Publication[]; conflicts: CalendarConflict[]; timezone: string; cadence: Cadence }>("/publications", {
        start: addDays(range.start, -1).toISOString(),
        end: addDays(range.end, 1).toISOString(),
      }),
    refetchInterval: 20_000,
  });
  const approved = useQuery({ queryKey: ["articles", { state: "approved" }], queryFn: () => get<Paginated<ArticleSummary>>("/articles", { state: "approved", page_size: 50 }) });

  const reschedule = useAction(({ id, at }: { id: string; at: string }) => patch<Publication>(`/publications/${id}`, { scheduled_at: at }), {
    success: (p) => `Rescheduled to ${formatIn(p.scheduled_at, tz, { weekday: "short" })}`,
    invalidate: [["publications"]],
  });

  const byDay = useMemo(() => {
    const map: Record<string, Publication[]> = {};
    for (const p of pubs.data?.items ?? []) {
      const w = when(p);
      if (!w) continue;
      (map[dayKey(w, tz)] ??= []).push(p);
    }
    for (const k of Object.keys(map)) map[k].sort((a, b) => (when(a) ?? "").localeCompare(when(b) ?? ""));
    return map;
  }, [pubs.data, tz]);
  const conflictDays = new Set((pubs.data?.conflicts ?? []).map((c) => c.date));
  const selectedPub = pubs.data?.items.find((p) => p.id === selected) ?? null;

  const drop = (e: DragEvent, key: string, hour?: number) => {
    e.preventDefault();
    setDragOver(null);
    const id = e.dataTransfer.getData("text/publication");
    const p = pubs.data?.items.find((x) => x.id === id);
    if (!p || !p.scheduled_at) return;
    const at = moveTo(p.scheduled_at, key, tz, hour);
    if (new Date(at).getTime() < Date.now()) {
      toast.error("Cannot move a publication into the past");
      return;
    }
    reschedule.mutate({ id, at });
  };
  const todayKey = dayKey(new Date(), tz);

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader
        title="Calendar"
        subtitle={`Times in ${tz}${pubs.data?.cadence ? ` · cadence ${pubs.data.cadence.per_day}/day at ${pubs.data.cadence.slots.join(", ")}${pubs.data.cadence.weekdays_only ? ", weekdays" : ""}` : ""}`}
        actions={
          <div className="flex items-center gap-2">
            <Tabs tabs={[{ value: "month", label: "Month" }, { value: "week", label: "Week" }]} value={view} onChange={setView} />
            <Button size="sm" variant="ghost" aria-label="Previous" onClick={() => setAnchor((a) => (view === "month" ? addMonths(a, -1) : addWeeks(a, -1)))}>
              <ChevronLeft className="size-4" />
            </Button>
            <Button size="sm" onClick={() => setAnchor(new Date())}>
              Today
            </Button>
            <Button size="sm" variant="ghost" aria-label="Next" onClick={() => setAnchor((a) => (view === "month" ? addMonths(a, 1) : addWeeks(a, 1)))}>
              <ChevronRight className="size-4" />
            </Button>
            <span className="min-w-[130px] font-display text-lg font-semibold text-ink">{view === "month" ? format(anchor, "MMMM yyyy") : `Week of ${format(range.start, "d MMM")}`}</span>
          </div>
        }
      />
      {pubs.data?.conflicts.length ? (
        <Banner tone="warn" title={`${pubs.data.conflicts.length} cadence conflict(s)`} className="mb-3">
          {pubs.data.conflicts.map((c) => c.message).join(" · ")}
        </Banner>
      ) : null}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="overflow-hidden">
          {pubs.isPending ? (
            <Skeleton className="h-[640px] rounded-none" />
          ) : pubs.isError ? (
            <ErrorState error={pubs.error} onRetry={() => pubs.refetch()} />
          ) : view === "month" ? (
            <div>
              <div className="grid grid-cols-7 border-b border-line bg-surface-2/40">
                {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
                  <div key={d} className="px-2 py-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">
                    {d}
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-7">
                {days.map((d) => {
                  const key = format(d, "yyyy-MM-dd");
                  const inMonth = d.getMonth() === anchor.getMonth();
                  const items = byDay[key] ?? [];
                  return (
                    <div
                      key={key}
                      onDragOver={(e) => {
                        e.preventDefault();
                        setDragOver(key);
                      }}
                      onDragLeave={() => setDragOver((k) => (k === key ? null : k))}
                      onDrop={(e) => drop(e, key)}
                      className={cn(
                        "min-h-[112px] border-r border-b border-line p-1.5",
                        !inMonth && "bg-surface-2/40",
                        dragOver === key && "bg-accent-soft/50",
                        conflictDays.has(key) && "ring-1 ring-warn ring-inset",
                      )}
                    >
                      <p className={cn("mb-1 text-[11px] tabular", key === todayKey ? "font-bold text-accent" : inMonth ? "text-ink-2" : "text-muted")}>{format(d, "d")}</p>
                      <div className="space-y-1">
                        {items.slice(0, 4).map((p) => (
                          <Chip key={p.id} p={p} color={p.article ? pbs[p.article.category]?.color : undefined} onOpen={() => setSelected(p.id)} />
                        ))}
                        {items.length > 4 ? <p className="text-[10px] text-muted">+{items.length - 4} more</p> : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <div className="grid min-w-[900px] grid-cols-[56px_repeat(7,minmax(0,1fr))]">
                <div className="border-b border-line" />
                {days.map((d) => (
                  <div key={d.toISOString()} className={cn("border-b border-l border-line px-2 py-1.5 text-xs", format(d, "yyyy-MM-dd") === todayKey ? "text-accent" : "text-ink-2")}>
                    {format(d, "EEE d")}
                  </div>
                ))}
                {HOURS.map((h) => (
                  <div key={h} className="contents">
                    <div className="border-b border-line px-1 py-1 text-right text-[10px] text-muted tabular">{String(h).padStart(2, "0")}:00</div>
                    {days.map((d) => {
                      const key = format(d, "yyyy-MM-dd");
                      const cellKey = `${key}-${h}`;
                      const items = (byDay[key] ?? []).filter((p) => hourIn(when(p) as string, tz) === h);
                      return (
                        <div
                          key={cellKey}
                          onDragOver={(e) => {
                            e.preventDefault();
                            setDragOver(cellKey);
                          }}
                          onDragLeave={() => setDragOver((k) => (k === cellKey ? null : k))}
                          onDrop={(e) => drop(e, key, h)}
                          className={cn("min-h-[40px] border-b border-l border-line p-0.5", dragOver === cellKey && "bg-accent-soft/50")}
                        >
                          {items.map((p) => (
                            <div key={p.id} className="mb-0.5">
                              <p className="px-1 text-[9px] text-muted">{timeIn(when(p) as string, tz)}</p>
                              <Chip p={p} compact color={p.article ? pbs[p.article.category]?.color : undefined} onOpen={() => setSelected(p.id)} />
                            </div>
                          ))}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
        <div className="space-y-4">
          {selectedPub ? <SidePanel p={selectedPub} tz={tz} onClose={() => setSelected(null)} /> : null}
          <Card>
            <CardHeader title="Approved, not scheduled" />
            {approved.isPending ? (
              <Skeleton className="m-4 h-16" />
            ) : approved.isError ? (
              <ErrorState error={approved.error} onRetry={() => approved.refetch()} />
            ) : approved.data.items.length === 0 ? (
              <EmptyState title="Nothing waiting" body="Approved articles appear here until they are scheduled." className="py-6" />
            ) : (
              <ul className="divide-y divide-line">
                {approved.data.items.map((a) => (
                  <li key={a.id} className="flex items-center justify-between gap-2 px-4 py-2">
                    <div className="min-w-0">
                      <p className="truncate text-[13px] font-medium text-ink">{a.title}</p>
                      <CategoryChip label={a.category_label} color={pbs[a.category]?.color} />
                    </div>
                    <Button size="xs" variant="primary" onClick={() => setScheduling(a)}>
                      Schedule
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card className="p-4 text-xs">
            <p className="mb-2 text-[11px] font-semibold tracking-wider text-muted uppercase">Categories</p>
            <div className="grid grid-cols-2 gap-1.5">
              {Object.values(pbs).map((p) => (
                <CategoryChip key={p.key} label={p.label} color={p.color} />
              ))}
            </div>
            <p className="mt-3 text-muted">Last refreshed {ago(new Date(pubs.dataUpdatedAt || Date.now()).toISOString())}</p>
          </Card>
        </div>
      </div>
      {scheduling ? <ScheduleModal articleId={scheduling.id} category={scheduling.category} title={scheduling.title} onClose={() => setScheduling(null)} /> : null}
    </div>
  );
}
