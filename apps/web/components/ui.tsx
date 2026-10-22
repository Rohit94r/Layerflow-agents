"use client";

import type { UseQueryResult } from "@tanstack/react-query";
import clsx, { type ClassValue } from "clsx";
import { AlertTriangle, Inbox, Loader2, Lock, RefreshCw, X } from "lucide-react";
import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { ApiError, errorMessage } from "@/lib/api";
import { STATE_LABEL } from "@/lib/format";

export const cn = (...v: ClassValue[]) => clsx(v);

/* ---------------- Button ---------------- */
type Variant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
type Size = "xs" | "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  /** When set, the button is disabled and the reason is shown as a tooltip (no cosmetic buttons). */
  disabledReason?: string | null | false;
  icon?: ReactNode;
}

const variants: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink hover:bg-accent-2 border border-accent",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-surface-2",
  ghost: "bg-transparent text-ink-2 border border-transparent hover:bg-surface-2 hover:text-ink",
  subtle: "bg-surface-2 text-ink border border-line hover:bg-surface-3",
  danger: "bg-bad text-white border border-bad hover:opacity-90",
};
const sizes: Record<Size, string> = {
  xs: "h-7 px-2 text-xs gap-1",
  sm: "h-8 px-2.5 text-[13px] gap-1.5",
  md: "h-9 px-3.5 text-sm gap-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "sm", loading, disabledReason, disabled, icon, className, children, title, type = "button", ...rest },
  ref,
) {
  const isDisabled = Boolean(disabled || loading || disabledReason);
  const btn = (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      title={disabledReason || title}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md font-medium whitespace-nowrap transition-colors select-none",
        "disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
  // Disabled buttons swallow hover events in some browsers; wrap so the reason tooltip still shows.
  return disabledReason ? (
    <span title={disabledReason} className="inline-flex">
      {btn}
    </span>
  ) : (
    btn
  );
});

/* ---------------- Layout primitives ---------------- */
export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("rounded-lg border border-line bg-surface", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, actions, className }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start justify-between gap-3 border-b border-line px-4 py-3", className)}>
      <div className="min-w-0">
        <h2 className="text-[13px] font-semibold tracking-wide text-ink uppercase">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-xs text-muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-line pb-4">
      <div className="min-w-0">
        <h1 className="font-display text-[28px] leading-tight font-semibold text-ink">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-ink-2">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/* ---------------- Badges ---------------- */
export type Tone = "neutral" | "accent" | "ok" | "warn" | "bad" | "info";
const tones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-2 border-line",
  accent: "bg-accent-soft text-accent border-transparent",
  ok: "bg-ok-soft text-ok border-transparent",
  warn: "bg-warn-soft text-warn border-transparent",
  bad: "bg-bad-soft text-bad border-transparent",
  info: "bg-info-soft text-info border-transparent",
};

export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] leading-none font-medium whitespace-nowrap", tones[tone], className)}>
      {children}
    </span>
  );
}

export function stateTone(state: string): Tone {
  if (["published"].includes(state)) return "ok";
  if (["approved", "scheduled", "publishing"].includes(state)) return "info";
  if (["in_review"].includes(state)) return "accent";
  if (["failed"].includes(state)) return "bad";
  if (["needs_sources"].includes(state)) return "warn";
  if (["archived"].includes(state)) return "neutral";
  return "neutral";
}

export function StateBadge({ state }: { state: string }) {
  return <Badge tone={stateTone(state)}>{STATE_LABEL[state] ?? state}</Badge>;
}

export function JobBadge({ status, attempts, max }: { status: string; attempts?: number; max?: number }) {
  const tone: Tone = status === "done" ? "ok" : status === "running" ? "info" : status === "queued" ? "neutral" : "bad";
  const label = status === "queued" && attempts && attempts > 0 ? `retrying ${attempts}/${max}` : status;
  return (
    <Badge tone={tone}>
      {status === "running" ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}
      {label}
    </Badge>
  );
}

export function StatusDot({ status, label }: { status: string | undefined; label?: string }) {
  const color = status === "ok" ? "bg-ok" : status === "degraded" || status === "stale" || status === "unknown" ? "bg-warn" : "bg-bad";
  return <span className={cn("inline-block size-2 shrink-0 rounded-full", color)} aria-label={label ?? status} role="img" />;
}

/* ---------------- Feedback states ---------------- */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden />;
}

