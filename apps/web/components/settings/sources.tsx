"use client";

import { useQuery } from "@tanstack/react-query";
import { FlaskConical, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, ErrorState, Field, Input, Select, Skeleton, Toggle, td, th } from "@/components/ui";
import { del, get, patch, post } from "@/lib/api";
import { ago, hostOf, ms } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import type { Source, SourceKind } from "@/lib/types";

const KINDS: SourceKind[] = ["rss", "gdelt", "edgar", "ir", "hn", "reddit"];
const REGIONS = ["", "global", "us", "eu", "uk", "india", "mena", "apac", "africa", "latam"];

interface TestResult {
  ok: boolean;
  item_count: number;
  latency_ms: number;
  error: string | null;
  sample: { title: string; url: string; published_at: string | null }[];
}

function SourceDialog({ source, onClose }: { source?: Source; onClose: () => void }) {
  const [kind, setKind] = useState<SourceKind>(source?.kind ?? "rss");
  const [name, setName] = useState(source?.name ?? "");
  const [url, setUrl] = useState(source?.url ?? "");
  const [weight, setWeight] = useState(String(source?.weight ?? 1));
  const [region, setRegion] = useState(source?.region ?? "");
  const save = useAction(
    () => {
      const body = { kind, name, url, weight: Number(weight), region: region || null };
      return source ? patch<Source>(`/sources/${source.id}`, body) : post<Source>("/sources", { ...body, active: true });
    },
    { success: source ? "Source updated" : "Source added", invalidate: [["sources"]], onSuccess: onClose },
  );
  return (
    <Dialog
      open
      onClose={onClose}
      title={source ? "Edit source" : "Add source"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)} disabledReason={name.trim().length < 2 ? "Name it" : !/^https?:\/\//.test(url) ? "Enter an http(s) URL" : null}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name" className="sm:col-span-2">
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="URL" className="sm:col-span-2" hint="RSS/Atom feed, GDELT DOC API query URL, EDGAR atom feed, HN Algolia or Reddit .json URL">
          <Input value={url} onChange={(e) => setUrl(e.target.value)} />
        </Field>
        <Field label="Kind">
          <Select value={kind} onChange={(e) => setKind(e.target.value as SourceKind)}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Region">
          <Select value={region} onChange={(e) => setRegion(e.target.value)}>
            {REGIONS.map((r) => (
              <option key={r} value={r}>
                {r ? r.toUpperCase() : "—"}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Quality weight (0.1–2.0)" hint="Feeds the source-quality part of the score.">
          <Input type="number" step="0.1" min={0.1} max={2} value={weight} onChange={(e) => setWeight(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}

export function SourcesSettings({ isOwner, canContent }: { isOwner: boolean; canContent: boolean }) {
  const q = useQuery({ queryKey: ["sources"], queryFn: () => get<{ items: Source[] }>("/sources") });
  const [editing, setEditing] = useState<Source | "new" | null>(null);
  const [results, setResults] = useState<Record<string, TestResult>>({});
  const toggle = useAction(({ id, active }: { id: string; active: boolean }) => patch<Source>(`/sources/${id}`, { active }), { success: (s) => `${s.name} ${s.active ? "enabled" : "disabled"}`, invalidate: [["sources"]] });
  const remove = useAction((id: string) => del(`/sources/${id}`), { success: "Source deleted", invalidate: [["sources"]] });
  const test = useAction((id: string) => post<TestResult>(`/sources/${id}/test`), {
    success: (r) => (r.ok ? `${r.item_count} items in ${ms(r.latency_ms)}` : undefined),
    invalidate: [["sources"]],
    onSuccess: (r, id) => setResults((m) => ({ ...m, [id]: r })),
  });
  if (q.isPending) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const active = q.data.items.filter((s) => s.active).length;
  return (
    <Card className="overflow-hidden">
      <CardHeader
        title={`Sources (${active} active of ${q.data.items.length})`}
        subtitle="Keyless feeds only. Sources switch themselves off after repeated failures."
        actions={
          <Button size="xs" variant="primary" icon={<Plus className="size-3" />} onClick={() => setEditing("new")} disabledReason={!isOwner ? "Only owners can add sources" : null}>
            Add source
          </Button>
        }
      />
      {q.data.items.length === 0 ? (
        <EmptyState title="No sources" body="Sources are seeded from config/sources/feeds.yaml on bootstrap, or add one here." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="border-b border-line">
              <tr>
                <th className={th}>Active</th>
                <th className={th}>Source</th>
                <th className={th}>Kind</th>
                <th className={th}>Weight</th>
                <th className={th}>Items (7d)</th>
                <th className={th}>Last fetch</th>
                <th className={th}>Health</th>
                <th className={th} />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {q.data.items.map((s) => {
                const r = results[s.id];
                return (
                  <tr key={s.id} className="align-top">
                    <td className={td}>
                      <Toggle checked={s.active} onChange={(v) => toggle.mutate({ id: s.id, active: v })} label={`Active: ${s.name}`} disabled={!isOwner} title={!isOwner ? "Only owners can change sources" : undefined} />
                    </td>
                    <td className={`${td} max-w-[360px]`}>
                      <p className="font-medium text-ink">{s.name}</p>
                      <a href={s.url} target="_blank" rel="noopener noreferrer" className="block truncate text-xs text-muted hover:text-accent" title={s.url}>
                        {hostOf(s.url)}
                      </a>
                      {r ? (
                        <div className="mt-1.5 rounded border border-line bg-surface-2/50 p-2 text-xs">
                          {r.ok ? (
                            <>
                              <p className="text-ok">
                                {r.item_count} items · {ms(r.latency_ms)}
                              </p>
                              <ul className="mt-1 space-y-0.5">
                                {r.sample.map((i) => (
                                  <li key={i.url} className="truncate text-ink-2">
                                    {i.title}
                                  </li>
                                ))}
                              </ul>
                            </>
                          ) : (
                            <p className="text-bad">{r.error}</p>
                          )}
                        </div>
                      ) : null}
                    </td>
                    <td className={td}>
                      <Badge>{s.kind}</Badge>
                      {s.region ? <span className="ml-1 text-[11px] text-muted">{s.region.toUpperCase()}</span> : null}
                    </td>
                    <td className={`${td} tabular`}>{s.weight.toFixed(1)}</td>
                    <td className={`${td} tabular`}>{s.items_7d ?? 0}</td>
                    <td className={`${td} text-xs text-ink-2`}>
                      {ago(s.last_fetched_at, "never")}
                      {s.last_latency_ms != null ? <span className="block text-muted">{ms(s.last_latency_ms)}</span> : null}
                    </td>
                    <td className={`${td} max-w-[220px] text-xs`}>
                      {s.last_error ? (
                        <span className="text-bad" title={s.last_error}>
                          {s.consecutive_failures}× failed: <span className="line-clamp-2">{s.last_error}</span>
                        </span>
                      ) : s.last_fetched_at ? (
                        <span className="text-ok">ok · {s.last_item_count ?? 0} items</span>
                      ) : (
                        <span className="text-muted">untested</span>
                      )}
                    </td>
                    <td className={`${td} whitespace-nowrap`}>
                      <Button size="xs" variant="ghost" icon={<FlaskConical className="size-3" />} loading={test.isPending && test.variables === s.id} onClick={() => test.mutate(s.id)} disabledReason={!canContent ? "Your role cannot test sources" : null}>
                        Test
                      </Button>
                      <Button size="xs" variant="ghost" onClick={() => setEditing(s)} disabledReason={!isOwner ? "Only owners can edit sources" : null}>
                        Edit
                      </Button>
                      <Button
                        size="xs"
                        variant="ghost"
                        icon={<Trash2 className="size-3" />}
                        aria-label={`Delete ${s.name}`}
                        loading={remove.isPending && remove.variables === s.id}
                        onClick={() => window.confirm(`Delete source “${s.name}”? Its stories stay in the feed.`) && remove.mutate(s.id)}
                        disabledReason={!isOwner ? "Only owners can delete sources" : null}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {editing ? <SourceDialog source={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} /> : null}
    </Card>
  );
}
