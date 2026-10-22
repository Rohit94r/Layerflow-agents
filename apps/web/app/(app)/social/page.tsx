"use client";

import { useQuery } from "@tanstack/react-query";
import { Copy, Download, ExternalLink, Globe, Send, Sparkles, ThumbsUp, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Badge, Banner, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, PageHeader, Skeleton, Textarea, cn } from "@/components/ui";
import { ApiError, errorMessage, get, patch, post } from "@/lib/api";
import { ago, hostOf, initials } from "@/lib/format";
import { useAction, useMe, usePlaybookMap } from "@/lib/hooks";
import { useJobs } from "@/lib/jobs";
import { useToast } from "@/lib/toast";
import type { ArticleState, Category, Job, SocialConnection, SocialPost } from "@/lib/types";

interface SocialList {
  items: SocialPost[];
  connection: SocialConnection;
  articles_without_post: { id: string; title: string; category: Category; state: ArticleState }[];
}

function escapeXml(s: string): string {
  return s.replace(/[<>&'"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" })[c] as string);
}

function wrap(text: string, max: number): string[] {
  const words = text.split(/\s+/);
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    if ((cur + " " + w).trim().length > max) {
      if (cur) lines.push(cur);
      cur = w;
    } else cur = (cur + " " + w).trim();
  }
  if (cur) lines.push(cur);
  return lines;
}

/** 1200×627 share card generated in the browser (no server, no image service). */
function cardSvg(title: string, kicker: string, brand: string, color: string): string {
  const lines = wrap(title, 34).slice(0, 4);
  const tspans = lines.map((l, i) => `<tspan x="80" dy="${i === 0 ? 0 : 78}">${escapeXml(l)}</tspan>`).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="627" viewBox="0 0 1200 627">
  <rect width="1200" height="627" fill="#f6f3ec"/>
  <rect x="0" y="0" width="16" height="627" fill="${color}"/>
  <text x="80" y="120" font-family="Helvetica, Arial, sans-serif" font-size="26" font-weight="700" letter-spacing="5" fill="${color}">${escapeXml(kicker.toUpperCase())}</text>
  <text x="80" y="230" font-family="Georgia, 'Times New Roman', serif" font-size="64" font-weight="700" fill="#17191e">${tspans}</text>
  <line x1="80" y1="540" x2="1120" y2="540" stroke="#cfc5b2" stroke-width="2"/>
  <text x="80" y="585" font-family="Georgia, serif" font-size="30" font-weight="700" fill="#17191e">${escapeXml(brand)}</text>
  <text x="1120" y="585" text-anchor="end" font-family="Helvetica, Arial, sans-serif" font-size="22" fill="#7b7f88">Powered by LayerFlow</text>
</svg>`;
}

function LinkedInPreview({ post, brand, text, hashtags }: { post: SocialPost; brand: string; text: string; hashtags: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const full = text;
  const cut = full.length > 210 && !expanded;
  return (
    <div className="mx-auto w-full max-w-[555px] rounded-lg border border-line bg-surface text-[14px] shadow-sm" aria-label="LinkedIn post preview">
      <div className="flex items-center gap-2.5 px-4 pt-3">
        <span className="flex size-11 items-center justify-center rounded bg-ink text-sm font-bold text-bg">{initials(brand)}</span>
        <div>
          <p className="font-semibold text-ink">{brand}</p>
          <p className="flex items-center gap-1 text-xs text-muted">
            Now · <Globe className="size-3" />
          </p>
        </div>
      </div>
      <div className="px-4 py-3 whitespace-pre-wrap text-ink">
        {cut ? full.slice(0, 210).trimEnd() : full}
        {cut ? (
          <button type="button" className="text-muted hover:text-info hover:underline" onClick={() => setExpanded(true)}>
            …see more
          </button>
        ) : null}
        {hashtags.length && !full.includes(`#${hashtags[0]}`) ? <p className="mt-2 text-info">{hashtags.map((h) => `#${h}`).join(" ")}</p> : null}
      </div>
      {post.link ? (
        <div className="border-y border-line bg-surface-2/60">
          {post.image_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={post.image_url} alt="" className="h-48 w-full bg-surface-3 object-contain" />
          ) : null}
          <div className="px-4 py-2.5">
            <p className="line-clamp-2 text-[13px] font-semibold text-ink">{post.article?.title ?? post.image_spec?.title}</p>
            <p className="text-xs text-muted">{hostOf(post.link)}</p>
          </div>
        </div>
      ) : null}
      <div className="flex items-center gap-4 px-4 py-2 text-xs text-muted">
        <span className="flex items-center gap-1">
          <ThumbsUp className="size-3.5" /> Like
        </span>
        <span>Comment</span>
        <span>Repost</span>
        <span>Send</span>
      </div>
    </div>
  );
}

