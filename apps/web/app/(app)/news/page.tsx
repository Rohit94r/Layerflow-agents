"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ExternalLink, Layers, RefreshCw, Search, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import {
  Badge,
  Banner,
  Button,
  Card,
  CategoryChip,
  Checkbox,
  Dialog,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
  ScoreBar,
  Select,
  Skeleton,
  Textarea,
  Toggle,
  td,
  th,
} from "@/components/ui";
import { get, post } from "@/lib/api";
import { ago, dateTime, hostOf, titleCase } from "@/lib/format";
import { useAction, useDebounced, useMe, usePlaybookMap, usePlaybooks } from "@/lib/hooks";
import { useJobs } from "@/lib/jobs";
import type { ArticleSummary, Category, FeedDetail, FeedItem, FeedList, Job, Source, Topic } from "@/lib/types";

const REGIONS = ["global", "us", "eu", "uk", "india", "mena", "apac", "africa", "latam"];

function breakdownTitle(item: FeedItem): string {
  const b = item.score_breakdown ?? {};
  const parts = ["recency", "entity", "signal", "source", "novelty"].map((k) => `${k}: ${typeof b[k] === "number" ? (b[k] as number).toFixed(2) : "—"}`);
  const signals = Array.isArray(b.signals) ? (b.signals as string[]) : [];
  return `Score ${item.score.toFixed(2)}\n${parts.join("\n")}${signals.length ? `\nsignals: ${signals.join(", ")}` : ""}`;
}

