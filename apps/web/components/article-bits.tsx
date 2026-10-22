"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ExternalLink, ShieldAlert, XCircle } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, apiUrl, get } from "@/lib/api";
import { wordDiff, diffStats } from "@/lib/diff";
import { ago, hostOf, titleCase } from "@/lib/format";
import { articleText } from "@/lib/markdown";
import type { ArticleBody, JobEvent, QaReport, ResearchPack, Version } from "@/lib/types";
import { Badge, EmptyState, ErrorState, Skeleton, cn, type Tone } from "./ui";

/* ---------------- Live events (SSE with polling fallback) ---------------- */
export function useArticleEvents(articleId: string) {
  const qc = useQueryClient();
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [mode, setMode] = useState<"sse" | "poll" | "connecting">("connecting");
  const lastId = useRef(0);

  useEffect(() => {
    setEvents([]);
    lastId.current = 0;
    let es: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let closed = false;
    const add = (e: JobEvent) => {
      if (e.id <= lastId.current) return;
      lastId.current = e.id;
      setEvents((prev) => [...prev.slice(-400), e]);
    };
    const refreshArticle = () => {
      qc.invalidateQueries({ queryKey: ["article", articleId] });
      qc.invalidateQueries({ queryKey: ["versions", articleId] });
    };
    const startPolling = () => {
      setMode("poll");
      const tick = async () => {
        try {
          const r = await get<{ items: JobEvent[] }>(`/articles/${articleId}/logs`, { after: lastId.current });
          if (r.items.length) {
            r.items.forEach(add);
            refreshArticle();
          }
        } catch {
          /* keep polling */
        }
      };
      void tick();
      pollTimer = setInterval(tick, 3000);
    };
    if (typeof EventSource !== "undefined") {
      es = new EventSource(apiUrl(`/articles/${articleId}/events`, { after: 0 }), { withCredentials: true });
      es.onopen = () => !closed && setMode("sse");
      es.addEventListener("log", (m) => add(JSON.parse((m as MessageEvent).data) as JobEvent));
      es.addEventListener("state", refreshArticle);
      es.addEventListener("job", () => {
        qc.invalidateQueries({ queryKey: ["article", articleId] });
      });
      let errors = 0;
      es.onerror = () => {
        errors += 1;
        if (errors >= 3 && es) {
          es.close();
          es = null;
          if (!closed) startPolling();
        }
      };
    } else {
      startPolling();
    }
    return () => {
      closed = true;
      es?.close();
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [articleId, qc]);

  return { events, mode };
}

export function LogStream({ events, mode }: { events: JobEvent[]; mode: string }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [events.length]);
  return (
    <div>
      <p className="mb-1.5 flex items-center justify-between text-[11px] text-muted">
        <span>Live agent log</span>
        <span title={mode === "sse" ? "Server-sent events" : mode === "poll" ? "Polling every 3 s" : "Connecting"}>
          <span className={cn("mr-1 inline-block size-1.5 rounded-full", mode === "sse" ? "bg-ok" : mode === "poll" ? "bg-warn" : "bg-muted")} />
          {mode === "sse" ? "live" : mode}
        </span>
      </p>
      <div ref={box} className="h-64 overflow-y-auto rounded-md border border-line bg-surface-2/50 p-2 font-mono text-[11.5px] leading-relaxed" aria-live="polite">
        {events.length === 0 ? <p className="text-muted">No agent activity yet.</p> : null}
        {events.map((e) => (
          <div key={e.id} className={cn("flex gap-2", e.level === "error" ? "text-bad" : e.level === "warn" ? "text-warn" : "text-ink-2")}>
            <span className="shrink-0 text-muted">{e.created_at ? new Date(e.created_at).toLocaleTimeString([], { hour12: false }) : ""}</span>
            <span className="break-words">{e.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- Research ---------------- */
const confTone: Record<string, Tone> = { high: "ok", medium: "info", low: "warn", needs_verification: "bad" };

export function ResearchPanel({ pack }: { pack: ResearchPack | null }) {
  if (!pack) return <EmptyState title="No research yet" body="Run Research to build the evidence pack." className="py-8" />;
  const p = pack.payload;
  return (
    <div className="space-y-4 text-[13px]">
      {pack.status !== "ok" ? (
        <div className="rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">
          <p className="font-semibold">Needs more sources</p>
          <p>{p.reason}</p>
        </div>
      ) : null}
      {p.summary ? <p className="font-display text-[14.5px] leading-relaxed text-ink">{p.summary}</p> : null}
      <div className="flex flex-wrap gap-1.5 text-[11px]">
        <Badge>{p.coverage.source_count} sources</Badge>
        <Badge>{p.coverage.independent_publishers} publishers</Badge>
        <Badge tone={p.coverage.has_primary_source ? "ok" : "neutral"}>{p.coverage.has_primary_source ? "primary source" : "no primary source"}</Badge>
      </div>
      {p.warnings?.length ? (
        <ul className="space-y-1">
          {p.warnings.map((w) => (
            <li key={w} className="flex gap-1.5 text-xs text-warn">
              <AlertTriangle className="mt-0.5 size-3 shrink-0" /> {w}
            </li>
          ))}
        </ul>
      ) : null}
      {p.key_facts.length ? (
        <section>
          <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Key facts</h4>
          <ol className="space-y-2">
            {p.key_facts.map((f) => (
              <li key={f.id} className="flex gap-2">
                <span className="mt-0.5 font-mono text-[11px] text-muted">[{f.id}]</span>
                <div className="min-w-0">
                  <p className="text-ink">{f.claim}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                    <a href={f.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 hover:text-accent">
                      {f.source_name ?? hostOf(f.source_url)} <ExternalLink className="size-2.5" />
                    </a>
                    <Badge tone={confTone[f.confidence] ?? "neutral"}>{f.confidence.replace("_", " ")}</Badge>
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      {p.numbers.length ? (
        <section>
          <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Numbers</h4>
          <ul className="space-y-1">
            {p.numbers.map((n, i) => (
              <li key={i} className="flex gap-2 text-xs">
                <span className={cn("font-mono font-semibold", n.verified ? "text-ink" : "text-bad")} title={n.verified ? "Found verbatim in the source" : "Not found verbatim in its source"}>
                  {n.value} {n.unit}
                </span>
                <span className="text-ink-2">{n.context}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {p.counterpoints?.length ? (
        <section>
          <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Counterpoints</h4>
          <ul className="list-disc space-y-1 pl-4 text-ink-2">
            {p.counterpoints.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </section>
      ) : null}
      <section>
        <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Sources</h4>
        <ul className="space-y-1.5">
          {p.sources.map((s) => (
            <li key={s.index} className="text-xs">
              <span className="mr-1 font-mono text-muted">[{s.index}]</span>
              {s.url.startsWith("http") ? (
                <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-ink hover:text-accent">
                  {s.title ?? s.url}
                </a>
              ) : (
                <span className="text-ink">{s.title ?? "Supplied material"}</span>
              )}
              <span className="text-muted"> — {s.publisher ?? hostOf(s.url)} · {s.word_count} words</span>
              {s.injection_flags?.length ? (
                <p className="mt-0.5 flex items-center gap-1 text-bad" title={s.injection_flags.join("; ")}>
                  <ShieldAlert className="size-3" /> Instruction-like text detected and ignored
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
      {p.skipped?.length ? (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted">{p.skipped.length} source(s) skipped</summary>
          <ul className="mt-1 space-y-1">
            {p.skipped.map((s) => (
              <li key={s.url} className="truncate text-ink-2" title={s.url}>
                {hostOf(s.url)} — {s.reason}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

/* ---------------- QA ---------------- */
const sevTone: Record<string, Tone> = { critical: "bad", major: "warn", minor: "neutral" };

export function QaPanel({ qa }: { qa: QaReport | null }) {
  if (!qa) return <EmptyState title="QA has not run" body="Run QA after SEO to score the article against its sources." className="py-8" />;
  const verdictTone: Tone = qa.verdict === "pass" ? "ok" : qa.verdict === "block" ? "bad" : "warn";
  return (
    <div className="space-y-4 text-[13px]">
      <div className="flex items-center justify-between">
        <Badge tone={verdictTone} className="px-2 py-1 text-xs uppercase">
          {qa.verdict}
        </Badge>
        <span className="font-display text-2xl font-semibold text-ink tabular">
          {qa.overall}
          <span className="text-sm text-muted">/100</span>
        </span>
      </div>
      {qa.stale_seo ? <p className="text-xs text-warn">SEO changed after this QA run.</p> : null}
      <p className="text-ink-2">{qa.summary}</p>
      <div className="grid grid-cols-3 gap-1.5">
        {Object.entries(qa.scores).map(([k, v]) => (
          <div key={k} className="rounded border border-line px-2 py-1.5">
            <p className="truncate text-[10px] text-muted uppercase">{titleCase(k)}</p>
            <p className={cn("font-semibold tabular", v >= 4 ? "text-ok" : v >= 3 ? "text-ink" : "text-bad")}>{v}/5</p>
          </div>
        ))}
      </div>
      <section>
        <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Quality gates</h4>
        <ul className="space-y-1">
          {qa.gates.map((g) => (
            <li key={g.gate} className="flex items-start gap-2 text-xs">
              {g.passed ? <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-ok" /> : <XCircle className={cn("mt-0.5 size-3.5 shrink-0", g.blocking ? "text-bad" : "text-warn")} />}
              <span className="min-w-0">
                <span className="font-medium text-ink">{titleCase(g.gate)}</span>
                {!g.blocking ? <span className="text-muted"> (warn)</span> : null}
                <span className="block text-ink-2">{g.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>
      {qa.issues.length ? (
        <section>
          <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Issues ({qa.issues.length})</h4>
          <ul className="space-y-1.5">
            {qa.issues.map((i, n) => (
              <li key={n} className="flex items-start gap-2 text-xs">
                <Badge tone={sevTone[i.severity]}>{i.severity}</Badge>
                <span className="min-w-0 text-ink-2">
                  {i.message} <span className="text-muted">· {i.location}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <p className="text-[11px] text-muted">
        Executive questions answered: {qa.exec_questions_answered.length ? qa.exec_questions_answered.map(titleCase).join(", ") : "none"} · rubric: {qa.rubric_source} · {ago(qa.created_at)}
      </p>
    </div>
  );
}

/* ---------------- Diff ---------------- */
export function DiffView({ before, after, className }: { before: ArticleBody | undefined; after: ArticleBody | undefined; className?: string }) {
  const parts = useMemo(() => wordDiff(articleText(before), articleText(after)), [before, after]);
  const stats = diffStats(parts);
  if (!before) return <p className="text-xs text-muted">No earlier version to compare.</p>;
  return (
    <div className={className}>
      <p className="mb-2 text-xs text-ink-2">
        <span className="text-ok">+{stats.added}</span> / <span className="text-bad">−{stats.removed}</span> words
      </p>
      <div className="max-h-[480px] overflow-y-auto rounded-md border border-line bg-surface p-3 font-display text-[14px] leading-relaxed whitespace-pre-wrap text-ink">
        {parts.map((p, i) =>
          p.type === "same" ? (
            <span key={i}>{p.text}</span>
          ) : p.type === "add" ? (
            <ins key={i} className="diff-add">
              {p.text}
            </ins>
          ) : (
            <del key={i} className="diff-del">
              {p.text}
            </del>
          ),
        )}
      </div>
    </div>
  );
}

/** Versions list for an article (newest first) with payloads; previous = the version before the current one. */
export function useVersions(articleId: string | null | undefined) {
  return useQuery({
    queryKey: ["versions", articleId],
    queryFn: () => get<{ items: Version[]; current_version_id: string | null }>(`/articles/${articleId}/versions`),
    enabled: Boolean(articleId),
  });
}

export function previousContentVersion(items: Version[] | undefined, currentId: string | null | undefined): Version | undefined {
  if (!items?.length) return undefined;
  const idx = items.findIndex((v) => v.id === currentId);
  const current = items[idx >= 0 ? idx : 0];
  const curText = articleText(current?.payload?.article);
  return items.slice((idx >= 0 ? idx : 0) + 1).find((v) => v.payload?.article && articleText(v.payload.article) !== curText);
}

/* ---------------- Preview ---------------- */
export function PreviewFrame({ articleId, versionKey, className }: { articleId: string; versionKey?: string | null; className?: string }) {
  const html = useQuery({
    queryKey: ["preview", articleId, versionKey],
    queryFn: () => api<string>(`/articles/${articleId}/preview`, { text: true }),
  });
  if (html.isPending) return <Skeleton className={cn("h-[640px] w-full", className)} />;
  if (html.isError) return <ErrorState error={html.error} onRetry={() => html.refetch()} />;
  return <iframe title="Rendered article preview" sandbox="" srcDoc={html.data} className={cn("h-[720px] w-full rounded-md border border-line bg-white", className)} />;
}
