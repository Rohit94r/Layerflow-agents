"use client";

import { useQuery } from "@tanstack/react-query";
import { Link2, Link2Off, PlugZap } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Badge, Button, Card, CardHeader, ErrorState, Field, Input, Select, Skeleton } from "@/components/ui";
import { get, post, put } from "@/lib/api";
import { ago } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import { useToast } from "@/lib/toast";
import type { IntegrationsView, PublishTarget } from "@/lib/types";

type Section = "ten_static" | "wordpress" | "webhook" | "linkedin";
const SECRETS: Record<Section, string[]> = {
  ten_static: ["sftp_password"],
  wordpress: ["app_password"],
  webhook: ["secret"],
  linkedin: ["client_secret", "access_token"],
};

function SecretField({ label, configured, value, onChange, onClear, disabled }: { label: string; configured: boolean; value: string; onChange: (v: string) => void; onClear: () => void; disabled: boolean }) {
  return (
    <Field label={label} hint={configured ? "Configured — stored encrypted. Leave blank to keep it." : "Not set"}>
      <div className="flex gap-2">
        <Input type="password" autoComplete="new-password" value={value} onChange={(e) => onChange(e.target.value)} placeholder={configured ? "•••••••• (unchanged)" : ""} disabled={disabled} />
        {configured ? (
          <Button size="sm" variant="ghost" onClick={onClear} disabledReason={disabled ? "Only owners can change secrets" : null}>
            Clear
          </Button>
        ) : null}
      </div>
    </Field>
  );
}

function TargetCard({ title, configured, children, onTest, testing, result, footer }: { title: string; configured: boolean; children?: ReactNode; onTest?: () => void; testing?: boolean; result?: { ok: boolean; detail: string } | null; footer?: ReactNode }) {
  return (
    <Card>
      <CardHeader
        title={title}
        actions={
          <>
            <Badge tone={configured ? "ok" : "neutral"}>{configured ? "configured" : "missing"}</Badge>
            {onTest ? (
              <Button size="xs" icon={<PlugZap className="size-3" />} loading={testing} onClick={onTest}>
                Test
              </Button>
            ) : null}
          </>
        }
      />
      <div className="space-y-3 p-4">
        {children}
        {result ? <p className={`rounded-md px-3 py-2 text-xs ${result.ok ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad"}`}>{result.detail}</p> : null}
        {footer}
      </div>
    </Card>
  );
}