function PromoteDialog({ item, onClose }: { item: FeedItem; onClose: () => void }) {
  const playbooks = usePlaybooks();
  const router = useRouter();
  const jobs = useJobs();
  const [category, setCategory] = useState<Category>((item.suggested_category as Category) ?? "brief");
  const [angle, setAngle] = useState(item.why_it_matters ?? "");
  const [auto, setAuto] = useState(true);
  const promote = useAction(() => post<{ topic: Topic; article: ArticleSummary; job: Job }>(`/feed/${item.id}/promote`, { category, angle: angle || undefined, auto }), {
    success: "Promoted to the studio",
    invalidate: [["feed"], ["summary"], ["articles"]],
    onSuccess: (r) => {
      jobs.watch(r.job, { label: auto ? "Pipeline: research" : "Research", invalidate: [["article", r.article.id], ["articles"]] });
      onClose();
      router.push(`/studio/${r.article.id}`);
    },
  });
  return (
    <Dialog
      open
      onClose={onClose}
      title="Promote to the studio"
      description={item.title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={promote.isPending} onClick={() => promote.mutate(undefined)}>
            Promote
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Category" hint={item.category_reason ? `Suggested: ${item.suggested_category} — ${item.category_reason}` : undefined}>
          <Select value={category} onChange={(e) => setCategory(e.target.value as Category)}>
            {(playbooks.data ?? []).map((p) => (
              <option key={p.key} value={p.key}>
                {p.label} — {p.min_words}–{p.max_words} words
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Angle" hint="The decision this changes for a senior leader. Leave blank to let the writer choose.">
          <Textarea rows={3} value={angle} onChange={(e) => setAngle(e.target.value)} maxLength={500} />
        </Field>
        <div className="flex items-center justify-between rounded-md border border-line px-3 py-2.5">
          <div>
            <p className="text-[13px] font-medium text-ink">Run the full pipeline</p>
            <p className="text-xs text-muted">Research → write → edit → SEO → QA, then into the review queue.</p>
          </div>
          <Toggle checked={auto} onChange={setAuto} label="Run the full pipeline" />
        </div>
      </div>
    </Dialog>
  );
}

function IgnoreDialog({ item, onClose }: { item: FeedItem; onClose: () => void }) {
  const [reason, setReason] = useState("Not relevant for executives");
  const ignore = useAction(() => post(`/feed/${item.id}/ignore`, { reason }), { success: "Ignored", invalidate: [["feed"], ["feedItem", item.id]], onSuccess: onClose });
  return (
    <Dialog
      open
      onClose={onClose}
      title="Ignore story"
      description={item.title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" loading={ignore.isPending} onClick={() => ignore.mutate(undefined)} disabledReason={!reason.trim() ? "Give a reason" : null}>
            Ignore
          </Button>
        </>
      }
    >
      <Field label="Reason (helps tune the scoring)">
        <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
      </Field>
    </Dialog>
  );
}

function ItemDrawer({ id, onClose, canContent }: { id: string; onClose: () => void; canContent: boolean }) {
  const pbs = usePlaybookMap();
  const detail = useQuery({ queryKey: ["feedItem", id], queryFn: () => get<FeedDetail>(`/feed/${id}`) });
  const [promoting, setPromoting] = useState(false);
  const [ignoring, setIgnoring] = useState(false);
  const restore = useAction(() => post(`/feed/${id}/restore`), { success: "Restored", invalidate: [["feed"], ["feedItem", id]] });
  const item = detail.data?.item;
  return (
    <Drawer
      open
      onClose={onClose}
      title={item?.title ?? "Story"}
      footer={
        item ? (
          item.article_id ? (
            <Link href={`/studio/${item.article_id}`}>
              <Button variant="primary">Open in studio</Button>
            </Link>
          ) : (
            <>
              {item.status === "ignored" ? (
                <Button loading={restore.isPending} onClick={() => restore.mutate(undefined)} disabledReason={!canContent ? "Your role cannot change stories" : null}>
                  Restore
                </Button>
              ) : (
                <Button variant="ghost" onClick={() => setIgnoring(true)} disabledReason={!canContent ? "Your role cannot change stories" : null}>
                  Ignore
                </Button>
              )}
              <Button variant="primary" icon={<Sparkles className="size-3.5" />} onClick={() => setPromoting(true)} disabledReason={!canContent ? "Your role cannot promote stories" : item.status === "ignored" ? "Restore the story first" : null}>
                Promote
              </Button>
            </>
          )
        ) : null
      }
    >
      {detail.isPending ? (
        <div className="space-y-3">
          <Skeleton className="h-5 w-1/2" />
          <Skeleton className="h-24" />
          <Skeleton className="h-40" />
        </div>
      ) : detail.isError ? (
        <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
      ) : item ? (
        <div className="space-y-5 text-[13px]">
          <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
            <a href={item.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
              {item.publisher ?? hostOf(item.url)} <ExternalLink className="size-3" />
            </a>
            <span>·</span>
            <span title={dateTime(item.published_at)}>{item.published_at ? ago(item.published_at) : "date unknown"}</span>
            {item.region ? <Badge>{item.region.toUpperCase()}</Badge> : null}
            {item.suggested_category ? <CategoryChip label={pbs[item.suggested_category]?.label ?? item.suggested_category} color={pbs[item.suggested_category]?.color} /> : null}
            <Badge tone={item.status === "promoted" ? "ok" : item.status === "ignored" ? "neutral" : "accent"}>{item.status}</Badge>
          </div>
          {item.why_it_matters ? (
            <div className="rounded-md border-l-2 border-accent bg-accent-soft/50 px-3 py-2">
              <p className="text-[11px] font-semibold tracking-wider text-accent uppercase">Why it matters</p>
              <p className="mt-0.5 font-display text-[15px] text-ink">{item.why_it_matters}</p>
            </div>
          ) : null}
          {item.summary ? <p className="font-display text-[15px] leading-relaxed text-ink-2">{item.summary}</p> : <p className="text-muted">The feed provided no summary.</p>}
          <section>
            <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-muted uppercase">Score {item.score.toFixed(2)}</h3>
            <div className="grid grid-cols-5 gap-2">
              {["recency", "entity", "signal", "source", "novelty"].map((k) => {
                const v = item.score_breakdown[k];
                return (
                  <div key={k} className="rounded border border-line px-2 py-1.5">
                    <p className="text-[10px] text-muted uppercase">{k}</p>
                    <p className="font-medium text-ink tabular">{typeof v === "number" ? v.toFixed(2) : "—"}</p>
                  </div>
                );
              })}
            </div>
            {Array.isArray(item.score_breakdown.signals) && (item.score_breakdown.signals as string[]).length ? (
              <p className="mt-2 text-xs text-ink-2">Signals: {(item.score_breakdown.signals as string[]).join(", ")}</p>
            ) : null}
            {item.category_reason ? <p className="mt-1 text-xs text-muted">Routing: {item.category_reason}</p> : null}
          </section>
          {item.entities.length ? (
            <section>
              <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-muted uppercase">Entities</h3>
              <div className="flex flex-wrap gap-1.5">
                {item.entities.map((e) => (
                  <Badge key={`${e.type}:${e.name}`} tone={e.watchlist ? "accent" : "neutral"} title={e.watchlist ? "On the watchlist" : e.type}>
                    {e.name} <span className="opacity-60">{e.type}</span>
                  </Badge>
                ))}
              </div>
            </section>
          ) : null}
          {detail.data.cluster.length ? (
            <section>
              <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-muted uppercase">Same story ({detail.data.cluster.length} duplicate{detail.data.cluster.length > 1 ? "s" : ""})</h3>
              <ul className="space-y-1.5">
                {detail.data.cluster.map((c) => (
                  <li key={c.id} className="flex items-start justify-between gap-3">
                    <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-ink-2 hover:text-accent">
                      {c.title}
                    </a>
                    <span className="shrink-0 text-xs text-muted">{c.publisher}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {detail.data.similar.length ? (
            <section>
              <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-muted uppercase">Similar coverage (14 days)</h3>
              <ul className="space-y-1.5">
                {detail.data.similar.map((c) => (
                  <li key={c.id} className="flex items-start justify-between gap-3">
                    <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-ink-2 hover:text-accent">
                      {c.title}
                    </a>
                    <span className="shrink-0 text-xs text-muted tabular">{c.similarity?.toFixed(2)}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <p className="text-xs text-muted">
            Source: {item.source?.name ?? "—"} ({item.source?.kind}) · fetched {ago(item.fetched_at)}
          </p>
        </div>
      ) : null}
      {promoting && item ? <PromoteDialog item={item} onClose={() => setPromoting(false)} /> : null}
      {ignoring && item ? <IgnoreDialog item={item} onClose={() => setIgnoring(false)} /> : null}
    </Drawer>
  );
}

function NewsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const me = useMe();
  const jobs = useJobs();
  const pbs = usePlaybookMap();
  const playbooks = usePlaybooks();
  const canContent = me.data?.user.role !== "reviewer";
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [region, setRegion] = useState("");
  const [status, setStatus] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [sort, setSort] = useState("score");
  const [minScore, setMinScore] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const dq = useDebounced(q, 300);
  const openId = params.get("item");

  const query = { q: dq, category, region, status, source_id: sourceId, sort, min_score: minScore, page, page_size: 50 };
  const feed = useQuery({
    queryKey: ["feed", query],
    queryFn: () => get<FeedList>("/feed", query),
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => get<{ items: Source[] }>("/sources") });

  const refresh = useAction(() => post<{ job: Job }>("/feed/refresh"), {
    success: "Discovery queued",
    onSuccess: (r) =>
      jobs.watch(r.job, {
        label: "Discovery",
        invalidate: [["feed"], ["summary"]],
        success: (j) => {
          const res = j.result as { new_items?: number; unique_stories?: number; sources_ok?: number; sources?: number } | null;
          return res ? `${res.new_items ?? 0} new · ${res.unique_stories ?? 0} unique · ${res.sources_ok ?? 0}/${res.sources ?? 0} sources ok` : undefined;
        },
      }),
  });
  const bulk = useAction(() => post<{ results: { id: string; ok: boolean; error?: string }[]; promoted: number }>("/feed/promote-bulk", { ids: [...selected], auto: true }), {
    success: (r) => `Promoted ${r.promoted} of ${r.results.length}`,
    invalidate: [["feed"], ["articles"], ["summary"]],
    onSuccess: () => setSelected(new Set()),
  });

  const items = feed.data?.items ?? [];
  const allSelected = items.length > 0 && items.filter((i) => !i.article_id).every((i) => selected.has(i.id));
  const totalPages = feed.data ? Math.max(1, Math.ceil(feed.data.total / feed.data.page_size)) : 1;
  const setOpen = (id: string | null) => {
    const p = new URLSearchParams(params.toString());
    if (id) p.set("item", id);
    else p.delete("item");
    router.replace(`/news${p.toString() ? `?${p}` : ""}`, { scroll: false });
  };
  const sourceOptions = useMemo(() => (sources.data?.items ?? []).slice().sort((a, b) => a.name.localeCompare(b.name)), [sources.data]);

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader
        title="News Feed"
        subtitle={feed.data ? `${feed.data.total} stories · last fetch ${ago(feed.data.last_fetched_at, "never")}` : "Candidates from free, keyless sources"}
        actions={
          <>
            {selected.size ? (
              <Button variant="secondary" icon={<Layers className="size-3.5" />} loading={bulk.isPending} onClick={() => bulk.mutate(undefined)}>
                Promote {selected.size} selected
              </Button>
            ) : null}
            <Button variant="primary" icon={<RefreshCw className="size-3.5" />} loading={refresh.isPending} onClick={() => refresh.mutate(undefined)} disabledReason={!canContent ? "Reviewers cannot start discovery" : null}>
              Refresh
            </Button>
          </>
        }
      />
      {feed.data?.stale ? (
        <Banner tone="warn" title="Feed is stale" className="mb-4" action={<Button size="xs" onClick={() => refresh.mutate(undefined)} disabledReason={!canContent ? "Reviewers cannot start discovery" : null}>Refresh now</Button>}>
          The newest item was fetched {ago(feed.data.last_fetched_at)}. Check the worker and source health.
        </Banner>
      ) : null}

      <Card className="mb-3 flex flex-wrap items-end gap-2 px-3 py-2.5">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted" aria-hidden />
          <Input aria-label="Search stories" placeholder="Search title, summary, publisher" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="pl-8" />
        </div>
        <Select aria-label="Category" value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }} className="w-36">
          <option value="">All categories</option>
          {(playbooks.data ?? []).map((p) => (
            <option key={p.key} value={p.key}>{p.label}</option>
          ))}
        </Select>
        <Select aria-label="Region" value={region} onChange={(e) => { setRegion(e.target.value); setPage(1); }} className="w-32">
          <option value="">All regions</option>
          {REGIONS.map((r) => (
            <option key={r} value={r}>{r.toUpperCase()}</option>
          ))}
        </Select>
        <Select aria-label="Source" value={sourceId} onChange={(e) => { setSourceId(e.target.value); setPage(1); }} className="w-44">
          <option value="">All sources</option>
          {sourceOptions.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </Select>
        <Select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="w-32">
          <option value="">Open</option>
          <option value="new">New</option>
          <option value="triaged">Triaged</option>
          <option value="promoted">Promoted</option>
          <option value="ignored">Ignored</option>
          <option value="duplicate">Duplicates</option>
          <option value="all">All</option>
        </Select>
        <Select aria-label="Minimum score" value={minScore} onChange={(e) => { setMinScore(e.target.value); setPage(1); }} className="w-28">
          <option value="">Any score</option>
          <option value="0.3">≥ 0.30</option>
          <option value="0.4">≥ 0.40</option>
          <option value="0.5">≥ 0.50</option>
          <option value="0.6">≥ 0.60</option>
        </Select>
        <Select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)} className="w-32">
          <option value="score">Top score</option>
          <option value="published">Newest</option>
          <option value="fetched">Recently fetched</option>
        </Select>
      </Card>

      <Card className="overflow-hidden">
        {feed.isPending ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 10 }).map((_, i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        ) : feed.isError ? (
          <ErrorState error={feed.error} onRetry={() => feed.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            title={dq || category || region || status || sourceId || minScore ? "No stories match these filters" : "No candidates yet"}
            body="Discovery pulls from the configured RSS, GDELT, EDGAR, Hacker News and Reddit sources."
            action={<Button variant="primary" icon={<RefreshCw className="size-3.5" />} loading={refresh.isPending} onClick={() => refresh.mutate(undefined)} disabledReason={!canContent ? "Reviewers cannot start discovery" : null}>Refresh discovery</Button>}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="border-b border-line bg-surface-2/40">
                <tr>
                  <th className={`${th} w-8`}>
                    <Checkbox
                      label="Select all on page"
                      checked={allSelected}
                      onChange={(v) => setSelected(v ? new Set(items.filter((i) => !i.article_id).map((i) => i.id)) : new Set())}
                    />
                  </th>
                  <th className={th}>Story</th>
                  <th className={th}>Published</th>
                  <th className={th}>Region</th>
                  <th className={th}>Score</th>
                  <th className={th}>Category</th>
                  <th className={th}>Status</th>
                </tr>
              </thead>
              <tbody className={`divide-y divide-line ${feed.isFetching ? "opacity-80" : ""}`}>
                {items.map((it) => (
                  <tr key={it.id} className="hover:bg-surface-2/50">
                    <td className={td}>
                      <Checkbox
                        label={`Select ${it.title}`}
                        checked={selected.has(it.id)}
                        onChange={(v) => {
                          const next = new Set(selected);
                          if (v) next.add(it.id);
                          else next.delete(it.id);
                          setSelected(next);
                        }}
                        className={it.article_id || !canContent ? "invisible" : ""}
                      />
                    </td>
                    <td className={`${td} max-w-[560px]`}>
                      <button type="button" onClick={() => setOpen(it.id)} className="text-left font-medium text-ink hover:text-accent">
                        {it.title}
                      </button>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted">
                        <a href={it.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 hover:text-accent">
                          {it.publisher ?? hostOf(it.url)} <ExternalLink className="size-3" />
                        </a>
                        {it.cluster_size && it.cluster_size > 1 ? <Badge tone="info" title="Same story from other publishers (deduplicated)">×{it.cluster_size} sources</Badge> : null}
                        {it.why_it_matters ? <span className="truncate italic">{it.why_it_matters}</span> : null}
                      </div>
                    </td>
                    <td className={`${td} whitespace-nowrap text-ink-2`} title={dateTime(it.published_at)}>
                      {it.published_at ? ago(it.published_at) : "—"}
                    </td>
                    <td className={td}>{it.region ? <Badge>{it.region.toUpperCase()}</Badge> : "—"}</td>
                    <td className={td}>
                      <ScoreBar value={it.score} title={breakdownTitle(it)} />
                    </td>
                    <td className={td}>
                      {it.suggested_category ? <CategoryChip label={pbs[it.suggested_category]?.label ?? titleCase(it.suggested_category)} color={pbs[it.suggested_category]?.color} /> : "—"}
                    </td>
                    <td className={td}>
                      {it.article_id ? (
                        <Link href={`/studio/${it.article_id}`}>
                          <Badge tone="ok">In studio</Badge>
                        </Link>
                      ) : (
                        <Badge tone={it.status === "ignored" ? "neutral" : it.status === "duplicate" ? "info" : "accent"}>{it.status}</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {feed.data && feed.data.total > feed.data.page_size ? (
          <div className="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-ink-2">
            <span>
              Page {page} of {totalPages}
            </span>
            <div className="flex gap-2">
              <Button size="xs" onClick={() => setPage((p) => Math.max(1, p - 1))} disabledReason={page <= 1 ? "First page" : null}>
                Previous
              </Button>
              <Button size="xs" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabledReason={page >= totalPages ? "Last page" : null}>
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </Card>
      {openId ? <ItemDrawer id={openId} onClose={() => setOpen(null)} canContent={canContent} /> : null}
    </div>
  );
}

export default function NewsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <NewsInner />
    </Suspense>
  );
}
