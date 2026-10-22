// Small LCS diff (word or line granularity) for version comparison. Bounded to keep the UI responsive.

export type DiffPart = { type: "same" | "add" | "del"; text: string };

function lcsDiff(a: string[], b: string[]): DiffPart[] {
  const n = a.length;
  const m = b.length;
  if (n * m > 4_000_000) {
    // Too large for a full table: fall back to a coarse prefix/suffix diff.
    let start = 0;
    while (start < n && start < m && a[start] === b[start]) start++;
    let endA = n - 1;
    let endB = m - 1;
    while (endA >= start && endB >= start && a[endA] === b[endB]) {
      endA--;
      endB--;
    }
    return [
      { type: "same", text: a.slice(0, start).join("") },
      { type: "del", text: a.slice(start, endA + 1).join("") },
      { type: "add", text: b.slice(start, endB + 1).join("") },
      { type: "same", text: a.slice(endA + 1).join("") },
    ].filter((p) => p.text) as DiffPart[];
  }
  const dp: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffPart[] = [];
  const push = (type: DiffPart["type"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.type === type) last.text += text;
    else out.push({ type, text });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      push("same", a[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push("del", a[i++]);
    } else {
      push("add", b[j++]);
    }
  }
  while (i < n) push("del", a[i++]);
  while (j < m) push("add", b[j++]);
  return out;
}

export function wordDiff(before: string, after: string): DiffPart[] {
  const tok = (s: string) => s.match(/\s+|[^\s]+/g) ?? [];
  return lcsDiff(tok(before), tok(after));
}

export function lineDiff(before: string, after: string): DiffPart[] {
  const tok = (s: string) => s.split(/(?<=\n)/);
  return lcsDiff(tok(before), tok(after));
}

export function diffStats(parts: DiffPart[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const p of parts) {
    const words = p.text.trim() ? p.text.trim().split(/\s+/).length : 0;
    if (p.type === "add") added += words;
    if (p.type === "del") removed += words;
  }
  return { added, removed };
}
