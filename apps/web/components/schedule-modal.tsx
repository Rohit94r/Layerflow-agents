"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, FileSearch, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { useAction, useMe } from "@/lib/hooks";
import { fromLocalInput, toLocalInput } from "@/lib/tz";
import type { Category, DryRun, IntegrationsView, Publication, PublishTarget } from "@/lib/types";
import { Badge, Button, Dialog, Field, Input, Select, Skeleton } from "./ui";

const TARGET_LABEL: Record<PublishTarget, string> = {
  export: "Export bundle (ZIP, always available)",
  ten_static: "TEN static site (SFTP or local staging)",
  wordpress: "WordPress REST",
  webhook: "Webhook",
};

export function ScheduleModal({ articleId, category, title, onClose, onScheduled }: { articleId: string; category: Category; title: string; onClose: () => void; onScheduled?: (p: Publication) => void }) {
  const me = useMe();
  const tz = me.data?.tenant.timezone ?? "UTC";
  const slot = useQuery({
    queryKey: ["nextSlot", category],
    queryFn: () => get<{ scheduled_at: string; reason: string; timezone: string; default_target: PublishTarget }>("/publications/next-slot", { category }),
  });
  const integrations = useQuery({ queryKey: ["integrations"], queryFn: () => get<IntegrationsView>("/settings/integrations") });
  const [when, setWhen] = useState("");
  const [target, setTarget] = useState<PublishTarget | "">("");
  const [dry, setDry] = useState<DryRun | null>(null);
  const [showHtml, setShowHtml] = useState(false);

  useEffect(() => {
    if (slot.data && !when) setWhen(toLocalInput(slot.data.scheduled_at, slot.data.timezone));
    if (slot.data && !target) setTarget(slot.data.default_target);
  }, [slot.data, when, target]);

  const dryRun = useAction(() => post<DryRun>("/publications/dry-run", { article_id: articleId, target: target || undefined }), {
    silent: false,
    error: "Dry run failed",
    onSuccess: (r) => setDry(r),
  });
  const schedule = useAction(
    () => post<Publication>("/publications", { article_id: articleId, target: target || undefined, scheduled_at: when ? fromLocalInput(when, slot.data?.timezone ?? tz) : undefined }),
    {
      success: (p) => (p.idempotent ? "Already scheduled — nothing duplicated" : "Scheduled"),
      invalidate: [["publications"], ["article", articleId], ["articles"], ["summary"]],
      onSuccess: (p) => {
        onScheduled?.(p);
        onClose();
      },
    },
  );
  const configured = (t: PublishTarget) => {
    const v = integrations.data?.targets[t];
    return t === "export" || t === "ten_static" ? true : Boolean(v && "configured" in v && v.configured);
  };

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title="Schedule publication"
      description={title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Not now
          </Button>
          <Button icon={<FileSearch className="size-3.5" />} loading={dryRun.isPending} onClick={() => dryRun.mutate(undefined)} disabledReason={!target ? "Choose a target" : null}>
            Dry run
          </Button>
          <Button variant="primary" loading={schedule.isPending} onClick={() => schedule.mutate(undefined)} disabledReason={!when ? "Pick a time" : !target ? "Choose a target" : null}>
            Schedule
          </Button>
        </>
      }
    >
      {slot.isPending ? (
        <Skeleton className="h-24" />
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={`Publish at (${slot.data?.timezone ?? tz})`} hint={slot.data?.reason}>
              <Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
            </Field>
            <Field label="Target">
              <Select value={target} onChange={(e) => { setTarget(e.target.value as PublishTarget); setDry(null); }}>
                {(Object.keys(TARGET_LABEL) as PublishTarget[]).map((t) => (
                  <option key={t} value={t} disabled={!configured(t)}>
                    {TARGET_LABEL[t]}
                    {configured(t) ? "" : " — not configured"}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          {target === "ten_static" && integrations.data?.targets.ten_static.mode === "local" ? (
            <p className="text-xs text-ink-2">No SFTP host configured: the page publishes to the local staging site (/site/…) for review, plus an export bundle.</p>
          ) : null}
          {dry ? (
            <div className="space-y-3 rounded-md border border-line p-3">
              <div className="flex flex-wrap items-center gap-2 text-[13px]">
                {dry.issues.length ? (
                  <Badge tone="bad">
                    <TriangleAlert className="size-3" /> {dry.issues.length} issue(s)
                  </Badge>
                ) : (
                  <Badge tone="ok">
                    <CheckCircle2 className="size-3" /> Ready to publish
                  </Badge>
                )}
                {dry.unchanged ? <Badge tone="info">Identical content is already live</Badge> : dry.will_update ? <Badge tone="info">Updates the existing page</Badge> : <Badge>New page</Badge>}
              </div>
              {dry.issues.length ? (
                <ul className="list-disc pl-5 text-xs text-bad">
                  {dry.issues.map((i) => (
                    <li key={i}>{i}</li>
                  ))}
                </ul>
              ) : null}
              <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1 text-xs">
                <dt className="text-muted">Live URL</dt>
                <dd className="break-all text-ink">{dry.live_url ?? "—"}</dd>
                {dry.existing_live_url ? (
                  <>
                    <dt className="text-muted">Currently live</dt>
                    <dd className="break-all text-ink">{dry.existing_live_url}</dd>
                  </>
                ) : null}
                <dt className="text-muted">Files</dt>
                <dd className="text-ink">{dry.files.join(", ") || "—"}</dd>
                <dt className="text-muted">Idempotency key</dt>
                <dd className="font-mono break-all text-ink-2">{dry.idempotency_key.slice(0, 24)}…</dd>
              </dl>
              <Button size="xs" variant="ghost" onClick={() => setShowHtml((s) => !s)}>
                {showHtml ? "Hide rendered page" : "Show rendered page"}
              </Button>
              {showHtml ? <iframe title="Dry-run rendered page" sandbox="" srcDoc={dry.html} className="h-[420px] w-full rounded border border-line bg-white" /> : null}
            </div>
          ) : (
            <p className="text-xs text-muted">Dry run renders the page and validates it without touching any server.</p>
          )}
        </div>
      )}
    </Dialog>
  );
}
