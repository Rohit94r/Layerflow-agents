"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Archive,
  CheckCircle2,
  Circle,
  ExternalLink,
  History,
  Loader2,
  Play,
  RotateCcw,
  Save,
  Send,
  ShieldAlert,
  Wand2,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { DiffView, LogStream, PreviewFrame, QaPanel, ResearchPanel, previousContentVersion, useArticleEvents, useVersions } from "@/components/article-bits";
import { ScheduleModal } from "@/components/schedule-modal";
import {
  Badge,
  Banner,
  Button,
  Card,
  CategoryChip,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  JobBadge,
  Select,
  Skeleton,
  StateBadge,
  Tabs,
  Textarea,
  cn,
} from "@/components/ui";
import { get, patch, post } from "@/lib/api";
import { JOB_LABEL, STATE_LABEL, ago, dateTime, ms, titleCase } from "@/lib/format";
import { useAction, useMe, usePlaybookMap } from "@/lib/hooks";
import { useJobs } from "@/lib/jobs";
import { fromMarkdown, toMarkdown, wordCount, articleText } from "@/lib/markdown";
import type { ArticleBody, ArticleDetail, Job, Section, Stage, Version } from "@/lib/types";

const STAGES: { stage: Stage; label: string; agent: string }[] = [
  { stage: "research", label: "Research", agent: "A2" },
  { stage: "write", label: "Write", agent: "A3" },
  { stage: "edit", label: "Edit", agent: "A4" },
  { stage: "seo", label: "SEO", agent: "A5" },
  { stage: "qa", label: "QA", agent: "A6" },
];
const STATE_ORDER: Record<string, number> = {
  queued: 0,
  researching: 1,
  needs_sources: 1,
  drafting: 2,
  editing: 3,
  seo: 4,
  qa: 5,
  in_review: 6,
  approved: 7,
  scheduled: 8,
  publishing: 8,
  published: 9,
};

