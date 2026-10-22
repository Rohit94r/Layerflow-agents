"use client";

import { useQuery } from "@tanstack/react-query";
import { Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Banner, Button, Card, CardHeader, ErrorState, Field, Input, Select, Skeleton, StatusDot, td, th } from "@/components/ui";
import { get, post } from "@/lib/api";
import { ms } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import type { AgentModel, ModelTest, ModelsView } from "@/lib/types";

const AGENT_INFO: Record<string, string> = {
  discovery: "A1 · routing & why-it-matters (small model is enough)",
  research: "A2 · evidence synthesis",
  writer: "A3 · long-form writing (largest model you can run)",
  editor: "A4 · clarity & rhythm (lower temperature)",
  seo: "A5 · title/meta phrasing",
  critic: "A6 · adversarial QA rubric",
  linkedin: "A9 · LinkedIn post",
};

export function ModelsSettings({ isOwner, canContent }: { isOwner: boolean; canContent: boolean }) {
  const q = useQuery({ queryKey: ["models"], queryFn: () => get<ModelsView>("/settings/models") });
  const [agents, setAgents] = useState<Record<string, AgentModel>>({});
  const [testModel, setTestModel] = useState("");
  const [result, setResult] = useState<ModelTest | null>(null);
  useEffect(() => {
    if (q.data) {
      setAgents(q.data.agents);
      setTestModel(q.data.agents.discovery?.model ?? q.data.defaults.fast);
    }
  }, [q.data]);
  const save = useAction(() => post<ModelsView>("/settings/models", { agents }), { success: "Model routing saved", invalidate: [["models"], ["health"]] });
  const test = useAction(() => post<ModelTest>("/settings/models/test", { model: testModel || undefined }), {
    silent: true,
    onSuccess: (r) => setResult(r),
    onError: (e) => setResult({ ok: false, model: testModel, models: [], latency_ms: null, sample: null, error: String(e) }),
  });
  if (q.isPending) return <Skeleton className="h-96" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const m = q.data;
  const options = Array.from(new Set([...m.available, ...Object.values(agents).map((a) => a.model ?? ""), m.defaults.writer, m.defaults.fast].filter(Boolean)));
  return (
    <div className="space-y-4">
      {m.provider === "mock" ? (
        <Banner tone="warn" title="Mock provider active">
          MODEL_PROVIDER=mock returns deterministic extractive output for tests and UI work. Set MODEL_PROVIDER=ollama for real writing.
        </Banner>
      ) : null}
      <Card>
        <CardHeader title="Provider" />
        <div className="grid gap-4 p-4 md:grid-cols-[1fr_1fr]">
          <dl className="grid grid-cols-[120px_1fr] gap-y-1.5 text-[13px]">
            <dt className="text-muted">Provider</dt>
            <dd className="flex items-center gap-1.5 text-ink">
              <StatusDot status={m.reachable ? "ok" : "down"} /> {m.provider} {m.reachable ? "reachable" : "unreachable"}
            </dd>
            <dt className="text-muted">Endpoint</dt>
            <dd className="font-mono text-xs break-all text-ink-2">{m.base_url ?? "—"}</dd>
            <dt className="text-muted">Defaults</dt>
            <dd className="text-xs text-ink-2">
              writer {m.defaults.writer} · fast {m.defaults.fast} · embed {m.defaults.embed}
            </dd>
            <dt className="text-muted">Limits</dt>
            <dd className="text-xs text-ink-2">
              ctx {m.defaults.num_ctx} · timeout {m.defaults.timeout_s}s · concurrency {m.defaults.concurrency}
            </dd>
            <dt className="text-muted">Pulled models</dt>
            <dd className="flex flex-wrap gap-1">
              {m.available.length ? m.available.map((x) => <Badge key={x}>{x}</Badge>) : <span className="text-xs text-warn">{m.detail ?? "none — run: ollama pull <model>"}</span>}
            </dd>
          </dl>
          <div className="space-y-2">
            <Field label="Smoke test (20 tokens)">
              <div className="flex gap-2">
                <Select value={testModel} onChange={(e) => setTestModel(e.target.value)}>
                  {options.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </Select>
                <Button icon={<Zap className="size-3.5" />} loading={test.isPending} onClick={() => test.mutate(undefined)} disabledReason={!canContent ? "Your role cannot run tests" : null}>
                  Test
                </Button>
              </div>
            </Field>
            {result ? (
              <div className={`rounded-md px-3 py-2 text-xs ${result.ok ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad"}`} role="status">
                {result.ok ? `OK · ${ms(result.latency_ms)} · ${result.completion_tokens ?? "?"} tokens` : `Failed: ${result.error}`}
                {result.sample ? <pre className="mt-1 font-mono text-[11px] whitespace-pre-wrap text-ink-2">{result.sample}</pre> : null}
              </div>
            ) : (
              <p className="text-xs text-muted">Pings the provider and runs a tiny structured generation.</p>
            )}
          </div>
        </div>
      </Card>
      <Card className="overflow-hidden">
        <CardHeader title="Model per agent" subtitle="One model is loaded at a time on CPU; reuse the same model across agents to avoid reloads." />
        <table className="w-full text-[13px]">
          <thead className="border-b border-line">
            <tr>
              <th className={th}>Agent</th>
              <th className={th}>Model</th>
              <th className={th}>Temperature</th>
              <th className={th}>Context</th>
              <th className={th}>Max tokens</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {Object.keys(AGENT_INFO).map((k) => {
              const a = agents[k] ?? {};
              const set = (patch: AgentModel) => setAgents({ ...agents, [k]: { ...a, ...patch } });
              return (
                <tr key={k}>
                  <td className={td}>
                    <p className="font-medium text-ink capitalize">{k}</p>
                    <p className="text-xs text-muted">{AGENT_INFO[k]}</p>
                  </td>
                  <td className={td}>
                    <Input list="model-options" value={a.model ?? ""} onChange={(e) => set({ model: e.target.value })} disabled={!isOwner} className="w-56" aria-label={`${k} model`} />
                  </td>
                  <td className={td}>
                    <Input type="number" step="0.05" min={0} max={1.5} value={a.temperature ?? ""} onChange={(e) => set({ temperature: e.target.value === "" ? undefined : Number(e.target.value) })} disabled={!isOwner} className="w-24" aria-label={`${k} temperature`} />
                  </td>
                  <td className={td}>
                    <Input type="number" step="1024" min={1024} max={131072} value={a.num_ctx ?? ""} placeholder={String(m.defaults.num_ctx)} onChange={(e) => set({ num_ctx: e.target.value === "" ? undefined : Number(e.target.value) })} disabled={!isOwner} className="w-28" aria-label={`${k} context`} />
                  </td>
                  <td className={td}>
                    <Input type="number" step="100" min={32} max={16384} value={a.max_tokens ?? ""} onChange={(e) => set({ max_tokens: e.target.value === "" ? undefined : Number(e.target.value) })} disabled={!isOwner} className="w-28" aria-label={`${k} max tokens`} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <datalist id="model-options">
          {options.map((o) => (
            <option key={o} value={o} />
          ))}
        </datalist>
        <div className="border-t border-line px-4 py-3">
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate(undefined)} disabledReason={!isOwner ? "Only owners can change models" : null}>
            Save model routing
          </Button>
        </div>
      </Card>
    </div>
  );
}
