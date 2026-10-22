"use client";

import { useQuery } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, CardHeader, Dialog, ErrorState, Field, Input, Select, Skeleton, Textarea, Toggle, td, th } from "@/components/ui";
import { get, patch, post } from "@/lib/api";
import { ago, titleCase } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import type { Me, Role, TenantInfo, TenantSettings, UserRow } from "@/lib/types";

const TIMEZONES = ["Asia/Kolkata", "UTC", "Europe/London", "Europe/Berlin", "America/New_York", "America/Los_Angeles", "Asia/Dubai", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney"];
const WEIGHTS = ["recency", "entity", "signal", "source", "novelty"] as const;

function list(s: string): string[] {
  return s
    .split(/[,\n]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function AddUser({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("editor");
  const [password, setPassword] = useState("");
  const create = useAction(() => post("/settings/users", { email, name: name || undefined, role, password }), { success: "User added", invalidate: [["users"]], onSuccess: onClose });
  return (
    <Dialog
      open
      onClose={onClose}
      title="Add user"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={create.isPending} onClick={() => create.mutate(undefined)} disabledReason={!email.includes("@") ? "Enter an email" : password.length < 10 ? "Password needs 10+ characters" : null}>
            Add user
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Email">
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Role" hint="Owner: everything · Editor: content · Reviewer: approve, schedule">
          <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="owner">Owner</option>
            <option value="editor">Editor</option>
            <option value="reviewer">Reviewer</option>
          </Select>
        </Field>
        <Field label="Initial password" hint="At least 10 characters. Share it securely; they can change it later.">
          <Input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}

export function GeneralSettings({ me, isOwner }: { me: Me; isOwner: boolean }) {
  const q = useQuery({ queryKey: ["tenant"], queryFn: () => get<{ tenant: TenantInfo; settings: TenantSettings }>("/settings/tenant") });
  const users = useQuery({ queryKey: ["users"], queryFn: () => get<{ items: UserRow[] }>("/settings/users") });
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [tz, setTz] = useState("");
  const [s, setS] = useState<TenantSettings | null>(null);
  const [companies, setCompanies] = useState("");
  const [sectors, setSectors] = useState("");
  const [avoid, setAvoid] = useState("");
  const [slots, setSlots] = useState("");
  const [adding, setAdding] = useState(false);
  useEffect(() => {
    if (!q.data) return;
    setName(q.data.tenant.name);
    setDomain(q.data.tenant.domain ?? "");
    setTz(q.data.tenant.timezone);
    setS(q.data.settings);
    setCompanies(q.data.settings.watchlist.companies.join(", "));
    setSectors(q.data.settings.watchlist.sectors.join(", "));
    setAvoid((q.data.settings.avoid?.topics ?? []).join(", "));
    setSlots(q.data.settings.cadence.slots.join(", "));
  }, [q.data]);

  const save = useAction(
    () =>
      patch("/settings/tenant", {
        name,
        domain,
        timezone: tz,
        settings: {
          brand: s?.brand,
          spelling: s?.spelling,
          cadence: { ...s?.cadence, slots: list(slots) },
          scoring: s?.scoring,
          watchlist: { ...s?.watchlist, companies: list(companies), sectors: list(sectors) },
          avoid: { ...s?.avoid, topics: list(avoid) },
          discovery: s?.discovery,
          research: s?.research,
          quality: s?.quality,
          social: s?.social,
        },
      }),
    { success: "Settings saved", invalidate: [["tenant"], ["me"]] },
  );
  const updateUser = useAction(({ id, body }: { id: string; body: Record<string, unknown> }) => patch(`/settings/users/${id}`, body), { success: "User updated", invalidate: [["users"]] });

  if (q.isPending || !s) return <Skeleton className="h-[600px]" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const set = <K extends keyof TenantSettings>(k: K, v: TenantSettings[K]) => setS({ ...s, [k]: v });
  const total = WEIGHTS.reduce((a, k) => a + (s.scoring[k] ?? 0), 0) || 1;
  const disabled = !isOwner;

  return (
    <div className="space-y-4">
      <fieldset disabled={disabled} className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Publication" />
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            <Field label="Tenant name">
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Domain">
              <Input value={domain} onChange={(e) => setDomain(e.target.value)} />
            </Field>
            <Field label="Timezone" hint="Scheduling and calendar use this zone (DST-safe).">
              <Input list="tz-list" value={tz} onChange={(e) => setTz(e.target.value)} />
              <datalist id="tz-list">
                {TIMEZONES.map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
            </Field>
            <Field label="Spelling">
              <Select value={s.spelling} onChange={(e) => set("spelling", e.target.value as TenantSettings["spelling"])}>
                <option value="en-US">US English</option>
                <option value="en-GB">British English</option>
              </Select>
            </Field>
            <Field label="Site URL" className="sm:col-span-2">
              <Input value={s.brand.site_url ?? ""} onChange={(e) => set("brand", { ...s.brand, site_url: e.target.value })} />
            </Field>
            <Field label="Byline / author">
              <Input value={s.brand.author_name ?? ""} onChange={(e) => set("brand", { ...s.brand, author_name: e.target.value })} />
            </Field>
            <Field label="Default OG image URL">
              <Input value={s.brand.og_image_url ?? ""} onChange={(e) => set("brand", { ...s.brand, og_image_url: e.target.value })} />
            </Field>
          </div>
        </Card>
        <Card>
          <CardHeader title="Cadence" subtitle="Used for the default schedule slot and conflict warnings" />
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            <Field label="Publications per day">
              <Input type="number" min={1} max={20} value={s.cadence.per_day} onChange={(e) => set("cadence", { ...s.cadence, per_day: Number(e.target.value) })} />
            </Field>
            <Field label="Max per category per day">
              <Input type="number" min={1} max={10} value={s.cadence.max_per_category_per_day} onChange={(e) => set("cadence", { ...s.cadence, max_per_category_per_day: Number(e.target.value) })} />
            </Field>
            <Field label="Slots (HH:MM, comma separated)">
              <Input value={slots} onChange={(e) => setSlots(e.target.value)} />
            </Field>
            <div className="flex items-center justify-between rounded-md border border-line px-3 py-2">
              <span className="text-[13px] text-ink">Weekdays only</span>
              <Toggle checked={s.cadence.weekdays_only} onChange={(v) => set("cadence", { ...s.cadence, weekdays_only: v })} label="Weekdays only" disabled={disabled} />
            </div>
          </div>
        </Card>
        <Card>
          <CardHeader title="Discovery scoring" subtitle="score = Σ weight × component · weights are normalised on save" />
          <div className="space-y-3 p-4">
            {WEIGHTS.map((k) => (
              <label key={k} className="flex items-center gap-3 text-[13px]">
                <span className="w-20 text-ink-2">{titleCase(k)}</span>
                <input type="range" min={0} max={1} step={0.05} value={s.scoring[k]} onChange={(e) => set("scoring", { ...s.scoring, [k]: Number(e.target.value) })} className="flex-1 accent-[var(--accent)]" aria-label={`${k} weight`} />
                <span className="w-12 text-right text-ink tabular">{((s.scoring[k] / total) * 100).toFixed(0)}%</span>
              </label>
            ))}
          </div>
        </Card>
        <Card>
          <CardHeader title="Watchlist & filters" />
          <div className="space-y-3 p-4">
            <Field label="Companies (comma separated)" hint="Watchlist matches lift the entity score.">
              <Textarea rows={3} value={companies} onChange={(e) => setCompanies(e.target.value)} />
            </Field>
            <Field label="Sectors">
              <Textarea rows={2} value={sectors} onChange={(e) => setSectors(e.target.value)} />
            </Field>
            <Field label="Topics to avoid">
              <Input value={avoid} onChange={(e) => setAvoid(e.target.value)} />
            </Field>
          </div>
        </Card>
        <Card>
          <CardHeader title="Discovery & research" />
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            <Field label="Lookback (hours)">
              <Input type="number" min={1} max={168} value={s.discovery.lookback_hours} onChange={(e) => set("discovery", { ...s.discovery, lookback_hours: Number(e.target.value) })} />
            </Field>
            <Field label="Auto-refresh every (minutes, 0 = off)">
              <Input type="number" min={0} max={1440} value={s.discovery.interval_minutes ?? 30} onChange={(e) => set("discovery", { ...s.discovery, interval_minutes: Number(e.target.value) })} />
            </Field>
            <Field label="Max items per run">
              <Input type="number" min={10} max={1000} value={s.discovery.max_items} onChange={(e) => set("discovery", { ...s.discovery, max_items: Number(e.target.value) })} />
            </Field>
            <Field label="Classify top N with the fast model">
              <Input type="number" min={0} max={50} value={s.discovery.enrich_top_k} onChange={(e) => set("discovery", { ...s.discovery, enrich_top_k: Number(e.target.value) })} />
            </Field>
            <Field label="Auto-disable a source after N failures">
              <Input type="number" min={1} max={50} value={s.discovery.auto_disable_after_failures} onChange={(e) => set("discovery", { ...s.discovery, auto_disable_after_failures: Number(e.target.value) })} />
            </Field>
            <div className="flex items-center justify-between rounded-md border border-line px-3 py-2">
              <span className="text-[13px] text-ink">LLM enrichment</span>
              <Toggle checked={s.discovery.llm_enrich} onChange={(v) => set("discovery", { ...s.discovery, llm_enrich: v })} label="LLM enrichment" disabled={disabled} />
            </div>
            <Field label="Research: max fetches">
              <Input type="number" min={1} max={12} value={s.research.max_fetches} onChange={(e) => set("research", { ...s.research, max_fetches: Number(e.target.value) })} />
            </Field>
            <Field label="Research: minimum sources" hint="Below this the agent refuses (Needs more sources).">
              <Input type="number" min={1} max={6} value={s.research.min_sources} onChange={(e) => set("research", { ...s.research, min_sources: Number(e.target.value) })} />
            </Field>
            <Field label="QA: max revision loops">
              <Input type="number" min={0} max={5} value={s.quality.max_revisions ?? 2} onChange={(e) => set("quality", { ...s.quality, max_revisions: Number(e.target.value) })} />
            </Field>
            <div className="flex items-center justify-between rounded-md border border-line px-3 py-2">
              <span className="text-[13px] text-ink">Emoji in LinkedIn posts</span>
              <Toggle checked={s.social.emoji} onChange={(v) => set("social", { ...s.social, emoji: v })} label="Emoji in LinkedIn posts" disabled={disabled} />
            </div>
          </div>
        </Card>
      </fieldset>
      <div className="flex items-center gap-3">
        <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)} disabledReason={!isOwner ? "Only owners can change settings" : null}>
          Save settings
        </Button>
        {!isOwner ? <span className="text-xs text-muted">Read-only for your role.</span> : null}
      </div>

      <Card>
        <CardHeader title="Users" actions={<Button size="xs" icon={<UserPlus className="size-3" />} onClick={() => setAdding(true)} disabledReason={!isOwner ? "Only owners can add users" : null}>Add user</Button>} />
        {users.isPending ? (
          <Skeleton className="m-4 h-20" />
        ) : users.isError ? (
          <ErrorState error={users.error} onRetry={() => users.refetch()} />
        ) : (
          <table className="w-full text-[13px]">
            <thead className="border-b border-line">
              <tr>
                <th className={th}>User</th>
                <th className={th}>Role</th>
                <th className={th}>Status</th>
                <th className={th}>Last sign-in</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {users.data.items.map((u) => (
                <tr key={u.id}>
                  <td className={td}>
                    <p className="font-medium text-ink">{u.name}</p>
                    <p className="text-xs text-muted">{u.email}</p>
                  </td>
                  <td className={td}>
                    <Select
                      aria-label={`Role for ${u.email}`}
                      value={u.role}
                      disabled={!isOwner || u.id === me.user.id}
                      onChange={(e) => updateUser.mutate({ id: u.id, body: { role: e.target.value } })}
                      className="w-32"
                    >
                      <option value="owner">Owner</option>
                      <option value="editor">Editor</option>
                      <option value="reviewer">Reviewer</option>
                    </Select>
                  </td>
                  <td className={td}>
                    <span className="flex items-center gap-2">
                      <Badge tone={u.active ? "ok" : "neutral"}>{u.active ? "active" : "disabled"}</Badge>
                      <Toggle checked={u.active} onChange={(v) => updateUser.mutate({ id: u.id, body: { active: v } })} label={`Active: ${u.email}`} disabled={!isOwner || u.id === me.user.id} />
                    </span>
                  </td>
                  <td className={`${td} text-xs text-ink-2`}>{ago(u.last_login_at, "never")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {adding ? <AddUser onClose={() => setAdding(false)} /> : null}
    </div>
  );
}
