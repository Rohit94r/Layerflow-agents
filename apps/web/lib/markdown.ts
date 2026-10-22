import type { ArticleBody, Playbook, Section } from "./types";

/** Article body → Markdown (headings per section, bullets, > pull quotes). Hidden-heading sections (lede) have no heading. */
export function toMarkdown(article: ArticleBody, playbook?: Playbook): string {
  const hidden = new Set((playbook?.sections ?? []).filter((s) => !s.show_heading).map((s) => s.key));
  const lines: string[] = [];
  for (const s of article.sections) {
    if (!hidden.has(s.key)) lines.push(`## ${s.heading}`, "");
    for (const p of s.paragraphs) lines.push(p, "");
    if (s.bullets?.length) {
      for (const b of s.bullets) lines.push(`- ${b}`);
      lines.push("");
    }
    if (s.pull_quote) lines.push(`> ${s.pull_quote}`, "");
  }
  return lines.join("\n").trim() + "\n";
}

/**
 * Markdown → sections. Blocks map onto the existing sections in order: text before the first heading belongs to
 * the first hidden-heading section (the lede) if there is one; every `## ` heading starts the next section.
 * Extra headings beyond the playbook are kept as additional sections with key `extra_n`.
 */
export function fromMarkdown(md: string, existing: Section[], playbook?: Playbook): Section[] {
  const hiddenKeys = (playbook?.sections ?? []).filter((s) => !s.show_heading).map((s) => s.key);
  const order = existing.map((s) => s.key);
  const blocks: { heading: string | null; body: string[] }[] = [];
  let cur: { heading: string | null; body: string[] } = { heading: null, body: [] };
  for (const line of md.replace(/\r\n/g, "\n").split("\n")) {
    const h = line.match(/^#{1,3}\s+(.*)$/);
    if (h) {
      if (cur.heading !== null || cur.body.some((l) => l.trim())) blocks.push(cur);
      cur = { heading: h[1].trim(), body: [] };
    } else {
      cur.body.push(line);
    }
  }
  if (cur.heading !== null || cur.body.some((l) => l.trim())) blocks.push(cur);

  const result: Section[] = [];
  const firstHidden = order[0] !== undefined && hiddenKeys.includes(order[0]);
  let keyIdx = 0;
  let extra = 0;
  for (const [bi, b] of blocks.entries()) {
    let key: string;
    if (b.heading === null) {
      if (bi === 0 && firstHidden) {
        key = order[0];
        keyIdx = 1;
      } else if (result.length) {
        result[result.length - 1].paragraphs.push(...parseBody(b.body).paragraphs);
        continue;
      } else {
        key = order[keyIdx++] ?? `extra_${++extra}`;
      }
    } else {
      if (bi === 0 && firstHidden) keyIdx = 1; // lede text was removed
      key = order[keyIdx++] ?? `extra_${++extra}`;
    }
    const prev = existing.find((s) => s.key === key);
    const body = parseBody(b.body);
    result.push({
      key,
      heading: b.heading ?? prev?.heading ?? key,
      paragraphs: body.paragraphs,
      bullets: body.bullets,
      pull_quote: body.quote,
      facts_used: prev?.facts_used ?? [],
    });
  }
  return result;
}

function parseBody(lines: string[]): { paragraphs: string[]; bullets: string[]; quote: string | null } {
  const paragraphs: string[] = [];
  const bullets: string[] = [];
  let quote: string | null = null;
  let buf: string[] = [];
  const flush = () => {
    const t = buf.join(" ").replace(/\s+/g, " ").trim();
    if (t) paragraphs.push(t);
    buf = [];
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flush();
    } else if (/^\s*[-*•]\s+/.test(line)) {
      flush();
      bullets.push(line.replace(/^\s*[-*•]\s+/, "").trim());
    } else if (/^\s*>\s?/.test(line)) {
      flush();
      quote = (quote ? `${quote} ` : "") + line.replace(/^\s*>\s?/, "").trim();
    } else {
      buf.push(line.trim());
    }
  }
  flush();
  return { paragraphs, bullets, quote };
}

export function articleText(a: ArticleBody | undefined | null): string {
  if (!a) return "";
  const parts = [a.title, a.dek];
  for (const s of a.sections ?? []) {
    parts.push(s.heading, ...(s.paragraphs ?? []), ...(s.bullets ?? []).map((b) => `• ${b}`));
    if (s.pull_quote) parts.push(`“${s.pull_quote}”`);
  }
  parts.push(a.takeaway);
  return parts.filter(Boolean).join("\n\n");
}

export function wordCount(text: string): number {
  return (text.match(/[A-Za-z0-9À-ɏ][A-Za-z0-9À-ɏ'’-]*/g) ?? []).length;
}