/* ---------------- Left column ---------------- */
function StageTimeline({ a, onRun, running }: { a: ArticleDetail; onRun: (s: Stage | "auto") => void; running: string | null }) {
  const order = STATE_ORDER[a.state] ?? -1;
  const runnable = new Set(a.allowed_actions.run_stages);
  const reason = (s: Stage) =>
    a.allowed_actions.busy_reason ? `Busy: ${a.allowed_actions.busy_reason}` : `Not available while the article is ${STATE_LABEL[a.state] ?? a.state}`;
  return (
    <ol className="space-y-1">
      {STAGES.map(({ stage, label, agent }, i) => {
        const job = a.jobs.find((j) => j.type === stage);
        const active = job && (job.status === "queued" || job.status === "running");
        const failed = job && (job.status === "failed" || job.status === "dead");
        const done = job?.status === "done" || order > i + 1;
        return (
          <li key={stage} className={cn("rounded-md border px-2.5 py-2", active ? "border-accent bg-accent-soft/40" : "border-line")}>
            <div className="flex items-center gap-2">
              {active ? (
                <Loader2 className="size-4 animate-spin text-accent" />
              ) : failed ? (
                <XCircle className="size-4 text-bad" />
              ) : done ? (
                <CheckCircle2 className="size-4 text-ok" />
              ) : (
                <Circle className="size-4 text-line-strong" />
              )}
              <span className="flex-1 text-[13px] font-medium text-ink">
                {label} <span className="font-mono text-[10px] text-muted">{agent}</span>
              </span>
              <Button
                size="xs"
                variant="ghost"
                icon={<Play className="size-3" />}
                loading={running === stage}
                onClick={() => onRun(stage)}
                disabledReason={!runnable.has(stage) ? reason(stage) : null}
                aria-label={`Run ${label}`}
              >
                Run
              </Button>
            </div>
            {job ? (
              <p className="mt-1 pl-6 text-[11px] text-muted">
                <JobBadge status={job.status} attempts={job.attempts} max={job.max_attempts} /> {job.duration_ms ? `· ${ms(job.duration_ms)}` : ""} · {ago(job.finished_at ?? job.started_at ?? job.created_at)}
              </p>
            ) : null}
            {failed && job?.last_error ? (
              <p className="mt-1 line-clamp-3 pl-6 text-[11px] text-bad" title={job.last_error}>
                {job.last_error}
              </p>
            ) : null}
          </li>
        );
      })}
      {[
        { label: "Human review", idx: 6, link: "/review" },
        { label: "Published", idx: 9, link: "/calendar" },
      ].map((s) => (
        <li key={s.label} className={cn("flex items-center gap-2 rounded-md border px-2.5 py-2", order === s.idx || (s.idx === 9 && order >= 7 && order < 9) ? "border-accent bg-accent-soft/40" : "border-line")}>
          {order >= s.idx ? <CheckCircle2 className="size-4 text-ok" /> : <Circle className="size-4 text-line-strong" />}
          <Link href={s.link} className="flex-1 text-[13px] font-medium text-ink hover:text-accent">
            {s.label}
          </Link>
          {s.idx === 9 && a.published_url ? (
            <a href={a.published_url} target="_blank" rel="noopener noreferrer" className="text-accent" aria-label="Open live page">
              <ExternalLink className="size-3.5" />
            </a>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function VersionList({ a, compareId, onCompare }: { a: ArticleDetail; compareId: string | null; onCompare: (v: Version) => void }) {
  const versions = useVersions(a.id);
  const restore = useAction((vid: string) => post<ArticleDetail>(`/articles/${a.id}/versions/${vid}/restore`), {
    success: "Version restored as a new version",
    invalidate: [["article", a.id], ["versions", a.id], ["articles"]],
  });
  if (versions.isPending) return <Skeleton className="h-32" />;
  if (versions.isError) return <ErrorState error={versions.error} onRetry={() => versions.refetch()} />;
  if (!versions.data.items.length) return <p className="text-xs text-muted">No versions yet.</p>;
  return (
    <ul className="max-h-[360px] space-y-1 overflow-y-auto">
      {versions.data.items.map((v) => {
        const current = v.id === versions.data.current_version_id;
        return (
          <li key={v.id} className={cn("rounded-md border px-2.5 py-1.5 text-xs", current ? "border-accent" : compareId === v.id ? "border-info" : "border-line")}>
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5">
                <Badge tone={current ? "accent" : "neutral"}>{v.stage}</Badge>
                {current ? <span className="text-[10px] text-accent">current</span> : null}
              </span>
              <span className="text-muted" title={dateTime(v.created_at)}>
                {ago(v.created_at)}
              </span>
            </div>
            {v.note ? <p className="mt-1 line-clamp-2 text-ink-2">{v.note}</p> : null}
            <div className="mt-1 flex items-center justify-between">
              <span className="text-muted">{v.word_count ? `${v.word_count} words` : ""}</span>
              {!current && v.payload?.article ? (
                <span className="flex gap-1">
                  <Button size="xs" variant="ghost" onClick={() => onCompare(v)}>
                    Diff
                  </Button>
                  <Button
                    size="xs"
                    variant="ghost"
                    icon={<RotateCcw className="size-3" />}
                    loading={restore.isPending && restore.variables === v.id}
                    onClick={() => restore.mutate(v.id)}
                    disabledReason={!a.allowed_actions.can_restore ? a.allowed_actions.busy_reason ?? "Restoring is not allowed in this state" : null}
                  >
                    Restore
                  </Button>
                </span>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/* ---------------- Center: editor ---------------- */
function SectionEditor({ s, onChange, showHeading }: { s: Section; onChange: (s: Section) => void; showHeading: boolean }) {
  return (
    <div className="rounded-md border border-line p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="font-mono text-[10px] text-muted">{s.key}</span>
        {showHeading ? (
          <Input aria-label={`Heading for ${s.key}`} value={s.heading} onChange={(e) => onChange({ ...s, heading: e.target.value })} className="font-display text-[15px] font-semibold" />
        ) : (
          <span className="text-xs text-muted">(no heading shown — lede)</span>
        )}
      </div>
      <Textarea
        aria-label={`Paragraphs for ${s.heading}`}
        value={s.paragraphs.join("\n\n")}
        onChange={(e) => onChange({ ...s, paragraphs: e.target.value.split(/\n\s*\n/).map((p) => p.replace(/\s*\n\s*/g, " ")) })}
        rows={Math.min(14, Math.max(3, s.paragraphs.join(" ").length / 90))}
        className="font-display text-[15px]"
      />
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        <Field label="Bullets (one per line)">
          <Textarea value={(s.bullets ?? []).join("\n")} onChange={(e) => onChange({ ...s, bullets: e.target.value.split("\n").filter((b, i, arr) => b.trim() || i < arr.length - 1) })} rows={2} />
        </Field>
        <Field label="Pull quote">
          <Input value={s.pull_quote ?? ""} onChange={(e) => onChange({ ...s, pull_quote: e.target.value || null })} />
        </Field>
      </div>
    </div>
  );
}

function Editor({ a }: { a: ArticleDetail }) {
  const version = a.current_version;
  const base = version?.payload?.article;
  const [draft, setDraft] = useState<ArticleBody | null>(base ?? null);
  const [dirty, setDirty] = useState(false);
  const [mode, setMode] = useState<"visual" | "markdown">("visual");
  const [md, setMd] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    if (!dirty) {
      setDraft(base ?? null);
      if (base) setMd(toMarkdown(base, a.playbook));
    }
  }, [version?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useAction(
    () => {
      const body = mode === "markdown" && draft ? { ...draft, sections: fromMarkdown(md, draft.sections, a.playbook) } : draft;
      return patch<ArticleDetail>(`/articles/${a.id}`, {
        title: body?.title,
        dek: body?.dek,
        takeaway: body?.takeaway,
        sections: body?.sections.map((s) => ({ ...s, bullets: s.bullets.filter((b) => b.trim()) })),
        note: note || undefined,
      });
    },
    {
      success: "Saved as a new version",
      invalidate: [["article", a.id], ["versions", a.id], ["articles"]],
      onSuccess: () => {
        setDirty(false);
        setNote("");
      },
    },
  );

  if (!draft) {
    return <EmptyState title="No draft yet" body={a.state === "queued" || a.state === "researching" ? "Research is gathering sources. The writer runs next." : "Run Write once research is ready."} />;
  }
  const update = (next: ArticleBody) => {
    setDraft(next);
    setDirty(true);
  };
  const hidden = new Set(a.playbook.sections.filter((s) => !s.show_heading).map((s) => s.key));
  const liveWords = wordCount(mode === "markdown" ? md : articleText({ ...draft, title: "", dek: "" }));
  const stats = a.stats;
  const canEdit = a.allowed_actions.can_edit;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface-2/50 px-3 py-2 text-xs">
        <span className={cn("font-medium tabular", stats && !stats.in_band ? "text-warn" : "text-ink")}>
          {dirty ? liveWords : (stats?.word_count ?? liveWords)} words
        </span>
        <span className="text-muted">band {a.playbook.min_words}–{a.playbook.max_words} (±15%)</span>
        {stats ? (
          <>
            <span className="text-line-strong">|</span>
            <span className="text-ink-2" title="Flesch reading ease (long-form target 45–65)">
              Flesch {stats.readability.flesch}
            </span>
            <span className="text-ink-2">avg sentence {stats.readability.avg_sentence_len} words</span>
            <span className="text-line-strong">|</span>
            {stats.banned_hits.length ? (
              <Badge tone="bad" title={stats.banned_hits.map((h) => `${h.phrase} ×${h.count}`).join(", ")}>
                {stats.banned_hits.length} banned phrase(s)
              </Badge>
            ) : (
              <Badge tone="ok">0 banned phrases</Badge>
            )}
            {stats.sections_missing.length ? <Badge tone="warn">missing: {stats.sections_missing.join(", ")}</Badge> : null}
          </>
        ) : null}
        <div className="ml-auto flex items-center gap-1">
          <Button
            size="xs"
            variant={mode === "visual" ? "subtle" : "ghost"}
            onClick={() => {
              if (mode === "markdown") update({ ...draft, sections: fromMarkdown(md, draft.sections, a.playbook) });
              setMode("visual");
            }}
          >
            Sections
          </Button>
          <Button
            size="xs"
            variant={mode === "markdown" ? "subtle" : "ghost"}
            onClick={() => {
              setMd(toMarkdown(draft, a.playbook));
              setMode("markdown");
            }}
          >
            Markdown
          </Button>
        </div>
      </div>
      <fieldset disabled={!canEdit} className="space-y-3">
        <Field label="Title (H1)">
          <Input value={draft.title} onChange={(e) => update({ ...draft, title: e.target.value })} className="h-10 font-display text-xl font-semibold" />
        </Field>
        <Field label="Dek">
          <Textarea value={draft.dek} onChange={(e) => update({ ...draft, dek: e.target.value })} rows={2} className="font-display text-[15px]" />
        </Field>
        {mode === "markdown" ? (
          <Field label="Body (Markdown — ## headings map to the category sections in order)">
            <Textarea
              value={md}
              onChange={(e) => {
                setMd(e.target.value);
                setDirty(true);
              }}
              rows={28}
              className="font-mono text-[13px]"
            />
          </Field>
        ) : (
          draft.sections.map((s, i) => (
            <SectionEditor
              key={s.key + i}
              s={s}
              showHeading={!hidden.has(s.key)}
              onChange={(next) => update({ ...draft, sections: draft.sections.map((x, j) => (j === i ? next : x)) })}
            />
          ))
        )}
        <Field label="Takeaway">
          <Textarea value={draft.takeaway} onChange={(e) => update({ ...draft, takeaway: e.target.value })} rows={2} className="font-display text-[15px]" />
        </Field>
      </fieldset>
      <div className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t border-line bg-bg/95 py-2.5">
        <Input aria-label="Version note" placeholder="Version note (optional)" value={note} onChange={(e) => setNote(e.target.value)} className="max-w-xs" disabled={!canEdit} />
        <Button
          variant="primary"
          icon={<Save className="size-3.5" />}
          loading={save.isPending}
          onClick={() => save.mutate(undefined)}
          disabledReason={!canEdit ? a.allowed_actions.busy_reason ?? `Editing is not allowed while ${STATE_LABEL[a.state] ?? a.state}` : !dirty ? "No changes to save" : null}
        >
          Save version
        </Button>
        {dirty ? (
          <Button
            variant="ghost"
            onClick={() => {
              setDraft(base ?? null);
              if (base) setMd(toMarkdown(base, a.playbook));
              setDirty(false);
            }}
          >
            Discard changes
          </Button>
        ) : null}
        <span className="text-xs text-muted">Saving invalidates QA: the article goes back through QA before review.</span>
      </div>
    </div>
  );
}

/* ---------------- Dialogs ---------------- */
function ReviseDialog({ a, onClose }: { a: ArticleDetail; onClose: () => void }) {
  const jobs = useJobs();
  const options = (["write", "edit", "seo"] as const).filter((s) => a.allowed_actions.run_stages.includes(s));
  const [stage, setStage] = useState<"write" | "edit" | "seo">(options[0] ?? "write");
  const [instruction, setInstruction] = useState("");
  const revise = useAction(() => post<{ job: Job }>(`/articles/${a.id}/revise`, { stage, instruction }), {
    success: "Revision started",
    invalidate: [["article", a.id]],
    onSuccess: (r) => {
      jobs.watch(r.job, { invalidate: [["article", a.id], ["versions", a.id]] });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onClose={onClose}
      title="Revise with an instruction"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={revise.isPending} onClick={() => revise.mutate(undefined)} disabledReason={!options.length ? "No revisable stage in this state" : instruction.trim().length < 3 ? "Write an instruction" : null}>
            Run revision
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Stage">
          <Select value={stage} onChange={(e) => setStage(e.target.value as typeof stage)}>
            {options.map((s) => (
              <option key={s} value={s}>
                {titleCase(s)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Instruction" hint="e.g. “Lead with the capex number; cut the history section by half.” The agent never adds facts outside the research pack.">
          <Textarea rows={4} value={instruction} onChange={(e) => setInstruction(e.target.value)} maxLength={2000} />
        </Field>
      </div>
    </Dialog>
  );
}

function ForceReviewDialog({ a, onClose }: { a: ArticleDetail; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const force = useAction(() => post<ArticleDetail>(`/articles/${a.id}/force-review`, { reason }), {
    success: "Sent to review (override logged)",
    invalidate: [["article", a.id], ["articles"]],
    onSuccess: onClose,
  });
  return (
    <Dialog
      open
      onClose={onClose}
      title="Send to review with failing gates"
      description="Owner override. The reason is recorded in the audit log and shown to reviewers."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" loading={force.isPending} onClick={() => force.mutate(undefined)} disabledReason={reason.trim().length < 10 ? "Reason needs at least 10 characters" : null}>
            Send to review
          </Button>
        </>
      }
    >
      <Field label="Reason">
        <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
    </Dialog>
  );
}

/* ---------------- Page ---------------- */
export default function StudioArticlePage() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const jobs = useJobs();
  const pbs = usePlaybookMap();
  const article = useQuery({
    queryKey: ["article", id],
    queryFn: () => get<ArticleDetail>(`/articles/${id}`),
    refetchInterval: (q) => (q.state.data?.active_job ? 4000 : 30_000),
  });
  const { events, mode } = useArticleEvents(id);
  const versions = useVersions(id);
  const [centerTab, setCenterTab] = useState<"edit" | "preview" | "diff">("edit");
  const [rightTab, setRightTab] = useState<"research" | "qa" | "log" | "distribution">("research");
  const [compare, setCompare] = useState<Version | null>(null);
  const [revising, setRevising] = useState(false);
  const [forcing, setForcing] = useState(false);
  const [scheduling, setScheduling] = useState(false);
  const [running, setRunning] = useState<string | null>(null);

  const run = useAction((stage: Stage | "auto") => post<{ job: Job }>(`/articles/${id}/run`, { stage }), {
    success: (_r, s) => (s === "auto" ? "Pipeline started" : `${titleCase(s)} started`),
    invalidate: [["article", id]],
    onSuccess: (r, s) => jobs.watch(r.job, { label: s === "auto" ? "Pipeline" : undefined, invalidate: [["article", id], ["versions", id]] }),
    onError: () => setRunning(null),
  });
  const retry = useAction((jobId: string) => post<{ job: Job }>(`/jobs/${jobId}/retry`), {
    success: "Retrying",
    invalidate: [["article", id]],
    onSuccess: (r) => jobs.watch(r.job, { invalidate: [["article", id], ["versions", id]] }),
  });
  const archive = useAction(() => post<ArticleDetail>(`/articles/${id}/archive`), { success: "Archived", invalidate: [["article", id], ["articles"]] });

  useEffect(() => {
    if (!run.isPending) setRunning(null);
  }, [run.isPending]);

  const a = article.data;
  const prev = useMemo(() => compare ?? previousContentVersion(versions.data?.items, a?.current_version?.id), [compare, versions.data, a?.current_version?.id]);

  if (article.isPending) {
    return (
      <div className="mx-auto max-w-[1600px] space-y-4">
        <Skeleton className="h-10 w-2/3" />
        <div className="grid gap-4 xl:grid-cols-[260px_1fr_400px]">
          <Skeleton className="h-[600px]" />
          <Skeleton className="h-[600px]" />
          <Skeleton className="h-[600px]" />
        </div>
      </div>
    );
  }
  if (article.isError || !a) return <ErrorState error={article.error} onRetry={() => article.refetch()} />;

  const aa = a.allowed_actions;
  const lastFailed = a.jobs.find((j) => j.status === "failed" || j.status === "dead");
  const canContent = me.data?.user.role !== "reviewer";
  const doRun = (s: Stage | "auto") => {
    setRunning(s);
    run.mutate(s);
  };

  return (
    <div className="mx-auto max-w-[1600px]">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3 border-b border-line pb-4">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2 text-xs">
            <Link href="/studio" className="text-muted hover:text-accent">
              Studio
            </Link>
            <span className="text-muted">/</span>
            <CategoryChip label={a.category_label} color={pbs[a.category]?.color} />
            <StateBadge state={a.state} />
            {a.revision_count ? <Badge>revision {a.revision_count}</Badge> : null}
            {a.slug ? <span className="font-mono text-muted">/{a.slug}</span> : null}
          </div>
          <h1 className="font-display text-[26px] leading-tight font-semibold text-ink">{a.title}</h1>
          {a.topic?.angle ? <p className="mt-1 max-w-3xl text-sm text-ink-2">Angle: {a.topic.angle}</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {a.published_url ? (
            <a href={a.published_url} target="_blank" rel="noopener noreferrer">
              <Button icon={<ExternalLink className="size-3.5" />}>Live page</Button>
            </a>
          ) : null}
          <Button icon={<Wand2 className="size-3.5" />} onClick={() => setRevising(true)} disabledReason={!canContent ? "Your role cannot revise" : aa.busy_reason ? `Busy: ${aa.busy_reason}` : !aa.run_stages.some((s) => ["write", "edit", "seo"].includes(s)) ? "Nothing to revise yet" : null}>
            Revise
          </Button>
          <Button variant="primary" icon={<Play className="size-3.5" />} loading={running === "auto"} onClick={() => doRun("auto")} disabledReason={!aa.can_run_auto ? aa.busy_reason ? `Busy: ${aa.busy_reason}` : "Auto runs from research; use the stage buttons instead" : null}>
            Run auto
          </Button>
          {aa.can_schedule ? (
            <Button variant="primary" icon={<Send className="size-3.5" />} onClick={() => setScheduling(true)}>
              Schedule
            </Button>
          ) : null}
          {a.state === "in_review" ? (
            <Link href={`/review?article=${a.id}`}>
              <Button variant="primary">Open in review</Button>
            </Link>
          ) : null}
          <Button variant="ghost" icon={<Archive className="size-3.5" />} loading={archive.isPending} onClick={() => archive.mutate(undefined)} disabledReason={!canContent ? "Your role cannot archive" : a.state === "archived" ? "Already archived" : aa.busy_reason ? `Busy: ${aa.busy_reason}` : ["scheduled", "publishing", "published"].includes(a.state) ? "Cancel or roll back publication first" : null}>
            Archive
          </Button>
        </div>
      </div>

      {a.state === "needs_sources" ? (
        <Banner
          tone="warn"
          title="Needs more sources"
          className="mb-4"
          action={
            <Button size="sm" onClick={() => doRun("research")} loading={running === "research"} disabledReason={!aa.run_stages.includes("research") ? aa.busy_reason ?? "Not available" : null}>
              Re-run research
            </Button>
          }
        >
          {a.last_error ?? "The research agent refused to write from thin evidence."} Add source links or notes to the topic, or try again later when more coverage exists.
        </Banner>
      ) : null}
      {a.state === "failed" ? (
        <Banner
          tone="bad"
          title="Pipeline stopped"
          className="mb-4"
          action={
            <div className="flex gap-2">
              {lastFailed ? (
                <Button size="sm" icon={<RotateCcw className="size-3.5" />} loading={retry.isPending} onClick={() => retry.mutate(lastFailed.id)} disabledReason={!canContent ? "Your role cannot retry" : null}>
                  Retry {JOB_LABEL[lastFailed.type] ?? lastFailed.type}
                </Button>
              ) : null}
              {aa.can_force_review ? (
                <Button size="sm" variant="danger" icon={<ShieldAlert className="size-3.5" />} onClick={() => setForcing(true)}>
                  Send to review anyway
                </Button>
              ) : null}
            </div>
          }
        >
          {a.last_error}
        </Banner>
      ) : null}
      {a.qa?.verdict === "revise" && a.state === "qa" && !a.active_job ? (
        <Banner tone="warn" title="QA asked for a revision" className="mb-4" action={aa.can_force_review ? <Button size="sm" variant="danger" onClick={() => setForcing(true)}>Send to review anyway</Button> : null}>
          {a.qa.revision_instruction}
        </Banner>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)_400px]">
        <div className="space-y-4">
          <Card className="p-3">
            <h2 className="mb-2 text-[11px] font-semibold tracking-wider text-muted uppercase">Pipeline</h2>
            <StageTimeline a={a} onRun={doRun} running={running} />
            {a.active_job ? (
              <p className="mt-2 text-xs text-ink-2">
                {JOB_LABEL[a.active_job.type]} is {a.active_job.status}…
              </p>
            ) : null}
          </Card>
          <Card className="p-3">
            <h2 className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">
              <History className="size-3.5" /> Versions
            </h2>
            <VersionList
              a={a}
              compareId={compare?.id ?? null}
              onCompare={(v) => {
                setCompare(v);
                setCenterTab("diff");
              }}
            />
          </Card>
        </div>

        <div className="min-w-0">
          <Tabs
            className="mb-3"
            tabs={[
              { value: "edit", label: "Editor" },
              { value: "preview", label: "Rendered preview" },
              { value: "diff", label: "Diff vs previous" },
            ]}
            value={centerTab}
            onChange={setCenterTab}
          />
          {centerTab === "edit" ? (
            <Editor a={a} />
          ) : centerTab === "preview" ? (
            a.current_version ? <PreviewFrame articleId={a.id} versionKey={a.current_version.id} /> : <EmptyState title="Nothing to preview yet" />
          ) : (
            <div>
              {compare ? (
                <p className="mb-2 text-xs text-ink-2">
                  Comparing the {compare.stage} version from {ago(compare.created_at)} with the current version.{" "}
                  <button type="button" className="text-accent underline" onClick={() => setCompare(null)}>
                    Use previous instead
                  </button>
                </p>
              ) : null}
              <DiffView before={prev?.payload?.article} after={a.current_version?.payload?.article} />
            </div>
          )}
        </div>

        <div className="min-w-0">
          <Tabs
            className="mb-3"
            tabs={[
              { value: "research", label: "Research" },
              { value: "qa", label: "QA" },
              { value: "log", label: "Log", count: events.length || undefined },
              { value: "distribution", label: "Publish" },
            ]}
            value={rightTab}
            onChange={setRightTab}
          />
          <Card className="p-3.5">
            {rightTab === "research" ? (
              <ResearchPanel pack={a.research_pack} />
            ) : rightTab === "qa" ? (
              <div className="space-y-5">
                <QaPanel qa={a.qa} />
                {a.editor ? (
                  <details className="text-xs">
                    <summary className="cursor-pointer font-medium text-ink-2">Editor report ({a.editor.change_log.length} changes)</summary>
                    {a.editor.format_report.violations.length ? (
                      <ul className="mt-2 list-disc pl-4 text-bad">
                        {a.editor.format_report.violations.map((v) => (
                          <li key={v.code + v.message}>{v.message}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-2 text-ok">No structural violations.</p>
                    )}
                    <ul className="mt-2 max-h-56 space-y-0.5 overflow-y-auto text-ink-2">
                      {a.editor.change_log.map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </div>
            ) : rightTab === "log" ? (
              <LogStream events={events} mode={mode} />
            ) : (
              <div className="space-y-4 text-[13px]">
                <section>
                  <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Publications</h4>
                  {a.publications.length ? (
                    <ul className="space-y-2">
                      {a.publications.map((p) => (
                        <li key={p.id} className="rounded-md border border-line px-2.5 py-2 text-xs">
                          <div className="flex items-center justify-between">
                            <span className="font-medium text-ink">{p.target}</span>
                            <Badge tone={p.status === "published" ? "ok" : p.status === "failed" ? "bad" : "info"}>{p.status}</Badge>
                          </div>
                          <p className="mt-1 text-ink-2">{p.published_at ? `Published ${dateTime(p.published_at)}` : p.scheduled_at ? `Scheduled ${dateTime(p.scheduled_at)}` : ""}</p>
                          {p.live_url ? (
                            <a href={p.live_url} target="_blank" rel="noopener noreferrer" className="mt-0.5 block break-all text-accent hover:underline">
                              {p.live_url}
                            </a>
                          ) : null}
                          {p.last_error ? <p className="mt-0.5 text-bad">{p.last_error}</p> : null}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted">Not scheduled yet. Approve in the review queue, then schedule.</p>
                  )}
                  {aa.can_schedule ? (
                    <Button className="mt-2" size="sm" variant="primary" onClick={() => setScheduling(true)}>
                      Schedule
                    </Button>
                  ) : null}
                </section>
                <section>
                  <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">LinkedIn</h4>
                  {a.social_posts.length ? (
                    <ul className="space-y-1.5">
                      {a.social_posts.map((p) => (
                        <li key={p.id} className="text-xs">
                          <Badge tone={p.status === "published" ? "ok" : "neutral"}>{p.status}</Badge> <span className="text-ink-2">{p.char_count} chars</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted">No LinkedIn draft yet (generated automatically after publishing, or from Social).</p>
                  )}
                  <Link href="/social" className="mt-1 inline-block text-xs text-accent hover:underline">
                    Open Social →
                  </Link>
                </section>
                {a.review_actions.length ? (
                  <section>
                    <h4 className="mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Review history</h4>
                    <ul className="space-y-1.5 text-xs">
                      {a.review_actions.map((r) => (
                        <li key={r.id}>
                          <Badge tone={r.action === "approve" ? "ok" : r.action === "reject" ? "bad" : "warn"}>{r.action.replace("_", " ")}</Badge>{" "}
                          <span className="text-ink-2">{r.user?.name ?? "user"} · {ago(r.created_at)}</span>
                          {r.reason ? <p className="mt-0.5 text-ink-2">“{r.reason}”</p> : null}
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}
              </div>
            )}
          </Card>
          {rightTab !== "log" ? (
            <div className="mt-3">
              <LogStream events={events.slice(-12)} mode={mode} />
            </div>
          ) : null}
        </div>
      </div>

      {revising ? <ReviseDialog a={a} onClose={() => setRevising(false)} /> : null}
      {forcing ? <ForceReviewDialog a={a} onClose={() => setForcing(false)} /> : null}
      {scheduling ? <ScheduleModal articleId={a.id} category={a.category} title={a.title} onClose={() => setScheduling(false)} /> : null}
    </div>
  );
}