export function SkeletonRows({ rows = 6, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2 p-4", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-7 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({ icon, title, body, action, className }: { icon?: ReactNode; title: string; body?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      <div className="mb-3 text-muted">{icon ?? <Inbox className="size-7" aria-hidden />}</div>
      <p className="font-display text-lg text-ink">{title}</p>
      {body ? <div className="mt-1 max-w-md text-sm text-ink-2">{body}</div> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function PermissionDenied({ message }: { message?: string }) {
  return (
    <EmptyState
      icon={<Lock className="size-7" aria-hidden />}
      title="You don't have access to this"
      body={message ?? "Your role cannot view or change this area. Ask an owner if you need access."}
    />
  );
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  if (error instanceof ApiError && error.status === 403) return <PermissionDenied message={error.message} />;
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-10 text-center", className)} role="alert">
      <AlertTriangle className="mb-3 size-7 text-bad" aria-hidden />
      <p className="font-display text-lg text-ink">Couldn&apos;t load this</p>
      <p className="mt-1 max-w-md text-sm text-ink-2">{errorMessage(error)}</p>
      {onRetry ? (
        <Button className="mt-4" icon={<RefreshCw className="size-3.5" />} onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

/** Renders loading skeleton / error with retry / empty state / content for a query. */
export function QueryView<T>({
  query,
  skeleton,
  empty,
  isEmpty,
  children,
}: {
  query: UseQueryResult<T>;
  skeleton?: ReactNode;
  empty?: ReactNode;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <>{skeleton ?? <SkeletonRows />}</>;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (isEmpty && isEmpty(query.data) && empty) return <>{empty}</>;
  return <>{children(query.data)}</>;
}

export function Banner({ tone = "info", title, children, action, className }: { tone?: Tone; title: ReactNode; children?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-start gap-3 rounded-md border px-3.5 py-2.5", tones[tone], className)} role={tone === "bad" ? "alert" : "status"}>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold">{title}</p>
        {children ? <div className="mt-0.5 text-xs opacity-90">{children}</div> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

/* ---------------- Forms ---------------- */
export function Field({ label, hint, error, children, className }: { label: ReactNode; hint?: ReactNode; error?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1 block text-xs font-medium text-ink-2">{label}</span>
      {children}
      {error ? <span className="mt-1 block text-xs text-bad">{error}</span> : hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

const control =
  "w-full rounded-md border border-line-strong bg-surface px-2.5 text-[13px] text-ink placeholder:text-muted focus:border-accent focus:outline-none disabled:opacity-60";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cn(control, "h-8", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cn(control, "py-2 leading-relaxed", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  return (
    <select ref={ref} className={cn(control, "h-8 pr-7", className)} {...rest}>
      {children}
    </select>
  );
});

export function Toggle({ checked, onChange, label, disabled, title }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean; title?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={title ?? label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors disabled:opacity-50",
        checked ? "border-accent bg-accent" : "border-line-strong bg-surface-3",
      )}
    >
      <span className={cn("inline-block size-3.5 rounded-full bg-surface shadow transition-transform", checked ? "translate-x-4" : "translate-x-0.5")} />
    </button>
  );
}

export function Checkbox({ checked, onChange, label, className }: { checked: boolean; onChange: (v: boolean) => void; label: string; className?: string }) {
  return <input type="checkbox" aria-label={label} checked={checked} onChange={(e) => onChange(e.target.checked)} className={cn("size-3.5 accent-[var(--accent)]", className)} />;
}

/* ---------------- Overlays ---------------- */
function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  const id = useId();
  const panel = useRef<HTMLDivElement>(null);
  useEscape(open, onClose);
  useEffect(() => {
    if (open) panel.current?.querySelector<HTMLElement>("input,textarea,select,button[data-autofocus]")?.focus();
  }, [open]);
  if (!open) return null;
  const width = { sm: "max-w-md", md: "max-w-xl", lg: "max-w-3xl", xl: "max-w-6xl" }[size];
  return (
    <div className="fixed inset-0 z-[80] flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-[8vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={panel} role="dialog" aria-modal="true" data-open="true" aria-labelledby={id} className={cn("w-full rounded-lg border border-line bg-surface shadow-2xl", width)}>
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
          <div>
            <h2 id={id} className="font-display text-lg font-semibold text-ink">
              {title}
            </h2>
            {description ? <p className="mt-0.5 text-xs text-ink-2">{description}</p> : null}
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-muted hover:bg-surface-2 hover:text-ink" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer ? <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3">{footer}</div> : null}
      </div>
    </div>
  );
}

export function Drawer({ open, onClose, title, children, footer, width = "w-[560px]" }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; width?: string }) {
  const id = useId();
  useEscape(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[70] flex justify-end bg-black/25" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside role="dialog" aria-modal="true" data-open="true" aria-labelledby={id} className={cn("flex h-full max-w-full flex-col border-l border-line bg-surface shadow-2xl", width)}>
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
          <h2 id={id} className="font-display text-lg leading-snug font-semibold text-ink">
            {title}
          </h2>
          <button type="button" onClick={onClose} className="rounded p-1 text-muted hover:bg-surface-2 hover:text-ink" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer ? <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3">{footer}</div> : null}
      </aside>
    </div>
  );
}

/* ---------------- Tabs ---------------- */
export function Tabs<T extends string>({ tabs, value, onChange, className }: { tabs: { value: T; label: ReactNode; count?: number }[]; value: T; onChange: (v: T) => void; className?: string }) {
  return (
    <div role="tablist" className={cn("flex flex-wrap gap-1 border-b border-line", className)}>
      {tabs.map((t) => (
        <button
          key={t.value}
          role="tab"
          type="button"
          aria-selected={value === t.value}
          onClick={() => onChange(t.value)}
          className={cn(
            "-mb-px border-b-2 px-3 py-2 text-[13px] font-medium transition-colors",
            value === t.value ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink",
          )}
        >
          {t.label}
          {t.count !== undefined ? <span className="ml-1.5 rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-ink-2 tabular">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

/* ---------------- Data display ---------------- */
export function Stat({ label, value, hint, tone, href }: { label: string; value: ReactNode; hint?: ReactNode; tone?: Tone; href?: string }) {
  const body = (
    <>
      <p className="text-[11px] font-semibold tracking-wider text-muted uppercase">{label}</p>
      <p className={cn("mt-1.5 font-display text-[30px] leading-none font-semibold tabular", tone === "bad" ? "text-bad" : tone === "ok" ? "text-ok" : "text-ink")}>{value}</p>
      {hint ? <p className="mt-1.5 text-xs text-ink-2">{hint}</p> : null}
    </>
  );
  return href ? (
    <a href={href} className="block rounded-lg border border-line bg-surface px-4 py-3.5 transition-colors hover:border-line-strong hover:bg-surface-2">
      {body}
    </a>
  ) : (
    <div className="rounded-lg border border-line bg-surface px-4 py-3.5">{body}</div>
  );
}

export function Meter({ value, min, max, label }: { value: number; min: number; max: number; label: string }) {
  const ok = value >= min && value <= max;
  const pctFill = Math.min(100, (value / (max * 1.15)) * 100);
  return (
    <div className="mt-1" aria-label={`${label}: ${value} characters (target ${min}–${max})`}>
      <div className="relative h-1.5 overflow-hidden rounded bg-surface-3">
        <div className="absolute inset-y-0 bg-ok/25" style={{ left: `${(min / (max * 1.15)) * 100}%`, width: `${((max - min) / (max * 1.15)) * 100}%` }} />
        <div className={cn("absolute inset-y-0 left-0", ok ? "bg-ok" : "bg-warn")} style={{ width: `${pctFill}%` }} />
      </div>
      <p className={cn("mt-1 text-[11px] tabular", ok ? "text-ok" : "text-warn")}>
        {value} chars · target {min}–{max}
      </p>
    </div>
  );
}

export function ScoreBar({ value, title }: { value: number; title?: string }) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <div className="flex items-center gap-2" title={title}>
      <div className="h-1.5 w-16 overflow-hidden rounded bg-surface-3">
        <div className="h-full bg-accent" style={{ width: `${v * 100}%` }} />
      </div>
      <span className="text-xs text-ink-2 tabular">{v.toFixed(2)}</span>
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-line-strong bg-surface-2 px-1 py-px font-mono text-[10px] text-ink-2">{children}</kbd>;
}

export function CategoryChip({ label, color }: { label: string; color?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap text-ink-2">
      <span className="inline-block size-2 rounded-sm" style={{ background: color ?? "var(--muted)" }} aria-hidden />
      {label}
    </span>
  );
}

export const th = "px-3 py-2 text-left text-[11px] font-semibold tracking-wider text-muted uppercase";
export const td = "px-3 py-2 align-top";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-4 animate-spin text-accent", className)} aria-label="Loading" />;
}
