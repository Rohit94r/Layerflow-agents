"use client";

import { useState } from "react";
import { Button, Card, CardHeader, Dialog, Field, Input } from "@/components/ui";
import { post } from "@/lib/api";
import { useAction } from "@/lib/hooks";

const ACTIONS = [
  { action: "retention", title: "Apply retention now", body: "Trims model-run outputs older than 90 days, prunes non-promoted feed items older than 60 days, finished jobs older than 30 days and expired sessions.", days: false },
  { action: "purge_feed", title: "Purge old feed items", body: "Deletes non-promoted feed items older than the given number of days. Promoted stories are kept.", days: true },
  { action: "clear_dead_jobs", title: "Clear failed and dead jobs", body: "Removes failed/dead job rows. Do this only after reviewing them — they are your failure record.", days: false },
  { action: "revoke_sessions", title: "Sign everyone else out", body: "Revokes all sessions except yours.", days: false },
] as const;

export function DangerZone({ slug, isOwner }: { slug: string; isOwner: boolean }) {
  const [open, setOpen] = useState<(typeof ACTIONS)[number] | null>(null);
  const [confirm, setConfirm] = useState("");
  const [days, setDays] = useState("30");
  const run = useAction(
    () => post<{ ok: boolean; detail: Record<string, number> }>(`/settings/maintenance/${open?.action}`, { confirm, older_than_days: open?.days ? Number(days) : undefined }),
    {
      success: (r) => `Done: ${Object.entries(r.detail).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(", ")}`,
      invalidate: [["summary"], ["jobs"], ["feed"]],
      onSuccess: () => {
        setOpen(null);
        setConfirm("");
      },
    },
  );
  return (
    <Card className="border-bad/40">
      <CardHeader title="Danger zone" subtitle="Each action asks you to type the tenant slug" />
      <ul className="divide-y divide-line">
        {ACTIONS.map((a) => (
          <li key={a.action} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
            <div className="max-w-2xl">
              <p className="text-[13px] font-medium text-ink">{a.title}</p>
              <p className="text-xs text-ink-2">{a.body}</p>
            </div>
            <Button variant="danger" size="sm" onClick={() => setOpen(a)} disabledReason={!isOwner ? "Only owners can run maintenance" : null}>
              {a.title}
            </Button>
          </li>
        ))}
      </ul>
      {open ? (
        <Dialog
          open
          onClose={() => setOpen(null)}
          title={open.title}
          size="sm"
          footer={
            <>
              <Button variant="ghost" onClick={() => setOpen(null)}>
                Cancel
              </Button>
              <Button variant="danger" loading={run.isPending} onClick={() => run.mutate(undefined)} disabledReason={confirm !== slug ? `Type “${slug}” to confirm` : null}>
                Confirm
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="text-[13px] text-ink-2">{open.body}</p>
            {open.days ? (
              <Field label="Older than (days)">
                <Input type="number" min={1} value={days} onChange={(e) => setDays(e.target.value)} />
              </Field>
            ) : null}
            <Field label={`Type “${slug}” to confirm`}>
              <Input value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
            </Field>
          </div>
        </Dialog>
      ) : null}
    </Card>
  );
}