export function IntegrationsSettings({ isOwner }: { isOwner: boolean }) {
  const toast = useToast();
  const q = useQuery({ queryKey: ["integrations"], queryFn: () => get<IntegrationsView>("/settings/integrations") });
  const [edits, setEdits] = useState<Record<Section, Record<string, string>>>({ ten_static: {}, wordpress: {}, webhook: {}, linkedin: {} });
  const [results, setResults] = useState<Record<string, { ok: boolean; detail: string }>>({});
  const set = (s: Section, k: string, v: string) => setEdits((e) => ({ ...e, [s]: { ...e[s], [k]: v } }));
  const save = useAction(
    (s: Section) => {
      // Plain fields are sent as typed (empty clears them); secrets are write-only: empty = unchanged, Clear = "".
      const body: Record<string, string> = {};
      for (const [k, v] of Object.entries(edits[s])) {
        if (k.endsWith("__clear")) body[k.replace("__clear", "")] = "";
        else if (SECRETS[s].includes(k)) {
          if (v !== "") body[k] = v;
        } else body[k] = v;
      }
      return put<IntegrationsView>("/settings/integrations", { [s]: body });
    },
    {
      success: "Integration saved",
      invalidate: [["integrations"], ["social"]],
      onSuccess: (_r, s) => setEdits((e) => ({ ...e, [s]: {} })),
    },
  );
  const setDefault = useAction((t: PublishTarget) => put<IntegrationsView>("/settings/integrations", { default_target: t }), { success: "Default target saved", invalidate: [["integrations"]] });
  const test = useAction((target: string) => post<{ ok: boolean; detail: string }>("/settings/integrations/test", { target }), {
    silent: true,
    onSuccess: (r, t) => setResults((m) => ({ ...m, [t]: r })),
    onError: (e, t) => setResults((m) => ({ ...m, [t]: { ok: false, detail: String(e) } })),
  });
  const connect = useAction(() => get<{ authorize_url: string }>("/settings/integrations/linkedin/connect"), {
    error: "Cannot start LinkedIn sign-in",
    onSuccess: (r) => {
      window.location.href = r.authorize_url;
    },
  });
  const disconnect = useAction(() => post<IntegrationsView>("/settings/integrations/linkedin/disconnect"), { success: "LinkedIn disconnected", invalidate: [["integrations"], ["social"]] });

  if (q.isPending) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const v = q.data;
  const t = v.targets;
  const val = (s: Section, k: string, current: string | number | null | undefined) => edits[s][k] ?? (current == null ? "" : String(current));
  const dirty = (s: Section) => Object.keys(edits[s]).length > 0;
  const disabled = !isOwner;
  const saveBtn = (s: Section) => (
    <Button variant="primary" size="sm" loading={save.isPending && save.variables === s} onClick={() => save.mutate(s)} disabledReason={!isOwner ? "Only owners can change integrations" : !dirty(s) ? "No changes" : null}>
      Save
    </Button>
  );
  const clear = (s: Section, k: string) => {
    set(s, `${k}__clear`, "1");
    toast.info("Secret will be cleared on save");
  };

  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-end gap-3 px-4 py-3">
        <Field label="Default publish target" className="w-80">
          <Select value={v.default_target} onChange={(e) => setDefault.mutate(e.target.value as PublishTarget)} disabled={disabled}>
            <option value="export">Export bundle (always available)</option>
            <option value="ten_static">TEN static site</option>
            <option value="wordpress" disabled={!t.wordpress.configured}>
              WordPress{t.wordpress.configured ? "" : " — not configured"}
            </option>
            <option value="webhook" disabled={!t.webhook.configured}>
              Webhook{t.webhook.configured ? "" : " — not configured"}
            </option>
          </Select>
        </Field>
        <p className="pb-2 text-xs text-muted">Every publish also writes an export bundle as a backup. Secrets are write-only: the dashboard only ever shows configured / missing.</p>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        <TargetCard title="Export bundle" configured onTest={() => test.mutate("export")} testing={test.isPending && test.variables === "export"} result={results.export}>
          <p className="text-xs text-ink-2">ZIP with index.html, article.md, meta.json, schema.json and a sitemap entry. Never blocks a demo.</p>
        </TargetCard>
        <TargetCard
          title={`TEN static site · ${t.ten_static.mode === "sftp" ? "SFTP" : "local staging"}`}
          configured={t.ten_static.configured}
          onTest={() => test.mutate("ten_static")}
          testing={test.isPending && test.variables === "ten_static"}
          result={results.ten_static}
          footer={saveBtn("ten_static")}
        >
          {t.ten_static.note ? <p className="text-xs text-ink-2">{t.ten_static.note}</p> : null}
          <fieldset disabled={disabled} className="grid gap-3 sm:grid-cols-2">
            <Field label="Site URL">
              <Input value={val("ten_static", "site_url", t.ten_static.site_url)} onChange={(e) => set("ten_static", "site_url", e.target.value)} />
            </Field>
            <Field label="Public root on server">
              <Input value={val("ten_static", "public_root", t.ten_static.public_root)} onChange={(e) => set("ten_static", "public_root", e.target.value)} />
            </Field>
            <Field label="SFTP host" hint="Empty = local staging mode">
              <Input value={val("ten_static", "sftp_host", t.ten_static.sftp_host)} onChange={(e) => set("ten_static", "sftp_host", e.target.value)} />
            </Field>
            <Field label="SFTP port">
              <Input type="number" value={val("ten_static", "sftp_port", t.ten_static.sftp_port)} onChange={(e) => set("ten_static", "sftp_port", e.target.value)} />
            </Field>
            <Field label="SFTP user">
              <Input value={val("ten_static", "sftp_user", t.ten_static.sftp_user)} onChange={(e) => set("ten_static", "sftp_user", e.target.value)} />
            </Field>
            <Field label="Private key path (inside the container)">
              <Input value={val("ten_static", "sftp_key_path", t.ten_static.sftp_key_path)} onChange={(e) => set("ten_static", "sftp_key_path", e.target.value)} />
            </Field>
          </fieldset>
          <SecretField label="SFTP password (if no key)" configured={t.ten_static.password_configured} value={edits.ten_static.sftp_password ?? ""} onChange={(x) => set("ten_static", "sftp_password", x)} onClear={() => clear("ten_static", "sftp_password")} disabled={disabled} />
        </TargetCard>
        <TargetCard title="WordPress REST" configured={t.wordpress.configured} onTest={() => test.mutate("wordpress")} testing={test.isPending && test.variables === "wordpress"} result={results.wordpress} footer={saveBtn("wordpress")}>
          <fieldset disabled={disabled} className="grid gap-3 sm:grid-cols-2">
            <Field label="Site URL">
              <Input value={val("wordpress", "url", t.wordpress.url)} onChange={(e) => set("wordpress", "url", e.target.value)} />
            </Field>
            <Field label="User">
              <Input value={val("wordpress", "user", t.wordpress.user)} onChange={(e) => set("wordpress", "user", e.target.value)} />
            </Field>
          </fieldset>
          <SecretField label="Application password" configured={t.wordpress.password_configured} value={edits.wordpress.app_password ?? ""} onChange={(x) => set("wordpress", "app_password", x)} onClear={() => clear("wordpress", "app_password")} disabled={disabled} />
        </TargetCard>
        <TargetCard title="Webhook" configured={t.webhook.configured} onTest={() => test.mutate("webhook")} testing={test.isPending && test.variables === "webhook"} result={results.webhook} footer={saveBtn("webhook")}>
          <Field label="Endpoint URL" hint="Receives HMAC-signed JSON (X-LayerFlow-Signature: sha256=…)">
            <Input value={val("webhook", "url", t.webhook.url)} onChange={(e) => set("webhook", "url", e.target.value)} disabled={disabled} />
          </Field>
          <SecretField label="Shared secret" configured={t.webhook.secret_configured} value={edits.webhook.secret ?? ""} onChange={(x) => set("webhook", "secret", x)} onClear={() => clear("webhook", "secret")} disabled={disabled} />
        </TargetCard>
        <TargetCard
          title="LinkedIn (official API)"
          configured={v.linkedin.client_id_set && v.linkedin.client_secret_set}
          onTest={() => test.mutate("linkedin")}
          testing={test.isPending && test.variables === "linkedin"}
          result={results.linkedin}
          footer={
            <div className="flex flex-wrap gap-2">
              {saveBtn("linkedin")}
              {v.linkedin.connected ? (
                <Button size="sm" icon={<Link2Off className="size-3.5" />} loading={disconnect.isPending} onClick={() => disconnect.mutate(undefined)} disabledReason={disabled ? "Only owners can disconnect" : null}>
                  Disconnect
                </Button>
              ) : (
                <Button size="sm" icon={<Link2 className="size-3.5" />} loading={connect.isPending} onClick={() => connect.mutate(undefined)} disabledReason={disabled ? "Only owners can connect" : !v.linkedin.client_id_set || !v.linkedin.client_secret_set ? "Save the app client ID and secret first" : null}>
                  Connect LinkedIn
                </Button>
              )}
            </div>
          }
        >
          <div className="text-xs">
            {v.linkedin.connected ? (
              <p className="text-ok">
                Connected as {v.linkedin.author_urn ?? "unknown author"}
                {v.linkedin.expires_at ? ` · token expires ${ago(v.linkedin.expires_at)}` : ""}
              </p>
            ) : (
              <p className="text-ink-2">Not connected. Posts stay “draft ready” and use the copy + open flow. Company-page posting needs w_organization_social approval from LinkedIn.</p>
            )}
            {v.linkedin.last_refresh_error ? <p className="mt-1 text-bad">Last refresh error: {v.linkedin.last_refresh_error}</p> : null}
          </div>
          <fieldset disabled={disabled} className="grid gap-3 sm:grid-cols-2">
            <Field label="Client ID">
              <Input value={val("linkedin", "client_id", v.linkedin.client_id)} onChange={(e) => set("linkedin", "client_id", e.target.value)} />
            </Field>
            <Field label="Post as">
              <Select value={val("linkedin", "author_type", v.linkedin.author_type)} onChange={(e) => set("linkedin", "author_type", e.target.value)}>
                <option value="organization">Organization page</option>
                <option value="member">Member (person)</option>
              </Select>
            </Field>
            <Field label="Organization URN" hint="urn:li:organization:123…">
              <Input value={val("linkedin", "org_urn", v.linkedin.org_urn)} onChange={(e) => set("linkedin", "org_urn", e.target.value)} />
            </Field>
            <Field label="Redirect URI" hint="Register this in the LinkedIn app">
              <Input value={val("linkedin", "redirect_uri", v.linkedin.redirect_uri)} onChange={(e) => set("linkedin", "redirect_uri", e.target.value)} />
            </Field>
          </fieldset>
          <SecretField label="Client secret" configured={v.linkedin.client_secret_set} value={edits.linkedin.client_secret ?? ""} onChange={(x) => set("linkedin", "client_secret", x)} onClear={() => clear("linkedin", "client_secret")} disabled={disabled} />
          <SecretField label="Access token (manual paste, optional)" configured={v.linkedin.connected} value={edits.linkedin.access_token ?? ""} onChange={(x) => set("linkedin", "access_token", x)} onClear={() => clear("linkedin", "access_token")} disabled={disabled} />
        </TargetCard>
      </div>
    </div>
  );
}
