"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Copy, Download, ExternalLink, RefreshCw, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import {
  Badge,
  Banner,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Meter,
  PageHeader,
  Select,
  Skeleton,
  Tabs,
  cn,
  td,
  th,
} from "@/components/ui";
import { ApiError, apiUrl, errorMessage, get, patch, post } from "@/lib/api";
import { ago, hostOf, initials, pathOf } from "@/lib/format";
import { useAction, useDebounced, useMe } from "@/lib/hooks";
import { useJobs } from "@/lib/jobs";
import { useToast } from "@/lib/toast";
import type { ArticleSummary, Competitor, Job, Paginated, SeoPayload, SiteAudit, SitePage } from "@/lib/types";

type Tab = "article" | "audit" | "inventory" | "competitors";
const sevTone = { critical: "bad", major: "warn", minor: "neutral", info: "info" } as const;

/* ---------------- Article tab ---------------- */
function ArticleSeo({ canContent }: { canContent: boolean }) {
  const toast = useToast();
  const jobs = useJobs();
  const list = useQuery({
    queryKey: ["articles", { state: "seo,qa,in_review,approved,scheduled,published,failed" }],
    queryFn: () => get<Paginated<ArticleSummary>>("/articles", { state: "seo,qa,in_review,approved,scheduled,published,failed", page_size: 100 }),
  });
  const [articleId, setArticleId] = useState("");
  useEffect(() => {
    if (!articleId && list.data?.items.length) setArticleId(list.data.items[0].id);
  }, [list.data, articleId]);
  const seo = useQuery({
    queryKey: ["seo", articleId],
    queryFn: () => get<{ article: { id: string; title: string; state: string; slug: string | null }; seo: SeoPayload | null; h1: string | null; dek: string | null }>(`/seo/${articleId}`),
    enabled: Boolean(articleId),
  });
  const s = seo.data?.seo;
  const [form, setForm] = useState({ title_tag: "", meta_description: "", slug: "", primary_keyword: "", h1: "" });
  const [errors, setErrors] = useState<string[]>([]);
  useEffect(() => {
    if (s) setForm({ title_tag: s.title_tag, meta_description: s.meta_description, slug: s.slug, primary_keyword: s.primary_keyword, h1: s.h1 });
    setErrors([]);
  }, [s]);
  const save = useAction(
    () => {
      const changes: Record<string, string> = {};
      if (s) for (const k of Object.keys(form) as (keyof typeof form)[]) if (form[k] !== (s[k] ?? "")) changes[k] = form[k];
      return patch<{ seo: SeoPayload }>(`/seo/${articleId}`, changes);
    },
    {
      success: "SEO override saved",
      invalidate: [["seo", articleId], ["article", articleId]],
      onError: (e) => setErrors(e instanceof ApiError && Array.isArray(e.details) ? (e.details as string[]) : [errorMessage(e)]),
      silent: false,
    },
  );
  const regen = useAction(() => post<{ job: Job }>(`/seo/${articleId}/regenerate`), {
    success: "SEO agent started",
    onSuccess: (r) => jobs.watch(r.job, { label: "SEO", invalidate: [["seo", articleId], ["article", articleId]] }),
  });
  const dirty = s ? (Object.keys(form) as (keyof typeof form)[]).some((k) => form[k] !== (s[k] ?? "")) : false;
  const jsonLd = s ? JSON.stringify(s.json_ld, null, 2) : "";

  if (list.isPending) return <Skeleton className="h-96" />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => list.refetch()} />;
  if (!list.data.items.length) return <EmptyState title="No articles have reached SEO yet" body="Articles appear here after the SEO stage runs." action={<Link href="/studio"><Button>Open studio</Button></Link>} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Article" className="min-w-[320px] flex-1">
          <Select value={articleId} onChange={(e) => setArticleId(e.target.value)}>
            {list.data.items.map((a) => (
              <option key={a.id} value={a.id}>
                {a.title} — {a.state}
              </option>
            ))}
          </Select>
        </Field>
        <Button icon={<RefreshCw className="size-3.5" />} loading={regen.isPending} onClick={() => regen.mutate(undefined)} disabledReason={!canContent ? "Your role cannot run agents" : null}>
          Regenerate
        </Button>
        <Link href={`/studio/${articleId}`}>
          <Button>Open in studio</Button>
        </Link>
      </div>
      {seo.isPending ? (
        <Skeleton className="h-96" />
      ) : seo.isError ? (
        <ErrorState error={seo.error} onRetry={() => seo.refetch()} />
      ) : !s ? (
        <EmptyState title="SEO has not run for this article" action={<Button onClick={() => regen.mutate(undefined)} disabledReason={!canContent ? "Your role cannot run agents" : null}>Run SEO</Button>} />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card>
            <CardHeader title="Metadata" subtitle={`Score ${s.score}/100 · ${s.fields_complete}/${s.fields_total} fields · intent: ${s.search_intent}`} actions={s.overrides?.length ? <Badge tone="info">overridden: {s.overrides.join(", ")}</Badge> : null} />
            <div className="space-y-3 p-4">
              <Field label="Title tag">
                <Input value={form.title_tag} onChange={(e) => setForm({ ...form, title_tag: e.target.value })} />
                <Meter value={form.title_tag.length} min={30} max={60} label="Title tag length" />
              </Field>
              <Field label="Meta description">
                <textarea
                  value={form.meta_description}
                  onChange={(e) => setForm({ ...form, meta_description: e.target.value })}
                  rows={3}
                  className="w-full rounded-md border border-line-strong bg-surface px-2.5 py-2 text-[13px] text-ink focus:border-accent focus:outline-none"
                />
                <Meter value={form.meta_description.length} min={140} max={158} label="Meta description length" />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Slug" hint={`≤60 chars, 3–8 words · ${form.slug.length} chars`}>
                  <Input value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} className="font-mono" />
                </Field>
                <Field label="Primary keyword">
                  <Input value={form.primary_keyword} onChange={(e) => setForm({ ...form, primary_keyword: e.target.value })} />
                </Field>
              </div>
              <Field label="H1 (must differ from the title tag)">
                <Input value={form.h1} onChange={(e) => setForm({ ...form, h1: e.target.value })} />
              </Field>
              <p className="text-xs text-ink-2">Secondary: {s.secondary_keywords.join(", ") || "—"}</p>
              {errors.length ? (
                <ul className="rounded-md bg-bad-soft px-3 py-2 text-xs text-bad" role="alert">
                  {errors.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              ) : null}
              <div className="flex gap-2">
                <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)} disabledReason={!canContent ? "Your role cannot override SEO" : !dirty ? "No changes" : null}>
                  Save override
                </Button>
                {dirty && s ? (
                  <Button variant="ghost" onClick={() => setForm({ title_tag: s.title_tag, meta_description: s.meta_description, slug: s.slug, primary_keyword: s.primary_keyword, h1: s.h1 })}>
                    Reset
                  </Button>
                ) : null}
              </div>
            </div>
          </Card>
          <div className="space-y-4">
            <Card>
              <CardHeader title="Google preview" />
              <div className="p-4">
                <p className="text-xs text-ok">{hostOf(s.canonical_url)} › {pathOf(s.canonical_url).split("/").filter(Boolean).join(" › ")}</p>
                <p className="mt-0.5 text-lg leading-snug text-info hover:underline">{form.title_tag} | TEN</p>
                <p className="mt-0.5 text-[13px] text-ink-2">{form.meta_description}</p>
              </div>
            </Card>
            <Card>
              <CardHeader title="LinkedIn / Open Graph preview" />
              <div className="p-4">
                <div className="overflow-hidden rounded-md border border-line">
                  {s.og.image ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={s.og.image} alt="" className="h-40 w-full bg-surface-2 object-contain" />
                  ) : (
                    <div className="flex h-40 items-center justify-center bg-surface-2 text-xs text-muted">No og:image</div>
                  )}
                  <div className="border-t border-line bg-surface-2/60 px-3 py-2">
                    <p className="text-[13px] font-semibold text-ink">{s.og.title}</p>
                    <p className="text-xs text-muted">{hostOf(s.og.url)}</p>
                  </div>
                </div>
              </div>
            </Card>
            <Card>
              <CardHeader title="Issues" />
              <div className="p-4">
                {s.issues.length ? (
                  <ul className="space-y-1.5 text-xs">
                    {s.issues.map((i, n) => (
                      <li key={n} className="flex gap-2">
                        <Badge tone={sevTone[i.severity]}>{i.severity}</Badge>
                        <span className="text-ink-2">
                          <span className="font-medium text-ink">{i.field}</span> — {i.message}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="flex items-center gap-1.5 text-xs text-ok">
                    <CheckCircle2 className="size-3.5" /> No SEO issues
                  </p>
                )}
              </div>
            </Card>
          </div>
          <Card>
            <CardHeader title="Internal links" subtitle={`${s.inventory_size ?? 0} pages in the site inventory`} />
            <div className="p-4">
              {s.internal_links.length ? (
                <ul className="space-y-2 text-xs">
                  {s.internal_links.map((l) => (
                    <li key={l.url} className="flex items-start gap-2">
                      {l.valid ? <CheckCircle2 className="mt-0.5 size-3.5 text-ok" /> : <XCircle className="mt-0.5 size-3.5 text-bad" />}
                      <span className="min-w-0">
                        <a href={l.url} target="_blank" rel="noopener noreferrer" className="text-ink hover:text-accent">
                          {l.anchor}
                        </a>
                        <span className="block truncate text-muted">
                          {l.url} · HTTP {l.status_code ?? "?"} {l.similarity != null ? `· sim ${l.similarity}` : ""}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted">No internal links. Crawl the site inventory in the Site audit tab, then regenerate.</p>
              )}
              {s.external_links.length ? (
                <>
                  <h4 className="mt-4 mb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">Sources cited</h4>
                  <ul className="space-y-1 text-xs">
                    {s.external_links.map((l) => (
                      <li key={l.url} className="truncate">
                        <a href={l.url} target="_blank" rel="noopener noreferrer" className="text-ink-2 hover:text-accent">
                          {l.publisher ?? hostOf(l.url)} — {l.title ?? l.url}
                        </a>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </div>
          </Card>
          <Card>
            <CardHeader
              title="JSON-LD"
              subtitle="Article + BreadcrumbList; dates are stamped at publish time"
              actions={
                <Button
                  size="xs"
                  icon={<Copy className="size-3" />}
                  onClick={async () => {
                    await navigator.clipboard.writeText(jsonLd);
                    toast.success("JSON-LD copied");
                  }}
                >
                  Copy
                </Button>
              }
            />
            <pre className="max-h-[360px] overflow-auto p-4 font-mono text-[11.5px] leading-relaxed text-ink-2">{jsonLd}</pre>
          </Card>
        </div>
      )}
    </div>
  );
}

/* ---------------- Audit tab ---------------- */
function AuditTab({ canContent }: { canContent: boolean }) {
  const jobs = useJobs();
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => get<SiteAudit>("/seo/audit") });
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const run = useAction(() => post<{ job: Job }>("/seo/inventory/refresh"), {
    success: "Site crawl started (≈1 request/second, robots.txt respected)",
    onSuccess: (r) => jobs.watch(r.job, { label: "Site audit crawl", invalidate: [["audit"], ["inventory"]] }),
  });
  if (audit.isPending) return <Skeleton className="h-96" />;
  if (audit.isError) return <ErrorState error={audit.error} onRetry={() => audit.refetch()} />;
  const a = audit.data;
  const rows = showAll ? a.fix_list : a.fix_list.slice(0, 40);
  return (
    <div className="space-y-4">
      {a.source === "baseline" ? (
        <Banner tone="warn" title="Recorded baseline (20 Oct 2026) — run audit to verify" action={<Button size="sm" variant="primary" loading={run.isPending} onClick={() => run.mutate(undefined)} disabledReason={!canContent ? "Your role cannot run crawls" : null}>Run audit</Button>}>
          {a.note ?? "These findings were observed on the live site and are shown until the first crawl replaces them with live data."}
        </Banner>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-ink-2">
          <span>
            {a.summary.pages} pages crawled · {a.summary.article_pages} article pages · {a.summary.with_issues ?? 0} with issues · crawled {ago(a.crawled_at)}
          </span>
          <Button icon={<RefreshCw className="size-3.5" />} loading={run.isPending} onClick={() => run.mutate(undefined)} disabledReason={!canContent ? "Your role cannot run crawls" : null}>
            Run audit again
          </Button>
        </div>
      )}
      <Card className="overflow-hidden">
        <CardHeader title="Findings" subtitle="The site-level problems the engine fixes on every new article" />
        <table className="w-full text-[13px]">
          <thead className="border-b border-line">
            <tr>
              <th className={th}>Severity</th>
              <th className={th}>Finding</th>
              <th className={th}>Evidence</th>
              <th className={th}>Affected</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {a.findings.map((f) => (
              <tr key={f.id} className="align-top">
                <td className={td}>
                  <Badge tone={sevTone[f.severity]}>{f.severity}</Badge>
                </td>
                <td className={`${td} max-w-xs`}>
                  <p className="font-medium text-ink">{f.title}</p>
                  <p className="text-xs text-muted">{f.impact}</p>
                  {f.fix ? <p className="mt-1 text-xs text-ok">Fix: {f.fix}</p> : null}
                </td>
                <td className={`${td} max-w-md text-xs text-ink-2`}>{f.evidence}</td>
                <td className={td}>
                  {f.affected_count ? (
                    <button type="button" className="text-xs text-accent underline" onClick={() => setExpanded(expanded === f.id ? null : f.id)} aria-expanded={expanded === f.id}>
                      {f.affected_count} page(s)
                    </button>
                  ) : (
                    <span className="text-xs text-muted">—</span>
                  )}
                  {expanded === f.id ? (
                    <ul className="mt-1 max-w-sm space-y-0.5 text-[11px]">
                      {f.affected_urls.map((u) => (
                        <li key={u} className="truncate">
                          <a href={u} target="_blank" rel="noopener noreferrer" className="text-ink-2 hover:text-accent">
                            {u}
                          </a>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card className="overflow-hidden">
        <CardHeader
          title={`Fix list (${a.fix_count} pages)`}
          subtitle="New titles, descriptions, canonicals and slugs for existing posts — no new content needed"
          actions={
            <>
              <a href={apiUrl("/seo/audit/export")} download>
                <Button size="xs" icon={<Download className="size-3" />} disabledReason={!a.fix_count ? "Run the audit to build the fix list" : null}>
                  CSV
                </Button>
              </a>
              <a href={apiUrl("/seo/audit/sitemap")} download>
                <Button size="xs" icon={<Download className="size-3" />}>Corrected sitemap.xml</Button>
              </a>
            </>
          }
        />
        {a.fix_list.length === 0 ? (
          <EmptyState title="No fix list yet" body="Run the audit to crawl the live site and propose fixes for every article page." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="border-b border-line">
                <tr>
                  <th className={th}>Page</th>
                  <th className={th}>Proposed title</th>
                  <th className={th}>Proposed description</th>
                  <th className={th}>Issues</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((r) => (
                  <tr key={r.url} className="align-top">
                    <td className={`${td} max-w-[240px]`}>
                      <a href={r.url} target="_blank" rel="noopener noreferrer" className="break-all text-ink-2 hover:text-accent">
                        {pathOf(r.url)}
                      </a>
                      {r.proposed_slug ? <p className="mt-0.5 font-mono text-[10px] text-ok">→ /{r.proposed_slug}</p> : null}
                    </td>
                    <td className={`${td} max-w-[240px] text-ink`}>
                      {r.proposed_title}
                      <p className="text-[10px] text-muted">was: {r.current_title ?? "—"}</p>
                    </td>
                    <td className={`${td} max-w-[360px] text-ink-2`}>{r.proposed_description}</td>
                    <td className={td}>
                      <div className="flex flex-wrap gap-1">
                        {r.issues.map((i) => (
                          <Badge key={i} tone="warn">
                            {i}
                          </Badge>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {a.fix_list.length > 40 ? (
              <div className="border-t border-line px-4 py-2">
                <Button size="xs" variant="ghost" onClick={() => setShowAll((v) => !v)}>
                  {showAll ? "Show fewer" : `Show all ${a.fix_list.length}`}
                </Button>
              </div>
            ) : null}
          </div>
        )}
      </Card>
    </div>
  );
}

/* ---------------- Inventory tab ---------------- */
function InventoryTab() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const dq = useDebounced(q, 300);
  const inv = useQuery({
    queryKey: ["inventory", dq, page],
    queryFn: () => get<Paginated<SitePage> & { crawled_at: string | null; sitemap: Record<string, unknown> | null }>("/seo/inventory", { q: dq, page, page_size: 100 }),
    placeholderData: keepPreviousData,
  });
  if (inv.isPending) return <Skeleton className="h-96" />;
  if (inv.isError) return <ErrorState error={inv.error} onRetry={() => inv.refetch()} />;
  const pages = Math.max(1, Math.ceil(inv.data.total / inv.data.page_size));
  return (
    <Card className="overflow-hidden">
      <CardHeader title={`Site inventory (${inv.data.total})`} subtitle={inv.data.crawled_at ? `Crawled ${ago(inv.data.crawled_at)}` : "Not crawled yet — run the audit"} actions={<Input aria-label="Filter inventory" placeholder="Filter URL or title" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="w-56" />} />
      {inv.data.items.length === 0 ? (
        <EmptyState title="No pages yet" body="Run the site audit to crawl the live site (sitemap + internal links, depth 2)." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="border-b border-line">
              <tr>
                <th className={th}>URL</th>
                <th className={th}>HTTP</th>
                <th className={th}>Title</th>
                <th className={th}>H1</th>
                <th className={th}>Meta</th>
                <th className={th}>OG</th>
                <th className={th}>JSON-LD</th>
                <th className={th}>Words</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {inv.data.items.map((p) => (
                <tr key={p.id}>
                  <td className={`${td} max-w-[280px]`}>
                    <a href={p.url} target="_blank" rel="noopener noreferrer" className="break-all text-ink-2 hover:text-accent">
                      {pathOf(p.url) || "/"}
                    </a>
                  </td>
                  <td className={td}>
                    <Badge tone={p.status_code === 200 ? "ok" : "bad"}>{p.status_code ?? "?"}</Badge>
                  </td>
                  <td className={`${td} max-w-[220px] truncate`} title={p.title ?? ""}>
                    {p.title ?? "—"}
                  </td>
                  <td className={td}>{p.h1 ? <CheckCircle2 className="size-3.5 text-ok" /> : <XCircle className="size-3.5 text-bad" />}</td>
                  <td className={td}>{p.meta_description ? <CheckCircle2 className="size-3.5 text-ok" /> : <XCircle className="size-3.5 text-bad" />}</td>
                  <td className={`${td} tabular`}>{p.og_count}</td>
                  <td className={td}>{p.has_jsonld ? <CheckCircle2 className="size-3.5 text-ok" /> : <XCircle className="size-3.5 text-bad" />}</td>
                  <td className={`${td} tabular`}>{p.word_count ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {pages > 1 ? (
            <div className="flex justify-end gap-2 border-t border-line px-4 py-2">
              <Button size="xs" onClick={() => setPage((p) => p - 1)} disabledReason={page <= 1 ? "First page" : null}>
                Previous
              </Button>
              <Button size="xs" onClick={() => setPage((p) => p + 1)} disabledReason={page >= pages ? "Last page" : null}>
                Next
              </Button>
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}

/* ---------------- Competitors tab ---------------- */
function CompetitorsTab({ canContent }: { canContent: boolean }) {
  const jobs = useJobs();
  const comps = useQuery({ queryKey: ["competitors"], queryFn: () => get<{ items: Competitor[]; own_pages: number }>("/seo/competitors") });
  const refresh = useAction(() => post<{ job: Job }>("/seo/competitors/refresh"), {
    success: "Competitor crawl started",
    onSuccess: (r) => jobs.watch(r.job, { label: "Competitor crawl", invalidate: [["competitors"]] }),
  });
  if (comps.isPending) return <Skeleton className="h-96" />;
  if (comps.isError) return <ErrorState error={comps.error} onRetry={() => comps.refetch()} />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-ink-2">
        <span>On-page scan of public pages only (rate-limited, robots.txt respected). No rankings, volumes or backlinks — those need paid data.</span>
        <Button icon={<RefreshCw className="size-3.5" />} loading={refresh.isPending} onClick={() => refresh.mutate(undefined)} disabledReason={!canContent ? "Your role cannot run crawls" : null}>
          Refresh competitors
        </Button>
      </div>
      {comps.data.items.length === 0 ? (
        <EmptyState title="No competitors configured" body="Add them to config/competitors.yaml." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {comps.data.items.map((c) => (
            <Card key={c.key} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <span className="flex size-8 items-center justify-center rounded bg-surface-2 text-xs font-semibold text-ink-2">{initials(c.name)}</span>
                  <div>
                    <p className="font-display text-[15px] font-semibold text-ink">{c.name}</p>
                    <a href={c.site} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-muted hover:text-accent">
                      {hostOf(c.site)} <ExternalLink className="size-3" />
                    </a>
                  </div>
                </div>
                <span className="text-[11px] text-muted">{c.last_crawled_at ? ago(c.last_crawled_at) : "never crawled"}</span>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                <div className="rounded border border-line py-1.5">
                  <p className="text-[10px] text-muted uppercase">Pages</p>
                  <p className="font-semibold text-ink tabular">{c.pages}</p>
                </div>
                <div className="rounded border border-line py-1.5">
                  <p className="text-[10px] text-muted uppercase">Avg words</p>
                  <p className="font-semibold text-ink tabular">{c.avg_word_count ?? "—"}</p>
                </div>
                <div className="rounded border border-line py-1.5">
                  <p className="text-[10px] text-muted uppercase">JSON-LD</p>
                  <p className="font-semibold text-ink tabular">{c.jsonld_share != null ? `${Math.round(c.jsonld_share * 100)}%` : "—"}</p>
                </div>
              </div>
              {c.top_terms.length ? (
                <div className="mt-3">
                  <p className="mb-1 text-[11px] font-semibold tracking-wider text-muted uppercase">Top topics</p>
                  <div className="flex flex-wrap gap-1">
                    {c.top_terms.slice(0, 12).map((t) => (
                      <Badge key={t.term}>
                        {t.term} <span className="opacity-60">{t.pages}</span>
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}
              <div className="mt-3">
                <p className="mb-1 text-[11px] font-semibold tracking-wider text-muted uppercase">They cover, you don&apos;t</p>
                {c.gaps.length ? (
                  <div className="flex flex-wrap gap-1">
                    {c.gaps.map((g) => (
                      <Badge key={g} tone="accent">
                        {g}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-muted">{c.pages ? "No gaps against your inventory." : "Crawl to compute gaps."}</p>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function SeoInner() {
  const params = useSearchParams();
  const router = useRouter();
  const me = useMe();
  const canContent = me.data?.user.role !== "reviewer";
  const tab = (params.get("tab") as Tab) || "article";
  const setTab = (t: Tab) => router.replace(`/seo?tab=${t}`, { scroll: false });
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="SEO Workspace" subtitle="Metadata, schema and site health — rules decide, the model only proposes wording" />
      <Tabs
        className="mb-4"
        tabs={[
          { value: "article", label: "Article" },
          { value: "audit", label: "Site audit" },
          { value: "inventory", label: "Inventory" },
          { value: "competitors", label: "Competitors" },
        ]}
        value={tab}
        onChange={setTab}
      />
      <div className={cn(tab !== "article" && "hidden")}>{tab === "article" ? <ArticleSeo canContent={canContent} /> : null}</div>
      {tab === "audit" ? <AuditTab canContent={canContent} /> : null}
      {tab === "inventory" ? <InventoryTab /> : null}
      {tab === "competitors" ? <CompetitorsTab canContent={canContent} /> : null}
    </div>
  );
}

export default function SeoPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <SeoInner />
    </Suspense>
  );
}

