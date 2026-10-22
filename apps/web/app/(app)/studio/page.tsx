"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  CategoryChip,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  JobBadge,
  PageHeader,
  Select,
  Skeleton,
  StateBadge,
  Tabs,
  Textarea,
  Toggle,
  td,
  th,
} from "@/components/ui";
import { get, post } from "@/lib/api";
import { JOB_LABEL, ago } from "@/lib/format";
import { useAction, useDebounced, useMe, usePlaybookMap, usePlaybooks } from "@/lib/hooks";
import { useJobs } from "@/lib/jobs";
import type { ArticleSummary, Category, Job, Paginated, Topic } from "@/lib/types";

const GROUPS = {
  active: { label: "In progress", states: "queued,researching,drafting,editing,seo,qa" },
  attention: { label: "Needs attention", states: "failed,needs_sources" },
  review: { label: "In review", states: "in_review" },
  ready: { label: "Approved & scheduled", states: "approved,scheduled,publishing" },
  published: { label: "Published", states: "published" },
  archived: { label: "Archived", states: "archived" },
  all: { label: "All", states: "" },
} as const;
type Group = keyof typeof GROUPS;

const REGIONS = ["global", "us", "eu", "uk", "india", "mena", "apac", "africa", "latam"];

function NewTopicDialog({ onClose }: { onClose: () => void }) {
  const playbooks = usePlaybooks();
  const router = useRouter();
  const jobs = useJobs();
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<Category>("brief");
  const [angle, setAngle] = useState("");
  const [region, setRegion] = useState("global");
  const [notes, setNotes] = useState("");
  const [links, setLinks] = useState("");
  const [auto, setAuto] = useState(true);
  const linkList = links
    .split(/\s+/)
    .map((l) => l.trim())
    .filter(Boolean);
  const badLink = linkList.find((l) => !/^https?:\/\//.test(l));
  const create = useAction(
    () =>
      post<{ topic: Topic; article: ArticleSummary; job: Job }>("/topics", {
        title,
        category,
        angle: angle || undefined,
        region,
        notes: notes || undefined,
        links: linkList,
        auto,
      }),
    {
      success: "Topic created",
      invalidate: [["articles"], ["summary"]],
      onSuccess: (r) => {
        jobs.watch(r.job, { label: auto ? "Pipeline: research" : "Research", invalidate: [["article", r.article.id], ["articles"]] });
        onClose();
        router.push(`/studio/${r.article.id}`);
      },
    },
  );
  const pb = playbooks.data?.find((p) => p.key === category);
  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title="New topic"
      description="A manual topic goes straight to research. Nothing publishes without review."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={create.isPending}
            onClick={() => create.mutate(undefined)}
            disabledReason={title.trim().length < 8 ? "Title needs at least 8 characters" : badLink ? `Not a URL: ${badLink}` : category === "room" && notes.trim().split(/\s+/).length < 40 ? "Room pieces need the transcript or interview notes" : null}
          >
            Create & start
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Working title" className="sm:col-span-2">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} placeholder="e.g. Why mid-cap manufacturers are re-shoring capex" />
        </Field>
        <Field label="Category" hint={pb ? `${pb.purpose} · ${pb.min_words}–${pb.max_words} words` : undefined}>
          <Select value={category} onChange={(e) => setCategory(e.target.value as Category)}>
            {(playbooks.data ?? []).map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Region">
          <Select value={region} onChange={(e) => setRegion(e.target.value)}>
            {REGIONS.map((r) => (
              <option key={r} value={r}>
                {r.toUpperCase()}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Angle" className="sm:col-span-2" hint="What decision does this change for a senior leader?">
          <Textarea rows={2} value={angle} onChange={(e) => setAngle(e.target.value)} maxLength={500} />
        </Field>
        <Field label={category === "room" ? "Transcript / interview notes (required for Room)" : "Notes (optional supplied material)"} className="sm:col-span-2" hint="Supplied material is treated as a source and cited like one.">
          <Textarea rows={category === "room" ? 8 : 4} value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={20000} />
        </Field>
        <Field label="Source links (optional, space or newline separated)" className="sm:col-span-2" error={badLink ? `Not a URL: ${badLink}` : undefined}>
          <Textarea rows={2} value={links} onChange={(e) => setLinks(e.target.value)} placeholder="https://…" />
        </Field>
        <div className="flex items-center justify-between rounded-md border border-line px-3 py-2.5 sm:col-span-2">
          <div>
            <p className="text-[13px] font-medium text-ink">Run the full pipeline</p>
            <p className="text-xs text-muted">Research → write → edit → SEO → QA. Off = research only.</p>
          </div>
          <Toggle checked={auto} onChange={setAuto} label="Run the full pipeline" />
        </div>
      </div>
    </Dialog>
  );
}

export default function StudioPage() {
  const me = useMe();
  const pbs = usePlaybookMap();
  const [group, setGroup] = useState<Group>("active");
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const dq = useDebounced(q, 300);
  const canContent = me.data?.user.role !== "reviewer";
  const params = { state: GROUPS[group].states, category, q: dq, page_size: 100 };
  const list = useQuery({
    queryKey: ["articles", params],
    queryFn: () => get<Paginated<ArticleSummary>>("/articles", params),
    placeholderData: keepPreviousData,
    refetchInterval: 8000,
  });

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader
        title="Content Studio"
        subtitle="Every article, its stage and the agent working on it"
        actions={
          <Button variant="primary" icon={<Plus className="size-3.5" />} onClick={() => setCreating(true)} disabledReason={!canContent ? "Reviewers cannot create topics" : null}>
            New topic
          </Button>
        }
      />
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <Tabs tabs={(Object.keys(GROUPS) as Group[]).map((g) => ({ value: g, label: GROUPS[g].label }))} value={group} onChange={setGroup} />
        <div className="flex gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-muted" aria-hidden />
            <Input aria-label="Search articles" placeholder="Search title or slug" value={q} onChange={(e) => setQ(e.target.value)} className="w-60 pl-8" />
          </div>
          <Select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)} className="w-36">
            <option value="">All categories</option>
            {Object.values(pbs).map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </Select>
        </div>
      </div>
      <Card className="overflow-hidden">
        {list.isPending ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : list.isError ? (
          <ErrorState error={list.error} onRetry={() => list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <EmptyState
            title={`Nothing ${GROUPS[group].label.toLowerCase()}`}
            body="Promote a story from the News Feed or start a topic by hand."
            action={
              <div className="flex gap-2">
                <Link href="/news">
                  <Button>Open News Feed</Button>
                </Link>
                <Button variant="primary" onClick={() => setCreating(true)} disabledReason={!canContent ? "Reviewers cannot create topics" : null}>
                  New topic
                </Button>
              </div>
            }
          />
        ) : (
          <table className="w-full text-[13px]">
            <thead className="border-b border-line bg-surface-2/40">
              <tr>
                <th className={th}>Article</th>
                <th className={th}>Category</th>
                <th className={th}>State</th>
                <th className={th}>Agent</th>
                <th className={th}>Quality</th>
                <th className={th}>Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {list.data.items.map((a) => (
                <tr key={a.id} className="hover:bg-surface-2/50">
                  <td className={`${td} max-w-[520px]`}>
                    <Link href={`/studio/${a.id}`} className="font-medium text-ink hover:text-accent">
                      {a.title}
                    </Link>
                    {a.last_error && (a.state === "failed" || a.state === "needs_sources") ? (
                      <p className="mt-0.5 truncate text-xs text-bad" title={a.last_error}>
                        {a.last_error}
                      </p>
                    ) : a.slug ? (
                      <p className="mt-0.5 font-mono text-[11px] text-muted">/{a.slug}</p>
                    ) : null}
                  </td>
                  <td className={td}>
                    <CategoryChip label={a.category_label} color={pbs[a.category]?.color} />
                  </td>
                  <td className={td}>
                    <StateBadge state={a.state} />
                    {a.revision_count ? <span className="ml-1.5 text-[11px] text-muted">rev {a.revision_count}</span> : null}
                  </td>
                  <td className={td}>
                    {a.active_job ? (
                      <span className="flex items-center gap-1.5 text-xs text-ink-2">
                        {JOB_LABEL[a.active_job.type] ?? a.active_job.type} <JobBadge status={a.active_job.status} />
                      </span>
                    ) : (
                      <span className="text-xs text-muted">idle</span>
                    )}
                  </td>
                  <td className={td}>
                    {a.qa_verdict ? (
                      <Badge tone={a.qa_verdict === "pass" ? "ok" : a.qa_verdict === "block" ? "bad" : "warn"}>
                        {a.qa_verdict} {a.qa_overall ?? ""}
                      </Badge>
                    ) : (
                      <span className="text-xs text-muted">—</span>
                    )}
                  </td>
                  <td className={`${td} text-xs whitespace-nowrap text-ink-2`}>{ago(a.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {creating ? <NewTopicDialog onClose={() => setCreating(false)} /> : null}
    </div>
  );
}
