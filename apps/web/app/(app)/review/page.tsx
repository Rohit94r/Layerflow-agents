"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, ClipboardCheck, PenLine, RotateCcw, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { DiffView, PreviewFrame, QaPanel, previousContentVersion, useVersions } from "@/components/article-bits";
import { ScheduleModal } from "@/components/schedule-modal";
import {
  Badge,
  Button,
  Card,
  CategoryChip,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  Kbd,
  PageHeader,
  Select,
  Skeleton,
  Tabs,
  Textarea,
  cn,
} from "@/components/ui";
import { get, post } from "@/lib/api";
import { ago } from "@/lib/format";
import { useAction, useHotkey, usePlaybookMap } from "@/lib/hooks";
import { useJobs } from "@/lib/jobs";
import type { ArticleDetail, ArticleSummary, Job, Paginated } from "@/lib/types";

function RevisionDialog({ a, onClose, onDone }: { a: ArticleDetail; onClose: () => void; onDone: () => void }) {
  const jobs = useJobs();
  const [reason, setReason] = useState("");
  const [stage, setStage] = useState<"write" | "edit">("write");
  const req = useAction(() => post<ArticleDetail & { job: Job }>(`/articles/${a.id}/request-revision`, { reason, stage }), {
    success: "Revision requested — the article will return to this queue after QA",
    invalidate: [["articles"], ["article", a.id], ["summary"]],
    onSuccess: (r) => {
      jobs.watch(r.job, { label: `Revision (${stage})`, invalidate: [["articles"], ["article", a.id]] });
      onClose();
      onDone();
    },
  });
  return (
    <Dialog
      open
      onClose={onClose}
      title="Request a revision"
      description={a.title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={req.isPending} onClick={() => req.mutate(undefined)} disabledReason={reason.trim().length < 3 ? "Explain what to change" : null}>
            Request revision
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="What should change?" hint="Sent to the agent as the revision instruction and kept in the review history.">
          <Textarea rows={4} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} />
        </Field>
        <Field label="Restart from">
          <Select value={stage} onChange={(e) => setStage(e.target.value as "write" | "edit")}>
            <option value="write">Write (content, structure, argument)</option>
            <option value="edit">Edit (clarity, rhythm, formatting only)</option>
          </Select>
        </Field>
      </div>
    </Dialog>
  );
}

function RejectDialog({ a, onClose, onDone }: { a: ArticleDetail; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const reject = useAction(() => post<ArticleDetail>(`/articles/${a.id}/reject`, { reason }), {
    success: "Rejected and archived",
    invalidate: [["articles"], ["article", a.id], ["summary"]],
    onSuccess: () => {
      onClose();
      onDone();
    },
  });
  return (
    <Dialog
      open
      onClose={onClose}
      title="Reject article"
      description={a.title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" loading={reject.isPending} onClick={() => reject.mutate(undefined)} disabledReason={reason.trim().length < 3 ? "Give a reason" : null}>
            Reject
          </Button>
        </>
      }
    >
      <Field label="Reason (recorded in the audit log)">
        <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} />
      </Field>
    </Dialog>
  );
}