function PostEditor({ post, connection, brand, canContent }: { post: SocialPost; connection: SocialConnection; brand: string; canContent: boolean }) {
  const toast = useToast();
  const jobs = useJobs();
  const pbs = usePlaybookMap();
  const [text, setText] = useState(post.text);
  const [tags, setTags] = useState<string[]>(post.hashtags);
  const [tagInput, setTagInput] = useState("");
  const [fallback, setFallback] = useState<string | null>(null);
  useEffect(() => {
    setText(post.text);
    setTags(post.hashtags);
    setFallback(null);
  }, [post.id, post.text, post.hashtags]);
  const dirty = text !== post.text || tags.join() !== post.hashtags.join();
  const published = post.status === "published" || post.status === "publishing";
  const save = useAction((status?: "approved" | "draft_ready") => patch<SocialPost>(`/social/${post.id}`, { text, hashtags: tags, ...(status ? { status } : {}) }), {
    success: "Post saved",
    invalidate: [["social"]],
  });
  const publish = useAction(() => post_<{ post: SocialPost; job: Job | null }>(`/social/${post.id}/publish`), {
    silent: true,
    invalidate: [["social"]],
    onSuccess: (r) => {
      if (r.job) {
        toast.success("Posting to LinkedIn");
        jobs.watch(r.job, { label: "LinkedIn post", invalidate: [["social"]] });
      } else toast.info("Already published");
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "linkedin_not_connected") setFallback(e.message);
      else toast.error("Publish failed", errorMessage(e));
    },
  });
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    toast.success("Post copied", "Paste it into LinkedIn.");
    void post_(`/social/${post.id}/copied`).catch(() => undefined);
  };
  const download = () => {
    const cat = post.article?.category ?? (post.image_spec?.kicker as Category | undefined) ?? "brief";
    const svg = cardSvg(post.article?.title ?? post.image_spec?.title ?? "The Executive Narrative", pbs[cat]?.label ?? String(cat), brand, pbs[cat]?.color ?? "#8a3b12");
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(post.article?.title ?? "post").toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 50)}-card.svg`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const n = text.length;
  const lengthTone = n < 700 ? "text-warn" : n > 1300 ? "text-bad" : "text-ok";
  const addTag = () => {
    const t = tagInput.trim().replace(/^#/, "").replace(/[^\w]/g, "");
    if (t && tags.length < 3 && !tags.some((x) => x.toLowerCase() === t.toLowerCase())) setTags([...tags, t]);
    setTagInput("");
  };

  return (
    <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_560px]">
      <Card>
        <CardHeader
          title="Post"
          subtitle={`${post.article?.title ?? ""} · ${post.status.replace("_", " ")}${post.published_at ? ` · posted ${ago(post.published_at)}` : ""}`}
          actions={post.article ? <Link href={`/studio/${post.article.id}`} className="text-xs text-accent hover:underline">Article</Link> : null}
        />
        <div className="space-y-3 p-4">
          <Field label="Text">
            <Textarea rows={14} value={text} onChange={(e) => setText(e.target.value)} disabled={published || !canContent} className="font-sans text-[14px]" />
          </Field>
          <p className={cn("text-xs tabular", lengthTone)}>
            {n} characters · target 700–1,300 (first ~210 show before “see more”)
          </p>
          <Field label="Hashtags (max 3)">
            <div className="flex flex-wrap items-center gap-1.5">
              {tags.map((t) => (
                <Badge key={t} tone="info">
                  #{t}
                  <button type="button" aria-label={`Remove #${t}`} onClick={() => setTags(tags.filter((x) => x !== t))} disabled={published}>
                    <X className="size-3" />
                  </button>
                </Badge>
              ))}
              <Input
                aria-label="Add hashtag"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === ",") {
                    e.preventDefault();
                    addTag();
                  }
                }}
                placeholder={tags.length >= 3 ? "Limit reached" : "Add tag + Enter"}
                disabled={tags.length >= 3 || published}
                className="h-7 w-40"
              />
            </div>
          </Field>
          {post.issues.length ? (
            <ul className="space-y-1 rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">
              {post.issues.map((i) => (
                <li key={i}>{i}</li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-ok">Passes the LinkedIn rules.</p>
          )}
          {post.last_error ? <p className="rounded-md bg-bad-soft px-3 py-2 text-xs text-bad">{post.last_error}</p> : null}
          {fallback ? (
            <Banner tone="warn" title="LinkedIn is not connected">
              {fallback}. Use “Copy post” and “Open LinkedIn” — the post is ready to paste.
            </Banner>
          ) : null}
          <div className="flex flex-wrap gap-2 border-t border-line pt-3">
            <Button loading={save.isPending && save.variables === undefined} onClick={() => save.mutate(undefined)} disabledReason={published ? "Already posted" : !canContent ? "Your role cannot edit posts" : !dirty ? "No changes" : null}>
              Save
            </Button>
            <Button icon={<Copy className="size-3.5" />} onClick={copy}>
              Copy post
            </Button>
            <a href="https://www.linkedin.com/feed/?shareActive=true" target="_blank" rel="noopener noreferrer">
              <Button icon={<ExternalLink className="size-3.5" />}>Open LinkedIn</Button>
            </a>
            <Button icon={<Download className="size-3.5" />} onClick={download}>
              Download image
            </Button>
            <Button
              variant="primary"
              icon={<Send className="size-3.5" />}
              loading={publish.isPending}
              onClick={() => publish.mutate(undefined)}
              disabledReason={
                published ? "Already posted" : !connection.connected ? connection.reason ?? "LinkedIn is not connected (Settings → Integrations)" : dirty ? "Save your changes first" : post.article && !["approved", "scheduled", "published"].includes(post.article.state) ? "Approve the article first" : null
              }
            >
              Publish to LinkedIn
            </Button>
          </div>
        </div>
      </Card>
      <div>
        <p className="mb-2 text-[11px] font-semibold tracking-wider text-muted uppercase">Preview</p>
        <LinkedInPreview post={post} brand={brand} text={text} hashtags={tags} />
      </div>
    </div>
  );
}

// `post` is also a prop name in this file; keep the API helper unambiguous.
const post_ = post;

export default function SocialPage() {
  const me = useMe();
  const jobs = useJobs();
  const canContent = me.data?.user.role !== "reviewer";
  const brand = me.data?.tenant.name ?? "The Executive Narrative";
  const list = useQuery({ queryKey: ["social"], queryFn: () => get<SocialList>("/social"), refetchInterval: 20_000 });
  const [selected, setSelected] = useState<string | null>(null);
  const generate = useAction((articleId: string) => post_<{ job: Job }>(`/social/${articleId}/generate`), {
    success: "Generating LinkedIn draft",
    onSuccess: (r) => jobs.watch(r.job, { label: "LinkedIn draft", invalidate: [["social"]] }),
  });
  const items = list.data?.items ?? [];
  const current = useMemo(() => items.find((p) => p.id === selected) ?? items[0], [items, selected]);

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader title="Social" subtitle="LinkedIn distribution — official API only; copy + open always works" />
      {list.data && !list.data.connection.connected ? (
        <Banner tone="info" title="LinkedIn auto-posting is off" className="mb-4" action={<Link href="/settings?tab=integrations"><Button size="sm">Integrations</Button></Link>}>
          Posting needs a LinkedIn developer app with w_member_social / w_organization_social approval. Until then every post is ready to copy: Copy post → Open LinkedIn → paste. {list.data.connection.reason}
        </Banner>
      ) : list.data ? (
        <Banner tone="ok" title="LinkedIn connected" className="mb-4">
          Posting as {list.data.connection.author_urn}
          {list.data.connection.expires_at ? ` · token expires ${ago(list.data.connection.expires_at)}` : ""}
        </Banner>
      ) : null}
      {list.isPending ? (
        <Skeleton className="h-[600px]" />
      ) : list.isError ? (
        <Card>
          <ErrorState error={list.error} onRetry={() => list.refetch()} />
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          <div className="space-y-4">
            <Card className="overflow-hidden">
              <CardHeader title={`Posts (${items.length})`} />
              {items.length === 0 ? (
                <EmptyState title="No posts yet" body="Drafts are generated after publishing, or on demand below." className="py-6" />
              ) : (
                <ul className="divide-y divide-line">
                  {items.map((p) => (
                    <li key={p.id}>
                      <button type="button" onClick={() => setSelected(p.id)} className={cn("block w-full px-3 py-2.5 text-left", current?.id === p.id ? "bg-accent-soft/60" : "hover:bg-surface-2")}>
                        <p className="line-clamp-2 text-[13px] font-medium text-ink">{p.article?.title ?? p.hook}</p>
                        <p className="mt-1 flex items-center gap-2 text-[11px] text-muted">
                          <Badge tone={p.status === "published" ? "ok" : p.status === "failed" ? "bad" : "neutral"}>{p.status.replace("_", " ")}</Badge>
                          {p.char_count} chars · {ago(p.created_at)}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card className="overflow-hidden">
              <CardHeader title="Articles without a post" />
              {list.data.articles_without_post.length === 0 ? (
                <p className="px-4 py-3 text-xs text-muted">Every reviewed article has a post.</p>
              ) : (
                <ul className="divide-y divide-line">
                  {list.data.articles_without_post.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-2 px-3 py-2">
                      <span className="min-w-0 truncate text-[13px] text-ink">{a.title}</span>
                      <Button size="xs" icon={<Sparkles className="size-3" />} loading={generate.isPending && generate.variables === a.id} onClick={() => generate.mutate(a.id)} disabledReason={!canContent ? "Your role cannot generate posts" : null}>
                        Generate
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
          <div className="min-w-0">
            {current ? (
              <PostEditor key={current.id} post={current} connection={list.data.connection} brand={brand} canContent={canContent} />
            ) : (
              <Card>
                <EmptyState title="Nothing to edit" body="Generate a LinkedIn draft for an approved or published article." />
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
