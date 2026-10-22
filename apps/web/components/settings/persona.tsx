"use client";

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, CardHeader, ErrorState, Field, Input, Skeleton, Textarea } from "@/components/ui";
import { get, put } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { PersonaView } from "@/lib/types";

export function PersonaSettings({ isOwner }: { isOwner: boolean }) {
  const q = useQuery({ queryKey: ["persona"], queryFn: () => get<PersonaView>("/settings/persona") });
  const [persona, setPersona] = useState("");
  const [phrases, setPhrases] = useState<string[]>([]);
  const [add, setAdd] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    if (q.data) {
      setPersona(q.data.persona.body);
      setPhrases(q.data.banned_phrases);
    }
  }, [q.data]);
  const savePersona = useAction(() => put<PersonaView>("/settings/persona", { persona, note: note || undefined }), { success: "Persona saved as a new version", invalidate: [["persona"], ["prompts"]] });
  const saveBanned = useAction(() => put<PersonaView>("/settings/persona", { banned_phrases: phrases, note: note || undefined }), { success: "Banned phrases saved", invalidate: [["persona"], ["prompts"]] });
  if (q.isPending) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const personaDirty = persona !== q.data.persona.body;
  const bannedDirty = phrases.join("|") !== q.data.banned_phrases.join("|");
  const addPhrase = () => {
    const p = add.trim().toLowerCase();
    if (p.length >= 3 && !phrases.includes(p)) setPhrases([...phrases, p].sort());
    setAdd("");
  };
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader title={`Persona (persona/ten@${q.data.persona.version})`} subtitle="The voice is the product — audience, stance, rhythm, what to avoid" />
        <div className="space-y-3 p-4">
          <Textarea rows={22} value={persona} onChange={(e) => setPersona(e.target.value)} className="font-mono text-[12.5px]" disabled={!isOwner} aria-label="Persona" />
          <Field label="Change note">
            <Input value={note} onChange={(e) => setNote(e.target.value)} disabled={!isOwner} />
          </Field>
          <Button variant="primary" loading={savePersona.isPending} onClick={() => savePersona.mutate(undefined)} disabledReason={!isOwner ? "Only owners can edit the persona" : !personaDirty ? "No changes" : null}>
            Save persona
          </Button>
        </div>
      </Card>
      <div className="space-y-4">
        <Card>
          <CardHeader title={`Banned phrases (${phrases.length})`} subtitle="Scanned in every draft; any hit blocks the review queue" />
          <div className="space-y-3 p-4">
            <div className="flex max-h-64 flex-wrap gap-1.5 overflow-y-auto">
              {phrases.map((p) => (
                <Badge key={p} tone="bad">
                  {p}
                  {isOwner ? (
                    <button type="button" onClick={() => setPhrases(phrases.filter((x) => x !== p))} aria-label={`Remove ${p}`}>
                      <X className="size-3" />
                    </button>
                  ) : null}
                </Badge>
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                value={add}
                onChange={(e) => setAdd(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addPhrase();
                  }
                }}
                placeholder="Add a phrase (substring match — avoid short common words)"
                disabled={!isOwner}
                aria-label="New banned phrase"
              />
              <Button onClick={addPhrase} disabledReason={!isOwner ? "Only owners can edit" : add.trim().length < 3 ? "At least 3 characters" : null}>
                Add
              </Button>
            </div>
            <Button variant="primary" loading={saveBanned.isPending} onClick={() => saveBanned.mutate(undefined)} disabledReason={!isOwner ? "Only owners can edit" : !bannedDirty ? "No changes" : null}>
              Save banned list
            </Button>
          </div>
        </Card>
        <Card>
          <CardHeader title="Measured style profile" subtitle="From mentor-approved samples in evals/style" />
          <div className="p-4">
            {q.data.style_profile ? (
              <pre className="max-h-72 overflow-auto font-mono text-[11.5px] text-ink-2">{JSON.stringify(q.data.style_profile, null, 2)}</pre>
            ) : (
              <p className="text-xs text-muted">
                No style profile yet. Add 8–12 approved articles to evals/style/good and 5 “not our voice” samples to evals/style/bad, then run <code className="font-mono">python scripts/eval_agents.py --style-profile</code>.
              </p>
            )}
          </div>
        </Card>
        <Card>
          <CardHeader title={`Structure rules (v${q.data.structure.version})`} subtitle="Edit under Prompts → style/structure" />
          <pre className="max-h-56 overflow-auto p-4 font-mono text-[11.5px] whitespace-pre-wrap text-ink-2">{q.data.structure.body}</pre>
        </Card>
      </div>
    </div>
  );
}