function ReviewDetail({ id, onAdvance, onApproved }: { id: string; onAdvance: () => void; onApproved: (a: ArticleDetail) => void }) {
  const detail = useQuery({ queryKey: ["article", id], queryFn: () => get<ArticleDetail>(`/articles/${id}`) });
  const versions = useVersions(id);
  const pbs = usePlaybookMap();
  const [tab, setTab] = useState<"preview" | "diff">("preview");
  const [dialog, setDialog] = useState<"revise" | "reject" | null>(null);
  const approve = useAction(() => post<ArticleDetail>(`/articles/${id}/approve`, {}), {
    success: "Approved",
    invalidate: [["articles"], ["article", id], ["summary"]],
    onSuccess: (r) => onApproved(r),
  });
  const a = detail.data;
  const prev = useMemo(() => previousContentVersion(versions.data?.items, a?.current_version?.id), [versions.data, a?.current_version?.id]);
  const canApprove = a?.allowed_actions.can_approve ?? false;
  const canRevise = a?.allowed_actions.can_request_revision ?? false;
  const canReject = a?.allowed_actions.can_reject ?? false;

  useHotkey("a", () => canApprove && !approve.isPending && approve.mutate(undefined), Boolean(a) && !dialog);
  useHotkey("r", () => canRevise && setDialog("revise"), Boolean(a) && !dialog);

  if (detail.isPending) return <Skeleton className="h-[720px]" />;
  if (detail.isError || !a) return <ErrorState error={detail.error} onRetry={() => detail.refetch()} />;
  const reason = (ok: boolean) => (ok ? null : a.allowed_actions.busy_reason ?? `Not available: article is ${a.state}`);

  return (
    <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs">
              <CategoryChip label={a.category_label} color={pbs[a.category]?.color} />
              {a.stats ? <span className="text-muted">{a.stats.word_count} words</span> : null}
              {a.seo ? <span className="font-mono text-muted">/{a.seo.slug}</span> : null}
              {a.review_actions.some((r) => r.action === "force_review") ? <Badge tone="bad">QA override</Badge> : null}
            </div>
            <h2 className="font-display text-[22px] leading-tight font-semibold text-ink">{a.title}</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href={`/studio/${a.id}`}>
              <Button icon={<PenLine className="size-3.5" />}>Open in studio</Button>
            </Link>
            <Button variant="danger" icon={<X className="size-3.5" />} onClick={() => setDialog("reject")} disabledReason={reason(canReject)}>
              Reject
            </Button>
            <Button icon={<RotateCcw className="size-3.5" />} onClick={() => setDialog("revise")} disabledReason={reason(canRevise)}>
              Request revision <Kbd>r</Kbd>
            </Button>
            <Button variant="primary" icon={<Check className="size-3.5" />} loading={approve.isPending} onClick={() => approve.mutate(undefined)} disabledReason={reason(canApprove)}>
              Approve <Kbd>a</Kbd>
            </Button>
          </div>
        </div>
        {a.review_actions.filter((r) => r.action === "force_review").map((r) => (
          <p key={r.id} className="mb-3 rounded-md bg-bad-soft px-3 py-2 text-xs text-bad">
            Sent to review despite failing QA gates by {r.user?.name ?? "an owner"}: “{r.reason}”
          </p>
        ))}
        <Tabs
          className="mb-3"
          tabs={[
            { value: "preview", label: "Rendered as it will appear" },
            { value: "diff", label: "Changes vs previous version" },
          ]}
          value={tab}
          onChange={setTab}
        />
        {tab === "preview" ? <PreviewFrame articleId={a.id} versionKey={a.current_version?.id} /> : <DiffView before={prev?.payload?.article} after={a.current_version?.payload?.article} />}
      </div>
      <div className="space-y-4">
        <Card className="p-3.5">
          <h3 className="mb-3 text-[11px] font-semibold tracking-wider text-muted uppercase">QA report</h3>
          <QaPanel qa={a.qa} />
        </Card>
        {a.seo ? (
          <Card className="p-3.5 text-xs">
            <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-muted uppercase">Search & social</h3>
            <p className="text-[15px] leading-snug text-info">{a.seo.title_tag}</p>
            <p className="mt-0.5 text-ok">{a.seo.canonical_url}</p>
            <p className="mt-1 text-ink-2">{a.seo.meta_description}</p>
            <p className="mt-2 text-muted">
              SEO {a.seo.score}/100 · {a.seo.fields_complete}/{a.seo.fields_total} fields · keyword “{a.seo.primary_keyword}”
            </p>
          </Card>
        ) : null}
        {a.research_pack ? (
          <Card className="p-3.5 text-xs">
            <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-muted uppercase">Sources ({a.research_pack.payload.sources.length})</h3>
            <ul className="space-y-1">
              {a.research_pack.payload.sources.map((s) => (
                <li key={s.index} className="truncate">
                  <span className="text-muted">[{s.index}]</span>{" "}
                  {s.url.startsWith("http") ? (
                    <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-ink hover:text-accent">
                      {s.publisher ?? s.url}
                    </a>
                  ) : (
                    s.publisher
                  )}
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </div>
      {dialog === "revise" ? <RevisionDialog a={a} onClose={() => setDialog(null)} onDone={onAdvance} /> : null}
      {dialog === "reject" ? <RejectDialog a={a} onClose={() => setDialog(null)} onDone={onAdvance} /> : null}
    </div>
  );
}

function ReviewInner() {
  const router = useRouter();
  const params = useSearchParams();
  const pbs = usePlaybookMap();
  const queue = useQuery({
    queryKey: ["articles", { state: "in_review" }],
    queryFn: () => get<Paginated<ArticleSummary>>("/articles", { state: "in_review", page_size: 100 }),
    refetchInterval: 15_000,
  });
  const items = queue.data?.items ?? [];
  const requested = params.get("article");
  const [selected, setSelected] = useState<string | null>(requested);
  const [scheduling, setScheduling] = useState<ArticleDetail | null>(null);

  useEffect(() => {
    if (!items.length) return;
    if (!selected || !items.some((i) => i.id === selected)) {
      if (!(selected && requested === selected)) setSelected(items[0].id);
    }
  }, [items, selected, requested]);

  const move = useCallback(
    (delta: number) => {
      if (!items.length) return;
      const idx = Math.max(0, items.findIndex((i) => i.id === selected));
      const next = items[Math.min(items.length - 1, Math.max(0, idx + delta))];
      setSelected(next.id);
      router.replace(`/review?article=${next.id}`, { scroll: false });
    },
    [items, selected, router],
  );
  useHotkey("j", () => move(1), items.length > 0);
  useHotkey("k", () => move(-1), items.length > 0);

  const advance = () => {
    const idx = items.findIndex((i) => i.id === selected);
    const next = items[idx + 1] ?? items[idx - 1];
    setSelected(next && next.id !== selected ? next.id : null);
  };

  return (
    <div className="mx-auto max-w-[1700px]">
      <PageHeader
        title="Review Queue"
        subtitle={
          <span>
            Human approval before anything publishes. Keys: <Kbd>a</Kbd> approve · <Kbd>r</Kbd> request revision · <Kbd>j</Kbd>/<Kbd>k</Kbd> next/previous
          </span>
        }
      />
      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <Card className="h-fit overflow-hidden">
          {queue.isPending ? (
            <div className="space-y-2 p-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-14" />
              ))}
            </div>
          ) : queue.isError ? (
            <ErrorState error={queue.error} onRetry={() => queue.refetch()} />
          ) : items.length === 0 ? (
            <EmptyState icon={<ClipboardCheck className="size-7" />} title="Queue is empty" body="Articles arrive here after passing QA." action={<Link href="/studio"><Button>Open studio</Button></Link>} />
          ) : (
            <ul className="divide-y divide-line">
              {items.map((a) => (
                <li key={a.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setSelected(a.id);
                      router.replace(`/review?article=${a.id}`, { scroll: false });
                    }}
                    className={cn("block w-full px-3 py-2.5 text-left", selected === a.id ? "bg-accent-soft/60" : "hover:bg-surface-2")}
                    aria-current={selected === a.id}
                  >
                    <p className="line-clamp-2 text-[13px] font-medium text-ink">{a.title}</p>
                    <p className="mt-1 flex items-center gap-2 text-[11px] text-muted">
                      <CategoryChip label={a.category_label} color={pbs[a.category]?.color} />
                      {a.qa_overall != null ? <Badge tone={a.qa_verdict === "pass" ? "ok" : "warn"}>QA {a.qa_overall}</Badge> : null}
                      <span>{ago(a.updated_at)}</span>
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="min-w-0">
          {selected && items.some((i) => i.id === selected) ? (
            <ReviewDetail
              key={selected}
              id={selected}
              onAdvance={advance}
              onApproved={(a) => {
                setScheduling(a);
                advance();
              }}
            />
          ) : items.length ? (
            <EmptyState title="Select an article" />
          ) : null}
        </div>
      </div>
      {scheduling ? <ScheduleModal articleId={scheduling.id} category={scheduling.category} title={scheduling.title} onClose={() => setScheduling(null)} /> : null}
    </div>
  );
}

export default function ReviewPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <ReviewInner />
    </Suspense>
  );
}
