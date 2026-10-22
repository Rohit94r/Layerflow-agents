"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  CalendarDays,
  ClipboardCheck,
  LayoutDashboard,
  LogOut,
  Moon,
  Newspaper,
  PenLine,
  Search,
  Settings,
  Share2,
  Sun,
  TrendingUp,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { post } from "@/lib/api";
import { ago, titleCase } from "@/lib/format";
import { useHealth } from "@/lib/hooks";
import type { Me } from "@/lib/types";
import { CommandPalette } from "./command-palette";
import { Kbd, StatusDot, cn } from "./ui";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/news", label: "News Feed", icon: Newspaper },
  { href: "/studio", label: "Content Studio", icon: PenLine },
  { href: "/review", label: "Review Queue", icon: ClipboardCheck },
  { href: "/seo", label: "SEO Workspace", icon: TrendingUp },
  { href: "/calendar", label: "Calendar", icon: CalendarDays },
  { href: "/social", label: "Social", icon: Share2 },
  { href: "/settings", label: "Settings", icon: Settings },
];

function useTheme(): [boolean, () => void] {
  const [dark, setDark] = useState(false);
  useEffect(() => setDark(document.documentElement.classList.contains("dark")), []);
  const toggle = () => {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("lf-theme", next ? "dark" : "light");
    } catch {
      /* storage unavailable */
    }
    setDark(next);
  };
  return [dark, toggle];
}

function HealthPills({ provider }: { provider: string }) {
  const { data, isError } = useHealth();
  const model = data?.checks.model;
  const worker = data?.checks.worker;
  const modelStatus = isError ? "down" : model?.status;
  const modelTitle = isError
    ? "Health endpoint unreachable"
    : model
      ? `${model.provider} ${model.base_url ?? ""} — ${model.status}${model.detail ? `: ${model.detail}` : ""}`
      : "Checking model…";
  return (
    <div className="flex items-center gap-2">
      {provider === "mock" || model?.is_mock ? (
        <span className="rounded border border-warn/40 bg-warn-soft px-2 py-0.5 text-[11px] font-semibold text-warn" title="MODEL_PROVIDER=mock: deterministic extractive output, not a language model">
          Mock provider
        </span>
      ) : null}
      <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-[11px] text-ink-2" title={modelTitle}>
        <StatusDot status={modelStatus} />
        Model {model ? (model.status === "ok" ? "ready" : model.status) : "…"}
      </span>
      <span
        className="hidden items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-[11px] text-ink-2 md:inline-flex"
        title={worker?.detail ?? (worker?.last_seen ? `Last heartbeat ${ago(worker.last_seen)}` : "No worker heartbeat")}
      >
        <StatusDot status={isError ? "down" : worker?.status} />
        Worker {worker ? (worker.status === "ok" ? `${worker.workers} live` : worker.status) : "…"}
      </span>
    </div>
  );
}

function UserMenu({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const qc = useQueryClient();
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  const logout = async () => {
    try {
      await post("/auth/logout");
    } finally {
      qc.clear();
      window.location.href = "/login";
    }
  };
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-2 rounded-md px-2 py-1 text-[13px] text-ink hover:bg-surface-2"
      >
        <span className="flex size-7 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent">{(me.user.name || me.user.email)[0]?.toUpperCase()}</span>
        <span className="hidden text-left lg:block">
          <span className="block leading-tight">{me.user.name}</span>
          <span className="block text-[11px] leading-tight text-muted">{titleCase(me.user.role)}</span>
        </span>
      </button>
      {open ? (
        <div role="menu" className="absolute right-0 z-50 mt-1 w-56 rounded-md border border-line bg-surface py-1 shadow-lg">
          <p className="truncate px-3 py-2 text-xs text-muted">{me.user.email}</p>
          <Link role="menuitem" href="/settings" className="block px-3 py-1.5 text-[13px] text-ink hover:bg-surface-2" onClick={() => setOpen(false)}>
            Settings
          </Link>
          <button role="menuitem" type="button" onClick={logout} className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] text-ink hover:bg-surface-2">
            <LogOut className="size-3.5" /> Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function AppShell({ me, children }: { me: Me; children: ReactNode }) {
  const pathname = usePathname();
  const [dark, toggleTheme] = useTheme();
  const [paletteOpen, setPaletteOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`));
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-[220px] shrink-0 flex-col border-r border-line bg-surface md:flex">
        <div className="border-b border-line px-4 py-4">
          <p className="font-display text-[17px] leading-tight font-semibold text-ink">{me.tenant.name}</p>
          <p className="mt-0.5 text-[11px] tracking-wider text-muted uppercase">Powered by LayerFlow</p>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-3" aria-label="Main">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(href) ? "page" : undefined}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] transition-colors",
                isActive(href) ? "bg-accent-soft font-medium text-accent" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          ))}
        </nav>
        <div className="border-t border-line px-4 py-3 text-[11px] text-muted">
          {me.tenant.timezone} · {me.tenant.slug}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-line bg-bg/95 px-4 backdrop-blur-[2px] lg:px-6">
          <nav className="flex gap-1 overflow-x-auto md:hidden" aria-label="Main (compact)">
            {NAV.map(({ href, icon: Icon, label }) => (
              <Link key={href} href={href} title={label} className={cn("rounded p-1.5", isActive(href) ? "text-accent" : "text-muted")}>
                <Icon className="size-4" />
              </Link>
            ))}
          </nav>
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="flex h-8 w-full max-w-sm items-center gap-2 rounded-md border border-line bg-surface px-2.5 text-[13px] text-muted hover:border-line-strong"
            aria-label="Search (Ctrl+K)"
          >
            <Search className="size-3.5" />
            <span className="flex-1 text-left">Search articles, stories, sources…</span>
            <Kbd>⌘K</Kbd>
          </button>
          <div className="ml-auto flex items-center gap-2">
            <HealthPills provider={me.provider} />
            <button type="button" onClick={toggleTheme} className="rounded-md p-2 text-ink-2 hover:bg-surface-2" aria-label={dark ? "Switch to light theme" : "Switch to dark theme"} title="Toggle theme">
              {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </button>
            <UserMenu me={me} />
          </div>
        </header>
        <main className="min-w-0 flex-1 px-4 py-6 lg:px-8">{children}</main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
