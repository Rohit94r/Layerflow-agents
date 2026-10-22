// Tenant-timezone helpers using Intl only (no extra dependency). DST-safe via the IANA database in the browser.

function parts(date: Date, timeZone: string): Record<string, number> {
  const fmt = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const out: Record<string, number> = {};
  for (const p of fmt.formatToParts(date)) {
    if (p.type !== "literal") out[p.type] = Number(p.value);
  }
  return out;
}

/** Offset (ms) of `timeZone` from UTC at instant `date`. */
export function tzOffset(date: Date, timeZone: string): number {
  const p = parts(date, timeZone);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return asUtc - Math.floor(date.getTime() / 1000) * 1000;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** ISO instant → "YYYY-MM-DDTHH:mm" wall time in the tenant zone (for <input type=datetime-local>). */
export function toLocalInput(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return "";
  const p = parts(new Date(iso), timeZone);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`;
}

/** Wall time in the tenant zone → ISO instant (UTC). */
export function fromLocalInput(value: string, timeZone: string): string {
  const [d, t = "00:00"] = value.split("T");
  const [y, m, day] = d.split("-").map(Number);
  const [hh, mm] = t.split(":").map(Number);
  const guess = Date.UTC(y, m - 1, day, hh, mm);
  let ts = guess - tzOffset(new Date(guess), timeZone);
  ts = guess - tzOffset(new Date(ts), timeZone); // second pass handles DST edges
  return new Date(ts).toISOString();
}

/** Calendar date key (YYYY-MM-DD) of an instant in the tenant zone. */
export function dayKey(iso: string | Date, timeZone: string): string {
  const p = parts(typeof iso === "string" ? new Date(iso) : iso, timeZone);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
}

export function hourIn(iso: string, timeZone: string): number {
  return parts(new Date(iso), timeZone).hour;
}

export function timeIn(iso: string, timeZone: string): string {
  const p = parts(new Date(iso), timeZone);
  return `${pad(p.hour)}:${pad(p.minute)}`;
}

export function formatIn(iso: string | null | undefined, timeZone: string, opts?: Intl.DateTimeFormatOptions): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    ...opts,
  }).format(new Date(iso));
}

/** Move an instant to another calendar day (and optionally hour) keeping the tenant-zone wall time. */
export function moveTo(iso: string, dateKey: string, timeZone: string, hour?: number): string {
  const wall = toLocalInput(iso, timeZone);
  const time = hour === undefined ? wall.split("T")[1] : `${pad(hour)}:${wall.split("T")[1].split(":")[1]}`;
  return fromLocalInput(`${dateKey}T${time}`, timeZone);
}
