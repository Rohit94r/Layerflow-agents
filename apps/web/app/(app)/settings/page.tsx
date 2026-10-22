"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";
import { DangerZone } from "@/components/settings/danger";
import { EvalsSettings } from "@/components/settings/evals";
import { GeneralSettings } from "@/components/settings/general";
import { IntegrationsSettings } from "@/components/settings/integrations";
import { ModelsSettings } from "@/components/settings/models";
import { PersonaSettings } from "@/components/settings/persona";
import { PromptsSettings } from "@/components/settings/prompts";
import { SourcesSettings } from "@/components/settings/sources";
import { PageHeader, Skeleton, Tabs } from "@/components/ui";
import { useMe } from "@/lib/hooks";
import { useToast } from "@/lib/toast";

const TABS = [
  { value: "general", label: "General" },
  { value: "sources", label: "Sources" },
  { value: "models", label: "Models" },
  { value: "prompts", label: "Prompts" },
  { value: "persona", label: "Persona & Style" },
  { value: "integrations", label: "Integrations" },
  { value: "evals", label: "Evaluations" },
  { value: "danger", label: "Danger zone" },
] as const;
type Tab = (typeof TABS)[number]["value"];

function SettingsInner() {
  const params = useSearchParams();
  const router = useRouter();
  const toast = useToast();
  const me = useMe();
  const notified = useRef(false);
  const tab = (TABS.find((t) => t.value === params.get("tab"))?.value ?? "general") as Tab;
  const setTab = (t: Tab) => router.replace(`/settings?tab=${t}`, { scroll: false });

  useEffect(() => {
    const li = params.get("linkedin");
    if (!li || notified.current) return;
    notified.current = true;
    if (li === "connected") toast.success("LinkedIn connected");
    else toast.error("LinkedIn connection failed", params.get("reason") ?? undefined);
  }, [params, toast]);

  if (!me.data) return <Skeleton className="h-96" />;
  const isOwner = me.data.user.role === "owner";
  const canContent = me.data.user.role !== "reviewer";
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Settings" subtitle={isOwner ? "Tenant configuration — changes are audited" : "Read-only for your role; owners can change settings"} />
      <Tabs tabs={TABS.map((t) => ({ value: t.value, label: t.label }))} value={tab} onChange={setTab} className="mb-4" />
      {tab === "general" ? <GeneralSettings me={me.data} isOwner={isOwner} /> : null}
      {tab === "sources" ? <SourcesSettings isOwner={isOwner} canContent={canContent} /> : null}
      {tab === "models" ? <ModelsSettings isOwner={isOwner} canContent={canContent} /> : null}
      {tab === "prompts" ? <PromptsSettings isOwner={isOwner} /> : null}
      {tab === "persona" ? <PersonaSettings isOwner={isOwner} /> : null}
      {tab === "integrations" ? <IntegrationsSettings isOwner={isOwner} /> : null}
      {tab === "evals" ? <EvalsSettings canContent={canContent} /> : null}
      {tab === "danger" ? <DangerZone slug={me.data.tenant.slug} isOwner={isOwner} /> : null}
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <SettingsInner />
    </Suspense>
  );
}
