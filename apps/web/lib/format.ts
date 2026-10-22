import { format, formatDistanceToNowStrict, parseISO } from "date-fns";

export function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = parseISO(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function ago(iso: string | null | undefined, fallback = "—"): string {
  const d = parse(iso);
  if (!d) return fallback;
  return `${formatDistanceToNowStrict(d)} ago`;
}

export function until(iso: string | null | undefined): string {
  const d = parse(iso);
  if (!d) return "—";
  const future = d.getTime() > Date.now();
  return future ? `in ${formatDistanceToNowStrict(d)}` : `${formatDistanceToNowStrict(d)} ago`;
}

export function dateTime(iso: string | null | undefined, fmt = "d MMM yyyy, HH:mm"): string {
  const d = parse(iso);
  return d ? format(d, fmt) : "—";
}

export function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 1000) return `${value} ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(1)} s`;
  return `${Math.floor(value / 60_000)}m ${Math.round((value % 60_000) / 1000)}s`;
}

export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function num(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en").format(value);
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export const STATE_LABEL: Record<string, string> = {
  queued: "Queued",
  researching: "Researching",
  drafting: "Drafting",
  editing: "Editing",
  seo: "SEO",
  qa: "QA",
  in_review: "In review",
  approved: "Approved",
  scheduled: "Scheduled",
  publishing: "Publishing",
  published: "Published",
  archived: "Archived",
  needs_sources: "Needs more sources",
  failed: "Failed",
};

export const JOB_LABEL: Record<string, string> = {
  discover: "Discovery",
  research: "Research",
  write: "Write",
  edit: "Edit",
  seo: "SEO",
  qa: "QA",
  publish: "Publish",
  social: "LinkedIn draft",
  distribute: "LinkedIn post",
  crawl_inventory: "Site crawl",
  crawl_competitors: "Competitor crawl",
  eval: "Evaluation",
  maintenance: "Maintenance",
};

export function hostOf(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function pathOf(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return decodeURIComponent(new URL(url).pathname);
  } catch {
    return url;
  }
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}
