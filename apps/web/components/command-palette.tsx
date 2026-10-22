"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText, Newspaper, Rss, Search, CornerDownLeft } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { get } from "@/lib/api";
import { STATE_LABEL } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import type { SearchResults } from "@/lib/types";
import { Kbd, Spinner, cn } from "./ui";

const PAGES = [
  { label: "Dashboard", href: "/" },
  { label: "News Feed", href: "/news" },
  { label: "Content Studio", href: "/studio" },
  { label: "Review Queue", href: "/review" },
  { label: "SEO Workspace", href: "/seo" },
  { label: "Site audit", href: "/seo?tab=audit" },
  { label: "Calendar", href: "/calendar" },
  { label: "Social", href: "/social" },
  { label: "Settings", href: "/settings" },
  { label: "Settings · Sources", href: "/settings?tab=sources" },
  { label: "Settings · Models", href: "/settings?tab=models" },
  { label: "Settings · Integrations", href: "/settings?tab=integrations" },
];

interface Item {
  key: string;
  label: string;
  hint?: string;
  href: string;
  icon: "page" | "article" | "feed" | "source";
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const dq = useDebounced(q.trim(), 200);
  const search = useQuery({
    queryKey: ["search", dq],
    queryFn: () => get<SearchResults>("/search", { q: dq }),
    enabled: open && dq.length >= 2,
  });

  useEffect(() => {
    if (open) {
      setQ("");
      setIdx(0);
      setTimeout(() => input.current?.focus(), 0);
    }
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const pages = PAGES.filter((p) => !q || p.label.toLowerCase().includes(q.toLowerCase())).map<Item>((p) => ({ key: `p:${p.href}`, label: p.label, href: p.href, icon: "page" }));
    const r = dq.length >= 2 ? search.data : undefined;
    const arts = (r?.articles ?? []).map<Item>((a) => ({ key: `a:${a.id}`, label: a.title, hint: STATE_LABEL[a.state], href: `/studio/${a.id}`, icon: "article" }));
    const feed = (r?.feed ?? []).map<Item>((f) => ({ key: `f:${f.id}`, label: f.title, hint: f.publisher ?? undefined, href: `/news?item=${f.id}`, icon: "feed" }));
    const sources = (r?.sources ?? []).map<Item>((s) => ({ key: `s:${s.id}`, label: s.name, hint: s.kind, href: "/settings?tab=sources", icon: "source" }));
    return [...arts, ...feed, ...sources, ...pages].slice(0, 20);
  }, [q, dq, search.data]);

  useEffect(() => setIdx(0), [items.length]);

  if (!open) return null;
  const go = (item: Item | undefined) => {
    if (!item) return;
    onClose();
    router.push(item.href);
  };
  const Icon = ({ kind }: { kind: Item["icon"] }) =>
    kind === "article" ? <FileText className="size-3.5" /> : kind === "feed" ? <Newspaper className="size-3.5" /> : kind === "source" ? <Rss className="size-3.5" /> : <CornerDownLeft className="size-3.5" />;

  return (
    <div className="fixed inset-0 z-[85] flex items-start justify-center bg-black/40 p-4 pt-[12vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" data-open="true" aria-label="Search" className="w-full max-w-xl overflow-hidden rounded-lg border border-line bg-surface shadow-2xl">
        <div className="flex items-center gap-2 border-b border-line px-3">
          <Search className="size-4 text-muted" aria-hidden />
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setIdx((i) => Math.min(items.length - 1, i + 1));
              }
              if (e.key === "ArrowUp") {
                e.preventDefault();
                setIdx((i) => Math.max(0, i - 1));
              }
              if (e.key === "Enter") go(items[idx]);
            }}
            placeholder="Search articles, stories, sources — or jump to a page"
            className="h-12 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-muted"
            aria-label="Search query"
          />
          {search.isFetching ? <Spinner /> : <Kbd>Esc</Kbd>}
        </div>
        <ul className="max-h-[50vh] overflow-y-auto py-1" role="listbox">
          {items.length === 0 ? <li className="px-4 py-6 text-center text-sm text-muted">{dq.length >= 2 ? "No matches" : "Type at least two characters"}</li> : null}
          {items.map((item, i) => (
            <li key={item.key} role="option" aria-selected={i === idx}>
              <button
                type="button"
                onMouseEnter={() => setIdx(i)}
                onClick={() => go(item)}
                className={cn("flex w-full items-center gap-2.5 px-4 py-2 text-left text-[13px]", i === idx ? "bg-surface-2 text-ink" : "text-ink-2")}
              >
                <span className="text-muted">
                  <Icon kind={item.icon} />
                </span>
                <span className="min-w-0 flex-1 truncate">{item.label}</span>
                {item.hint ? <span className="shrink-0 text-[11px] text-muted">{item.hint}</span> : null}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
