"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { Button, Field, Input } from "@/components/ui";
import { ApiError, errorMessage, post } from "@/lib/api";
import type { Me } from "@/lib/types";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const me = await post<Omit<Me, "provider">>("/auth/login", { email, password });
      qc.setQueryData(["me"], undefined);
      await qc.invalidateQueries({ queryKey: ["me"] });
      const next = params.get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
      void me;
    } catch (err) {
      setError(err instanceof ApiError && err.code === "rate_limited" ? "Too many attempts. Wait a few minutes and try again." : errorMessage(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4" aria-describedby={error ? "login-error" : undefined}>
      <Field label="Email">
        <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className="h-10" />
      </Field>
      <Field label="Password">
        <Input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="h-10" />
      </Field>
      {error ? (
        <p id="login-error" role="alert" className="rounded-md bg-bad-soft px-3 py-2 text-[13px] text-bad">
          {error}
        </p>
      ) : null}
      <Button type="submit" variant="primary" size="md" loading={pending} className="w-full">
        Sign in
      </Button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <p className="font-display text-[30px] leading-tight font-semibold text-ink">The Executive Narrative</p>
          <p className="mt-1 text-[11px] tracking-[0.2em] text-muted uppercase">Editorial engine · Powered by LayerFlow</p>
        </div>
        <div className="rounded-lg border border-line bg-surface p-6 shadow-sm">
          <Suspense fallback={null}>
            <LoginForm />
          </Suspense>
        </div>
        <p className="mt-6 text-center text-xs text-muted">Nothing publishes without human approval.</p>
      </div>
    </div>
  );
}
