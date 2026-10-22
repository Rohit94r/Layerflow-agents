"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Badge, Banner, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, Skeleton, Textarea, cn } from "@/components/ui";
import { get, post, put } from "@/lib/api";
import { lineDiff } from "@/lib/diff";
import { ago } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import type { PromptDetail, PromptListItem, PromptVersionRow } from "@/lib/types";

function LineDiff({ before, after }: { before: string; after: string }) {
  const parts = useMemo(() => lineDiff(before, after), [before, after]);
  return (
    <pre className="max-h-[420px] overflow-auto rounded-md border border-line bg-surface p-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap">
      {parts.map((p, i) =>
        p.type === "same" ? (
          <span key={i} className="text-muted">
            {p.text}
          </span>
        ) : (
          <span key={i} className={p.type === "add" ? "diff-add" : "diff-del"}>
            {p.text}
          </span>
        ),
      )}
    </pre>
  );
}

export function PromptsSettings({ isOwner }: { isOwner: boolean }) {
  const list = useQuery({ queryKey: ["prompts"], queryFn: () => get<{ items: PromptListItem[] }>("/settings/prompts") });
  const [key, setKey] = useState<string | null>(null);
  useEffect(() => {
    if (!key && list.data?.items.length) setKey(list.data.items.find((p) => p.key === "agents/writer")?.key ?? list.data.items[0].key);
  }, [list.data, key]);
  const detail = useQuery({ queryKey: ["prompt", key], queryFn: () => get<PromptDetail>(`/settings/prompts/${key}`), enabled: Boolean(key) });
  const [body, setBody] = useState("");
  const [note, setNote] = useState("");
  const [compare, setCompare] = useState<PromptVersionRow | null>(null);
  useEffect(() => {
    if (detail.data) {
      setBody(detail.data.active.body);
      setCompare(null);
    }
  }, [detail.data]);
  const save = useAction(() => put<PromptDetail>(`/settings/prompts/${key}`, { body, note: note || undefined }), {
    success: (d) => `Saved as ${d.key}@${d.active.version} — run an evaluation to measure the change`,
    invalidate: [["prompts"], ["prompt", key]],
    onSuccess: () => setNote(""),
  });
  const activate = useAction((versionId: string) => post<PromptDetail>(`/settings/prompts/${key}/activate`, { version_id: versionId }), {
    success: (d) => `Active: ${d.active.version} (${d.active.source})`,
    invalidate: [["prompts"], ["prompt", key]],
  });

  if (list.isPending) return <Skeleton className="h-96" />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => list.refetch()} />;
  const groups: Record<string, PromptListItem[]> = {};
  for (const p of list.data.items) (groups[p.key.split("/")[0]] ??= []).push(p);
  const dirty = detail.data ? body !== detail.data.active.body : false;

  return (
    <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
      <Card className="h-fit overflow-hidden">
        {Object.entries(groups).map(([g, items]) => (
          <div key={g}>
            <p className="border-b border-line bg-surface-2/50 px-3 py-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">{g}</p>
            <ul>
              {items.map((p) => (
                <li key={p.key}>
                  <button type="button" onClick={() => setKey(p.key)} className={cn("flex w-full items-center justify-between px-3 py-1.5 text-left text-[13px]", key === p.key ? "bg-accent-soft/60 text-ink" : "text-ink-2 hover:bg-surface-2")}>
                    <span className="truncate">{p.key.split("/").slice(1).join("/") || p.key}</span>
                    <Badge tone={p.source === "db" ? "accent" : "neutral"}>{p.version}</Badge>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Card>
      <div className="min-w-0 space-y-4">
        <Banner tone="info" title="Prompt changes are versioned, never in place">
          Each save creates a new version; activate any earlier version (or the repository baseline) to roll back. Run an evaluation after changing a prompt.
        </Banner>
        {!key ? (
          <EmptyState title="Select a prompt" />
        ) : detail.isPending ? (
          <Skeleton className="h-96" />
        ) : detail.isError ? (
          <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
        ) : (
          <>
            <Card>
              <CardHeader title={`${detail.data.key}@${detail.data.active.version}`} subtitle={`Active source: ${detail.data.active.source === "db" ? "edited in Settings" : "repository file"}`} />
              <div className="space-y-3 p-4">
                <Textarea value={body} onChange={(e) => setBody(e.target.value)} rows={22} className="font-mono text-[12.5px]" disabled={!isOwner} aria-label="Prompt body" />
                <div className="flex flex-wrap items-end gap-2">
                  <Field label="Change note" className="min-w-[260px] flex-1">
                    <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why this change?" disabled={!isOwner} />
                  </Field>
                  <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)} disabledReason={!isOwner ? "Only owners can edit prompts" : !dirty ? "No changes" : body.trim().length < 20 ? "Prompt is too short" : null}>
                    Save as new version
                  </Button>
                  {dirty ? (
                    <Button variant="ghost" onClick={() => setBody(detail.data.active.body)}>
                      Discard
                    </Button>
                  ) : null}
                </div>
                {dirty ? (
                  <details open>
                    <summary className="cursor-pointer text-xs text-ink-2">Unsaved diff vs active</summary>
                    <div className="mt-2">
                      <LineDiff before={detail.data.active.body} after={body} />
                    </div>
                  </details>
                ) : null}
              </div>
            </Card>
            <Card className="overflow-hidden">
              <CardHeader title="Version history" />
              <ul className="divide-y divide-line">
                {detail.data.versions.map((v) => (
                  <li key={v.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-[13px]">
                    <span className="flex items-center gap-2">
                      <Badge tone={v.active ? "accent" : "neutral"}>{v.version}</Badge>
                      <span className="text-ink-2">{v.source === "file" ? "Repository baseline" : v.note || "No note"}</span>
                      {v.created_at ? <span className="text-xs text-muted">{ago(v.created_at)}</span> : null}
                    </span>
                    <span className="flex gap-1">
                      <Button size="xs" variant="ghost" onClick={() => setCompare(compare?.id === v.id ? null : v)}>
                        {compare?.id === v.id ? "Hide diff" : "Diff vs active"}
                      </Button>
                      <Button size="xs" loading={activate.isPending && activate.variables === v.id} onClick={() => activate.mutate(v.id)} disabledReason={!isOwner ? "Only owners can roll back" : v.active ? "Already active" : null}>
                        Activate
                      </Button>
                    </span>
                    {compare?.id === v.id ? (
                      <div className="w-full">
                        <LineDiff before={v.body} after={detail.data.active.body} />
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
